#!/usr/bin/env python3
"""Offline tests for diagnostic redaction, exact inputs and single publication."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("diagnostic", Path(__file__).with_name("journal-registry-diagnostic.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Response(io.BytesIO):
    def __init__(self, status, body, headers=None):
        super().__init__(body)
        self.code = status
        self.headers = headers or {}


class DiagnosticTests(unittest.TestCase):
    def create(self, status=200, put_status=201, missing=None, corrupt=None, put_error=None):
        config = json.dumps({"architecture": "amd64", "os": "linux", "config": {
            "Env": ["DO_NOT_EMIT=private-value"], "Labels": {"org.opencontainers.image.source": "https://github.com/plurality-run/sync-web"}}}).encode()
        digest = lambda body: "sha256:" + hashlib.sha256(body).hexdigest()
        objects = {"config": config, "attestation": b'{"mediaType":"application/vnd.oci.image.manifest.v1+json"}'}
        objects["platform"] = json.dumps({"config": {"digest": digest(config)}}).encode()
        objects["index"] = json.dumps({"mediaType": "application/vnd.oci.image.index.v1+json", "manifests": [
            {"digest": digest(objects[k]), "size": len(objects[k])} for k in ["platform", "attestation"]]}).encode()
        digests = {k: digest(v) for k, v in objects.items()}
        calls = []

        def transport(request, timeout):
            calls.append(request)
            if "/token?" in request.full_url:
                return Response(status, json.dumps({"token": "registry-private-token"}).encode())
            if request.method == "PUT":
                if put_error:
                    raise put_error
                self.assertEqual(request.data, objects["index"])
                return Response(put_status, b'{"errors":[{"code":"DENIED","message":"Bearer registry-private-token https://x.invalid/path?token=signed-secret"}]}')
            kind = next(k for k, v in digests.items() if request.full_url.endswith(v))
            if kind == missing:
                return Response(404, b'{"errors":[{"code":"MANIFEST_UNKNOWN","message":"unknown"}]}')
            return Response(200, b'{}' if kind == corrupt else objects[kind])

        return module.Diagnostic("ghs_job-secret", "actor", "diagnostic-c2-123-1", transport), digests, calls

    def run_case(self, **kwargs):
        diagnostic, digests, calls = self.create(**kwargs)
        with patch.object(module, "DIGESTS", digests):
            diagnostic.run()
        return diagnostic, calls

    def test_complete_original_index_put_once(self):
        diagnostic, calls = self.run_case()
        self.assertEqual(diagnostic.report["publication"], "accepted")
        puts = [r for r in calls if r.method == "PUT"]
        self.assertEqual(len(puts), 1)
        self.assertTrue(puts[0].full_url.endswith("/diagnostic-c2-123-1"))
        self.assertNotIn("private-value", json.dumps(diagnostic.report))

    def test_missing_platform_no_publication(self):
        diagnostic, calls = self.run_case(missing="platform")
        self.assertEqual(diagnostic.report["phase"], "exact-existing-inputs-unavailable-no-publication")
        self.assertFalse(any(r.method == "PUT" for r in calls))

    def test_missing_index_no_publication(self):
        diagnostic, calls = self.run_case(missing="index")
        self.assertFalse(any(r.method == "PUT" for r in calls))

    def test_put_denied_is_sanitized_and_not_retried(self):
        diagnostic, calls = self.run_case(put_status=403)
        self.assertEqual(diagnostic.report["publication"], "unconfirmed")
        output = json.dumps(diagnostic.report)
        for value in ["ghs_job-secret", "registry-private-token", "signed-secret", "Authorization", "private-value"]:
            self.assertNotIn(value, output)
        self.assertEqual(sum(r.method == "PUT" for r in calls), 1)
        self.assertEqual(diagnostic.report["operations"][-1]["errors"][0]["code"], "DENIED")

    def test_server_error_keeps_mutation_unconfirmed(self):
        diagnostic, calls = self.run_case(put_status=503)
        self.assertEqual(diagnostic.report["publication"], "unconfirmed")
        self.assertEqual(diagnostic.report["operations"][-1]["status"], 503)
        self.assertEqual(sum(r.method == "PUT" for r in calls), 1)

    def test_corrupt_digest_fails_before_put(self):
        diagnostic, digests, calls = self.create(corrupt="platform")
        with patch.object(module, "DIGESTS", digests), self.assertRaises(ValueError):
            diagnostic.run()
        self.assertFalse(any(r.method == "PUT" for r in calls))

    def test_ambiguous_put_is_not_retried(self):
        diagnostic, digests, calls = self.create(put_error=TimeoutError("do-not-emit"))
        with patch.object(module, "DIGESTS", digests), self.assertRaises(TimeoutError):
            diagnostic.run()
        self.assertEqual(sum(r.method == "PUT" for r in calls), 1)
        self.assertEqual(diagnostic.report["publication"], "attempting-one-fresh-tag")
        self.assertNotIn("do-not-emit", json.dumps(diagnostic.report))

    def test_original_or_final_tag_rejected(self):
        for tag in ["latest", "0.1.0", "sha-a47ac0f2-musl", "diagnostic-c2-123-1?other=value"]:
            with self.assertRaises(ValueError):
                module.Diagnostic("secret", "actor", tag)

    def test_auth_failure_no_registry_or_publication(self):
        diagnostic, calls = self.run_case(status=403)
        self.assertEqual(diagnostic.report["phase"], "token-exchange-failed")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
