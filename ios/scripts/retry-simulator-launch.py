"""Retry one failed XCTest launch on the same already-built app and simulator."""
import json
import os
from pathlib import Path
import subprocess
import sys

TEST_ID = "CustomerRegistrationUITests/testNewClientFromListThenUseExactMatchInDraft()"
LAUNCH_ERROR = "Application 'ec.com.b2b.iaerp.demo' does not have a process ID"


def launch_failure(summary: dict, activities: dict) -> bool:
    failures = summary.get("testFailures", [])
    return (
        summary.get("result") == "Failed"
        and summary.get("failedTests") == 1
        and summary.get("skippedTests") == 0
        and summary.get("totalTestCount") == 100
        and summary.get("passedTests") == 99
        and summary.get("expectedFailures") == 0
        and len(failures) == 1
        and failures[0].get("targetName") == "IAERPUITests"
        and failures[0].get("testIdentifierString") == TEST_ID
        and failures[0].get("failureText") == LAUNCH_ERROR
        and stopped_at_launch(activities)
    )


def stopped_at_launch(report: dict) -> bool:
    runs = report.get("testRuns", [])
    if report.get("testIdentifier") != TEST_ID or len(runs) != 1:
        return False
    steps = runs[0].get("activities", [])
    if len(steps) != 3:
        return False
    start, setup, opening = steps
    children = opening.get("childActivities", [])
    if len(children) != 1:
        return False
    launch = children[0]
    events = launch.get("childActivities", [])
    return (
        start.get("title", "").startswith("Start Test at ")
        and setup.get("title") == "Set Up"
        and opening.get("title") == "Open ec.com.b2b.iaerp.demo"
        and launch.get("title") == "Launch ec.com.b2b.iaerp.demo"
        and launch.get("isAssociatedWithFailure") is True
        and [event.get("title") for event in events] == [LAUNCH_ERROR, "Tear Down"]
        and events[0].get("isAssociatedWithFailure") is True
    )


def main() -> int:
    original = Path(os.environ["IAERP_RESULT_PATH"])
    result = subprocess.check_output([
        "xcrun", "xcresulttool", "get", "test-results", "summary", "--path", str(original),
    ])
    activities = subprocess.check_output([
        "xcrun", "xcresulttool", "get", "test-results", "activities", "--path", str(original), "--test-id", TEST_ID,
    ])
    if not launch_failure(json.loads(result), json.loads(activities)):
        print("The failure is outside the known simulator launch condition.", file=sys.stderr)
        return 1
    print("XCTest did not attach to the application at launch. Repeating the entire customer flow once.", flush=True)
    retry = original.with_name(original.stem + "-launch-retry.xcresult")
    target = "IAERPUITests/" + TEST_ID.removesuffix("()")
    subprocess.run([
        "xcodebuild", "test-without-building", "-project", "ios/IAERP/IAERP.xcodeproj",
        "-scheme", "IAERP", "-destination", "platform=iOS Simulator,id=" + os.environ["IAERP_SIMULATOR_ID"],
        "-derivedDataPath", os.environ["IAERP_DERIVED_DATA_PATH"], "-resultBundlePath", str(retry),
        "-parallel-testing-enabled", "NO", "-only-testing:" + target,
        "-test-timeouts-enabled", "YES", "-maximum-test-execution-time-allowance", "390",
        "-default-test-execution-time-allowance", "360",
    ], check=True)
    rerun = json.loads(subprocess.check_output([
        "xcrun", "xcresulttool", "get", "test-results", "summary", "--path", str(retry),
    ]))
    return 0 if (rerun["result"], rerun["passedTests"], rerun["failedTests"], rerun["skippedTests"]) == ("Passed", 1, 0, 0) else 1


if __name__ == "__main__":
    sys.exit(main())
