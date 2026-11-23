"""Extract all steps from one ordered trajectory and apply shared quote checks."""
from argparse import ArgumentParser
from collections import Counter
from pathlib import Path

from chain_extractor import encode, identity, jsonl, load, prepare, replace_text
from chain_extractor_v2 import extract_conditions, judge, list_field, obj, read_prompts, run_chain


def whole_payload(data, conditions):
    rings = data["rings"]
    return {
        "question": data["question"],
        "conditions": conditions,
        "start_thinking": rings[0]["thinking"],
        "steps": [
            {
                "step": ring["stage"],
                "queries": [call["query"] for call in ring["calls"]],
                "returns": [{k: v for k, v in call.items() if k != "query"} for call in ring["calls"]],
                "thinking_after": ring["thinking_after"],
            }
            for ring in rings[1:-1]
        ],
        "terminal": {key: rings[-1][key] for key in ("formal_answer", "termination_reason")},
    }


def check_steps(value, expected):
    rows = list_field(value, "steps")
    seen = [obj(row).get("step") for row in rows]
    numbers = Counter(x for x in seen if type(x) is int)
    states = {row["step"]: row for row in rows if isinstance(row, dict)
              and type(row.get("step")) is int and row["step"] in expected and numbers[row["step"]] == 1}
    check = {
        "expected_count": len(expected),
        "returned_count": len(rows),
        "steps_is_array": isinstance(obj(value).get("steps"), list),
        "returned_ids": seen,
        "invalid_id_count": sum(type(x) is not int for x in seen),
        "duplicate_ids": sorted(x for x, count in numbers.items() if count > 1),
        "missing_ids": [x for x in expected if x not in states],
        "out_of_range_ids": sorted(set(numbers) - set(expected)),
        "exact_order_and_count": all(type(x) is int for x in seen) and seen == expected,
    }
    return states, check


def run_whole(data, conditions, prompt, cfg, out):
    out.mkdir(parents=True, exist_ok=True)
    payload = whole_payload(data, conditions)
    cache = out / "checkpoint"
    cache.mkdir(exist_ok=True)
    identity(cache / "identity.sha256", {"payload": payload, "prompt": prompt,
                                       "config": {k: v for k, v in cfg.items() if k != "url"}})
    value, error, attempts = judge(cache, "whole", prompt, payload, cfg, extended_max_tokens=cfg["whole_max_tokens"])
    raw = [{"phase": "W", "stage": None, **row} for row in attempts]
    expected = [r["stage"] for r in data["rings"][1:-1]]
    steps, check = check_steps(value, expected)
    check["request_error"] = error
    check["length_retry"] = any(row["request"]["max_tokens"] == cfg["whole_max_tokens"] for row in raw)
    replace_text(out / "STEP_CHECK.json", encode(check) + "\n")
    if error:
        replace_text(out / "CHAIN.md", "# 思维链\n\n整条提取失败，详见 RAW.jsonl。\n")
        jsonl(out / "STATE.jsonl", [])
        jsonl(out / "VERIFY.jsonl", [])
        result = {"quotes": {}, "steps": len(expected), "carried": 0, "summaries_over_30": 0}
    else:
        model = obj(value)
        result = run_chain(data, conditions, {}, cfg, out,
                           whole={"start": model.get("start"), "steps": steps, "final": model.get("final")})
    jsonl(out / "RAW.jsonl", raw)
    return {**result, "raw": raw, "whole_failed": bool(error), "step_check": check}


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("trajectory", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--terminal", type=Path)
    parser.add_argument("--conditions", type=Path)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config_v2_sw.json"))
    args = parser.parse_args()
    cfg = load(args.config)
    data = prepare(load(args.trajectory), load(args.terminal or args.trajectory.with_name("TERMINAL.json")),
                   cfg["thought_truncation"])
    args.output.mkdir(parents=True, exist_ok=True)
    frozen = load(args.conditions) if args.conditions else extract_conditions(
        data["question"], read_prompts(Path(__file__).parent)["C"], cfg, args.output / "condition_checkpoint"
    )
    replace_text(args.output / "CONDITIONS.json", encode(frozen) + "\n")
    prompt = Path(__file__).with_name("prompt_v2_W.txt").read_text(encoding="utf-8")
    run_whole(data, frozen["conditions"], prompt, cfg, args.output)


if __name__ == "__main__":
    main()
