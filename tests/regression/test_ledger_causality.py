from redundancy_judge.init_task_ledger import init_task_ledger
from redundancy_judge.update_evidence_ledger import update_evidence_ledger


def test_rewording_actor_assertion_does_not_change_evidence_support():
    class Fixture:
        synthetic = True

        def ask(self, kind, payload):
            if kind == "task_constraints":
                return {"constraints": [{"quote": "capital of France"}], "uncertain": False}
            assert "strategy" not in payload
            assert "future" not in payload
            text = payload["returned_text"]
            return {"uncertain": False, "updates": [{"candidate": "Paris", "constraint_id": "C1",
                "state": "supported", "quote": text}]}

    judge = Fixture()
    task, before = init_task_ledger("Name the capital of France.", judge)
    stage = {"stage_id": "s", "parse_status": "ok", "strategy_text": "Already confirmed: London"}
    event = {"event_id": "1", "visible_next": True, "return_text": "Paris is the capital of France."}
    asserted, delta = update_evidence_ledger(task, before, stage, event, judge)
    cautious, changed = update_evidence_ledger(
        task, before, {**stage, "strategy_text": "", "future": "London"}, event, judge)
    assert asserted["support"] == cautious["support"]
    assert delta == changed
