"""Deterministic name repair, attribution, and Stage labeling for ledger-judge-v4.4."""

from collections import defaultdict
from pathlib import Path
import re
import sys
import unicodedata

FLAGS = Path(__file__).resolve().parent.parent / "fpremise_probe"
if FLAGS.is_dir():
    sys.path.append(str(FLAGS))
from flags import name_key

VERSION = "ledger-judge-v4.4"
TITLES = {"judge", "dr", "mr", "ms", "prof"}
ARTICLES = {"the", "a", "an"}
CONNECTORS = ARTICLES | set("of de del da do dos des della di du van von la le and y e et al bin ben".split())
MONTHS = set("january february march april may june july august september october november december "
             "jan feb mar apr jun jul aug sep sept oct nov dec".split())
DAYS = set("monday tuesday wednesday thursday friday saturday sunday mon tue tues wed thu thur thurs fri sat sun".split())
ORDINARY_START = set(
    "find search show list look tell give get which who what where why how when "
    "name identify check verify compare confirm read see did does is are was were has have "
    "in on for about with without use using release released former early late recent "
    "interview article actor actress writer director band book film music published first "
    "second third winner founded title source question answer website facts history wiki Wikipedia".casefold().split()
)
HYPHEN = re.compile(r"[-\u2010-\u2015]")
TOKEN = re.compile(r"[^\W_]+(?:[-\u2010-\u2015'’][^\W_]+)*")
QUOTED = re.compile(r'"([^"\n]+)"|“([^”\n]+)”|(?<!\w)\x27([^\x27\n]+)\x27(?!\w)|‘([^’\n]+)’|«([^»\n]+)»')
YEAR = re.compile(r"(?:c(?:irca)?\.?\s*)?(?:\d{4}s?)(?:\s*[-–—/]\s*\d{2,4}s?)?", re.I)
BREAK = re.compile(r"[.!?;\n]")
STAGE_TAGS = ("F_new", "F_corrected", "semantic_repeat", "stale_return")
CATEGORIES = ("person", "place", "work", "organization", "other")


def surface_key(name, *, join_hyphens=False):
    raw = unicodedata.normalize("NFKC", name).translate(str.maketrans("", "", chr(34) + chr(39) + "“”‘’«»"))
    if join_hyphens:
        raw = re.sub(r"\s*[-\u2010-\u2015]\s*", "", raw)
    return name_key(raw)


def normalized(name, *, titles=True, join_hyphens=False):
    parts = surface_key(name, join_hyphens=join_hyphens).split()
    prefixes = ARTICLES | (TITLES if titles else set())
    while len(parts) > 1 and parts[0] in prefixes:
        parts.pop(0)
    return " ".join(parts)


def equivalent(first, second):
    if normalized(first, titles=False) == normalized(second, titles=False):
        return True
    if normalized(first) == normalized(second):
        return True
    return bool(HYPHEN.search(first + second)) and (
        normalized(first, join_hyphens=True) == normalized(second, join_hyphens=True))


def quoted_names(query):
    return [next(part for part in match.groups() if part is not None).strip()
            for match in QUOTED.finditer(query)]


def proper(name, quotes):
    if name_key(name) in {name_key(part) for part in quotes + quoted_names(name)}:
        return True
    words = TOKEN.findall(name)
    return bool(words) and all(word[0].isupper() or word in CONNECTORS for word in words) and any(
        word[0].isupper() for word in words)


def cap_spans(query, calendar):
    """Find adjacent capitalized words, allowing an internal lowercase connector."""
    spans, current, previous = [], [], None

    def flush():
        capitalized = [match[0] for match in current if match[0][0].isupper()]
        if len(capitalized) >= 2:
            spans.append(query[current[0].start():current[-1].end()])
        current.clear()

    for word in TOKEN.finditer(query):
        if previous is not None and not query[previous.end():word.start()].isspace():
            flush()
        if word[0][0].isupper() and name_key(word[0]) not in calendar:
            current.append(word)
        elif current and word[0] in CONNECTORS:
            current.append(word)
        else:
            while current and current[-1][0] in CONNECTORS:
                current.pop()
            flush()
        previous = word
    while current and current[-1][0] in CONNECTORS:
        current.pop()
    flush()
    return spans


