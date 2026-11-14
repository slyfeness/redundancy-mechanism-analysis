from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from launch_event_calibration import run_calibration


class CalibrationLaunchTest(unittest.TestCase):
    def run_case(self, startup_failure=False):
        order = []
        services = Mock()
        services.start.side_effect = (RuntimeError('startup failed') if startup_failure
                                      else lambda *_: order.append('ready'))
        services.close.side_effect = lambda: order.append('closed')
        services.actors.all.side_effect = lambda _: order.append('probe') or [{'token_ids': [1]}] * 4
        services.servers = [Mock(url=f'http://127.0.0.1:{i}', folder=Path(f'actor-{i}')) for i in range(4)]
        services.port = 9000

        def execute(actors, port):
            order.append('dispatch')
            self.assertEqual(len(actors), 4)
            self.assertEqual(port, 9000)
            return {'completed_branches': 64, 'failed_cases': {}}

        with TemporaryDirectory() as tmp:
            if startup_failure:
                with self.assertRaisesRegex(RuntimeError, 'startup failed'):
                    run_calibration(Path(tmp), services, object(), execute, 64)
            else:
                report = run_calibration(Path(tmp), services, object(), execute, 64)
                self.assertEqual(report['completed_branches'], 64)
        return order

    def test_runs_only_after_services_and_probes(self):
        self.assertEqual(self.run_case(), ['ready','probe','dispatch','closed'])

    def test_failure_does_not_dispatch_and_still_closes(self):
        self.assertEqual(self.run_case(startup_failure=True), ['closed'])
