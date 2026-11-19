"""Check the existing recorder layout using only this round's 50 sampled IDs."""
import json
import sys
from collections import Counter
from pathlib import Path

from read_stages import outcome_record


def main(selection, history, tokenizer, output):
    load = lambda path: json.loads(path.read_bytes())
    evaluation = {row["id"]: row for row in load(selection / "evaluation_private.json")}
    split = load(selection / "split.json")
    assert not set(evaluation) & set(split["test"])
    added = {item["content"]: item["id"] for item in load(tokenizer)["added_tokens"]}
    markers = {k: added[k] for k in ("<tool_call>", "</tool_call>", "<tool_response>", "</tool_response>")}
    count = Counter()
    for task in load(history / "task_manifest.json")["tasks"]:
        qid = str(task["query_id"])
        if qid not in evaluation:
            continue
        q = evaluation[qid]
        tid = task["run_id"]
        row, stages = outcome_record(task, history / "trajectories" / tid, output.parent / "no_historical_verdict",
                                     markers, set(q["evidence_docs"]), set(q["gold_docs"]))
        count["sampled_training_trajectories_examined"] += 1
        count[row["stage_accounting"]] += 1
        count["stages"] += len(stages)
        count["unparsed_returns"] += sum(not s["return_parsed"] for s in stages)
        count["unfed_terminal_returns"] += sum(s["terminal_unfed"] for s in stages)
        count["strict_repeat"] += sum(s["strict_repeat"] for s in stages)
    count["historical_trajectories_reused_for_scoring"] = 0
    count["heldout_trajectories_read"] = 0
    with output.open("x", encoding="utf-8") as handle:
        json.dump(count, handle, indent=2)
        handle.write("\n")
    print(json.dumps(count), flush=True)


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