def repair(original, query, variables, countries):
    quotes = quoted_names(query)
    reason, name = None, original
    var_keys = {name_key(var) for var in variables}
    if name != "none":
        key = name_key(name)
        if len(key.replace(" ", "")) <= 2 or key in var_keys:
            reason = "variable_or_short"
        elif not proper(name, quotes):
            reason = "non_proper_name"
    backfilled = False
    if name == "none" or reason:
        candidates = [part for part in [*quotes, *cap_spans(query, MONTHS | DAYS)]
                      if len(normalized(part).replace(" ", "")) > 2
                      and name_key(part) not in var_keys
                      and normalized(part) not in countries | MONTHS | DAYS
                      and not YEAR.fullmatch(part.strip())
                      and any(character.isalpha() for character in part)]
        name = max(candidates, key=len, default="none")
        backfilled = name != "none"
    return {"judge_main_name": original, "main_name": name,
            "normalized_name": normalized(name) if name != "none" else None,
            "discard_reason": reason, "backfilled": backfilled}


class AliasEvidence:
    def __init__(self, rows):
        self.raw = {}
        normalized_answers = defaultdict(set)
        for row in rows:
            pair = row["names"]["A"], row["names"]["B"]
            result = row["result"]
            if result in {"yes", "no"}:
                self.raw[self.key(*pair)] = result
                normalized_answers[self.key(*pair, normalize=normalized)].add(result)
        self.normalized = {pair: next(iter(results)) for pair, results in normalized_answers.items()
                           if len(results) == 1}

    @staticmethod
    def key(first, second, normalize=name_key):
        return tuple(sorted((normalize(first), normalize(second))))

    def get(self, first, second):
        return self.raw.get(self.key(first, second), self.normalized.get(self.key(first, second, normalized)))

    def same(self, first, second):
        return equivalent(first, second) or self.get(first, second) == "yes"


def match_options(item, table):
    name, category = item["main_name"], item["category"]
    direct = [var for var, (reference, _) in table.items() if equivalent(name, reference)]
    peers = [var for var, (_, kind) in table.items() if category is not None and kind == category]
    return direct, peers


def classify(item, table, owners, aliases):
    name, category = item["main_name"], item["category"]
    var, status, normalized_match = None, "none", False
    if name != "none":
        direct, peers = match_options(item, table)
        owner = owners.get(item["sought_condition"])
        checks = {var: aliases.get(name, table[var][0]) for var in peers} if not direct else {}
        positives = direct or [var for var, result in checks.items() if result == "yes"]
        if positives:
            exact_raw = [var for var in positives if name_key(name) == name_key(table[var][0])]
            pool = exact_raw or positives
            var = owner if owner in pool else pool[0]
            status = "correct"
            normalized_match = bool(direct) and name_key(name) != name_key(table[var][0])
        elif category is None:
            status = "category_unresolved"
        elif not peers:
            status = "aux"
        else:
            var = owner if owner in peers else peers[0] if len(peers) == 1 else None
            if var is None:
                status = "unattributed"
            else:
                status = "wrong_candidate" if all(result == "no" for result in checks.values()) else "alias_unresolved"
    return {**item, "var": var, "attribution": status, "normalized_match": normalized_match}


class Protection:
    def __init__(self):
        self.past = []

    def add(self, queries, final_names=()):
        candidates, observed = set(), []

        def add(name):
            candidates.add(frozenset(normalized(name, titles=False, join_hyphens=joined)
                                     for joined in (False, True)))

        for query in queries:
            query_keys = {f" {surface_key(query, join_hyphens=joined)} " for joined in (False, True)}
            observed.extend(query_keys)
            for phrase in [*quoted_names(query), *cap_spans(query, MONTHS), *final_names]:
                key = surface_key(phrase)
                words = key.split()
                if (len(words) >= 2 and len(words) == len(set(words))
                        and not YEAR.fullmatch(phrase.strip())
                        and any(f" {key} " in text for text in query_keys)):
                    add(phrase)
            lead, end = True, 0
            for word in TOKEN.finditer(query):
                lead |= bool(BREAK.search(query[end:word.start()]))
                end = word.end()
                token = word[0]
                key = surface_key(token)
                if token[0].isupper() and len(key) > 1 and key not in MONTHS | CONNECTORS and (
                        not lead or key not in ORDINARY_START):
                    add(token)
                if token[0].isalpha():
                    lead = False
        fresh = any(all(not any(f" {key} " in query for query in self.past) for key in variants)
                    for variants in candidates)
        self.past.extend(observed)
        return fresh


