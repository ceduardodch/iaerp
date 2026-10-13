"""The source-built MinIO override belongs only to synthetic CI tests."""

import re
import subprocess
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


class CiMinioIsolationTest(unittest.TestCase):
    def test_ci_minio_changes_trigger_oidc_without_production_deploy(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
        detector = next(
            step["run"]
            for step in workflow["jobs"]["changes"]["steps"]
            if "set_output()" in step.get("run", "")
        )
        for path in (
            "compose.ci.yaml",
            "infra/minio-ci/Dockerfile",
            "scripts/tests/test_ci_minio.py",
        ):
            for flag, expected in (("oidc", True), ("deploy", False)):
                line = next(
                    line
                    for line in detector.splitlines()
                    if f"then {flag}=true;" in line
                )
                pattern = re.search(r"changed '([^']+)'", line).group(1)
                result = subprocess.run(
                    ["grep", "-Eq", pattern], input=path + "\n", text=True, check=False
                )
                self.assertEqual(result.returncode == 0, expected, (path, flag))

    def test_override_changes_only_the_ci_minio_service(self):
        override = yaml.safe_load((ROOT / "compose.ci.yaml").read_text())
        self.assertEqual(set(override), {"services"})
        self.assertEqual(set(override["services"]), {"minio"})
        minio = override["services"]["minio"]
        self.assertEqual(minio["pull_policy"], "build")
        self.assertEqual(minio["build"]["context"], "./infra/minio-ci")

    def test_compose_override_is_scoped_to_oidc_test_job(self):
        jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
        self.assertEqual(
            jobs["oidc"]["env"]["COMPOSE_FILE"], "compose.yaml:compose.ci.yaml"
        )
        for name, job in jobs.items():
            if name != "oidc":
                self.assertNotIn("COMPOSE_FILE", job.get("env", {}))
        production = (ROOT / "compose.coolify.yaml").read_text()
        self.assertNotIn("iaerp-minio-ci", production)
        self.assertNotIn("infra/minio-ci", production)

    def test_source_is_official_pinned_and_checksum_verified(self):
        recipe = (ROOT / "infra/minio-ci/Dockerfile").read_text()
        self.assertIn("https://codeload.github.com/minio/minio/tar.gz/", recipe)
        self.assertRegex(recipe, r"tar.gz/[0-9a-f]{40}\b")
        self.assertRegex(recipe, r'echo "[0-9a-f]{64}  /tmp/minio.tar.gz"')
        self.assertIn("sha256sum -c -", recipe)
        self.assertIn("-mod=readonly", recipe)
        self.assertIn("GOTOOLCHAIN=local", recipe)
        self.assertIn("COPY --from=build /src/LICENSE", recipe)
        self.assertRegex(recipe, r"(?m)^USER minio$")
        self.assertIsNone(re.search(r"FROM .*:latest\b", recipe))


if __name__ == "__main__":
    unittest.main()
