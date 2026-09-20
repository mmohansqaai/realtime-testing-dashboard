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
        self.assertNotIn('PLAYWRIGHT_TEST_FAILURE', '\n'.join(result['evidence']))
        self.assertEqual(
            result['related_failures'],
            ['AUTOMATION_DEFECT/LOCATOR_FAILURE', 'PRODUCT_DEFECT/ASSERTION_MISMATCH'],
        )
        tests = result['failed_tests']
        self.assertEqual(len(tests), 3)
        self.assertEqual(
            [item['classification'].value for item in tests],
            ['AUTOMATION_DEFECT', 'PRODUCT_DEFECT', 'ENVIRONMENT'],
        )
        env = next(item for item in tests if item['classification'].value == 'ENVIRONMENT')
        self.assertEqual(env['subtype'], 'SERVICE_CONNECTION_REFUSED')
        self.assertIn('connection was refused', env['what_happened'].lower())
        titles = [item['title'] for item in tests]
        self.assertTrue(any('checkout promo' in title for title in titles))
        self.assertTrue(any('Nova Retail' in title for title in titles))
        self.assertTrue(any('connection-refused' in title for title in titles))
        by_class = {item['classification'].value: item for item in tests}
        self.assertIn('AUTOMATION_DEFECT', by_class)
        self.assertIn('PRODUCT_DEFECT', by_class)
        self.assertIn('Flash checkout', by_class['AUTOMATION_DEFECT']['what_happened'])
        self.assertIn('Nova Retail', by_class['PRODUCT_DEFECT']['what_happened'])
        self.assertIn('BayOne Retail', by_class['PRODUCT_DEFECT']['what_happened'])
        self.assertIn('executive_summary', result)
        self.assertIn('do not share one root cause', result['executive_summary'])

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


class AiTriageMergeTests(unittest.TestCase):
    def test_ai_copy_does_not_change_classification(self):
        from app.ai_triage import _merge
        from app.schemas import TriageClassification

        payload = {
            'probable_cause': 'old',
            'executive_summary': 'old',
            'recommended_action': 'old action',
            'failed_tests': [
                {
                    'title': 'home page shows checkout promo that does not exist',
                    'full_name': 'tests/a.spec.ts:14:7 › home page shows checkout promo that does not exist',
                    'classification': TriageClassification.AUTOMATION_DEFECT,
                    'subtype': 'LOCATOR_FAILURE',
                    'what_happened': 'old',
                    'why_it_failed': 'old',
                    'recommended_action': 'old',
                    'owner': 'QE',
                }
            ],
        }
        merged = _merge(
            payload,
            {
                'runSummary': 'One locator is outdated and should be updated by QE.',
                'tests': [
                    {
                        'fullName': payload['failed_tests'][0]['full_name'],
                        'whatHappened': 'The heading Flash checkout was not on the page.',
                        'whyItFailed': 'The test still looks for a promo that the UI no longer shows.',
                        'recommendedAction': 'Change or remove that locator.',
                        'owner': 'QE',
                    }
                ],
            },
        )
        self.assertEqual(merged['executive_summary'], 'One locator is outdated and should be updated by QE.')
        self.assertEqual(merged['failed_tests'][0]['classification'], TriageClassification.AUTOMATION_DEFECT)
        self.assertEqual(merged['failed_tests'][0]['what_happened'], 'The heading Flash checkout was not on the page.')
        self.assertEqual(merged['failed_tests'][0]['owner'], 'QE')


if __name__ == '__main__':
    unittest.main()
