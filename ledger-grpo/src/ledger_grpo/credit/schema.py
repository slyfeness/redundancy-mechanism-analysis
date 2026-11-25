"""Program-side trajectory and v13.4 ledger schemas.

Gold is deliberately carried only by this scoring representation. No prompt
builder consumes this object or serializes it wholesale to a model request.
"""
import ast
from copy import deepcopy
from dataclasses import dataclass, field


def literal(value):
    if isinstance(value, str):
        try:
            return ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return value
    return value


def _object(value, allowed, name):
    value = deepcopy(value)
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValueError(f'{name} contains unknown fields or is not an object')
    return value


def _string(value, name, nullable=False):
    if not isinstance(value, str) and not (nullable and value is None):
        raise ValueError(f'{name} must be a string')


def _strings(value, name):
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
        raise ValueError(f'{name} must be a list of strings')


def _enum(value, options, name):
    if value not in options:
        raise ValueError(f'invalid {name}: {value!r}')


def _chain(value):
    if value is None:
        return
    value = _object(value, ('answer', 'linked'), 'answer chain')
    _string(value.get('answer'), 'answer', nullable=True)
    for link in value.get('linked', []):
        link = _object(link, ('object', 'conditions'), 'linked object')
        _string(link.get('object'), 'linked.object')
        _strings(link.get('conditions', []), 'linked.conditions')


def _exclusion(value):
    value = _object(value, ('object', 'reason', 'basis', 'basis_conditions', 'valid'), 'exclusion')
    for key in ('object', 'reason'):
        if key in value:
            _string(value[key], key)
    _strings(value.get('basis_conditions', []), 'basis_conditions')
    if 'basis' in value:
        _enum(value['basis'], ('条件', '题外', '无依据', None, ''), 'exclusion basis')
    if 'valid' in value:
        _enum(value['valid'], ('成立', '不成立', '看不出', None, ''), 'exclusion validity')


RECORD_FIELDS = {'step', 'targets', 'plan_match', 'query', 'new_docs', 'old_docs', 'strict',
                 'evidence', 'verdicts', 'earlier_adopted', 'excluded', 'answer_chain', 'assertions',
                 'unjudged_evidence'}
DERIVED_FIELDS = {'step', 'targets', 'adopted_now', 'ignored_now', 'excluded_now', 'excluded_role_only',
                  'chain', 'view', 'labels', 'position', 'tier', 'missed', 'missed_gold', 'unused', 'unsupported'}


def validate_record(raw):
    row = _object(raw, RECORD_FIELDS, 'record')
    if type(row.get('step')) is not int or row['step'] < 1:
        raise ValueError('record.step must be a positive integer')
    for key in ('new_docs', 'old_docs'):
        if key in row and (type(row[key]) is not int or row[key] < 0):
            raise ValueError(f'{key} must be a nonnegative integer')
    if 'query' in row and not isinstance(row['query'], (str, list)):
        raise ValueError('query must be a string or list of strings')
    if isinstance(row.get('query'), list):
        _strings(row['query'], 'query')
    for key in ('earlier_adopted', 'unjudged_evidence'):
        if key in row:
            _strings(row[key], key)
    if 'strict' in row and (not isinstance(row['strict'], list) or any(type(x) is not int or x < 1 for x in row['strict'])):
        raise ValueError('strict must contain positive integer step indices')
    if 'plan_match' in row:
        _enum(row['plan_match'], ('一致', '不一致', None), 'plan_match')
    for target in row.get('targets', []):
        target = _object(target, ('object', 'conditions', 'restriction'), 'target')
        _string(target.get('object'), 'target.object')
        _strings(target.get('conditions', []), 'target.conditions')
        _string(target.get('restriction', ''), 'target.restriction')
    for ev in row.get('evidence', []):
        ev = _object(ev, ('key', 'doc', 'sents', 'text', 'fact', 'about', 'conditions', 'strength', 'broad'), 'evidence')
        _string(ev.get('key'), 'evidence.key')
        for key in ('doc', 'text', 'fact', 'about'):
            if key in ev:
                _string(ev[key], 'evidence.' + key)
        if 'sents' in ev:
            _strings(ev['sents'], 'evidence.sents')
        _enum(ev.get('strength'), ('直接', '推断'), 'evidence strength')
        if 'broad' in ev:
            _enum(ev['broad'], ('是', '否', True, False), 'evidence broad')
        for cond in ev.get('conditions', []):
            cond = _object(cond, ('id', 'effect'), 'evidence condition')
            _string(cond.get('id'), 'condition.id')
            _enum(cond.get('effect'), ('支持', '冲突'), 'condition effect')
    if not isinstance(row.get('verdicts', {}), dict):
        raise ValueError('verdicts must be an object')
    for key, value in row.get('verdicts', {}).items():
        _string(key, 'verdict key')
        if isinstance(value, dict):
            value = _object(value, ('verdict', 'reason'), 'verdict')
            _string(value.get('reason', ''), 'verdict.reason')
            value = value.get('verdict')
        _enum(value, ('采纳', '不信', '没理会'), 'verdict')
    for ex in row.get('excluded', []):
        _exclusion(ex)
    _chain(row.get('answer_chain'))
    for assertion in row.get('assertions', []):
        assertion = _object(assertion, ('claim', 'conditions', 'tokens'), 'assertion')
        _string(assertion.get('claim'), 'assertion.claim')
        _strings(assertion.get('conditions', []), 'assertion.conditions')
        _strings(assertion.get('tokens', []), 'assertion.tokens')
    return row


