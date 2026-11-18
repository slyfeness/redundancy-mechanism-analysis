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
REPETITIONS = 2
SIZE = os.environ["LEDGER_ACTOR_SIZE"]
assert SIZE in {"4B", "9B"}
MODEL_NAME = "Qwen/Qwen3.5-" + SIZE
MODEL_REV = {"4B": "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a",
             "9B": "c202236235762e1c871ad0ccb60c8ee5ba337b9a"}[SIZE]
from plan import build_tasks, reusable_receipt


def model_path():
    path = Path(os.environ["LEDGER_ACTOR_MODEL"])
    if SIZE == "4B":
        assert json.loads((path / "SOURCE_RECEIPT.json").read_bytes())["revision"] == MODEL_REV
    else:
        # Historical 9B directory predates SOURCE_RECEIPT. Do not invent one.
        assert path == Path("/file_storage01/home/weiyu/lanyi/models/Qwen3.5-9B")
        assert (path / "model.safetensors.index.json").is_file()
    return path


def tools(port):
    from qwen_agent.tools import BaseTool
    from qwen_agent.tools.base import ToolServiceError

    class WikiTool(BaseTool):
        def call(self, params, **kwargs):
            try:
                arguments = self._verify_json_format_args(params)
            except ValueError:
                return json.dumps({"error": "invalid tool arguments"})
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/{self.name}", json.dumps(arguments).encode(),
                {"Content-Type": "application/json"}, method="POST",
            )
            try:
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=90) as response:
                    return response.read().decode()
            except urllib.error.HTTPError as exc:
                if exc.code == 400:
                    return json.dumps({"error": "invalid tool arguments"})
                raise ToolServiceError(exc, code=str(exc.code), message="Local retrieval failed") from exc
            except OSError as exc:
                raise ToolServiceError(exc, message="Local retrieval connection failed") from exc

    class Search(WikiTool):
        name = "search"
        description = "Search the local Wikipedia corpus. Returns up to five article IDs and captions."
        parameters = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}

    class Open(WikiTool):
        name = "open"
        description = "Read a local Wikipedia article by its Search docid. Use next_start to read the next segment."
        parameters = {"type": "object", "properties": {
            "docid": {"type": "string"}, "start": {"type": "integer", "minimum": 0}},
            "required": ["docid"]}

    return [Search(), Open()]


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
    native = phase06_runtime.make_native_agent
    phase06_runtime.make_native_agent = lambda recorder, _: native(recorder, tools(int(port)))
    sys.argv[1:] = ["worker", run_id, url, folder, port]
    from src.rollout import main as legacy_worker
    legacy_worker(keep_services=True)


