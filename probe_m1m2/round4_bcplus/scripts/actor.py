"""Run the frozen Ledger-GRPO Actor with local Search/Open."""

from concurrent.futures import ThreadPoolExecutor
import errno
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request


SEED = 20261110
REPETITIONS = 8
MODEL_NAME = "Qwen/Qwen3.5-4B"
MODEL_REV = "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"


def model_path():
    path = Path(os.environ["LEDGER_ACTOR_MODEL"])
    assert json.loads((path / "SOURCE_RECEIPT.json").read_bytes())["revision"] == MODEL_REV
    return path


def worker():
    from src import rollout

    root = Path(os.environ["SMOKE_RUN"])
    run_id, url, folder, port = sys.argv[2:]
    weights = model_path()
    original_runtime = rollout.runtime

    def runtime_with_model(*args, **kwargs):
        namespace = original_runtime(*args, **kwargs)
        namespace["MODEL"] = weights
        return namespace

    rollout.runtime = runtime_with_model
    rollout.runtime(root)
    import phase06_runtime

    phase06_runtime.MODEL = weights
    phase06_runtime.MODEL_NAME = MODEL_NAME
    phase06_runtime.MODEL_REV = MODEL_REV

    def durable_dump(path, obj):
        payload = json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n"
        temp = path.with_name(path.name + ".pending")
        for delay in (0, 1, 3, 7, 15):
            time.sleep(delay)
            try:
                temp.write_text(payload, encoding="utf-8")
                temp.replace(path)
                return
            except OSError as exc:
                if exc.errno not in {errno.EIO, errno.ESTALE} or delay == 15:
                    raise

    phase06_runtime.dump = durable_dump
    sys.argv[1:] = ["worker", run_id, url, folder, port]
    from src.rollout import main as legacy_worker
    legacy_worker(keep_services=True)


