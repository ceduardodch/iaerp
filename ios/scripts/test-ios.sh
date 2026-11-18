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
swift test --package-path ios/IAERP
# Xcode 27 reused an older loaded UI test bundle after incremental reinstalls
# on the local simulator. Remove only this app's test runner before testing.
runner_id='ec.com.b2b.iaerp.demo.uitests.xctrunner'
if xcrun simctl get_app_container "$IAERP_SIMULATOR_ID" "$runner_id" app >/dev/null 2>&1; then
  xcrun simctl uninstall "$IAERP_SIMULATOR_ID" "$runner_id"
fi
xcodebuild test -project ios/IAERP/IAERP.xcodeproj -scheme IAERP \
  -destination "platform=iOS Simulator,id=$IAERP_SIMULATOR_ID" \
  -derivedDataPath "$derived_path" -resultBundlePath "$result_path" \
  -parallel-testing-enabled NO -maximum-concurrent-test-simulator-destinations 1 \
  -test-timeouts-enabled YES -default-test-execution-time-allowance 120 \
  -maximum-test-execution-time-allowance 150 CODE_SIGNING_ALLOWED=YES CODE_SIGN_IDENTITY=-
