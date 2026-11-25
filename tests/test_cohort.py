import unittest
from pathlib import Path
from scripts.run_cohort import TASKS, command, budget_metrics


class CohortTests(unittest.TestCase):
    def test_complete_balanced_grid_and_common_settings(self):
        self.assertEqual(len(TASKS), 48)
        self.assertEqual(len(set(TASKS)), 48)
        for size in ('14B', '32B'):
            for condition in ('solo', 'coop'):
                self.assertEqual(sum(s == size and c == condition for s,c,g in TASKS), 12)
        for index in range(48):
            cmd = command(index, Path('/tmp/results'))
            for key, value in [('--interface','original'),('--max-batch','1'),('--max-steps','4000')]:
                self.assertEqual(cmd[cmd.index(key)+1], value)

    def row(self, progress, hints=0, forced=False):
        return dict(upstream=dict(tracking=dict(progress=progress),response='Nothing happens.'),
                    hints_used=hints, forced_action=forced)

    def test_interrupted_is_missing_not_zero(self):
        self.assertIsNone(budget_metrics([self.row(25)], {'stop_reason':'interrupted'}, 50))

    def test_early_success_is_carried_with_help_count(self):
        result = budget_metrics([self.row(50),self.row(100,1,True)], {'stop_reason':'success'}, 50)
        self.assertEqual(result['progress'],100)
        self.assertEqual(result['hints'],1)
        self.assertEqual(result['forced'],1)

    def test_fixed_budget_does_not_use_future_progress_or_hints(self):
        result = budget_metrics([self.row(10),self.row(90,2,True)], {'stop_reason':'success'}, 1)
        self.assertEqual(result['progress'],10)
        self.assertEqual(result['hints'],0)
        self.assertEqual(result['forced'],0)


if __name__ == '__main__':
    unittest.main()