def main():
    import isolate_runtime
    from src import stability_controller as runtime
    from src.resident_controller import fingerprint, generated_probe
    from src.resident_rollout import ActorAdmin, ResidentActors
    from src.stability import write_json

    root, sample_file, deletion, reference = map(Path, sys.argv[1:])
    weights = model_path()
    root.mkdir(exist_ok=False)
    os.chdir(root)
    sample = json.loads(sample_file.read_bytes())
    assert len(sample) == len({row["id"] for row in sample}) == 50
    assert all(set(row) == {"id", "question"} for row in sample)
    selected = [dict(query_id=row["id"], question=row["question"],
                     question_sha256=hashlib.sha256(row["question"].encode()).hexdigest()) for row in sample]
    tasks = json.loads((sample_file.parent / "task_manifest.json").read_bytes())["tasks"]
    assert len(tasks) == 400 and {t["query_id"] for t in tasks} == {r["id"] for r in sample}
    config = {"temperature": 1.0, "top_p": 1.0, "top_k": 0, "context": 65536,
              "max_tokens_per_call": 10000, "max_actor_calls": 20, "thinking": True,
              "dtype": "bfloat16", "tensor_parallel": 1, "actors": 4, "max_num_seqs": 32,
              "prefix_cache": True, "cuda_graphs": True, "model": MODEL_NAME.split("/")[-1],
              "model_revision": MODEL_REV,
              "retrieval": {"reference_job": 183352, "k": 5, "snippet_max_tokens": 512}, "seed": SEED, "samples_per_query": REPETITIONS}
    write_json(root / "sample_manifest.json", {"selected": selected})
    write_json(root / "task_manifest.json", {"tasks": tasks})
    write_json(root / "config_manifest.json", config)
    baseline = json.loads((reference / "config_manifest.json").read_bytes())
    allowed_differences = {"samples_per_query", "retrieval"}
    assert {k: v for k, v in config.items() if k not in allowed_differences} == {
        k: v for k, v in baseline.items() if k not in allowed_differences}
    (root / "trajectories").mkdir()
    from src.stability_rollout import instrument_search_timing
    namespace = runtime.runtime(root, resident=True, retriever_instrumenter=instrument_search_timing)
    _, hardware = runtime.read_hardware()
    write_json(root / "HARDWARE.json", hardware)
    isolate_runtime.REPLACEMENTS["'--tokenizer',str(MODEL)"] = (
        "'--tokenizer',os.environ['LEDGER_ACTOR_MODEL']")
    isolate_runtime.install_runtime_isolation(runtime)
    gate = root / "actor-gate"
    snapshots = root / "snapshots"
    snapshots.mkdir()
    secret = secrets.token_urlsafe(32)
    os.environ.update(OCCAM_ACTOR_ADMIN=secret, OCCAM_ACTOR_GATE=str(gate), OCCAM_SNAPSHOT_DIR=str(snapshots))
    devices = os.environ["CUDA_VISIBLE_DEVICES"].split(",")
    assert len(devices) == len(set(devices)) == 4 and all(device.isdecimal() for device in devices)
    factory = runtime.graph_server_class(namespace, root, prefix_cache=True, resident=True)
    factory.__init__.__globals__["MODEL_NAME"] = MODEL_NAME
    servers = []
    retriever = retriever_log = None
    try:
        retriever, port, retriever_log = namespace["start_retriever"](root / "retriever", devices[1])
        launch = json.loads((root / "retriever/launch.json").read_bytes())
        frozen = json.loads((deletion / "retriever/launch.json").read_bytes())
        for field in ("original_source", "adapted_source"):
            assert launch[field]["sha256"] == frozen[field]["sha256"]
        assert launch["retrieval_compat_path"] == frozen["retrieval_compat_path"]
        definitions = json.loads((root / "retriever/tool_definitions.json").read_bytes())
        assert definitions == json.loads((deletion / "retriever/tool_definitions.json").read_bytes())
        schema = [{"type": "function", "function": {"name": "search-server-" + tool["name"],
                   "description": tool["description"], "parameters": tool["inputSchema"]}}
                  for tool in definitions]
        previous_bc = Path(os.environ["LEDGER_BC_TOOL_SCHEMA_REFERENCE"])
        expected_schema = json.loads(previous_bc.read_bytes())["actor"]["frozen_native_tool_schema"]
        assert schema == expected_schema
        write_json(root / "EXECUTION_FREEZE.json", {"actor": {"frozen_native_tool_schema": schema}, "tasks": tasks})
        print("retriever_ready", flush=True)
        for index, gpu in enumerate(devices):
            server = factory(root / f"actor{index}", 65536, gpu=gpu, memory=.75)
            servers.append(server)
            old = json.loads((reference / f"actor{index}/launch.json").read_bytes())["command"]
            expected = old.copy()
            for flag, value in (("--model", str(weights)), ("--tokenizer", str(weights)),
                                ("--served-model-name", MODEL_NAME),
                                ("--port", server.cmd[server.cmd.index("--port") + 1])):
                expected[expected.index(flag) + 1] = value
            assert server.cmd == expected, "Actor launch arguments diverged from round3"
        write_json(root / "PAIR_CONFIG_CHECK.json", {
            "reference_job": 191021, "paired_tasks": len(tasks), "verified_launches": len(servers),
            "changed_launch_fields": ["model", "tokenizer", "served_model_name", "local_port"],
            "actor_workers": 8,
        })
        for server in servers:
            server.wait()
        actors = ResidentActors([ActorAdmin(server.url, secret) for server in servers], gate)
        fingerprints = actors.all(fingerprint)
        assert len(set(fingerprints)) == 1
        frozen_fingerprints = json.loads((reference / "ACTORS_READY.json").read_bytes())["fingerprints"]
        assert fingerprints == frozen_fingerprints, "Loaded weights fingerprint differs from frozen model"
        probes = actors.all(generated_probe)
        assert all(row["token_ids"] == probes[0]["token_ids"] for row in probes)
        write_json(root / "ACTORS_READY.json", {"fingerprints": fingerprints, "probes": probes})
        print("Actor services ready", flush=True)
        env = dict(os.environ, SMOKE_RUN=str(root), CUDA_VISIBLE_DEVICES="", OMP_NUM_THREADS="1")
        env.pop("OCCAM_ACTOR_ADMIN", None)
        worker_logs = root / "worker-logs"
        worker_logs.mkdir()

        def execute(index, task):
            server = servers[index % len(servers)]
            run_id = task["run_id"]
            with (worker_logs / f"{run_id}.log").open("w") as log:
                code = subprocess.call(
                    [sys.executable, "-u", __file__, "worker", run_id, server.url, str(server.folder), str(port)],
                    env=env, stdout=log, stderr=subprocess.STDOUT,
                )
            terminal = root / "trajectories" / run_id / "TERMINAL.json"
            if code or not terminal.is_file():
                print("worker_failed", run_id, code, flush=True)
                return None
            data = json.loads(terminal.read_bytes())
            print("rollout", index + 1, data["status"], data["actor_calls"], data["search_calls"], flush=True)
            return data

        with ThreadPoolExecutor(max_workers=8) as pool:
            generated = list(pool.map(lambda pair: execute(*pair), enumerate(tasks)))
        write_json(root / "ACTOR_COMPLETE.json", {
            "rollouts": len(generated), "reused": 0, "generated": sum(row is not None for row in generated),
            "optimizer_steps": 0,
        })
    finally:
        from src.rollout import stop_services
        stop_services(servers, retriever, retriever_log)
        gate.unlink(missing_ok=True)


if __name__ == "__main__":
    worker() if sys.argv[1] == "worker" else main()
