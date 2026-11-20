"""Add normalized word-subset matches to the committed v4.6 name decisions."""

from argparse import ArgumentParser
from hashlib import sha256
import json
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parent.parent
for directory in ("ledger_judge_v46", "ledger_judge_v45", "ledger_judge_v44"):
    sys.path.append(str(BASE / directory))

from probe_v44 import ALIAS_PROMPT, NAME_PROMPT, TYPE_PROMPT, V4_ALIAS, V4_EXTRACT
from replay_v46 import committed, key, replay
from rules_v44 import name_key, normalized

FILES = ("stages", "stage_signals", "events")
VERSION = "ledger-judge-v4.7"
EXPECTED = {("1033__rep6", 3, 2, "T"), ("1033__rep7", 7, 1, "T")}


def subset_match(name, reference):
    tokens = set(normalized(name, titles=True).split())
    return bool(tokens) and tokens <= set(normalized(reference, titles=True).split())


def update_item(item, references):
    name = item["main_name"]
    if name in (None, "none") or item["attribution"] in ("correct", "invalid"):
        return item
    matches = [var for var, (reference, _) in references.items()
               if reference and reference.upper() != "UNRESOLVED" and subset_match(name, reference)]
    if not matches:
        return item
    var = item["var"] if item["var"] in matches else matches[0]
    return {**item, "attribution": "correct", "var": var, "decision_reason": "subset",
            "normalized_match": name_key(name) != name_key(references[var][0])}


def differences(before, after, prior_signals, signals, prior_events, events):
    changed, labels, other = [], [], []
    for old, new in zip(before, after, strict=True):
        if key(old) != key(new):
            raise ValueError("Stage identity or order changed")
        for index, (prior, current) in enumerate(zip(old["items"], new["items"], strict=True), 1):
            if prior != current:
                changed.append((*key(old), index, current["var"], prior["attribution"], current["attribution"]))
                expected_subset_fields = {"attribution", "var", "decision_reason", "normalized_match"}
                if (set(prior) != set(current) or any(prior[f] != current[f] for f in prior.keys() - expected_subset_fields)
                        or current["decision_reason"] != "subset"):
                    other.append((*key(old), f"查询 {index} 存在非子集匹配变更"))
        for tag in old["labels"].keys() | new["labels"].keys():
            if old["labels"].get(tag) != new["labels"].get(tag):
                labels.append((*key(old), tag, old["labels"].get(tag), new["labels"].get(tag)))
        for field in old.keys() | new.keys():
            if field not in ("items", "labels") and old.get(field) != new.get(field):
                other.append((*key(old), field))
    for old, new in zip(prior_signals, signals, strict=True):
        if old != new:
            fields = ", ".join(sorted(k for k in old.keys() | new.keys() if old.get(k) != new.get(k)))
            other.append((*key(old), f"stage_signals {fields}"))
    if prior_events != events:
        old_keys = {(key(row), row["event"], row["var"]): row for row in prior_events}
        new_keys = {(key(row), row["event"], row["var"]): row for row in events}
        for loc in sorted(old_keys.keys() | new_keys.keys()):
            if old_keys.get(loc) != new_keys.get(loc):
                other.append((*loc[0], f"{loc[1]} ({loc[2]}) 变更"))
        if not any(old_keys.get(loc) != new_keys.get(loc) for loc in old_keys.keys() | new_keys.keys()):
            other.append(("events", 0, "事件顺序或条数变化"))
    return sorted(changed), sorted(labels), sorted(other)