def validate_derived(raw):
    row = _object(raw, DERIVED_FIELDS, 'derived')
    row = {key: literal(value) for key, value in row.items()}
    if type(row.get('step')) is not int or row['step'] < 1:
        raise ValueError('derived.step must be a positive integer')
    for key in ('adopted_now', 'ignored_now', 'labels', 'position', 'missed', 'missed_gold', 'unused', 'excluded_role_only'):
        if key in row:
            _strings(row[key], key)
    if 'tier' in row:
        _enum(row['tier'], ('有进展', '冗余', '跑偏', '无进展'), 'tier')
    if 'chain' in row:
        _chain(row['chain'])
    for key in ('excluded_now',):
        for ex in row.get(key, []):
            _exclusion(ex)
    if not isinstance(row.get('view', {}), dict):
        raise ValueError('derived.view must be an object')
    for key, value in row.get('view', {}).items():
        _string(key, 'view condition')
        if not isinstance(value, (list, tuple)) or len(value) not in (2, 3):
            raise ValueError('view values require state, evidence keys and optional direct flag')
        _enum(value[0], ('✔', '✘', '○'), 'condition state')
        _strings(value[1], 'view evidence')
        if len(value) == 3 and type(value[2]) is not bool:
            raise ValueError('view direct flag must be boolean')
    for key in ('unsupported',):
        if key in row and (not isinstance(row[key], list) or any(not isinstance(x, dict) for x in row[key])):
            raise ValueError(f'derived.{key} must be a list of objects')
    if not isinstance(row.get('targets', []), list):
        raise ValueError('derived.targets must be a list')
    for target in row.get('targets', []):
        if (not isinstance(target, (list, tuple)) or len(target) != 3
                or not isinstance(target[0], str) or not isinstance(target[1], str) or type(target[2]) is not bool):
            raise ValueError('derived target must contain object, condition and restricted flag')
    return row


def validate_ledger(records, derived, conds):
    _strings(conds, 'conditions')
    if not conds or len(set(conds)) != len(conds):
        raise ValueError('conditions must be nonempty and unique')
    if len(records) != len(derived):
        raise ValueError('records and derived must have equal lengths')
    recs, ders = [validate_record(x) for x in records], [validate_derived(x) for x in derived]
    if any(r['step'] != i or d['step'] != i for i, (r, d) in enumerate(zip(recs, ders), 1)):
        raise ValueError('ledger steps must be contiguous and one-based')
    return recs, ders, list(conds)


