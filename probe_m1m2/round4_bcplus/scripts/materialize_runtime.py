"""Derive the isolated round4 launcher from the checked-in round3 runtime."""
import ast
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1] / "round3" / "scripts"


def change(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"Expected one frozen runtime boundary: {old[:60]}")
    return text.replace(old, new, 1)


def replace_block(text, start, end, replacement=""):
    begin = text.index(start)
    finish = text.index(end, begin)
    return text[:begin] + replacement + text[finish:]


def main():
    actor = (SOURCE / "actor.py").read_text(encoding="utf-8")
    actor = replace_block(actor, "REPETITIONS = ", "def worker():", '''REPETITIONS = 8
MODEL_NAME = "Qwen/Qwen3.5-4B"
MODEL_REV = "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"


def model_path():
    path = Path(os.environ["LEDGER_ACTOR_MODEL"])
    assert json.loads((path / "SOURCE_RECEIPT.json").read_bytes())["revision"] == MODEL_REV
    return path


''')
    actor = replace_block(actor, "    native = phase06_runtime.make_native_agent", "    sys.argv[1:]")
    actor = change(actor, "root, sample_file, ready, reference", "root, sample_file, deletion, reference")
    actor = replace_block(actor, "    wiki = json.loads", "    sample = ")
    actor = change(actor, "== 100", "== 50")
    actor = replace_block(actor, "    tasks = build_tasks", "    config = ",
                          '    tasks = json.loads((sample_file.parent / "task_manifest.json").read_bytes())["tasks"]\n'
                          '    assert len(tasks) == 400 and {t["query_id"] for t in tasks} == {r["id"] for r in sample}\n')
    actor = change(actor, '"retrieval": wiki', '"retrieval": {"reference_job": 183352, "k": 5, "snippet_max_tokens": 512}')
    actor = replace_block(actor, "    old_tasks =", "    isolate_runtime.REPLACEMENTS", '''    baseline = json.loads((reference / "config_manifest.json").read_bytes())
    allowed_differences = {"samples_per_query", "retrieval"}
    assert {k: v for k, v in config.items() if k not in allowed_differences} == {
        k: v for k, v in baseline.items() if k not in allowed_differences}
    (root / "trajectories").mkdir()
    from src.stability_rollout import instrument_search_timing
    namespace = runtime.runtime(root, resident=True, retriever_instrumenter=instrument_search_timing)
    _, hardware = runtime.read_hardware()
    write_json(root / "HARDWARE.json", hardware)
''')
    actor = change(actor, "    servers = []\n    try:\n", '''    servers = []
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
''')
    actor = change(actor, '"reference_job": 184534 if SIZE == "9B" else 190085', '"reference_job": 191021')
    actor = change(actor, 'Actor launch arguments diverged from 184534', 'Actor launch arguments diverged from round3')
    # Allow one worker failure to leave an explicit missing trajectory rather than discarding other groups.
    actor = change(actor, '''            if task["run_id"] in reused:
                return json.loads((root / "trajectories" / task["run_id"] / "TERMINAL.json").read_bytes())
''', "")
    actor = change(actor, '''                raise RuntimeError(f"Actor worker failed: {run_id} exit={code}")''', '''                print("worker_failed", run_id, code, flush=True)
                return None''')
    actor = change(actor, '"rollouts": len(generated), "reused": len(reused), "generated": len(generated)-len(reused),',
                   '"rollouts": len(generated), "reused": 0, "generated": sum(row is not None for row in generated),')
    actor = change(actor, "        for server in servers:\n            server.stop()",
                   "        from src.rollout import stop_services\n        stop_services(servers, retriever, retriever_log)")
    score = (SOURCE / "score.py").read_text(encoding="utf-8")
    score = change(score, "len(tasks) == 200 and len(questions) == 100", "len(tasks) == 400 and len(questions) == 50")
    score = change(score, "        terminal = json.loads", """        if not (folder / "TERMINAL.json").is_file():
            return None
        terminal = json.loads""")
    score = change(score, '''        assert status in TERMINAL_BUDGET | {"MODEL_FINAL_STOP"}, status''', '''        if status not in TERMINAL_BUDGET | {"MODEL_FINAL_STOP"}:
            return None''')
    score = change(score, "for row in rounds)\n        status", 'for row in rounds if row["response_received"])\n        status')
    score = change(score, 'assert all(row["response_received"] and row["token_accounting"]', 'assert all(row["token_accounting"]')
    start = score.index("            verdict = judge._request")
    end = score.index("        else:", start)
    body = score[start:end]
    score = score[:start] + "            try:\n" + "".join("    " + line for line in body.splitlines(keepends=True)) + (
        "            except Exception as error:\n"
        "                result.update(correct=None, judge=model, judge_error=type(error).__name__)\n"
    ) + score[end:]
    score = replace_block(score, "    def stats(", '\n\nif __name__', '''    print(json.dumps({"expected": len(tasks), "receipts": sum(row is not None for row in rows),
                      "judge_failures": sum(row is not None and row["correct"] is None for row in rows),
                      "optimizer_steps": 0}), flush=True)
''')
    for name, text in {"actor.py": actor, "score.py": score}.items():
        ast.parse(text)
        (HERE / name).write_text(text, encoding="utf-8", newline="\n")
    (HERE / "rules.py").write_bytes((SOURCE / "rules.py").read_bytes())
    names = ("actor.py", "score.py", "rules.py", "native_stages.py")
    receipt = {
        "round3_reference_commit": "91f08c78bb537f2095601960b584361f44ec5364",
        "round3_sha256": {name: hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() for name in names},
        "derived_sha256": {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest() for name in names},
        "generation_workers": 8, "reuse": 0, "retrieval_reference_job": 183352,
    }
    (HERE.parent / "runtime_derivation.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