def build(repo):
    before, prior_signals, prior_events = (committed(repo, f"ledger_judge_v46/{name}.jsonl") for name in FILES)
    refs = {row["question_id"]: {ent["var"]: (ent["canonical_name"], ent["final_type"])
                                  for ent in row["entities"]}
            for row in committed(repo, "ledger_judge_v42/entity_types_v41.jsonl")}
    if len(before) != 430 or len({row["trajectory_id"] for row in before}) != 40:
        raise ValueError("unexpected v4.6 scope")
    repaired = []
    for row in before:
        table = refs[row["trajectory_id"].split("__", 1)[0]]
        items = [update_item(item, table) for item in row["items"]]
        repaired.append({**row, "items": items})
    after, signals, events, _ = replay(repaired, prior_signals, [], refs)
    changed, labels, other = differences(before, after, prior_signals, signals, prior_events, events)
    expected_items = sorted((*loc, "wrong_candidate", "correct") for loc in EXPECTED)
    expected_labels = sorted((tid, sid, "wrong_candidate", True, False) for tid, sid, _, _ in EXPECTED)
    approved = changed == expected_items and labels == expected_labels and not other
    lines = ["# 搜索词账本判定 v4.7",
             f"- 状态 · {'已冻结' if approved else '暂不冻结'}。",
             f"- 与 v4.6 逐项对照 40 条轨迹、{len(before)} 个 Stage。新增 Judge 调用 0。",
             f"- 搜索词归属变化 {len(changed)}｜Stage 标签变化 {len(labels)}｜其余差异 {len(other)}。"]
    for tid, step, slot, var, a, b in changed:
        lines.append(f"- {tid}/{step} 查询 {slot} ({var}) · {a} → {b}")
    for tid, step, tag, a, b in labels:
        lines.append(f"- {tid}/{step} · Stage {tag} {str(a).lower()} → {str(b).lower()}")
    lines.extend(f"- {tid}/{step} · {field}" for tid, step, field in other)
    if approved:
        lines.append("- 8 个 F_new、1 个 F_corrected、全部 idle_type 和 430 行 stage_signals 与 v4.6 一致。")
    return (after, signals, events), "\n".join(lines) + "\n", approved


def freeze():
    code_paths = [
        "ledger_judge_v47/replay_v47.py", "ledger_judge_v46/replay_v46.py",
        "ledger_judge_v45/probe_v45.py", "ledger_judge_v45/rules_v45.py", "ledger_judge_v44/rules_v44.py",
        "ledger_judge_v44/probe_v44.py", "ledger_judge_v42/probe_v42.py", "ledger_judge_v4/probe_v4.py",
        "fpremise_probe/flags.py",
    ]
    prompts = {"v4.extract.frozen": V4_EXTRACT, "v4.alias.frozen": V4_ALIAS, "v4.2.name.frozen": NAME_PROMPT,
               "v4.4.backfill_category": TYPE_PROMPT, "v4.4.alias_batch": ALIAS_PROMPT}
    fingerprints = {label: sha256(prompt.encode("utf-8")).hexdigest() for label, prompt in prompts.items()}
    provenance = json.loads((BASE / "ledger_judge_v44" / "FREEZE.json").read_bytes())
    if fingerprints != provenance["prompts_sha256_utf8"]:
        raise ValueError("inherited Judge prompt fingerprints changed")
    return {"version": VERSION, "status": "frozen", "baseline": "ledger-judge-v4.6", "judge_calls": 0,
            "code_sha256": {path: sha256((BASE / path).read_bytes()).hexdigest() for path in code_paths},
            "prompts_sha256_utf8": fingerprints, "prompts_provenance": "inherited_no_invocation",
            "accepted_changes": [{"trajectory_id": tid, "stage_id": sid, "query_index": slot, "var": var}
                                 for tid, sid, slot, var in sorted(EXPECTED)]}


def main():
    parser = ArgumentParser(description=__doc__)
    for name in ("private_repo", "output", "public_output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    artifacts, report, approved = build(args.private_repo)
    args.output.mkdir()
    for name, rows in zip(FILES, artifacts, strict=True):
        with (args.output / f"{name}.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    (args.public_output / "REPORT.md").write_text(report, encoding="utf-8", newline="\n")
    if approved:
        text = json.dumps(freeze(), ensure_ascii=False, indent=2) + "\n"
        with (args.public_output / "FREEZE.json").open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
    print(json.dumps({"stages": len(artifacts[0]), "events": len(artifacts[2]), "judge_calls": 0, "frozen": approved}))


if __name__ == "__main__":
    main()
