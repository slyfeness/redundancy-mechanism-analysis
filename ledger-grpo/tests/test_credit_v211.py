"""Synthetic v2.1.1 patch tests; no recorded dataset content or model calls."""
from copy import deepcopy
import inspect

import pytest
import torch

from ledger_grpo.credit.allocate import allocate, allocate_mode, shuffle_roles, _ks_distance
from ledger_grpo.credit.config import PARAMS, CreditConfig
from ledger_grpo.credit.group import credit_for_group, ledger_complete
from ledger_grpo.credit.metrics import collect_credit_metrics
from ledger_grpo.credit.providers import LiveJudgeLedgerProvider, MockLedgerProvider, NullLedgerProvider
from ledger_grpo.credit.schema import Unit, Trajectory, Group
from ledger_grpo.credit.tokens import units_from_stages
from ledger_grpo.credit.training import prepare_credit_native_records
from ledger_grpo.credit.utility import trajectory_reward, utility_reward


def chain(n):
    return ([{} for _ in range(n)], [{} for _ in range(n)], ['c1', 'A'])


def test_all_one_execution_counts_match_legacy_progress_area():
    for n in (1, 7, 14, 20):
        for success in (False, True):
            records, derived, conds = chain(n)
            derived = [{'chain': {'answer': 'object'}, 'view': {'c1': ('✔', [], True)}} for _ in derived]
            outcome = {'Y': success, 'submitted': success}
            default = trajectory_reward(records, derived, conds, outcome, .03)
            explicit = trajectory_reward(records, derived, conds, outcome, .03, exec_counts={i: 1 for i in range(1, n+1)})
            assert explicit == default
            # Legacy slots: initial zero, half of weighted c1 coverage, then terminal tail.
            from ledger_grpo.credit.utility import best_candidate_progress
            p = best_candidate_progress(derived, conds)
            phi = [0.] + [.5*x for x in p[:19]]
            phi += [phi[-1]] * (20-len(phi))
            if success:
                phi[min(n, 19):] = [1.] * (20-min(n, 19))
            expected = int(success) - .2*int(not success) + .3*(sum(phi)/20) - (.03 if success else 0.)
            assert default[0] == expected


@pytest.mark.parametrize('mode', ['progress', 'progress_waste'])
def test_parallel_execution_axis(mode):
    outcome = {'Y': True, 'submitted': True}
    kwargs = dict(PARAMS, utility=mode)
    parallel = utility_reward(*chain(7), outcome, 0., kwargs, exec_counts={**{i: 3 for i in range(1, 7)}, 7: 2})
    serial = utility_reward(*chain(14), outcome, 0., kwargs)
    assert parallel[0] == 1.015
    assert serial[0] == 1.09
    assert parallel[1]['executions'] == 20


def test_actual_events_deduplicate_and_exclude_unexecuted_parallel_calls():
    events = [dict(event_id='a', tool_name='search', obs_tokens=2), dict(event_id='b', tool_name='search', obs_tokens=3)]
    stages = [dict(model_call_index=1, span_id=0, gen_token_range=[0, 2], unit_type='tool_stage',
                   tool_events=events),
              dict(model_call_index=1, span_id=0, gen_token_range=[0, 2], unit_type='tool_stage',
                   tool_events=events[:1])]
    units = units_from_stages(stages)
    tr = Trajectory('q', 0, units, {'Y': True, 'submitted': True}, response_mask=[1, 1])
    row = tr.to_credit_dict()
    assert row['exec_counts'] == {1: 2}
    assert row['tool_call_count'] == 2
    assert units[0].returned_tokens == 5
    result = utility_reward([], [], [], tr.outcome, 0., CreditConfig.from_preset('A_eff'), tool_call_count=row['tool_call_count'])
    assert result[0] == .98


@pytest.mark.parametrize('sign,role', [(-1., 'C'), (1., 'R')])
@pytest.mark.parametrize('mode', ['transfer', 'transfer_uniform', 'shuffled', 'clear_only'])
def test_no_receiver_zeroes_giveups_and_records_mass(sign, role, mode):
    units = [1, 2, 3, 'F']
    nu = {1: .3, 2: .3, 3: .2, 'F': .2}
    roles = {1: role, 2: role, 3: 'K', 'F': 'F'}
    weights = {1: .1, 2: .2, 3: 0., 'F': 0.}
    A, log = allocate_mode(units, nu, sign, roles, weights, dict(PARAMS, step_credit=mode))
    assert A == {1: 0., 2: 0., 3: sign, 'F': sign}
    assert log['no_receiver'] and log['dropped'] == .6


