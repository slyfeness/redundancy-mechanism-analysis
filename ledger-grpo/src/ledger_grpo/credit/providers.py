"""Interchangeable recorded, synthetic and v13.4 Judge ledger sources."""
from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Protocol
import ast
import json

from . import ledger, ledger_v135
from .config import CreditConfig
from .sampling import select_group
from .judge import ReplayJudgeClient, HttpJudgeClient, HttpJudgeConfig
from .pipeline import execute, next_behaviour, WIRE
from .pipeline_checked import checked
from .pipeline_rules import validate_q0


def literal(value):
    if isinstance(value, str):
        try:
            return ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return value
    return value


def get(value, key, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def trajectories(group):
    return get(group, "trajectories", group)


def payload(call):
    call = call[0] if isinstance(call, list) else call
    return json.loads(call["attempts"][0]["receipt"]["request"]["messages"][1]["content"])


def reference_length(value):
    value = literal(value)
    if isinstance(value, list):
        return sum(len(x.get("text", "")) if isinstance(x, dict) else len(str(x)) for x in value)
    return len(str(value or ""))


@dataclass
class LedgerResult:
    records: list
    derived: list
    conds: list
    confident: dict
    tokens: dict = field(default_factory=dict)
    rows: list = field(default_factory=list)
    rendered: str = ""
    stats: dict = field(default_factory=dict)
    records_b: list | None = None
    derived_b: list | None = None
    rows_b: list = field(default_factory=list)

    def __iter__(self):
        return iter((self.records, self.derived, self.conds, self.confident))


class LedgerProvider(Protocol):
    def build(self, group) -> list[LedgerResult]: ...


def _shared_conditions(results):
    if results:
        conditions = next((result.conds for result in results if result.conds), [])
        if any(result.conds and result.conds != conditions for result in results):
            raise ValueError("All trajectories in one group must share exactly one condition list")
        for result in results:
            if result.conds or not result.records:
                result.conds = conditions
    return results


class RecordedLedgerProvider:
    def __init__(self, state_root, *, variant="a", confidence_root=None, compare_b=False):
        self.state_root = Path(state_root)
        if variant not in ("a", "b"):
            raise ValueError("variant must be a or b")
        self.variant = variant
        self.confidence_root = Path(confidence_root) if confidence_root else self.state_root.parent / "CONFIDENCE"
        self.compare_b = compare_b

    def _read(self, trajectory_id, variant):
        path = self.state_root / trajectory_id / (variant + ".jsonl")
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _project(self, rows, conditions, cfg, gold, t_belief, group):
        records = [deepcopy(row["record"]) for row in rows]
        derived = [{key: literal(value) for key, value in row["derived"].items()} for row in rows]
        already_current = bool(derived and all("route" in row for row in derived))
        if cfg.use_q3 and already_current:
            raise ValueError("C_W_v211 requires saved v13.4 ledgers with Q3 verdicts")
        if already_current:
            ledger_v135.annotate_routes(records, derived, k_hold=cfg.k_hold, k_restrict=cfg.k_restrict)
        if cfg.use_q3 or not rows or already_current:
            return records, derived
        header = payload(rows[0]["calls"]["Q1"])
        returns_text, next_text = {}, {}
        for row in rows:
            step = row["step"]
            returns_text[step] = " ".join(
                sentence["text"] for call in row["calls"]["Q2"] for doc in payload(call)["返回句子"]
                for sentence in doc["sentences"]
            )
            later = payload(row["calls"].get("Q3") or row["calls"]["Q4"])
            next_text[step] = next_behaviour(later.get("下一轮思考"), later.get("下一次查询"), later.get("正式答案"))
        track = {"conditions": conditions, "group": group, "steps": records}
        projected = ledger_v135.run(track, returns_text, gold, t_belief, header["题目原文"], next_text,
                                    k_hold=cfg.k_hold, k_restrict=cfg.k_restrict)
        return projected["record"]["steps"], projected["steps"]

    def load(self, trajectory_id, *, config=None, gold=None, t_belief=None, group=None):
        if Path(trajectory_id).name != trajectory_id or trajectory_id in (".", ".."):
            raise ValueError("trajectory_id must be one path component")
        cfg = CreditConfig.from_params(config or {})
        rows = self._read(trajectory_id, self.variant)
        if not rows:
            return LedgerResult([], [], [], {})
        conditions = [condition["id"] for condition in literal(payload(rows[0]["calls"]["Q1"])["条件清单"])]
        records, derived = self._project(rows, conditions, cfg, gold, t_belief, group)
        token_counts = {t: reference_length(payload(row["calls"]["Q1"])["调用前思考"]) +
                        reference_length(payload(row["calls"]["Q1"])["本次查询"]) for t, row in enumerate(rows, 1)}
        final = payload(rows[-1]["calls"].get("Q3") or rows[-1]["calls"]["Q4"])
        token_counts["F"] = reference_length(final.get("下一轮思考")) + reference_length(final.get("正式答案"))
        confident = {row["step"]: True for row in rows}
        confidence_path = self.confidence_root / trajectory_id / "CONFIDENCE.jsonl"
        if cfg.use_q3 and confidence_path.is_file():
            for line in confidence_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    value = json.loads(line)
                    confident[value["step"]] = bool(value["agree"])
        other = "b" if self.variant == "a" else "a"
        second_path = self.state_root / trajectory_id / (other + ".jsonl")
        records_b = derived_b = None
        second = []
        if second_path.is_file() and (cfg.gate_two_pass or cfg.gate_low_conf or self.compare_b):
            second = self._read(trajectory_id, other)
            if [row["step"] for row in second] == [row["step"] for row in rows]:
                other_conditions = [condition["id"] for condition in literal(
                    payload(second[0]["calls"]["Q1"])["条件清单"])]
                if other_conditions != conditions:
                    raise ValueError("Paired ledgers must share the same conditions")
                records_b, derived_b = self._project(second, conditions, cfg, gold, t_belief, group)
                if not cfg.use_q3 or (self.compare_b and not confidence_path.is_file()):
                    confident.update(_confidence(derived, derived_b))
            else:
                records_b, derived_b = [], []
        confident["F"] = confident.get(rows[-1]["step"], True)
        return LedgerResult(records, derived, conditions, confident, token_counts, rows,
                            records_b=records_b, derived_b=derived_b, rows_b=second)

    def build(self, group, *, config=None):
        results = []
        for trajectory in trajectories(group):
            trajectory_id = get(trajectory, "trajectory_id") or get(trajectory, "traj_id")
            if not trajectory_id:
                trajectory_id = f"{get(trajectory, 'qid')}__rep{int(get(trajectory, 'rollout', 0)) + 1}"
            outcome = get(trajectory, "outcome", {})
            result_group = "C" if outcome.get("Y") else ("W" if outcome.get("submitted") else "N")
            metadata = get(trajectory, "metadata", {}).get("ledger_metadata", {})
            results.append(self.load(trajectory_id, config=config, gold=get(trajectory, "gold", metadata.get("gold")),
                                     t_belief=metadata.get("t_belief"), group=result_group))
        return _shared_conditions(results)

    build_for_credit = build


def _confidence(first, second):
    confident = {}
    for a, b in zip(first, second, strict=True):
        left, right = a["chain"]["answer"], b["chain"]["answer"]
        confident[a["step"]] = a["tier"] == b["tier"] and (left is right or ledger.same(left, right))
    return confident


class NullLedgerProvider:
    def build(self, group):
        return [LedgerResult([], [], [], {}) for _ in trajectories(group)]


class MockLedgerProvider:
    """A supplied factory or a deterministic synthetic supported candidate."""
    def __init__(self, factory=None):
        self.factory = factory

    def build(self, group):
        results = []
        for trajectory in trajectories(group):
            if self.factory is not None:
                result = self.factory(trajectory)
                results.append(result if isinstance(result, LedgerResult) else LedgerResult(*result))
                continue
            units = get(trajectory, "units", [])
            tool_units = [unit for unit in units if get(unit, "unit_id", get(unit, "id")) != "F"]
            records = []
            for step in range(1, len(tool_units) + 1):
                key = f"E1@{step}"
                records.append({"step": step, "query": "synthetic query", "targets": [{"object": "Synthetic Candidate", "conditions": ["A"], "restriction": ""}],
                    "new_docs": 1, "old_docs": 0, "strict": [],
                    "evidence": [{"key": key, "doc": "synthetic", "sents": ["s1"], "text": "Synthetic Candidate meets the requirement.", "about": "Synthetic Candidate", "fact": "meets the requirement", "conditions": [{"id": "A", "effect": "支持"}], "strength": "直接", "broad": "否"}],
                    "verdicts": {key: {"verdict": "采纳", "reason": ""}}, "earlier_adopted": [], "excluded": [],
                    "answer_chain": {"answer": "Synthetic Candidate", "linked": []}, "assertions": []})
            record = {"conditions": ["A"], "steps": records}
            derived = ledger.run(record)["steps"]
            results.append(LedgerResult(records, derived, ["A"], {step: True for step in range(1, len(records) + 1)}))
        return _shared_conditions(results)


class LiveJudgeLedgerProvider:
    def __init__(self, client, prompts, *, cfg=None, q1_early_stop=True, cache_q2=True, conditions_version="v13.4",
                 case_loader=None, condition_builder=None, q3_audit_rate=None):
        self.client, self.prompts = client, dict(prompts)
        client_config = getattr(client, "config", None)
        client_wire = client_config.wire() if isinstance(client_config, HttpJudgeConfig) else {}
        self.cfg = {**WIRE, **client_wire, **(cfg or {})}
        self.q1_early_stop, self.cache_q2 = q1_early_stop, cache_q2
        self.conditions_version = conditions_version
        self.case_loader, self.condition_builder = case_loader, condition_builder
        if q3_audit_rate is not None:
            CreditConfig(q3_audit_rate=q3_audit_rate)
        self.q3_audit_rate = q3_audit_rate
        self.stats = {"groups": 0, "q0_calls": 0, "q1_early_stops": 0, "q2_cache_hits": 0, "q2_cache_misses": 0,
                      "q5_skippable": 0, "q3_audit_groups": 0, "q3_audit_calls": 0}

    def build(self, group, *, config=None):
        credit = CreditConfig.from_params(config or {})
        entries = []
        for trajectory in trajectories(group):
            if self.case_loader is not None:
                case, metadata = self.case_loader(trajectory)
            else:
                stored = get(trajectory, "metadata", {})
                case, metadata = stored["case"], stored["ledger_metadata"]
            entries.append((deepcopy(case), deepcopy(metadata)))
        if not entries:
            return []
        qids = {str(case["query_id"]) for case, _ in entries}
        if len(qids) != 1:
            raise ValueError("Online ledger construction requires one question per group")
        conditions = entries[0][0].get("conditions")
        if conditions is None:
            # Only the question reaches Q0: never forward metadata containing gold.
            if self.condition_builder is None:
                call = checked(Path(entries[0][0]["trajectory_id"]), "Q0", self.prompts["Q0"],
                    {"题目原文": entries[0][1]["question"]}, self.cfg, validate_q0, self.client)
                self.stats["q0_calls"] += len(call["attempts"])
                if not call["passed"]:
                    raise ValueError("Q0 did not produce valid shared conditions")
                conditions = call["parsed"]["conditions"]
                for _, metadata in entries:
                    metadata["answer_type"] = call["parsed"]["answer_type"]
            else:
                conditions = self.condition_builder(entries[0][1]["question"])
                self.stats["q0_calls"] += 1
        rate = credit.q3_audit_rate if self.q3_audit_rate is None else self.q3_audit_rate
        audit = not credit.use_q3 and bool(rate) and select_group(next(iter(qids)), self.stats["groups"],
                                                                rate, seed="q3_audit")
        self.stats["q3_audit_groups"] += audit

        def run_pass(variant, audit_q3):
            # Keep group-level Q2 caching while letting the second pass sample independently.
            cache = {} if self.cache_q2 else None
            select_receipts = getattr(self.client, "for_pass", None)
            send = select_receipts(variant) if select_receipts is not None else self.client
            results = []
            for case, metadata in entries:
                if case.get("conditions") not in (None, conditions):
                    raise ValueError("Frozen conditions disagree within a question group")
                case["conditions"] = conditions
                rows = execute(case, metadata, self.prompts, send, cfg=self.cfg,
                    q1_early_stop=self.q1_early_stop, q2_cache=cache, conditions_version=self.conditions_version,
                    stats=self.stats, use_q3=credit.use_q3, q3_audit=audit_q3,
                    k_hold=credit.k_hold, k_restrict=credit.k_restrict)
                results.append(rows)
            return results

        primary = run_pass("a", audit)
        secondary = run_pass("b", False) if credit.gate_two_pass else [[] for _ in primary]
        results = []
        for (case, _), rows, rows_b in zip(entries, primary, secondary, strict=True):
            records, derived = [row["record"] for row in rows], [row["derived"] for row in rows]
            records_b, derived_b = [row["record"] for row in rows_b], [row["derived"] for row in rows_b]
            conds = [condition["id"] for condition in conditions]
            full = {"query_id": case["query_id"], "group": case["group"], "conditions": conds, "steps": records}
            renderer = ledger if credit.use_q3 else ledger_v135
            rendered = renderer.render(full, {"steps": derived}, case["trajectory_id"] + " · a")
            eligible = q5_skip_candidates(records)
            q3_calls = sum(len(row["q3_audit"]["attempts"]) for row in rows if "q3_audit" in row)
            self.stats["q5_skippable"] += len(eligible)
            self.stats["q3_audit_calls"] += q3_calls
            confident = _confidence(derived, derived_b) if credit.gate_two_pass else {row["step"]: True for row in rows}
            if rows:
                confident["F"] = confident[rows[-1]["step"]]
            results.append(LedgerResult(records, derived, conds, confident, rows=rows, rendered=rendered,
                stats={"q5_skippable": len(eligible), "q3_audit_calls": q3_calls},
                records_b=records_b if credit.gate_two_pass else None,
                derived_b=derived_b if credit.gate_two_pass else None, rows_b=rows_b))
        self.stats["groups"] += 1
        return _shared_conditions(results)

    build_for_credit = build


def q5_skip_candidates(records):
    """Audit only: exclusions with no prior pursuit and no supporting evidence."""
    pursued, registry, eligible = [], [], []
    for record in records:
        registry.extend(record.get("evidence", []))
        for index, exclusion in enumerate(record.get("excluded", [])):
            name = exclusion.get("object")
            followed = any(ledger.same(name, other) for other in pursued)
            supported = any(ledger.same(name, evidence.get("about")) and any(condition.get("effect") == "支持" for condition in evidence.get("conditions", [])) for evidence in registry)
            if not followed and not supported:
                eligible.append((record["step"], index))
        chain = record.get("answer_chain") or {}
        pursued.extend(target.get("object") for target in record.get("targets", []))
        pursued.extend([chain.get("answer"), *(item.get("object") for item in chain.get("linked", []))])
    return eligible


def blank_skippable_q5(records):
    """Return a copy for the required audit; never changes the provider default."""
    copied = deepcopy(records)
    eligible = set(q5_skip_candidates(records))
    for record in copied:
        for index, exclusion in enumerate(record.get("excluded", [])):
            if (record["step"], index) in eligible:
                exclusion["basis"] = None
                exclusion["valid"] = None
    return copied


FROZEN_PROMPT_SHA256 = {
    "Q0": "5880b684d6b5425ceac7419185bba842c3f82161d3d11ddaf263bae231b9f18e",
    "Q1": "cf50d42d1e9c1492356c8bed0ef94486f813fa7130240be0551dd9d719df5be0",
    "Q2": "32f984ea150e2f7665ccf9381ce921289b60713dbe0e297e97e270bcb41f4617",
    "Q3": "f1125bc8955e99e9b38aba9b5153e314e4afce1d0dbd3f47cbfe4f1b99b82abd",
    "Q4": "030e904b5a5023100be2291cb25d5ff3bc13c898303eb5733d020b7566852011",
    "Q5": "e3a36224cc15c4d783cf11da514b290a149511ef9ab6512d74bd75da5ceacc2c",
}


def load_frozen_prompts(directory):
    """Load the external frozen protocol, checking bytes before UTF-8 decoding."""
    prompts = {}
    for phase, expected in FROZEN_PROMPT_SHA256.items():
        raw = (Path(directory) / ("prompt_v134_" + phase + ".txt")).read_bytes()
        if sha256(raw).hexdigest() != expected:
            raise ValueError("Frozen v13.4 prompt hash mismatch: " + phase)
        prompts[phase] = raw.decode("utf-8")
    return prompts
