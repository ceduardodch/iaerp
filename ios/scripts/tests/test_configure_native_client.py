"""Offline configuration gate tests; use the existing backend httpx dependency.

Run from the repository root, including optimized Python to catch assert gates:
backend/.venv/bin/python -O -m unittest discover -s ios/scripts/tests -v
"""

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx


IOS_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = IOS_ROOT / "scripts/configure-native-client.py"
SPEC = importlib.util.spec_from_file_location("configure_native_client", SCRIPT)
NATIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NATIVE)
CLIENT_TEMPLATE = json.loads((IOS_ROOT / "configuration/keycloak-ios-client.json").read_text())
PROFILE_TEMPLATE = json.loads((IOS_ROOT / "configuration/keycloak-ios-profile-scope.json").read_text())
REAL_HTTPX_CLIENT = httpx.Client


class ConfigureNativeClientTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.hashes = {}
        for name in NATIVE.BACKEND_FILES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            content = ("synthetic:" + name).encode()
            path.write_bytes(content)
            self.hashes[name] = hashlib.sha256(content).hexdigest()

    def test_exact_hash_validation(self):
        NATIVE.verify_backend_hashes(self.hashes, self.root)
        malformed = [None, {}, {"extra": "a" * 64}, {**self.hashes, "extra": "a" * 64}]
        missing = dict(self.hashes)
        del missing["app/core/auth.py"]
        malformed.append(missing)
        for value in ("", "a" * 63, "A" * 64, 12):
            malformed.append({**self.hashes, "app/core/auth.py": value})
        for expected in malformed:
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                NATIVE.verify_backend_hashes(expected, self.root)
        with self.assertRaises(ValueError):
            NATIVE.verify_backend_hashes({**self.hashes, "app/core/auth.py": "0" * 64}, self.root)
        (self.root / "app/core/auth.py").unlink()
        with self.assertRaises(RuntimeError):
            NATIVE.verify_backend_hashes(self.hashes, self.root)

    def run_script(self, *, enable=False, mode=None, malformed=False):
        desired = copy.deepcopy(CLIENT_TEMPLATE)
        if malformed:
            desired["directAccessGrantsEnabled"] = True
        envelope = {
            "client": desired,
            "profileScope": PROFILE_TEMPLATE,
            "expectedBackendHashes": self.hashes,
        }
        state = {
            "registered": None, "default": {"unexpected"}, "optional": set(),
            "oauthCalls": 0, "enableCalls": 0, "mutations": [],
        }
        names = NATIVE.DEFAULT_SCOPES | {"organization", "unexpected"}
        scopes = [{"id": name, "name": name} for name in sorted(names)]

        if mode == "customer-scope-absent":
            scopes[:] = [scope for scope in scopes if scope["name"] not in {"customers:create", "products:create", "invoices:issue", "invoices:email"}]
        for scope in scopes:
            if scope["name"] in {"customers:create", "products:create", "invoices:issue", "invoices:email"}:
                scope.update(protocol="openid-connect", attributes={"include.in.token.scope": "true"})
                if mode == "invalid-customer-scope":
                    scope["protocolMappers"] = [{"name": "unexpected"}]

        def handler(request):
            path, verb = request.url.path, request.method

            def response(body=None):
                return httpx.Response(200, json={} if body is None else body)

            if path.endswith("/token"):
                state["oauthCalls"] += 1
                return response({"access_token": "synthetic-never-printed"})
            path = path.split("/admin/realms/test")[-1]
            if path == "/client-scopes":
                if verb == "POST":
                    data = json.loads(request.content)
                    self.assertIn(data["name"], {"customers:create", "products:create", "invoices:issue", "invoices:email"})
                    self.assertEqual(data, {"name": data["name"], "protocol": "openid-connect",
                                            "attributes": {"include.in.token.scope": "true"}})
                    scopes.append({**data, "id": data["name"]})
                return response(scopes)
            if path == "/clients":
                if verb == "POST":
                    state["registered"] = {**json.loads(request.content), "id": "native-id"}
                    state["mutations"].append(("stage", state["registered"]["enabled"]))
                    if mode == "stage-enabled":
                        state["registered"]["enabled"] = True
                    return response()
                return response([state["registered"]] if state["registered"] else [])
            if path == "/clients/native-id":
                if verb == "PUT":
                    updated = json.loads(request.content)
                    if updated["enabled"]:
                        state["enableCalls"] += 1
                    state["registered"] = {**updated, "id": "native-id"}
                    state["mutations"].append(("client", updated["enabled"]))
                    return response()
                body = copy.deepcopy(state["registered"])
                if mode == "final-mismatch" and body["enabled"]:
                    body["publicClient"] = False
                return response(body)
            for kind in ("default", "optional"):
                prefix = f"/clients/native-id/{kind}-client-scopes"
                if path == prefix:
                    actual = state[kind]
                    if mode == "scope-mismatch" and kind == "optional":
                        actual = actual | {"unexpected"}
                    return response([{"id": name, "name": name} for name in sorted(actual)])
                if path.startswith(prefix + "/"):
                    self.assertIs(state["registered"]["enabled"], False)
                    state["mutations"].append(("scope", False))
                    name = path[len(prefix) + 1:]
                    if verb == "PUT":
                        state[kind].add(name)
                    elif verb == "DELETE":
                        state[kind].discard(name)
                    else:
                        self.fail("Unexpected scope mutation")
                    return response()
            self.fail(f"Unexpected request {verb} {path}")

        def create_client(**kwargs):
            return REAL_HTTPX_CLIENT(transport=httpx.MockTransport(handler), **kwargs)

        verify = NATIVE.verify_backend_hashes
        args = [str(SCRIPT)] + (["--enable"] if enable else [])
        environment = {
            "OIDC_ADMIN_URL": "https://synthetic.invalid", "OIDC_ADMIN_REALM": "test",
            "OIDC_ADMIN_CLIENT_ID": "synthetic", "OIDC_ADMIN_CLIENT_SECRET": "synthetic",
        }
        with (
            patch.object(sys, "argv", args),
            patch.object(sys, "stdin", io.StringIO(json.dumps(envelope))),
            patch.dict(os.environ, environment),
            patch.object(NATIVE.httpx, "Client", create_client),
            patch.object(NATIVE, "verify_backend_hashes", lambda expected: verify(expected, self.root)),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            try:
                NATIVE.main()
            except Exception as error:
                return state, error, output.getvalue()
        return state, None, output.getvalue()

    def test_preparation_never_enables(self):
        state, error, output = self.run_script()
        self.assertIsNone(error)
        self.assertEqual(state["enableCalls"], 0)
        self.assertIs(state["registered"]["enabled"], False)
        self.assertNotIn("synthetic-never-printed", output)

    def test_customer_scope_created_and_assigned_only_to_native_client(self):
        state, error, _ = self.run_script(enable=True, mode="customer-scope-absent")
        self.assertIsNone(error)
        self.assertEqual(state["default"], NATIVE.DEFAULT_SCOPES)
        self.assertNotIn("parties:write", state["default"])

    def test_unexpected_scope_mapper_blocks_activation(self):
        state, error, _ = self.run_script(enable=True, mode="invalid-customer-scope")
        self.assertIsInstance(error, ValueError)
        self.assertEqual(state["mutations"], [])

    def test_enable_is_last_mutation(self):
        state, error, _ = self.run_script(enable=True)
        self.assertIsNone(error)
        self.assertEqual(state["enableCalls"], 1)
        self.assertEqual(state["mutations"][-1], ("client", True))
        self.assertIs(state["registered"]["enabled"], True)

    def test_hash_mismatch_before_oauth(self):
        (self.root / "app/core/auth.py").write_text("changed")
        state, error, _ = self.run_script(enable=True)
        self.assertIsInstance(error, ValueError)
        self.assertEqual(state["oauthCalls"], 0)
        self.assertIsNone(state["registered"])

    def test_scope_readback_blocks_enable(self):
        state, error, _ = self.run_script(enable=True, mode="scope-mismatch")
        self.assertIsInstance(error, ValueError)
        self.assertEqual(state["enableCalls"], 0)
        self.assertIs(state["registered"]["enabled"], False)

    def test_final_readback_rolls_back(self):
        state, error, _ = self.run_script(enable=True, mode="final-mismatch")
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(state["enableCalls"], 1)
        self.assertIs(state["registered"]["enabled"], False)

    def test_stage_must_be_disabled(self):
        state, error, _ = self.run_script(enable=True, mode="stage-enabled")
        self.assertIsInstance(error, ValueError)
        self.assertFalse(any(kind == "scope" for kind, _ in state["mutations"]))

    def test_unsafe_input_rejected_under_optimized_python(self):
        state, error, _ = self.run_script(enable=True, malformed=True)
        self.assertIsInstance(error, ValueError)
        self.assertEqual(state["oauthCalls"], 0)
        self.assertIsNone(state["registered"])


if __name__ == "__main__":
    unittest.main()
