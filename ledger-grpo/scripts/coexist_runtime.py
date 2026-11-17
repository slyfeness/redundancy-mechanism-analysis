"""Isolated service lifecycle for the four-A800 coexistence trial."""
from contextlib import contextmanager
import csv
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

from redundancy_judge.common import atomic_json


def actor_fractions(layout, adjusted):
    if layout in ("A", "B"):
        return [.75] * (4 if layout == "A" else 2)
    return [.45, .37, .45, .45] if adjusted else [.45] * 4


def transition_actors(actors, *, sleeping):
    if sleeping:
        actors.gate.touch(exist_ok=False)
        actors.all(lambda actor: actor.post("/sleep?level=1&mode=wait"))
    else:
        if not actors.gate.is_file():
            raise RuntimeError("cannot wake actors without a closed admission gate")
        actors.all(lambda actor: actor.post("/wake_up"))
    if not all(state is sleeping for state in actors.all(lambda actor: actor.get("/is_sleeping")["is_sleeping"])):
        raise RuntimeError("actor state does not match the sleep transition")
    if not sleeping:
        actors.gate.unlink()


def local_request(url, route, *, method="GET", timeout=1200):
    request = Request(url + route, data=b"" if method == "POST" else None, method=method)
    with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw) if raw else None


def save_prometheus(url, path):
    with build_opener(ProxyHandler({})).open(url + "/metrics", timeout=20) as response:
        path.write_bytes(response.read())


def stop_process(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=90)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=25)


class JudgeService:
    def __init__(self, root, python, model, devices, memory):
        self.root = root
        self.root.mkdir()
        with socket.socket() as port:
            port.bind(("127.0.0.1", 0))
            self.port = port.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.model = Path(model).name
        self.env = dict(os.environ, CUDA_VISIBLE_DEVICES=",".join(devices), VLLM_SERVER_DEV_MODE="1")
        for key in ("PYTORCH_CUDA_ALLOC_CONF", "PYTORCH_ALLOC_CONF", "OCCAM_ACTOR_ADMIN"):
            self.env.pop(key, None)
        self.command = [str(python), "-m", "vllm.entrypoints.openai.api_server", "--model", str(model),
                        "--served-model-name", self.model, "--host", "127.0.0.1", "--port", str(self.port),
                        "--tensor-parallel-size", str(len(devices)), "--generation-config", "vllm",
                        "--gpu-memory-utilization", str(memory), "--max-model-len", "131072",
                        "--max-num-seqs", "16", "--enforce-eager", "--enable-sleep-mode"]
        self.process = None
        self.log = None

    def start(self):
        atomic_json(self.root / "launch.json", {"command": self.command,
                    "device_count": len(self.env["CUDA_VISIBLE_DEVICES"].split(","))})
        self.log = (self.root / "server.log").open("wb")
        self.process = subprocess.Popen(self.command, env=self.env, stdout=self.log, stderr=subprocess.STDOUT)
        until = time.monotonic() + 1800
        while time.monotonic() < until:
            if self.process.poll() is not None:
                raise RuntimeError(f"Judge service exited ({self.process.returncode})")
            try:
                models = local_request(self.url, "/v1/models", timeout=2)
                if self.model in {entry["id"] for entry in models["data"]}:
                    return
            except (URLError, TimeoutError, ConnectionError):
                pass
            time.sleep(2)
        raise TimeoutError("Judge service readiness exceeded 1800 seconds")

    def transition(self, sleeping):
        route = "/sleep?level=1&mode=wait" if sleeping else "/wake_up"
        local_request(self.url, route, method="POST")
        if local_request(self.url, "/is_sleeping")["is_sleeping"] is not sleeping:
            raise RuntimeError("Judge state does not match the sleep transition")

    def close(self):
        stop_process(self.process)
        if self.log:
            self.log.close()