@dataclass
class Unit:
    unit_id: object
    token_ranges: list
    generated_tokens: int
    returned_tokens: int = 0
    tool_names: list = field(default_factory=list)
    model_call_index: int = 0
    kind: str = 'tool'

    def __post_init__(self):
        if self.unit_id != 'F' and (type(self.unit_id) is not int or self.unit_id < 1):
            raise ValueError('unit id must be a positive integer or F')
        if any(type(x) is not int or x < 0 for x in (self.generated_tokens, self.returned_tokens)):
            raise ValueError('token counts must be nonnegative integers')
        if self.unit_id == 'F' and self.returned_tokens:
            raise ValueError('F cannot own tool returns')
        if any(len(r) != 2 or any(type(x) is not int for x in r) or not 0 <= r[0] < r[1] for r in self.token_ranges):
            raise ValueError('token ranges must be nonempty half-open intervals')
        if sum(b-a for a,b in self.token_ranges) != self.generated_tokens:
            raise ValueError('generated token count must match token ranges')
        _strings(self.tool_names, 'tool_names')


@dataclass
class Trajectory:
    qid: str
    rollout: int
    units: list
    outcome: dict
    gold: object = None
    records: list = field(default_factory=list)
    derived: list = field(default_factory=list)
    conds: list = field(default_factory=list)
    response_mask: list = field(default_factory=list)
    traj_id: str = None
    confident: object = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.qid, str) or not self.qid or type(self.rollout) is not int or self.rollout < 0:
            raise ValueError('qid and nonnegative rollout are required')
        if any(not isinstance(u, Unit) for u in self.units) or len({u.unit_id for u in self.units}) != len(self.units):
            raise ValueError('trajectory units must have unique identities')
        if self.outcome.get('Y') not in (0, 1) or self.outcome.get('submitted') not in (False, True):
            raise ValueError('outcome requires Y and submitted booleans')
        if self.outcome['Y'] and not self.outcome['submitted']:
            raise ValueError('correct outcome requires submission')
        if self.traj_id is None:
            self.traj_id = f'{self.qid}__rep{self.rollout + 1}'

    @property
    def trajectory_id(self):
        return self.traj_id

    def to_credit_dict(self, c_ref=3146):
        tool_units = [u.unit_id for u in self.units if u.unit_id != 'F' and u.kind == 'tool']
        unmatched = tool_units if len(self.records) != len(tool_units) or len(self.derived) != len(self.records) else []
        unfinished = [u.unit_id for u in self.units if u.unit_id != 'F' and u.kind != 'tool']
        explicit = self.metadata.get('unmatched_units', [])
        if any(u not in {unit.unit_id for unit in self.units} for u in explicit):
            raise ValueError('explicit unmatched unit does not belong to trajectory')
        unmatched = list(dict.fromkeys(list(unmatched) + unfinished + list(explicit)))
        return dict(qid=self.qid, rollout=self.rollout, records=self.records, derived=self.derived,
                    conds=self.conds or ['A'], outcome=self.outcome, gold=self.gold,
                    has_final=any(u.unit_id == 'F' for u in self.units),
                    tokens={u.unit_id: u.generated_tokens for u in self.units},
                    costs={u.unit_id: (u.generated_tokens + u.returned_tokens) / c_ref for u in self.units},
                    unit_types={u.unit_id: u.kind for u in self.units}, unmatched_units=unmatched,
                    confident=self.confident, tool_call_count=len(tool_units), unfinished_units=unfinished)


@dataclass
class Group:
    qid: str
    trajectories: list
    allow_mixed_qids: bool = False

    def __post_init__(self):
        if not self.trajectories or (not self.allow_mixed_qids and any(t.qid != self.qid for t in self.trajectories)):
            raise ValueError('a group must contain trajectories of one question')
        identities = [(t.qid, t.rollout) if self.allow_mixed_qids else t.rollout for t in self.trajectories]
        if len(set(identities)) != len(self.trajectories):
            raise ValueError('rollout indices must be unique within a group')

    def __iter__(self):
        return iter(self.trajectories)

    def __len__(self):
        return len(self.trajectories)
