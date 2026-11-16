"""Deterministic BrowseComp-Plus DocID exposure and action labels."""

from copy import deepcopy
import json
import re
import unicodedata

from .common import identity


R1_TRIGGER = re.compile(r"(?i)\b(verify|verifying|confirm|confirming|confirmation|double-check|make sure)\b")


def normalize_query(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def passages_from_return(text):
    value = json.loads(text)
    if isinstance(value, dict):
        value = value.get("results", [value])
    if not isinstance(value, list):
        raise ValueError("search return must be a list of documents")
    passages = {}
    for row in value:
        docid, snippet = row["docid"], row["snippet"]
        if type(docid) is int:
            docid = str(docid)
        if not isinstance(docid, str) or not docid.strip() or not isinstance(snippet, str):
            raise ValueError("search return lacks a DocID or passage")
        passages.setdefault(docid.strip(), snippet)
    return passages


def evidence_labels(content):
    rows = {}
    for line in content.decode("utf-8-sig").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        qid = str(row["question_id"])
        if qid in rows:
            raise ValueError("duplicate evidence label question")
        for name in ("evidence", "gold"):
            ids = row[name]
            if (not isinstance(ids, list) or any(not isinstance(k, str) or not k.isdecimal() for k in ids)
                    or len(ids) != len(set(ids))):
                raise ValueError("invalid evidence label DocIDs")
        rows[qid] = row
    return rows


def bind_labels(task, labels):
    return {**task, "phase1_mode": "docid", "evidence_labels_missing": labels is None,
            "evidence_doc_ids": labels["evidence"] if labels is not None else [],
            "gold_doc_ids": labels["gold"] if labels is not None else []}


def docid_update(task, before, stage, event):
    after = deepcopy(before)
    action = stage.get("action")
    after.update(stage_id=stage["stage_id"], visibility=list(stage.get("visible_return_ids", ())))
    delta = {"status": "unavailable", "effective_gain": None, "new_documents": [], "new_evidence": [],
             "new_support": [], "strengthening": [], "conflicts": [], "resolved_conflicts": [],
             "evidence": [], "rejected_evidence": []}
    visible = event.get("visible_next") and isinstance(event.get("return_text"), str) and not event.get("error")
    if visible:
        text = event["return_text"]
        passages = passages_from_return(text)
        docs = list(event["document_ids"])
        if docs != list(passages):
            raise ValueError("document IDs differ from the visible return")
        prior = set(before["documents"])
        evidence = set(task["evidence_doc_ids"])
        new = [docid for docid in docs if docid not in prior]
        new_evidence = [docid for docid in new if docid in evidence]
        after["documents"] = sorted(prior | passages.keys())
        ledger_passages = after.setdefault("evidence_passages", {})
        for docid in docs:
            if docid in evidence:
                ledger_passages.setdefault(docid, passages[docid])
        delta.update(status="ok", effective_gain=bool(new_evidence), new_documents=new, new_evidence=new_evidence)
        content_id = identity(text)
    else:
        docs, content_id = [], None
    after["attempts"].append({"stage_id": stage["stage_id"], "event_id": event["event_id"], "action": action,
                              "content_id": content_id, "document_ids": docs, "status": delta["status"],
                              "gain": delta["effective_gain"], "error": event.get("error")})
    return after, delta


def planned_query(action):
    query = (action.get("arguments") or {}).get("query") if isinstance(action.get("arguments"), dict) else None
    return normalize_query(query) if isinstance(query, str) else None


def result_label(task, history, event, action, delta):
    if delta["status"] != "ok":
        return "no_return"
    query = planned_query(action)
    if query is not None and any(query == planned_query(row.get("action") or {}) for row in history):
        return "repeat_query"
    if not delta["new_documents"]:
        return "no_new_information"
    if delta["new_evidence"]:
        return "effective"
    if set(event["document_ids"]) & set(task["evidence_doc_ids"]):
        return "repeat_evidence"
    return "ineffective"


def judge_docid_stage(task, before, stage, event, target, delta, comparable, record_only):
    action = stage.get("action") or {}
    spans = stage.get("charge_token_spans") or []
    visible_ids = set(stage.get("visible_return_ids", ()))
    history = before["attempts"]
    has_return = delta["status"] == "ok"
    protocol_ok = stage.get("parse_status") == "ok"
    action_key = comparable(action, docid=True)
    docs = set(event.get("document_ids", ()))
    repeated = [past for past in history if action_key and comparable(past.get("action") or {}, docid=True) == action_key]
    content_id = identity(event["return_text"]) if has_return else None
    exact = [p for p in repeated if has_return and p.get("status") == "ok" and not p.get("error")
             and (docs == set(p.get("document_ids", ())) or content_id == p.get("content_id"))]
    protections = []
    if target.get("intent") in {"resolve_conflict", "strengthen", "open_fulltext", "recover", "retry"}:
        protections.append({"resolve_conflict": "resolve_conflict", "strengthen": "independent_support",
                            "open_fulltext": "summary_to_fulltext", "recover": "restore_invisible_evidence",
                            "retry": "tool_failure_retry"}[target["intent"]])
    if delta.get("effective_gain"):
        protections.append("effective_evidence" if history else "first_evidence")
    if repeated and repeated[-1].get("error"):
        protections.append("tool_failure_retry")
    if exact and not any(p["event_id"] in visible_ids for p in exact):
        protections.append("restore_invisible_evidence")
    r2b = ("positive" if exact and not protections else "negative") if (
        protocol_ok and has_return and action_key) else "abstain"
    subtype = None
    if protocol_ok and has_return and r2b != "positive" and not protections:
        if not delta["new_documents"]:
            subtype = "zero_new_info"
        elif docs & set(task["evidence_doc_ids"]) and not delta["new_evidence"]:
            subtype = "repeated_evidence"
    r2a = ("positive" if subtype else "negative") if protocol_ok and has_return else "abstain"
    r1_reason = target.get("skip_reason")
    cited = target.get("passage_ids", [])
    allowed = {"P" + docid for docid in before.get("evidence_passages", {})}
    valid_citation = (target.get("already_stated") is True and bool(cited)
                      and set(cited) <= allowed and set(cited) <= set(target.get("provided_passage_ids", ()))
                      and not target.get("format_conflict"))
    if not protocol_ok:
        r1_reason = "protocol_error"
    r1 = ("abstain" if r1_reason else "positive" if valid_citation and r2b != "positive" and not protections
          else "negative")
    r1_terms = ([term.lower() for term in R1_TRIGGER.findall((stage.get("m3_reasoning") or "")[-400:])]
                if r1 == "positive" else [])
    r1_confidence = ("high" if r1_terms else "normal") if r1 == "positive" else None
    positionable = (stage["stage_type"] == "tool" and protocol_ok and not stage.get("parallel_group_id") and bool(spans))

    def label(name, decision, reason=None, evidence=()):
        known_at = event.get("return_time") if has_return else None
        return {"label": name, "decision": decision, "protected": bool(protections),
                "reward_eligible": (name == "R2b" or (name == "R1" and not record_only))
                                   and decision == "positive" and positionable,
                "known_at": known_at, "decision_time": "after_return" if known_at else "unavailable",
                "abstention_reason": reason if decision == "abstain" else None, "evidence": list(evidence)}

    abstention = ("protocol_error" if not protocol_ok else "successful_visible_return_missing" if not has_return
                  else "comparison_environment_or_arguments_unverified")
    exact_ids = [p["event_id"] for p in exact if p["event_id"] in visible_ids]
    labels = [label("R2b", r2b, abstention, exact_ids),
              label("R1", r1, r1_reason, cited if valid_citation else ()),
              label("R2a", r2a, abstention)]
    price = next((row["label"] for row in labels if row["reward_eligible"]), None)
    return {"stage_id": stage["stage_id"], "event_id": event["event_id"], "labels": labels,
            "price_label": price, "protections": sorted(set(protections)), "risk_guard_reason": None,
            "risk_guard_refs": [], "pricing_blocked_by_risk": False, "charge_token_spans": spans if price else [],
            "position_strategy": "verified_call_envelope" if price else "unpriced",
            "diagnostics": {"r1_check": target.get("already_stated"),
                            "r1_funnel": {"outcome": r1, "reason": r1_reason},
                            "r1_confidence": r1_confidence, "r1_trigger_terms": r1_terms,
                            "r2a_similarity": 0.0, "same_gap_attempts": [], "effective_gain": delta["effective_gain"],
                            "exact_repeat_ids": exact_ids, "r2a_subtype": subtype,
                            "r2a_whatif_token_spans": spans if r2a == "positive" and positionable else [],
                            "result_label": result_label(task, history, event, action, delta)}, "errors": []}


def grounding_coverage(task, ledger):
    expected = set(task["evidence_doc_ids"])
    if task["evidence_labels_missing"] or not expected:
        return None, "evidence_labels_missing" if task["evidence_labels_missing"] else "evidence_docs_empty"
    return len(expected & set(ledger["documents"])) / len(expected), None
