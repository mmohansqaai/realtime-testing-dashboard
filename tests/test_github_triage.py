import io
import unittest
import zipfile

from app.github_triage import classify_github_flow


PLAYWRIGHT_FLOW = {
    'id': 35502326185,
    'name': 'Playwright Tests',
    'status': 'completed',
    'conclusion': 'failure',
    'jobs': [
        {
            'name': 'Run tests (Ubuntu)',
            'conclusion': 'failure',
            'steps': [
                {'number': 1, 'name': 'Checkout', 'conclusion': 'success'},
                {'number': 6, 'name': 'Run Playwright tests', 'conclusion': 'failure'},
                {'number': 11, 'name': 'Publish results to dashboard (multipart curl)', 'conclusion': 'success'},
            ],
        }
    ],
}


class GithubTriageTests(unittest.TestCase):
    def test_playwright_step_without_logs_is_not_automation_by_name(self):
        result = classify_github_flow(PLAYWRIGHT_FLOW)
        self.assertIsNotNone(result)
        self.assertEqual(result['classification'].value, 'UNKNOWN')
        self.assertEqual(result['failed_step'], 'Run Playwright tests')
        self.assertTrue(result['human_review_required'])
        self.assertNotEqual(result['subtype'], 'PLAYWRIGHT_TEST_FAILURE')

    def test_mixed_playwright_logs_keep_environment_primary(self):
        log = """
  1) [chromium] › tests/triage-demo-failure.spec.ts:14:7 › home page shows checkout promo that does not exist @triage-demo-failure
    Error: expect(locator).toBeVisible() failed
    Locator: getByRole('heading', { name: 'Flash checkout: everything $0.01' })
    Error: element(s) not found
  2) [chromium] › tests/triage-demo-failure.spec.ts:23:7 › document title still says Nova Retail @triage-demo-failure
    Error: expect(received).toBe(expected)
    Expected: "Nova Retail"
    Received: "BayOne Retail (Demo)"
  3) [chromium] › tests/triage-demo-failure.spec.ts:28:7 › product catalog request is connection-refused @triage-demo-failure
    Error: page.goto: net::ERR_CONNECTION_REFUSED at https://retail-website-fawn.vercel.app/app/products
  3 failed
  3 passed (1.4m)
"""
        result = classify_github_flow(PLAYWRIGHT_FLOW, log)
        self.assertEqual(result['classification'].value, 'ENVIRONMENT')
        self.assertEqual(result['subtype'], 'SERVICE_CONNECTION_REFUSED')
        self.assertTrue(result['human_review_required'])
        self.assertEqual(result['triage_state'].value, 'REVIEW_REQUIRED')
        evidence = '\n'.join(result['evidence'])
        self.assertRegex(evidence, r'ERR_CONNECTION_REFUSED|connection-refused')
        self.assertRegex(evidence, r'toBeVisible|Flash checkout')
        self.assertRegex(evidence, r'Nova Retail|BayOne Retail')
        self.assertIn('PRODUCT_DEFECT/ASSERTION_MISMATCH', evidence)
        self.assertNotIn('PLAYWRIGHT_TEST_FAILURE', evidence)
        self.assertEqual(
            result['related_failures'],
            ['AUTOMATION_DEFECT/LOCATOR_FAILURE', 'PRODUCT_DEFECT/ASSERTION_MISMATCH'],
        )

    def test_publish_step_without_logs_is_infrastructure(self):
        flow = {
            'id': 1,
            'name': 'Playwright Tests',
            'status': 'completed',
            'conclusion': 'failure',
            'jobs': [
                {
                    'name': 'Run tests (Ubuntu)',
                    'conclusion': 'failure',
                    'steps': [
                        {'number': 6, 'name': 'Run Playwright tests', 'conclusion': 'success'},
                        {'number': 11, 'name': 'Publish results to dashboard', 'conclusion': 'failure'},
                    ],
                }
            ],
        }
        result = classify_github_flow(flow)
        self.assertEqual(result['classification'].value, 'CI_INFRASTRUCTURE')
        self.assertEqual(result['failed_step'], 'Publish results to dashboard')


class GithubJobLogDecodeTests(unittest.TestCase):
    def test_zip_archive_is_unpacked(self):
        from app.github_ci import decode_job_logs

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as archive:
            archive.writestr('0_run.txt', 'net::ERR_CONNECTION_REFUSED at https://example.test')
        text = decode_job_logs(buf.getvalue())
        self.assertIn('ERR_CONNECTION_REFUSED', text)


if __name__ == '__main__':
    unittest.main()
