"""Domain-isolated exact-match outcomes for the A/C test update only."""
import unicodedata

RESULT_SOURCE = "local_strict_match_test_only"


def normalize_answer(text):
    if not isinstance(text, str):
        raise ValueError("strict matching requires text")
    text = unicodedata.normalize("NFKC", text).casefold()
    start, end = 0, len(text)
    while start < end and (text[start].isspace() or unicodedata.category(text[start]).startswith("P")):
        start += 1
    while start < end and (text[end - 1].isspace() or unicodedata.category(text[end - 1]).startswith("P")):
        end -= 1
    return text[start:end]


def strict_match_updates(core_rows, native_batch, answers, gold, *, snapshot):
    """Store only a test outcome. The standard scorer's projection is in-memory."""
    core = {row["traj_id"]: row for row in core_rows}
    if len(core) != len(core_rows) or core.keys() != {row["id"] for row in native_batch["trajectories"]}:
        raise ValueError("test outcome inputs differ from the original trajectory set")
    receipts, scoring, native_rows = [], [], []
    for row in native_batch["trajectories"]:
        tid, qid = row["id"], row["query_id"]
        receipt = core[tid]
        final = row["terminal"] == "MODEL_FINAL_STOP"
        if final and (receipt["outcome"] is not None or row["reward"] is not None):
            raise ValueError("a test outcome may not replace an existing official result")
        reference = normalize_answer(gold[qid]) if final else None
        if final and not reference:
            raise ValueError("empty official answer after test normalization")
        outcome = int(final and normalize_answer(answers[tid]) == reference)
        receipts.append({"traj_id": tid, "task_id": qid, "policy_snapshot_id": snapshot,
                         "test_outcome": outcome, "result_source": RESULT_SOURCE, "had_final": final})
        scored = {**receipt, "outcome": outcome}
        if scored.get("exclusion_reason") == "independent_outcome_unresolved":
            scored.pop("exclusion_reason")
        scoring.append(scored)
        native_rows.append({**row, "reward": outcome})
    return receipts, scoring, {**native_batch, "trajectories": native_rows}