@pytest.mark.parametrize('mode', ['abstain', 'partial'])
def test_no_receiver_nondrop_modes_keep_base(mode):
    A, log = allocate([1, 'F'], {1: .8, 'F': .2}, -1., {1: 'C', 'F': 'F'}, {1: 1., 'F': 0.}, dict(PARAMS, infeasible=mode))
    assert A == {1: -1., 'F': -1.}
    assert log['no_receiver'] and log['infeasible'] and log['dropped'] == 0.


def test_no_giveups_unchanged():
    A, log = allocate([1, 'F'], {1: .8, 'F': .2}, 1., {1: 'C', 'F': 'F'}, {1: 1., 'F': 0.})
    assert A == {1: 1., 'F': 1.}
    assert log['mode'] == 'nothing_to_move'
    assert not log.get('no_receiver')


def fixture():
    trajectories = [Trajectory('q', i, [Unit(1, [(0, 2)], 2, 1, ['search']), Unit('F', [(3, 5)], 2)],
                         {'Y': i == 0, 'submitted': True}, response_mask=[1, 1, 0, 1, 1], traj_id=f'r{i}') for i in range(2)]
    group = Group('q', trajectories)
    for tr, result in zip(group, MockLedgerProvider().build(group)):
        tr.records, tr.derived, tr.conds, tr.confident = tuple(result)
    native = [{'id': tr.traj_id, 'query_id': 'q', 'segments': [
        {'prompt_ids': [1], 'completion_ids': [2, 3], 'vllm_logprobs': [0., 0.]},
        {'prompt_ids': [1, 2, 3, 10], 'completion_ids': [4, 5], 'vllm_logprobs': [0., 0.]}]} for tr in group]
    return group, native


@pytest.mark.parametrize('preset', ['B', 'B_W', 'C', 'C_W', 'C_uniform', 'clear_only', 'D'])
@pytest.mark.parametrize('process', ['off', 'masked_nll', 'zero_sum'])
def test_incomplete_group_uses_baseline_without_auxiliary(preset, process):
    group, native = fixture()
    group.trajectories[1].records = []
    group.trajectories[1].derived = []
    config = CreditConfig.from_preset(preset, process_sup=process)
    result = prepare_credit_native_records(native, [group], config=config, max_generated_tokens=8)
    baseline = prepare_credit_native_records(native, [group], config=CreditConfig.from_preset('A'), max_generated_tokens=8)
    for got, expected in zip(result['credits'], baseline['credits']):
        assert got['log']['ledger_fallback']
        assert got['U'] == expected['U'] and got['A'] == expected['A']
        assert 'zero_sum' not in got['log']
    assert result['metrics']['ledger_fallback_groups'] == 1
    assert result['metrics']['ledger_fallback_trajectories'] == 2
    assert result['metrics']['process_selected_tokens'] == 0
    assert all(not row['masked_nll_mask'].any() for row in result['records'])


@pytest.mark.parametrize('provider', [None, NullLedgerProvider()])
def test_empty_ledgers_and_null_provider_fall_back(provider):
    group, native = fixture()
    for tr in group:
        tr.records = tr.derived = tr.conds = []
    result = prepare_credit_native_records(native, [group], provider=provider, max_generated_tokens=8)
    assert result['metrics']['ledger_fallback_groups'] == 1


def test_complete_group_explicit_mismatch_and_unfinished_not_fallback():
    group, _ = fixture()
    group.trajectories[0].metadata['unmatched_units'] = [1]
    group.trajectories[0].units.append(Unit(2, [(6, 7)], 1, kind='unfinished'))
    result = credit_for_group(group)
    assert not any(cr['log'].get('ledger_fallback') for cr in result)
    assert result[0]['role'][1] == result[0]['role'][2] == 'K'
    assert ledger_complete(dict(tokens={'F': 3}, records=[], derived=[], conds=[]))
    assert ledger_complete(Trajectory('q', 0, [Unit(1, [(0, 1)], 1, kind='unfinished')],
                                      {'Y': False, 'submitted': False}).to_credit_dict())


def test_batch_ks_pools_samples_not_per_trajectory_max():
    from test_credit_core import trajectory
    trajs = [trajectory(True), trajectory(False)]
    credits = credit_for_group(trajs, CreditConfig.from_preset('D'))
    # Opposite displacements cancel in the pooled distribution.
    credits[0]['log']['shuffle_samples'] = {'C_length': ([1.], [2.])}
    credits[1]['log']['shuffle_samples'] = {'C_length': ([2.], [1.])}
    for credit in credits:
        credit['log']['shuffle_ks'] = {'C_length': 1.}
    metrics = collect_credit_metrics(trajs, credits)
    assert metrics['modules']['shuffle_ks_batch']['C_length'] == 0.
    assert metrics['modules']['shuffle_ks_max']['C_length'] == 1.


def test_live_provider_q1_early_stop_default_enabled():
    assert inspect.signature(LiveJudgeLedgerProvider).parameters['q1_early_stop'].default is True