def main():
    import isolate_runtime
    from src import stability_controller as runtime
    from src.resident_controller import fingerprint, generated_probe
    from src.resident_rollout import ActorAdmin, ResidentActors
    from src.stability import write_json

    root, sample_file, ready, reference = map(Path, sys.argv[1:])
    weights = model_path()
    root.mkdir(exist_ok=False)
    os.chdir(root)
    wiki = json.loads(ready.read_bytes())
    port = wiki["port"]
    sample = json.loads(sample_file.read_bytes())
    assert len(sample) == len({row["id"] for row in sample}) == 100
    assert all(set(row) == {"id", "question"} for row in sample)
    selected = [dict(query_id=row["id"], question=row["question"],
                     question_sha256=hashlib.sha256(row["question"].encode()).hexdigest()) for row in sample]
    tasks = build_tasks(sample)
    assert tasks == json.loads((sample_file.parent / "task_manifest.json").read_bytes())["tasks"]
    reuse_rows = json.loads((sample_file.parent / "reuse_manifest.json").read_bytes())[SIZE]
    reused = {row["run_id"]: row for row in reuse_rows}
    config = {"temperature": 1.0, "top_p": 1.0, "top_k": 0, "context": 65536,
              "max_tokens_per_call": 10000, "max_actor_calls": 20, "thinking": True,
              "dtype": "bfloat16", "tensor_parallel": 1, "actors": 4, "max_num_seqs": 32,
              "prefix_cache": True, "cuda_graphs": True, "model": MODEL_NAME.split("/")[-1],
              "model_revision": MODEL_REV,
              "retrieval": wiki, "seed": SEED, "samples_per_query": REPETITIONS}
    write_json(root / "sample_manifest.json", {"selected": selected})
    write_json(root / "task_manifest.json", {"tasks": tasks})
    write_json(root / "config_manifest.json", config)
    old_tasks = {t["run_id"]: t for t in json.loads((reference / "task_manifest.json").read_bytes())["tasks"]}
    assert all(t == old_tasks[t["run_id"]] for t in tasks if t["run_id"] in reused)
    baseline = json.loads((reference / "config_manifest.json").read_bytes())
    changed = {"model", "model_revision", "samples_per_query"}
    assert {key: value for key, value in baseline.items() if key not in changed | {"retrieval"}} == {
        key: value for key, value in config.items() if key not in changed | {"retrieval"}
    }
    assert {key: value for key, value in baseline["retrieval"].items() if key != "port"} == {
        key: value for key, value in wiki.items() if key != "port"
    }
    (root / "trajectories").mkdir()
    (root / "verdicts").mkdir()
    for task in tasks:
        if task["run_id"] not in reused:
            continue
        row = reused[task["run_id"]]
        folder = Path(row["trajectory_dir"])
        vp = Path(row["verdict_path"])
        trace_sha = hashlib.sha256((folder / "trajectory.json").read_bytes()).hexdigest()
        assert trace_sha == row["trajectory_sha256"]
        assert hashlib.sha256(vp.read_bytes()).hexdigest() == row["verdict_sha256"]
        reusable_receipt(task, json.loads(vp.read_bytes()), json.loads((folder / "TERMINAL.json").read_bytes()), trace_sha, old_tasks[task["run_id"]])
        (root / "trajectories" / task["run_id"]).symlink_to(folder, target_is_directory=True)
        (root / "verdicts" / (task["run_id"] + ".json")).symlink_to(vp)
    write_json(root / "REUSE_RECEIPT.json", {"read_only_existing": reuse_rows, "reused": len(reused), "new": len(tasks)-len(reused)})
    namespace = runtime.runtime(root, resident=True)
    from phase06_runtime import native_tool_function
    schema = [{"type": "function", "function": native_tool_function(tool.function)} for tool in tools(port)]
    write_json(root / "EXECUTION_FREEZE.json", {"actor": {"frozen_native_tool_schema": schema}, "tasks": tasks})
    _, hardware = runtime.read_hardware()
    write_json(root / "HARDWARE.json", hardware)
    assert schema == json.loads((reference / "EXECUTION_FREEZE.json").read_bytes())["actor"]["frozen_native_tool_schema"]
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
    try:
        for index, gpu in enumerate(devices):
            server = factory(root / f"actor{index}", 65536, gpu=gpu, memory=.75)
            servers.append(server)
            old = json.loads((reference / f"actor{index}/launch.json").read_bytes())["command"]
            expected = old.copy()
            for flag, value in (("--model", str(weights)), ("--tokenizer", str(weights)),
                                ("--served-model-name", MODEL_NAME),
                                ("--port", server.cmd[server.cmd.index("--port") + 1])):
                expected[expected.index(flag) + 1] = value
            assert server.cmd == expected, "Actor launch arguments diverged from 184534"
        write_json(root / "PAIR_CONFIG_CHECK.json", {
            "reference_job": 184534 if SIZE == "9B" else 190085, "paired_tasks": len(tasks), "verified_launches": len(servers),
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
            if task["run_id"] in reused:
                return json.loads((root / "trajectories" / task["run_id"] / "TERMINAL.json").read_bytes())
            server = servers[index % len(servers)]
            run_id = task["run_id"]
            with (worker_logs / f"{run_id}.log").open("w") as log:
                code = subprocess.call(
                    [sys.executable, "-u", __file__, "worker", run_id, server.url, str(server.folder), str(port)],
                    env=env, stdout=log, stderr=subprocess.STDOUT,
                )
            terminal = root / "trajectories" / run_id / "TERMINAL.json"
            if code or not terminal.is_file():
                raise RuntimeError(f"Actor worker failed: {run_id} exit={code}")
            data = json.loads(terminal.read_bytes())
            print("rollout", index + 1, data["status"], data["actor_calls"], data["search_calls"], flush=True)
            return data

        with ThreadPoolExecutor(max_workers=8) as pool:
            generated = list(pool.map(lambda pair: execute(*pair), enumerate(tasks)))
        write_json(root / "ACTOR_COMPLETE.json", {
            "rollouts": len(generated), "reused": len(reused), "generated": len(generated)-len(reused),
            "optimizer_steps": 0,
        })
    finally:
        for server in servers:
            server.stop()
        gate.unlink(missing_ok=True)


if __name__ == "__main__":
    worker() if sys.argv[1] == "worker" else main()
