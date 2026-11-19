import importlib.util
from pathlib import Path
import unittest


script = Path(__file__).resolve().parents[1] / "retry-simulator-launch.py"
spec = importlib.util.spec_from_file_location("simulator_launch_retry", script)
retry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retry)


class SimulatorLaunchRetryTests(unittest.TestCase):
    def test_only_one_exact_launch_failure_can_repeat(self):
        incident = {"targetName": "IAERPUITests", "testIdentifierString": retry.TEST_ID,
                    "failureText": retry.LAUNCH_ERROR}
        report = {"result": "Failed", "failedTests": 1, "skippedTests": 0,
                  "totalTestCount": 100, "passedTests": 99, "expectedFailures": 0, "testFailures": [incident]}
        launch = {"title": "Launch ec.com.b2b.iaerp.demo", "isAssociatedWithFailure": True,
                  "childActivities": [{"title": retry.LAUNCH_ERROR, "isAssociatedWithFailure": True},
                                      {"title": "Tear Down"}]}
        steps = [{"title": "Start Test at 10:00"}, {"title": "Set Up"},
                 {"title": "Open ec.com.b2b.iaerp.demo", "childActivities": [launch]}]
        activities = {"testIdentifier": retry.TEST_ID, "testRuns": [{"activities": steps}]}
        self.assertTrue(retry.launch_failure(report, activities))
        after_tap = steps + [{"title": 'Tap "Clientes" Button'}]
        self.assertFalse(retry.launch_failure(report, activities | {"testRuns": [{"activities": after_tap}]}))
        for change in ({"failedTests": 2}, {"skippedTests": 1}, {"passedTests": 0}, {"passedTests": 1}, {"passedTests": 98},
                       {"testFailures": [incident, incident]}, {"result": "Passed"},
                       {"testFailures": [incident | {"failureText": "XCTAssertTrue failed"}]},
                       {"testFailures": [incident | {"testIdentifierString": "anotherTest()"}]},
                       {"testFailures": [incident | {"targetName": "IAERPAppTests"}]}):
            with self.subTest(change=change):
                self.assertFalse(retry.launch_failure(report | change, activities))
