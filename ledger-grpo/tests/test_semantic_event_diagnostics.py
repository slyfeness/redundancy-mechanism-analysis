import unittest

from diagnose_semantic_events import through_event
from event_price_pilot import semantic_rule_config, training_config
from ledger_grpo.browsecomp_events import semantic_event_predictions
from ledger_grpo.pipeline import analyze_trajectory
from test_pipeline import fixture


class RepetitionJudge:
    model = 'fixture'

    def __init__(self, verdict='yes'):
        self.verdict = verdict

    def extract(self, payload):
        if payload['turn']['turn_id'] == 7:
            raise ValueError('later extraction failure')
        return {'facts': []}

    def check(self, kind, payload):
        return {'verdict': self.verdict, 'evidence_refs': ['e1', 'e2'] if self.verdict == 'yes' else []}


class SemanticEventDiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.trace = fixture()
        self.settings = {'credit': dict(group_size=8, loss_denominator=32768, median_event_cost=1.,
                                        r1_price=0., r2a_price=0.),
                         'price_schedule': dict(update=1, warmup=0, ramp=1)}
        self.events = [dict(event_id='e', turn_id=3, known_at=3, prior_event_id=None, label=None)]
        self.raw = {'tool_events': [{'event_id': 'e', 'round_id': 3}]}

    def test_zero_price_can_collect_semantic_predictions(self):
        config, enabled = training_config(self.settings)
        rule = semantic_rule_config(check_r2a=True)
        self.assertTrue(rule.r2_local_check)
        self.assertEqual((config.r2a_price, enabled), (0., []))
        report = analyze_trajectory(self.trace, judge=RepetitionJudge(), rule_config=rule)
        self.assertFalse(report['qa']['parse_ok'])
        predictions = semantic_event_predictions(self.raw, self.trace, report, self.events)
        self.assertEqual(predictions[0]['predictions']['R2a']['prediction'], 'positive')
        self.assertEqual(self.events[0]['label'], None)

    def test_explicit_no_and_uncertain_are_different(self):
        for verdict, expected in [('no', 'negative'), ('uncertain', 'uncertain')]:
            report = analyze_trajectory(self.trace, judge=RepetitionJudge(verdict),
                                        rule_config=semantic_rule_config(check_r2a=True))
            with self.subTest(verdict=verdict):
                pred = semantic_event_predictions(self.raw, self.trace, report, self.events)[0]['predictions']['R2a']
                self.assertEqual(pred['prediction'], expected)

    def test_absent_disabled_or_unmeasured_evidence_is_unknown(self):
        for report, events in [(analyze_trajectory(self.trace), self.events),
                               (analyze_trajectory(self.trace, judge=RepetitionJudge()), self.events),
                               (analyze_trajectory(self.trace, judge=RepetitionJudge(),
                                                   rule_config=semantic_rule_config(check_r2a=True)), [])]:
            predictions = semantic_event_predictions(self.raw, self.trace, report, events)
            self.assertEqual(predictions[0]['predictions']['R2a']['prediction'], 'uncertain')

    def test_live_diagnostic_reaches_only_the_selected_event(self):
        prefix = through_event(self.trace, 3)
        self.assertEqual([turn['turn_id'] for turn in prefix['turns']], [1, 3])
        self.assertEqual(prefix['response_mask'], self.trace['response_mask'][:8])
        self.assertFalse(prefix['complete'])
        self.assertIsNone(prefix['submitted_candidate'])
        self.assertEqual(self.trace['outcome'], 1)
