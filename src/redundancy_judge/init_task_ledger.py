"""Freeze a question-only task specification."""

from .common import JudgeFailure, exact_quote, identity, require


def init_task_ledger(question, judge):
    task = {"question": question, "question_sha256": identity(question),
            "constraints": [], "uncertain": True, "status": "ok"}
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
    ledger = {"stage_id": None, "support": {}, "documents": [], "attempts": [],
              "visibility": [], "open_gaps": [c["constraint_id"] for c in task["constraints"]],
              "candidate_gaps": {}, "conflicts": []}
    return task, ledger
