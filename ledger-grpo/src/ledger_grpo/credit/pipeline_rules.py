"""Mechanical input selection and answer validation for the frozen v12 prompts."""
import re
import unicodedata
from . import ledger

WORD = re.compile(r"(?<!\w)[’']?[0-9]+\s*[sS]\b|[^\W_]+")
STOP = set("about above across after again along among another before being below between could during "
           "every first found given having might other should since still their there these those through "
           "under until using where which while whose within without would years".split())


def words(source):
    return WORD.findall(unicodedata.normalize("NFKC", source))


def compact_text(source):
    return "".join(c for c in unicodedata.normalize("NFKC", source).casefold() if c.isalnum())


def word_root(token):
    key = token.casefold().replace("’", "'").replace(" ", "")
    decade = re.fullmatch(r"'?(\d{2}|\d{4})s", key)
    if decade:
        return "decade:" + decade[1][-2:] if len(decade[1]) == 2 else "century_decade:" + decade[1]
    if len(key) >= 6 and key.isascii() and key.isalpha():
        if key.endswith("ing"):
            key = key[:-3]
        elif key.endswith("ed"):
            key = key[:-2]
        elif key.endswith("s") and not key.endswith("ss"):
            key = key[:-1]
        if len(key) > 4 and key.endswith("e"):
            key = key[:-1]
    return key


def restriction_errors(rows, question, known):
    phrase = compact_text(question)
    original = {word_root(x) for x in words(question)}
    rejects = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            rejects.append({"index": index, "value": row, "reason": "malformed"})
            continue
        exact, restricted = row.get("question_phrase"), row.get("words")
        reason = None
        if not isinstance(exact, str) or not compact_text(exact) or compact_text(exact) not in phrase:
            reason = "question_phrase_not_found"
        elif not isinstance(restricted, str) or not words(restricted):
            reason = "empty_words"
        elif any(ledger.same(restricted, name) for name in known):
            reason = "known_object"
        else:
            roots = {word_root(x) for x in words(restricted)}
            def already_present(root):
                return root in original or (root.startswith("decade:") and
                    any(old.startswith("century_decade:") and old[-2:] == root[-2:] for old in original))
            if all(already_present(root) for root in roots):
                reason = "question_words"
        if reason:
            rejects.append({"index": index, "value": row, "reason": reason})
    return rejects


def select_sentences(docs, names, conditions):
    normalized_names = {tuple(x.casefold() for x in words(ledger.clean(n))) for n in names if n and n != "未知"}
    normalized_names.discard(())
    normalized_names |= {tuple(t for t in n if len(t) != 1) for n in normalized_names if len(n) >= 3}
    normalized_names.discard(())
    keywords = {word_root(x) for c in conditions for x in words(c["text"])
                if any(ch.isdigit() for ch in x) or (len(x) >= 5 and x.casefold() not in STOP)}

    def mentions(source):
        terms = tuple(x.casefold() for x in words(source))
        for name in normalized_names:
            length = len(name)
            for width in (length, length + 1):
                for i in range(max(0, len(terms) - width + 1)):
                    span = terms[i:i+width]
                    if span == name or (length >= 2 and tuple(t for t in span if len(t) != 1) == name):
                        return True
        return False

    output, log = [], []
    for doc in docs:
        sentences = doc["sentences"]
        whole = mentions(doc["title"] or "") or any(mentions(row["text"]) for row in sentences)
        chosen = (sentences[:60] if whole else
                  [row for row in sentences if any(word_root(word) in keywords for word in words(row["text"]))][:10])
        kept = [s["id"] for s in chosen]
        output.append({"docid": doc["docid"], "title": doc["title"], "sentences": chosen})
        log.append({"docid": doc["docid"], "mode": "name" if whole else "keyword",
                    "kept_ids": kept, "discarded_ids": [s["id"] for s in sentences if s["id"] not in kept]})
    return output, log


def valid_ids(values, allowed):
    return isinstance(values, list) and all(isinstance(x, str) and x in allowed for x in values)


def label_text(text):
    return isinstance(text, str) and bool(text.strip())


def validate_q1(value, conditions):
    if not isinstance(value, dict) or not isinstance(value.get("targets"), list) or not isinstance(value.get("restrictions"), list):
        return ["targets 和 restrictions 必须是数组"]
    if any(not isinstance(r, dict) or not label_text(r.get("object")) or not valid_ids(r.get("conditions"), conditions)
           for r in value["targets"]):
        return ["targets 每项必须有对象名，且 conditions 只能用本题编号"]
    return []


