#!/bin/bash
set -euo pipefail

# No installs or simulator downloads. Run from any directory.
repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repo_root"
: "${DEVELOPER_DIR:=/Applications/Xcode.app/Contents/Developer}"
export DEVELOPER_DIR
if [[ -z "${IAERP_SIMULATOR_ID:-}" ]]; then
  echo 'Set IAERP_SIMULATOR_ID to an existing simulator from xcrun simctl list devices.' >&2
  exit 2
fi
result_path="${IAERP_RESULT_PATH:-/tmp/iaerp-ios-$(date +%Y%m%d-%H%M%S).xcresult}"
derived_path="${IAERP_DERIVED_DATA_PATH:-/tmp/iaerp-workspace-derived}"
layout_log="${IAERP_LAYOUT_LOG_PATH:-${result_path%.xcresult}-layout.log}"
test_timeout="${IAERP_TEST_TIMEOUT_SECONDS:-120}"
test_max_timeout="${IAERP_TEST_MAX_TIMEOUT_SECONDS:-150}"
swift test --package-path ios/IAERP
xcrun simctl bootstatus "$IAERP_SIMULATOR_ID" -b
# Xcode 27 reused an older loaded UI test bundle after incremental reinstalls
# on the local simulator. Remove only this app's test runner before testing.
runner_id='ec.com.b2b.iaerp.demo.uitests.xctrunner'
if xcrun simctl get_app_container "$IAERP_SIMULATOR_ID" "$runner_id" app >/dev/null 2>&1; then
  xcrun simctl uninstall "$IAERP_SIMULATOR_ID" "$runner_id"
fi
# Capture only synthetic, explicitly enabled layout diagnostics. Keep the
# stream alive across XCTest app relaunches and preserve the test exit code.
xcrun simctl spawn "$IAERP_SIMULATOR_ID" log stream --style compact --level info --timeout "${IAERP_LAYOUT_LOG_TIMEOUT:-25m}" \
  --predicate 'subsystem == "ec.com.b2b.iaerp.layout" AND category == "InvoiceLayout"' \
  > "$layout_log" 2>&1 &
layout_stream_pid=$!
cleanup_layout_stream() {
  local test_exit=$?
  kill "$layout_stream_pid" 2>/dev/null || true
  wait "$layout_stream_pid" 2>/dev/null || true
  exit "$test_exit"
}
trap cleanup_layout_stream EXIT
xcodebuild test -project ios/IAERP/IAERP.xcodeproj -scheme IAERP \
  -destination "platform=iOS Simulator,id=$IAERP_SIMULATOR_ID" \
  -derivedDataPath "$derived_path" -resultBundlePath "$result_path" \
  -parallel-testing-enabled NO -maximum-concurrent-test-simulator-destinations 1 \
  -test-timeouts-enabled YES -default-test-execution-time-allowance "$test_timeout" \
  -maximum-test-execution-time-allowance "$test_max_timeout" CODE_SIGNING_ALLOWED=YES CODE_SIGN_IDENTITY=-
