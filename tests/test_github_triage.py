import unittest

from app.github_triage import classify_github_flow


class GithubTriageTests(unittest.TestCase):
    def test_playwright_step_is_automation_defect(self):
        flow = {
            'id': 35469224754,
            'name': 'Playwright Tests',
            'status': 'completed',
            'conclusion': 'failure',
            'jobs': [
                {
                    'name': 'Run tests (Ubuntu)',
                    'conclusion': 'failure',
                    'steps': [
                        {'number': 1, 'name': 'Checkout', 'conclusion': 'success'},
                        {'number': 8, 'name': 'Run Playwright tests', 'conclusion': 'failure'},
                    ],
                }
            ],
        }
        result = classify_github_flow(flow)
        self.assertIsNotNone(result)
        self.assertEqual(result['classification'].value, 'AUTOMATION_DEFECT')
        self.assertEqual(result['failed_step'], 'Run Playwright tests')
        self.assertEqual(result['triage_state'].value, 'COMPLETED')


if __name__ == '__main__':
    unittest.main()