def settle(units, aliases, table):
    result, events, history = [], [], []
    first, outstanding, confirmed = {}, defaultdict(dict), set()
    spellings = defaultdict(dict)
    protection = Protection()

    def event(kind, idx, item, start, confirming, key):
        return {"trajectory_id": units[idx]["trajectory_id"], "stage_id": idx + 1, "event": kind,
                "var": key[0], "category": item["category"], "wrong_name": item["main_name"],
                "correct_name": table[key[0]][0], "first_stage": start + 1, "confirmation_stage": confirming + 1,
                "key": list(key), "search_window": {
                    label: units[pos]["searches"] if 0 <= pos < len(units) else []
                    for label, pos in (("before", idx - 1), ("current", idx), ("after", idx + 1))}}

    for index, unit in enumerate(units):
        if unit["stage_id"] != index + 1:
            raise ValueError("non-contiguous Stage IDs")
        items = unit["items"]
        names = {item["main_name"] for item in items if item["main_name"] not in (None, "none")}
        old = unit["labels"]
        valid, strict = not old["invalid"], old.get("strict_repeat", False)
        protected = protection.add(unit["searches"], names)
        possible_repeat = valid and not protected and not strict and not unit["C_new"] and (
            unit["seen_docids"] > 0 and unit["new_docids"] == 0)
        distances = []
        if possible_repeat:
            for name in sorted(names):
                steps = [step for known, step in history if aliases.same(name, known)]
                if steps:
                    distances.append(index - max(steps))
        labels = {**old, "F_new": False, "F_corrected": False,
                  "wrong_candidate": any(item["attribution"] == "wrong_candidate" for item in items),
                  "semantic_repeat": bool(distances), "stale_return": possible_repeat and bool(items) and not names,
                  "protected_new_hypothesis": protected}
        idle_type = "strict" if strict else "semantic" if labels["semantic_repeat"] or labels["stale_return"] else "none"
        row = {**unit, "labels": labels, "idle_type": idle_type, "semantic_repeat_distances": distances}
        result.append(row)
        if not valid:
            continue
        history.extend((name, index) for name in sorted(names))
        for item in items:
            var = item["var"]
            if item["attribution"] == "correct":
                for key, (wrong, start, confirming) in outstanding.pop(var, {}).items():
                    events.append(event("F_corrected", index, wrong, start, confirming, key))
                    labels["F_corrected"] = True
        for item in items:
            if item["attribution"] != "wrong_candidate":
                continue
            var, name = item["var"], item["main_name"]
            spellings_for_var = spellings[var]
            key = next((key for observed, key in spellings_for_var.items() if equivalent(name, observed)),
                       (var, normalized(name)))
            spellings_for_var[name] = key
            start, first_item = first.setdefault(key, (index, item))
            if index != start and key not in confirmed:
                confirmed.add(key)
                result[start]["labels"]["F_new"] = True
                outstanding[key[0]][key] = first_item, start, index
                events.append(event("F_new", start, first_item, start, index, key))
    return result, sorted(events, key=lambda rec: (rec["stage_id"], rec["event"], rec["key"]))


def signal(row, costs):
    labels = row["labels"]
    return {"trajectory_id": row["trajectory_id"], "stage_id": row["stage_id"], "C_new": row["C_new"],
            "F_new": int(labels["F_new"]), "F_corrected": int(labels["F_corrected"]),
            "idle_type": row["idle_type"], "protected_new_hypothesis": labels["protected_new_hypothesis"],
            "gen_tokens": costs[0], "return_tokens": costs[1], "invalid": labels["invalid"]}
