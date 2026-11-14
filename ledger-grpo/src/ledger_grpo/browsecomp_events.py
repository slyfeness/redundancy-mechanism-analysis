"""Bind observed BrowseComp tool events to original policy and prompt tokens."""

import json
from collections import Counter, defaultdict
from pathlib import Path

from .browsecomp_adapter import _recorded_search_response
from .event_replay import delivered_repeat_witnesses
from .native_tool_coordinates import call_ranges as _call_ranges
from .native_tool_coordinates import matches_return_suffix as _matches_return_suffix
from .native_tool_coordinates import prompt_return_counts


_DETERMINISTIC = {'search-server-search'}


def _return_counts(next_row, events, tokenizer, artifact_root):
    if next_row is None or next_row.get('request_sent') is not True or not _matches_return_suffix(next_row, events):
        return None
    tokens = next_row['token_accounting']
    if not tokens.get('serialized_prompt_path') or not tokens.get('exact_prompt_token_ids_equal'):
        return None
    path = Path(tokens['serialized_prompt_path']).resolve()
    if not path.is_relative_to(artifact_root):
        raise ValueError('serialized prompt artifact is outside the bound rollout directory')
    rendered = path.read_bytes().decode('utf-8')
    return prompt_return_counts(rendered, tokens['prompt_token_ids'], events, tokenizer)


def _terminal_guard_matches(raw, row, events):
    attempts = raw.get('unsent_guard_attempts') or []
    if raw.get('metadata', {}).get('terminal_status') != 'CONTEXT_LIMIT_STOP' or len(attempts) != 1:
        return False
    guard = attempts[0]
    return (guard.get('attempted_round_id') == row['round_id'] + 1
            and guard.get('stop_classification') == 'CONTEXT_LIMIT_STOP'
            and guard.get('request_sent') is False and guard.get('response_received') is False
            and guard.get('guard_intercepted') is True and _matches_return_suffix(guard, events))


def exact_repeat_witnesses(rounds, events_by_round):
    """Map a repeat to an earlier identical return observed before its action."""
    def event_key(event):
        if event['tool_name'] in _DETERMINISTIC and _recorded_search_response(event):
            arguments = json.dumps(json.loads(event['exact_arguments']), sort_keys=True)
            return event['tool_name'], arguments, event['exact_result']
        return None

    return delivered_repeat_witnesses(rounds, events_by_round, event_key=event_key)


def _semantic_spans(trace, report):
    from .pipeline import _digest

    if report.get('trace_digest') != _digest(trace):
        raise ValueError('semantic event evidence must be bound to the same canonical trajectory')
    by_turn = defaultdict(list)
    for span in report['spans']:
        label = {'R1': 'R1', 'R2': 'R2a'}.get(span['label'])
        if label and len(span['turns']) == 1 and span.get('known_at', span['turns'][0]) == span['turns'][0]:
            by_turn[span['turns'][0]].append((label, span))
    return by_turn


def _eligible_span(span, report):
    eligible = span.get('prefix_reward_eligible', report['qa']['parse_ok'] and
                        report['qa']['citations_verified'] and span['reward_eligible'])
    return eligible and span['confidence'] >= .9


def semantic_event_predictions(raw, trace, report, measured_events):
    """Record zero-price predictions from the same prefix spans used for credit."""
    from .schema import validate_trajectory

    spans = _semantic_spans(validate_trajectory(trace), report)
    known = {row['turn_id'] for row in report['ledger_history'] if row['known'] is True}
    first_error = min((row['turn'] for row in report['qa']['errors'] if type(row.get('turn')) is int), default=float('inf'))
    measured = {event['event_id']: event for event in measured_events}
    counts = Counter(event['round_id'] for event in raw['tool_events'])
    rows = []
    for event in raw['tool_events']:
        event_id, turn = str(event['event_id']), event['round_id']
        record = measured.get(event_id)
        if counts[turn] != 1 or record is None or record['turn_id'] != turn:
            unavailable = 'unmapped_single_event'
        elif record['prior_event_id'] is not None:
            unavailable = 'exact_repeat_precedence'
        elif report['judge']['mode'] != 'local' or turn not in known or turn >= first_error:
            unavailable = 'prefix_judge_unavailable'
        else:
            unavailable = None
        predictions = {}
        for label in ('R1', 'R2a'):
            matching = [span for span_label, span in spans.get(turn, []) if span_label == label]
            reason = unavailable
            if reason is None and label == 'R2a' and report['judge'].get('r2_local_check') is not True:
                reason = 'semantic_check_not_enabled'
            if reason is not None:
                prediction = 'uncertain'
            elif any(_eligible_span(span, report) for span in matching):
                prediction, reason = 'positive', 'confirmed_prefix_span'
            elif matching:
                prediction, reason = 'uncertain', 'inconclusive_semantic_span'
            else:
                prediction, reason = 'negative', 'evaluated_no_label'
            predictions[label] = {'prediction': prediction, 'reason': reason}
        rows.append({'event_id': event_id, 'turn_id': turn, 'predictions': predictions})
    return rows


def collect_tool_events(raw, trace, report, tokenizer, *, artifact_root, enabled_semantic_labels=()):
    """Use exact native envelopes. Unassigned reasoning and cost stay unassigned.

    The ledger's semantic decision identifies a model turn. It is transferable
    only when that turn has one tool event. Exact-repeat evidence is independent
    of ledger extraction. A completed earlier return must be present in an
    actor request that received a model response before the current action.
    """
    root = Path(artifact_root).resolve()
    turns = {row['turn_id']: row for row in trace['turns']}
    by_round = {}
    for event in raw['tool_events']:
        by_round.setdefault(event['round_id'], []).append(event)
    labels = {turn: {label for label, span in spans if label in enabled_semantic_labels and _eligible_span(span, report)}
              for turn, spans in _semantic_spans(trace, report).items()} if enabled_semantic_labels else {}
    repeats = exact_repeat_witnesses(raw['rounds'], by_round)
    result = []
    guard_events = 0
    for index,row in enumerate(raw['rounds']):
        rid = row['round_id']
        if rid not in by_round:
            continue
        events = sorted(by_round[rid], key=lambda e: e['tool_ordinal'])
        spans = _call_ranges(row, events, turns[rid]['token_start'], tokenizer=tokenizer)
        next_row = raw['rounds'][index+1] if index+1 < len(raw['rounds']) else None
        counts = _return_counts(next_row, events, tokenizer, root) if spans is not None else None
        stopped_before_send = spans is not None and next_row is None and _terminal_guard_matches(raw, row, events)
        if stopped_before_send:
            counts = [0] * len(events)
        for i,event in enumerate(events):
            if not _recorded_search_response(event):
                continue
            earlier = repeats.get(str(event['event_id']))
            if spans is None or counts is None:
                continue
            label = 'R2b' if earlier is not None else None
            semantic = labels.get(rid, set()) if len(events) == 1 else set()
            if label is None and semantic:
                label = 'R1' if 'R1' in semantic else 'R2a'
            start,stop = spans[i]
            guard_events += int(stopped_before_send)
            result.append({'event_id': str(event['event_id']), 'turn_id': rid, 'known_at': rid,
                           'event_tokens': [start,stop], 'label': label, 'prior_event_id': earlier,
                           'event_cost': {'generated_tokens': stop-start, 'returned_tokens': counts[i], 'tool_calls': 1}})
    return result, {'recorded_tool_events': len(raw['tool_events']), 'measured_tool_events': len(result),
                    'observed_exact_repeats': len(repeats), 'terminal_guard_measured_tool_events': guard_events}
