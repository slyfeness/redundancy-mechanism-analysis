"""Verify cross-task process projection on native-format fixtures and the frozen tokenizer."""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from transformers import AutoTokenizer

from ledger_grpo.browsecomp_events import semantic_event_predictions
from ledger_grpo.pipeline import analyze_trajectory
from ledger_grpo.rules import RuleConfig
from ledger_grpo.sampler_grpo import adapt_sampler_trajectory
from test_sampler_grpo import fixture


class FixtureJudge:
    model = 'synthetic-evidence-check'

    def extract(self, payload):
        return {'facts': [], 'action_target': {'target_id': 'c1'}}

    def check(self, kind, payload):
        if kind != 'R2a':
            raise ValueError('fixture only covers near-repeat search')
        return {'verdict': 'yes', 'evidence_refs': [payload[key][0]['evidence_id']
                                                  for key in ('prior_evidence','current_observations')]}


def verify(tokenizer, scratch):
    def response(prompt, completion, calls):
        prefix = tokenizer(prompt, add_special_tokens=False)['input_ids']
        encoded = tokenizer(completion, add_special_tokens=False, return_offsets_mapping=True)
        actions = encoded['input_ids']
        pieces = [completion[a:b].encode() for a,b in encoded['offset_mapping']]
        if b''.join(pieces) != completion.encode():
            raise ValueError('fixture bytes differ from the token boundaries')
        return {'prompt_token_ids': prefix, 'usage': {'prompt_tokens': len(prefix), 'completion_tokens': len(actions)},
                'choices': [{'token_ids': actions, 'message': {'tool_calls': calls},
                             'logprobs': {'content': [{'bytes': list(piece), 'logprob': -.01} for piece in pieces]}}]}

    result = {}
    with TemporaryDirectory(dir=scratch) as tmp:
        for dataset in ('sage','scicode'):
            root = Path(tmp)/dataset
            fixture(root, dataset, encode_response=response, near_repeat=dataset == 'sage')
            row, _, coverage = adapt_sampler_trajectory(dataset, root, traj_id='fixture', task_id='task', outcome=0,
                tokenizer=tokenizer, process_frames=[[{'cid':'c1','text':'identity'}]])
            binding, = coverage['process_traces']
            trace = binding['trace']
            report = analyze_trajectory(trace, judge=FixtureJudge(),
                                        rule_config=RuleConfig(query_similarity_threshold=.65, r2_local_check=True))
            predictions = semantic_event_predictions(binding, trace, report, binding['measured_events'])
            expected = ('positive','confirmed_prefix_span',None) if dataset=='sage' else ('uncertain','exact_repeat_precedence','R2b')
            event = row['events'][1]
            judged = predictions[1]['predictions']['R2a']
            if (judged['prediction'],judged['reason'],event['label']) != expected or not report['qa']['parse_ok']:
                raise ValueError('semantic diagnosis and event-pricing label did not match the fixture')
            result[dataset] = {'turns': len(trace['turns']), 'measured_events': len(binding['measured_events']),
                               'observations': sum(len(turn['observations']) for turn in trace['turns']),
                               'diagnosed_event_id': event['event_id'], 'diagnosed_event_tokens': event['event_tokens'],
                               'r2a_diagnostic': judged, 'event_pricing_label': event['label']}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('model','scratch','output'):
        parser.add_argument('--'+option, type=Path, required=True)
    args = parser.parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    report = {'scope': 'Synthetic native-format tool exchanges and a synthetic Judge with the frozen Qwen tokenizer.',
              'datasets': verify(tokenizer, args.scratch)}
    with args.output.open('x', encoding='utf-8') as out:
        json.dump(report, out, indent=2, allow_nan=False)
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
