"""Dataset boundaries; scoring labels stay on the program side."""
from abc import ABC, abstractmethod
import re
import string

from .schema import Trajectory
from .tokens import units_from_stages


class DatasetAdapter(ABC):
    @abstractmethod
    def parse_model_calls(self, trajectory, **kwargs): ...

    @abstractmethod
    def identify_answer(self, message): ...

    @abstractmethod
    def score(self, answer, gold): ...


class BCPlusAdapter(DatasetAdapter):
    def __init__(self, scorer=None):
        self.scorer = scorer

    def parse_model_calls(self, trajectory, *, count_tokens=None, gold=None, rollout=0, scorer=None):
        """Accept the recorder's native M1 result or construct it from raw rounds."""
        from ..hf_native import native_turn_layout
        if 'stages' in trajectory and 'native' in trajectory:
            parsed = trajectory
        else:
            from ..ledgercredit.stages import parse_stages
            if count_tokens is None:
                raise ValueError('raw recorder parsing requires the existing tokenizer counter')
            parsed = parse_stages(str(trajectory['query_id']), trajectory['id'], trajectory['rounds'],
                                  trajectory['tool_events'], count_tokens=count_tokens,
                                  terminal_status=trajectory.get('terminal_status'))
        native = parsed['native']
        layout = native_turn_layout(native)
        units = units_from_stages(parsed['stages'], {i: s['axis_start'] for i,s in enumerate(layout['spans'])})
        answer = trajectory.get('final_answer')
        if answer is None and trajectory.get('rounds'):
            raw = trajectory['rounds'][-1].get('raw_response', {})
            choices = raw.get('choices', [])
            final_stop = (trajectory.get('terminal_status') == 'MODEL_FINAL_STOP'
                          and choices and choices[0].get('finish_reason') == 'stop')
            answer = self.identify_answer(choices[0].get('message', {})) if final_stop else None
        final_stage = any(s['unit_type'] in ('final', 'abstain') for s in parsed['stages'])
        if not final_stage:
            answer = None
        outcome = trajectory.get('outcome')
        if outcome and outcome.get('submitted') and not final_stage:
            raise ValueError('recorded submission conflicts with unfinished terminal metadata')
        if outcome is None:
            if answer is None and any(s['unit_type'] == 'final' for s in parsed['stages']):
                raise ValueError('a final M1 stage requires its recorded outcome or final answer and explicit scorer')
            outcome = {'Y': bool((scorer or self.score)(answer, gold)) if answer is not None else False,
                       'submitted': answer is not None}
        return Trajectory(str(native['query_id']), rollout, units, outcome, gold=gold,
                          response_mask=layout['response_mask'], traj_id=native['id'])

    def identify_answer(self, message):
        if message.get('tool_calls'):
            return None
        answer = (message.get('content') or '').strip()
        return answer or None

    def score(self, answer, gold):
        """Use the caller's frozen grading rule, never silently change its semantics."""
        if self.scorer is None:
            raise ValueError('BC-Plus requires recorded outcome or an explicitly supplied frozen scorer')
        return bool(self.scorer(answer, gold))

    @staticmethod
    def normalized_exact_match(answer, gold):
        """Explicit synthetic/test helper; not the BC-Plus semantic grading rule."""
        def normalize(text):
            text = str(text).lower().translate(str.maketrans('', '', string.punctuation))
            return ' '.join(re.sub(r'\b(a|an|the)\b', ' ', text).split())
        if answer is None or gold is None:
            return False
        aliases = gold if isinstance(gold, (list, tuple)) else [gold]
        return any(normalize(answer) == normalize(alias) for alias in aliases)


class _PendingAdapter(DatasetAdapter):
    mapping_note = 'Dataset mapping is pending.'
    def parse_model_calls(self, trajectory, **kwargs):
        raise NotImplementedError(self.mapping_note)
    def identify_answer(self, message):
        raise NotImplementedError(self.mapping_note)
    def score(self, answer, gold):
        raise NotImplementedError(self.mapping_note)


class DeepSearchWorldAdapter(_PendingAdapter):
    mapping_note = 'DeepSearch-World call and submission mapping is pending.'


class SAGEAdapter(_PendingAdapter):
    mapping_note = 'SAGE submission tool maps to F; scorer and progress mapping are pending.'


class SciCodeAdapter(_PendingAdapter):
    mapping_note = 'SciCode progress is the first validation of a requirement; mapping is pending.'