class ActorServices:
    """Use the frozen worker/graph and retriever factories with explicit per-card budgets."""
    def __init__(self, root, devices, fractions, gate, secret):
        self.root, self.devices, self.fractions = root, devices, fractions
        self.gate, self.secret = gate, secret
        self.retriever = self.log = self.actors = self.search = None
        self.servers = []

    def start(self):
        from src.resident_controller import fingerprint
        from src.resident_rollout import ActorAdmin, ResidentActors
        from src.rollout import graph_server_class, runtime
        from src.stability_rollout import instrument_search_timing

        self.root.mkdir()
        bundle = runtime(self.root, resident=True, retriever_instrumenter=instrument_search_timing)
        self.retriever, self.port, self.log = bundle["start_retriever"](
            self.root / "retriever", self.devices[1])
        factory = graph_server_class(bundle, self.root, prefix_cache=True, resident=True)
        for index, (device, memory) in enumerate(zip(self.devices, self.fractions, strict=True)):
            self.servers.append(factory(self.root / f"actor{index}", 65536, gpu=device, memory=memory))
        for server in self.servers:
            server.wait()
        self.actors = ResidentActors([ActorAdmin(server.url, self.secret) for server in self.servers], self.gate)
        self.search = ActorAdmin(f"http://127.0.0.1:{self.port}", self.secret)
        actual = self.actors.all(fingerprint)
        if len(set(actual)) != 1:
            raise RuntimeError("constituent Actor replicas loaded different weights")
        return actual[0]

    def close(self):
        from src.rollout import stop_services
        stop_services(self.servers, self.retriever, self.log)
        self.gate.unlink(missing_ok=True)


class Telemetry:
    fields = "timestamp,uuid,memory.used,memory.total,utilization.gpu,utilization.memory,driver_version"

    def __init__(self, root, uuids):
        self.root = root
        self.samples = root / "gpu-samples.csv"
        self.command = ["nvidia-smi", "--id=" + ",".join(uuids), "--query-gpu=" + self.fields, "--format=csv,noheader,nounits"]
        self.log = self.samples.open("wb")
        self.process = subprocess.Popen([*self.command, "-l", "1"], stdout=self.log, stderr=subprocess.STDOUT)

    def snapshot(self):
        records = subprocess.check_output(self.command, text=True).splitlines()
        return [{"uuid": col[1].strip(), "used_mib": int(col[2]), "total_mib": int(col[3])}
                for col in csv.reader(records)]

    @contextmanager
    def phase(self, name, **metadata):
        started = time.time()
        record = {"phase": name, "started_epoch": started, "initial_gpu": self.snapshot(), **metadata}
        try:
            yield record
        except BaseException as exc:
            record["error_type"] = type(exc).__name__
            raise
        finally:
            end = time.time()
            record.update(ended_epoch=end, seconds=end - started, final_gpu=self.snapshot())
            with (self.root / "phases.jsonl").open("a", encoding="utf-8") as out:
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
            print("phase", name, f"{end - started:.3f}s", record.get("error_type", "ok"), flush=True)

    def close(self):
        stop_process(self.process)
        self.log.close()


def versions(python):
    code = ("import importlib.metadata as m,torch; print({"
            "'python': __import__('sys').version.split()[0], 'vllm':m.version('vllm'), "
            "'torch':torch.__version__, 'torch_cuda':torch.version.cuda})")
    import ast
    return ast.literal_eval(subprocess.check_output([str(python), "-c", code], text=True).splitlines()[-1])


def memory_failure(root):
    check = re.compile(r"out of memory|OutOfMemoryError|less than (desired|requested) GPU memory utilization|"
                       r"insufficient (GPU )?(memory|KV cache)|no available memory for the cache blocks|"
                       r"to serve at least one request|KV cache.*not enough", re.I)
    for path in root.rglob("server.log"):
        with path.open("r", errors="replace") as stream:
            if any(check.search(line) for line in stream):
                return True
    return False
