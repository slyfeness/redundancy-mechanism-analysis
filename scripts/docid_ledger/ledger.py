"""Deterministic document exposure and redundancy rules for the DocID trial."""

from collections import defaultdict
from dataclasses import dataclass
from itertools import groupby
import json
import re
import unicodedata


SIGNALS = ("repeat_open_evidence", "repeat_open_other", "search_no_new_evidence",
           "search_exact_repeat", "search_jaccard_repeat")
ID_FIELDS = ("docid", "document_id")


def normalized(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def document_id(value):
    if type(value) is int or isinstance(value, str) and value.strip():
        return str(value).strip()
    return None


def metadata(text):
    boundary = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text.lstrip(), re.S)
    if not boundary:
        return {}
    pairs = (line.partition(":") for line in boundary[1].splitlines())
    return {key: value.strip() for key, separator, value in pairs if separator and key in {"title", "url"}}


def records(payload):
    if isinstance(payload, str):
        try:
            value = json.loads(payload)
        except ValueError:
            info = metadata(payload)
            return [info] if info else []
    else:
        value = payload
    if isinstance(value, dict):
        value = value.get("results", [value])
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


class DocumentIndex:
    def __init__(self):
        self.ids = set()
        self.urls = defaultdict(set)
        self.titles = defaultdict(set)

    def add(self, id_value, title=None, url=None):
        self.ids.add(id_value)
        if title:
            self.titles[title].add(id_value)
        if url:
            self.urls[url].add(id_value)

    def identify(self, payload):
        identified = {}
        for record in records(payload):
            direct = {identifier for key in ID_FIELDS if (identifier := document_id(record.get(key))) is not None}
            if direct:
                if len(direct) == 1:
                    docid = next(iter(direct))
                    if docid in self.ids:
                        identified[docid] = "direct"
                continue
            by_url = self.urls.get(record.get("url"), set()) if isinstance(record.get("url"), str) else set()
            by_title = self.titles.get(record.get("title"), set()) if isinstance(record.get("title"), str) else set()
            possible = (by_url & by_title) if by_url and by_title else by_url or by_title
            if len(possible) == 1:
                identified.setdefault(next(iter(possible)), "url" if by_url else "title")
        return identified


@dataclass(frozen=True)
class Observation:
    event_id: str
    round_id: int
    kind: str
    docids: tuple
    query: str | None
    visible: bool


def rounds(events):
    ordered = sorted(events, key=lambda event: event.round_id)
    return groupby(ordered, key=lambda event: event.round_id)


def search_repeat(query, history):
    query = normalized(query)
    if not query:
        return None
    previous = {normalized(entry) for entry in history}
    if query in previous:
        return "search_exact_repeat"
    terms = set(re.findall(r"\w+", query))
    for entry in previous:
        other = set(re.findall(r"\w+", entry))
        if terms | other and len(terms & other) / len(terms | other) >= 0.8:
            return "search_jaccard_repeat"
    return None


def evidence_exposure(events, evidence, gold):
    first_seen, first_opened, queries = {}, {}, []
    signals = dict.fromkeys(SIGNALS, 0)
    for round_id, batch in rounds(events):
        to_see, to_open, to_query = set(), set(), []
        for event in batch:
            if event.kind == "search":
                if event.query:
                    if signal := search_repeat(event.query, queries):
                        signals[signal] += 1
                    to_query.append(event.query)
                if event.visible:
                    matched = set(event.docids) & evidence
                    if matched and matched <= first_seen.keys():
                        signals["search_no_new_evidence"] += 1
                    to_see.update(event.docids)
            if event.kind == "open" and event.visible:
                for identifier in event.docids:
                    if identifier in first_opened:
                        signal = "repeat_open_evidence" if identifier in evidence else "repeat_open_other"
                        signals[signal] += 1
                to_open.update(event.docids)
        queries.extend(to_query)
        for identifier in sorted(to_see):
            first_seen.setdefault(identifier, round_id)
        for identifier in sorted(to_open):
            first_opened.setdefault(identifier, round_id)
    return {
        "first_seen": {key: first_seen[key] for key in sorted(evidence & first_seen.keys())},
        "first_opened": {key: first_opened[key] for key in sorted(evidence & first_opened.keys())},
        "seen_recall": len(evidence & first_seen.keys()) / len(evidence) if evidence else None,
        "opened_recall": len(evidence & first_opened.keys()) / len(evidence) if evidence else None,
        "gold_seen": len(gold & first_seen.keys()),
        "gold_opened": len(gold & first_opened.keys()),
        "signals": signals,
    }


def has_keyword(query, keyword):
    if not keyword:
        return False
    return any(
        (not keyword[0].isalnum() or match.start() == 0 or not query[match.start() - 1].isalnum())
        and (not keyword[-1].isalnum() or match.end() == len(query) or not query[match.end()].isalnum())
        for match in re.finditer(re.escape(keyword), query)
    )


def keyword_decision(query, keywords, confirmed):
    query = normalized(query)
    hits = {cid for cid, words in keywords.items() if any(has_keyword(query, normalized(word)) for word in words)}
    if hits & confirmed:
        return "pending" if hits - confirmed else "r1"
    return "neither"


def proposal_events(events, document_support, keywords):
    first_seen, first_confirmed, r1_a, searches = {}, {}, [], []
    for round_id, batch in rounds(events):
        confirmed = set(first_confirmed)
        to_confirm = set()
        for event in batch:
            if event.kind == "search" and event.query and confirmed:
                searches.append({"event_id": event.event_id, "round_id": round_id,
                                 "decision": keyword_decision(event.query, keywords, confirmed),
                                 "confirmed": sorted(confirmed)})
            if not event.visible:
                continue
            for docid in event.docids:
                support = document_support.get(docid, set())
                if event.kind == "search":
                    for cid in sorted(support):
                        first_seen.setdefault(cid, round_id)
                if event.kind == "open":
                    if support and support <= confirmed:
                        r1_a.append({"event_id": event.event_id, "round_id": round_id, "docid": docid})
                    to_confirm.update(support)
        for cid in sorted(to_confirm):
            first_confirmed.setdefault(cid, round_id)
    return {"first_seen": first_seen, "first_confirmed": first_confirmed, "r1_a": r1_a, "searches": searches}