def fact_rows(value, conditions, shown):
    rows, rejected = [], []
    for index, row in enumerate(value["facts"]):
        reason = None
        if not isinstance(row, dict) or not label_text(row.get("about")) or not label_text(row.get("fact")):
            reason = "missing_object_or_fact"
        elif not isinstance(row.get("condition"), str) or row["condition"] not in conditions:
            reason = "condition_not_in_list"
        elif not valid_ids(row.get("ids"), shown) or not row["ids"]:
            reason = "citation_not_shown"
        elif row.get("effect") not in ("满足", "不满足") or row.get("explicit") not in ("是", "否"):
            reason = "invalid_effect_or_explicit"
        if reason:
            rejected.append({"index": index, "value": row, "reason": reason})
        else:
            rows.append({"about": row["about"], "fact": row["fact"], "ids": list(dict.fromkeys(row["ids"])),
                         "conditions": [{"id": row["condition"], "effect": "支持" if row["effect"] == "满足" else "冲突"}],
                         "strength": "直接" if row["explicit"] == "是" else "推断"})
    return rows, rejected


def tokens_for_claim(claim):
    claim = unicodedata.normalize("NFKC", claim)
    pattern = r"(?<![A-Za-z0-9])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![0-9])|(?<![A-Za-z])(?:[A-Z][A-Za-z]+)(?:(?:[ \t]+)(?:[A-Z][A-Za-z]+|[A-Z]\.))*"
    return list(dict.fromkeys(m[0] for m in re.finditer(pattern, claim)))


def normalize_q3(value, allowed):
    if not isinstance(value, dict):
        return {}, None, ["输出必须为 JSON 对象"]
    errors, verdicts = [], {}
    raw = value.get("verdicts")
    if not isinstance(raw, dict):
        errors.append("verdicts 必须是对象")
    else:
        for key, verdict in raw.items():
            if key in allowed and verdict in ("用了", "不信", "没提"):
                verdicts[key] = verdict
            else:
                errors.append(f"无效的证据编号或裁决：{key}")
    claims = value.get("claims")
    if not isinstance(claims, list) or any(not label_text(r) for r in claims):
        errors.append("claims 必须是字符串数组")
        claims = None
    return verdicts, claims, errors


def usable_dropped(value):
    source = value.get("dropped") if isinstance(value, dict) else None
    if not isinstance(source, list):
        return []
    return [r for r in source if isinstance(r, dict) and label_text(r.get("object")) and label_text(r.get("reason"))]


def validate_q4(value, conditions):
    if not isinstance(value, dict):
        return ["输出必须为 JSON 对象"]
    errors = []
    answer = value.get("answer")
    if "answer" not in value or (answer is not None and not label_text(answer)):
        errors.append("answer 必须是名字或 null")
    dropped = usable_dropped(value)
    if not isinstance(value.get("dropped"), list) or len(dropped) != len(value["dropped"]):
        errors.append("dropped 必须有具体对象和理由")
    if answer is not None and label_text(answer) and any(ledger.same(answer, r["object"]) for r in dropped):
        errors.append("answer 不能与本步 dropped 对象相同")
    linked = value.get("linked")
    if not isinstance(linked, list) or any(not isinstance(r, dict) or not label_text(r.get("object"))
                                           or not valid_ids(r.get("conditions"), conditions) for r in linked):
        errors.append("linked 必须是具名对象及本题条件编号")
    return errors


def validate_q5(value, conditions):
    if not isinstance(value, dict) or value.get("basis") not in ("条件", "题外", "无依据") or value.get("valid") not in ("成立", "不成立", "看不出"):
        return ["basis 或 valid 不是提示词指定的选项"]
    refs = value.get("basis_conditions")
    if not valid_ids(refs, conditions) or (value["basis"] == "条件" and not refs):
        return ["basis_conditions 必须使用本题的条件编号，basis 为条件时不能为空"]
    return []

def normalized_name(text):
    text=unicodedata.normalize("NFKC",text).casefold()
    return " ".join(re.findall(r"[^\W_]+",text))

