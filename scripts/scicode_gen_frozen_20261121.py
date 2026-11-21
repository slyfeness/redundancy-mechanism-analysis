"""Generate SciCode rollouts with the dated task-pool profile."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from prometheus_client.parser import text_string_to_metric_families
import requests
import yaml


CONFIG_PATH = Path(__file__).resolve().parents[1] / "configs/scicode_gen_frozen_20261122.yaml"


def read(path):
    return json.loads(path.read_bytes())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def import_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_actor(base, profile):
    server = profile["server"]
    inference = profile["inference"]
    model = profile["model"]

    class Actor(base.Server):
        def __init__(self, folder, gpu):
            self.folder, self.gpu = folder, gpu
            folder.mkdir(parents=True, exist_ok=False)
            self.p = base.port()
            self.url = f'http://{server["host"]}:{self.p}'
            command = [
                str(base.PY), "-u", "-m", server["entrypoint"],
                "--model", model["local_path"], "--tokenizer", model["local_path"],
                "--served-model-name", model["name"], "--host", server["host"],
                "--port", str(self.p), "--tensor-parallel-size", str(server["tensor_parallel_size"]),
                "--dtype", model["dtype"], "--max-model-len", str(inference["max_model_len"]),
                "--gpu-memory-utilization", str(server["gpu_memory_utilization"]),
                "--max-num-seqs", str(inference["max_num_seqs"]),
                "--max-num-batched-tokens", str(inference["max_num_batched_tokens"]),
                "--reasoning-parser", server["reasoning_parser"],
                "--tool-call-parser", server["tool_call_parser"],
                "--generation-config", server["generation_config"],
                "--speculative-config", json.dumps(server["speculative_config"]),
            ]
            toggles = {
                "--enable-auto-tool-choice": server["auto_tool_choice"],
                "--language-model-only": server["language_model_only"],
                "--enable-prefix-caching": server["enable_prefix_caching"],
                "--enable-chunked-prefill": server["enable_chunked_prefill"],
                "--enforce-eager": not server["cuda_graph"],
            }
            self.cmd = command + [arg for arg, enabled in toggles.items() if enabled]
            environ = os.environ.copy()
            environ.update(server["engine_environment"])
            environ["CUDA_VISIBLE_DEVICES"] = gpu
            environ.pop("PYTHONPATH", None)
            self.log = (folder / "server.log").open("w")
            self.proc = subprocess.Popen(self.cmd, stdout=self.log, stderr=subprocess.STDOUT,
                                         env=environ, start_new_session=True)
            write(folder / "launch.json", {"command": self.cmd, "gpu": gpu, "inference": inference})

        def call(self, body):
            for field in ("temperature", "top_p", "top_k", "repetition_penalty", "max_tokens"):
                if body.get(field) != inference[field]:
                    raise RuntimeError(f"request differs from frozen {field}")
            if body.get("n", server["n"]) != server["n"]:
                raise RuntimeError("request differs from frozen n")
            return super().call(body)

    return Actor


def job_cpu_seconds():
    path = Path("/proc/self/cgroup")
    for line in path.read_text().splitlines():
        _, controllers, scope = line.split(":", 2)
        if not controllers:
            entry = Path("/sys/fs/cgroup" + scope) / "cpu.stat"
            if entry.is_file():
                items = dict(x.split() for x in entry.read_text().splitlines())
                return float(items["usage_usec"]) / 1e6
        if "cpuacct" in controllers.split(","):
            for prefix in ("/sys/fs/cgroup/cpu,cpuacct", "/sys/fs/cgroup/cpuacct,cpu", "/sys/fs/cgroup/cpuacct"):
                entry = Path(prefix + scope) / "cpuacct.usage"
                if entry.is_file():
                    return int(entry.read_text()) / 1e9
    return None


def sample_host():
    total = list(map(int, Path("/proc/stat").open().readline().split()[1:9]))
    command = ["nvidia-smi", "--query-gpu=index,uuid,name,utilization.gpu,memory.used",
               "--format=csv,noheader,nounits"]
    devices = {}
    for row in subprocess.check_output(command, text=True, timeout=5).splitlines():
        idx, uid, name, util, memory = map(str.strip, row.split(","))
        devices[idx] = devices[uid] = {"name": name, "util_pct": int(util) if util.isdigit() else None,
                                       "memory_mib": int(memory) if memory.isdigit() else None}
    return {"node_ticks": sum(total), "node_idle_and_iowait": sum(total[3:5]),
            "job_cpu_seconds": job_cpu_seconds(), "devices": devices}


METRIC_KEYS = {
    "vllm:num_requests_running", "vllm:num_requests_waiting", "vllm:kv_cache_usage_perc",
    "vllm:num_preemptions_total", "vllm:generation_tokens_total",
}


def sample_engine(actor, progress):
    row = {"elapsed_seconds": time.monotonic() - progress["t0"]}
    try:
        response = requests.get(actor.url + "/metrics", timeout=3)
        response.raise_for_status()
        for family in text_string_to_metric_families(response.text):
            for metric in family.samples:
                if metric.name in METRIC_KEYS:
                    row[metric.name] = row.get(metric.name, 0) + metric.value
    except Exception as exc:
        row["error"] = str(exc)
    return row


def monitor_once(sink, actors, states, executor, timing):
    timestamp = time.monotonic() - timing["t0"]
    engine = [executor.submit(sample_engine, actor, timing) for actor in actors]
    try:
        host = sample_host()
    except Exception as exc:
        host = {"error": str(exc)}
    devices = []
    for i, (job, state) in enumerate(zip(engine, states)):
        with state["lock"]:
            counters = {k: state[k] for k in ("started", "completed", "active", "finished")}
        devices.append({"slot": i, "schedule": state["schedule"], **counters,
                        "engine": job.result(), "nvml": host.get("devices", {}).get(actors[i].gpu)})
    event = {"elapsed_seconds": timestamp, "cards": devices,
             "host": {key: value for key, value in host.items() if key != "devices"}}
    sink.write(json.dumps(event, ensure_ascii=False) + "\n")
    sink.flush()


def card_queues(cohort, card_count):
    owners = {}
    queues = [[] for _ in range(card_count)]
    for row in cohort:
        target = row["target_id"]
        if target not in owners:
            owners[target] = len(owners) % card_count
        queues[owners[target]].append(row)
    return queues


def run_card(actor, state, base, targets, cohort, gpu_root, workers, timing, start):
    records = []
    groups = {}
    expected = {}
    for row in cohort:
        expected.setdefault(row["target_id"], set()).add(row["rep"])

    def run_one(row):
        target_id = row["target_id"]
        run_dir = base.OUT / gpu_root.name / "trajectories" / f'rep_{row["rep"]}'
        with state["lock"]:
            state["started"] += 1
            state["active"] += 1
            dispatched = time.monotonic() - timing["t0"]
        traj = base.execute_target(targets[target_id], row["seed"]-base.CFG["seed_base"], [actor], run_dir)
        assert traj["seed"] == row["seed"] and traj["actor_calls"] <= base.CFG["max_actor_calls_total"]
        record = {
            **row, "status": traj["status"], "stop_reason": traj["stop_reason"],
            "actor_calls": traj["actor_calls"], "output_tokens": traj["usage"]["completion_tokens"],
            "trajectory": str(run_dir / target_id / "trajectory.json"),
            "dispatched_seconds": dispatched,
            "completed_seconds": time.monotonic() - timing["t0"],
        }
        with state["lock"]:
            state["active"] -= 1
            state["completed"] += 1
            members = groups.setdefault(target_id, [])
            members.append(record)
            if len(members) == len(expected[target_id]):
                assert {x["rep"] for x in members} == expected[target_id]
                write(gpu_root / "groups_ready" / f"{target_id}.json", {
                    "target_id": target_id, "members": sorted(members, key=lambda x: x["rep"]),
                    "handoff_seconds": time.monotonic() - timing["t0"],
                })
            if state["completed"] % 8 == 0 or state["completed"] == len(cohort):
                write(gpu_root / "PROGRESS.json", {"completed": state["completed"], "total": len(cohort),
                                                   "step_utc": base.utc()})
        return record

    if not start.wait(timeout=30):
        raise RuntimeError("common generation start missing")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_one, row) for row in cohort]
        records.extend(job.result() for job in as_completed(futures))
    end = time.monotonic() - timing["t0"]
    with state["lock"]:
        state["finished"] = end
    assert len(records) == len({(r["target_id"], r["rep"]) for r in records}) == len(cohort)
    assert groups.keys() == expected.keys()
    assert all({r["rep"] for r in records} == expected[target] for target, records in groups.items())
    result = {"schedule": state["schedule"], "seconds": end, "count": len(records),
              "trajectories_per_hour": 3600*len(records)/end, "rows": records,
              "final_metrics": sample_engine(actor, timing)}
    write(gpu_root / "RESULT.json", result)
    return result


def main():
    if len(sys.argv) != 1:
        raise SystemExit("Use the dated config file. Command-line overrides are disabled.")
    conf = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    provenance = conf["provenance"]
    source = Path(provenance["runtime_source"])
    assert sha256(source) == provenance["runtime_source_sha256"]
    assert importlib.metadata.version("vllm") == conf["server"]["vllm_version"]
    model = Path(conf["model"]["local_path"])
    for name, expected in conf["model"]["artifact_sha256"].items():
        if not name.endswith(".safetensors"):
            assert sha256(model / name) == expected
    base = import_file("scicode_formal_runtime", source)
    base.CFG = dict(conf["inference"])
    base.MODEL, base.MODEL_NAME = model, conf["model"]["name"]
    base.EXEC_SEMAPHORE = threading.BoundedSemaphore(conf["tools"]["max_concurrent_code_tests"])
    output = Path(conf["experiment"]["output_parent"]) / f'run_{os.environ["SLURM_JOB_ID"]}'
    output.mkdir(parents=True, exist_ok=False)
    base.OUT = output / "raw"
    base.OUT.mkdir()
    targets_path = Path(conf["experiment"]["targets"])
    targets = {r["target_id"]: r for r in map(json.loads, targets_path.read_bytes().splitlines())}
    cohort = read(Path(conf["experiment"]["cohort_96"]))
    assert cohort and len({(r["target_id"], r["rep"]) for r in cohort}) == len(cohort)
    assert all(r["target_id"] in targets for r in cohort)
    gpus = os.environ["CUDA_VISIBLE_DEVICES"].split(",")
    schedules = conf["experiment"]["card_schedule"]
    assert len(gpus) == len(set(gpus)) == conf["server"]["actors"] == len(schedules) == 4
    assert schedules == ["B"] * len(gpus)
    queues = card_queues(cohort, len(gpus))
    assert os.environ["SLURM_CPUS_PER_TASK"] == "24"
    actor_type = make_actor(base, conf)
    actors = []
    states = [{"schedule": s, "lock": threading.Lock(), "started": 0, "completed": 0,
               "active": 0, "finished": None} for s in schedules]
    try:
        for i, gpu in enumerate(gpus):
            actors.append(actor_type(output / f"gpu{i}/actor", gpu))
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda x: x.wait(), actors))
        timing, start = {}, threading.Event()
        write(output / "READY.json", {"gpu_mask": gpus, "config_sha256": sha256(CONFIG_PATH),
                                    "cohort_sha256": sha256(Path(conf["experiment"]["cohort_96"])),
                                    "source_sha256": sha256(Path(__file__)),
                                    "code_commit": provenance["code_commit"],
                                    "vllm_version": conf["server"]["vllm_version"], "ready_utc": base.utc()})
        with ThreadPoolExecutor(max_workers=4) as work, ThreadPoolExecutor(max_workers=4) as probe:
            jobs = [work.submit(run_card, actor, states[i], base, targets, queues[i], output/f"gpu{i}",
                                base.CFG["workers_per_actor"], timing, start) for i, actor in enumerate(actors)]
            timing["t0"] = time.monotonic()
            start.set()
            with (output / "MONITOR.jsonl").open("x", encoding="utf-8") as sink:
                while not all(job.done() for job in jobs):
                    monitor_once(sink, actors, states, probe, timing)
                    time.sleep(5)
                monitor_once(sink, actors, states, probe, timing)
            cards = [job.result() for job in jobs]
        assert sum(c["count"] for c in cards) == len(cohort)
        write(output / "COMPLETE.json", {"cards": [{k:v for k,v in c.items() if k!="rows"} for c in cards],
                                       "count": sum(c["count"] for c in cards), "finished_utc": base.utc()})
    finally:
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda a: a.stop(), actors))


if __name__ == "__main__":
    main()
