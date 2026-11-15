"""Freeze a question-only task specification."""

from hashlib import sha256

from .common import JudgeFailure, exact_quote, identity, require


def task_spec(question, question_hash):
    return {"question": question, "question_sha256": question_hash,
            "constraints": [], "uncertain": True, "status": "ok"}


def initial_ledger(task):
    return {"stage_id": None, "support": {}, "documents": [], "attempts": [],
            "visibility": [], "open_gaps": [c["constraint_id"] for c in task["constraints"]],
            "candidate_gaps": {}, "conflicts": [],
            "unresolved_evidence_risk": {"global": [], "by_support": {}}}


def init_task_ledger(question, judge):
    task = task_spec(question, identity(question))
    try:
        response = judge.ask("task_constraints", {"question": question})
        rows = response.get("constraints")
        require(isinstance(rows, list) and bool(rows), "missing task constraints")
        require(type(response.get("uncertain")) is bool, "missing task uncertainty")
        quotes = [exact_quote(question, row) for row in rows]
        require(len({(q["start"], q["end"]) for q in quotes}) == len(quotes), "duplicate constraint")
        task["constraints"] = [{"constraint_id": f"C{i}", "text": q["quote"], "source": q}
                               for i, q in enumerate(quotes, 1)]
        task["uncertain"] = response["uncertain"]
    except (JudgeFailure, AttributeError, TypeError) as exc:
        task.update(status="annotation_error", error=str(exc))
    return task, initial_ledger(task)


def init_task_ledger_frozen(question, frozen_row):
    """Initialize from the sealed v4 record without asking a Judge."""
    task = task_spec(question, sha256(question.encode("utf-8")).hexdigest())
    try:
        require(bool(frozen_row), "missing frozen v4 constraints for question")
        require(frozen_row["question_sha256"] == task["question_sha256"], "frozen v4 question SHA-256 mismatch")
        rows = frozen_row["constraints"]
        require(isinstance(rows, list) and bool(rows), "empty frozen v4 constraints")
        constraints = []
        for i, row in enumerate(rows, 1):
            require(row["constraint_id"] == f"C{i}" and isinstance(row["text"], str)
                    and isinstance(row["keywords"], list) and all(isinstance(k, str) for k in row["keywords"])
                    and row["origin"] in ("extract", "audit") and type(row["certain"]) is bool,
                    "invalid frozen v4 constraint")
            constraints.append({key: row[key] for key in ("constraint_id", "text", "keywords", "origin", "certain")})
        notes = {key: frozen_row[key] for key in ("answer_type", "answer_format", "global_notes")}
        require(all(isinstance(notes[key], str) for key in ("answer_type", "answer_format"))
                and isinstance(notes["global_notes"], list) and all(isinstance(note, str) for note in notes["global_notes"]),
                "invalid frozen v4 answer metadata")
        task.update(constraints=constraints, uncertain=False, constraint_source="frozen_v4", **notes)
    except (JudgeFailure, KeyError, TypeError) as exc:
        task.update(status="annotation_error", error=str(exc))
    return task, initial_ledger(task)