def ground_answer(answer,sources):
    if not isinstance(answer,str) or not answer.strip():
        return None
    name=normalized_name(answer)
    if not name:
        return None
    left="" if "\u3400" <= name[0] <= "\u9fff" else r"(?<!\w)"
    right="" if "\u3400" <= name[-1] <= "\u9fff" else r"(?!\w)"
    pattern=re.compile(left+re.escape(name)+right)
    for kind,texts in sources.items():
        if any(pattern.search(normalized_name(s)) for s in texts if isinstance(s,str)):
            return kind
    return None

def select_all_new(docs):
    return docs,[{"docid":doc["docid"],"mode":"unfiltered",
                  "kept_ids":[r["id"] for r in doc["sentences"]],"discarded_ids":[]} for doc in docs]

def prior_candidates(steps):
    names=[]
    for row in steps:
        chain=row.get("answer_chain") or {}
        candidates=[r["object"] for r in row.get("targets",[])]
        candidates.append(chain.get("answer"))
        candidates.extend(x["object"] for x in chain.get("linked",[]))
        candidates.extend(x["object"] for x in row.get("excluded",[]))
        for name in candidates:
            if not isinstance(name,str) or (name:=name.strip()) in ("",ledger.UNKNOWN):
                continue
            if not any(ledger.same(name,other) for other in names):
                names.append(name)
                if len(names)==30:
                    return names
    return names

Q1_CONFIGS = ({"temperature": 0, "seed": 2026112004}, {"temperature": 0.7, "seed": 2026112005}, {"temperature": 0.7, "seed": 2026112006})

def combine_votes(calls, question, known):
    ballots = []
    for index, call in enumerate(calls, 1):
        restrictions = (call["parsed"] or {}).get("restrictions", [])
        invalid = restriction_errors(restrictions, question, known)
        rejected = {item["index"] for item in invalid}
        kept = [item["words"].strip() for j, item in enumerate(restrictions) if j not in rejected]
        ballots.append({"number": index, "yes": bool(kept), "restrictions": kept,
                        "rejected": invalid, "call": call})
    yes = sum(ballot["yes"] for ballot in ballots)
    majority = yes >= 2
    restriction = "；".join(next(b["restrictions"] for b in ballots if b["yes"])) if majority else ""
    first = calls[0]["parsed"] or {}
    targets = [{"object": row["object"], "conditions": row["conditions"], "restriction": restriction}
               for row in first.get("targets", [])]
    return targets, {"ballots": ballots, "yes_count": yes, "has_restriction": majority,
                     "restriction": restriction, "changed_from_primary": majority != ballots[0]["yes"]}

def check_document_facts(value):
    if not isinstance(value, dict) or not isinstance(value.get("facts"), list):
        return ["facts 必须是数组"]
    errors = []
    if len(value["facts"]) > 3:
        errors.append("同一篇文档最多 3 条 facts")
    for index, fact in enumerate(value["facts"], 1):
        if not isinstance(fact, dict) or fact.get("broad") not in ("是", "否"):
            errors.append(f"第 {index} 条事实必须带 broad，且只能为“是”或“否”")
    return errors

def facts_with_broad(value, ids, shown):
    facts, rejected = fact_rows(value, ids, shown)
    bad = {row["index"] for row in rejected}
    flags = (row["broad"] for index, row in enumerate(value["facts"]) if index not in bad)
    return [{**fact, "broad": flag} for fact, flag in zip(facts, flags, strict=True)], rejected

def inherited_q0(value):
    if not isinstance(value,dict):
        return ["输出必须是对象"]
    conditions=value.get("conditions")
    errors=[]
    if not isinstance(conditions,list) or len(conditions)<3 or any(
        not isinstance(c,dict) or not isinstance(c.get("text"),str) or not c["text"].strip()
        for c in conditions
    ):
        errors.append("conditions 至少包含 2 条 c 条件及最后的 A，每条都需要非空 text")
    else:
        expected=[f"c{i}" for i in range(1,len(conditions))]+["A"]
        if [c.get("id") for c in conditions] != expected:
            errors.append("conditions 编号必须依次为 c1、c2……，最后为 A")
        if not conditions[-1]["text"].startswith("Asked:"):
            errors.append("最后一个条件的 text 必须以 Asked: 开头")
    answer=value.get("answer_type")
    if not isinstance(answer,str) or not answer.strip():
        errors.append("answer_type 必须是非空字符串")
    return errors

def validate_q0(value):
    errors = inherited_q0(value)
    if not errors and len(value["conditions"]) - 1 > 10:
        errors.append("c 开头的条件不超过 10 条，请合并同一对象同一件事的细节")
    return errors
