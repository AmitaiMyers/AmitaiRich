"""The committed JS parity fixture must match what the Python engine produces today.

If this fails, the Python engine changed: regenerate with `python -m tests.make_js_fixtures`
and make the JS engine (pwa/js/engine) pass `node --test pwa/tests/*.test.mjs` again.
"""

import unittest

from tests.make_js_fixtures import FIXTURE_PATH, fixture_json


class JsFixtureFreshnessTest(unittest.TestCase):
    def test_fixture_is_up_to_date(self):
        with open(FIXTURE_PATH) as fh:
            committed = fh.read()
        self.assertTrue(committed == fixture_json(),
                        "pwa/tests/fixtures/parity.json is stale — run: python -m tests.make_js_fixtures")


if __name__ == "__main__":
    unittest.main()
