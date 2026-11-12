#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

module = load("readback", "journal-registry-readback.py")
fixtures = load("upload_tests", "test-journal-registry-upload.py")


class ReadbackTests(unittest.TestCase):
    def exercise(self, *, redirect=None, corrupt=False):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"image.tar"
            fixtures.UploadTests().graph(path)
            index, manifests, required, blobs = module.upload.read_graph(path)
            calls = []
            first_blob = next(iter(required))
            def transport(request, timeout=60):
                calls.append(request)
                self.assertEqual(request.method, "GET")
                if "/token?" in request.full_url:
                    self.assertNotIn("push", request.full_url)
                    return fixtures.Response(200, b'{"token":"registry-secret"}')
                if request.full_url.startswith("https://pkg-containers.githubusercontent.com/"):
                    self.assertNotIn("Authorization", request.headers)
                    return fixtures.Response(200, blobs[first_blob])
                reference = request.full_url.rsplit("/", 1)[-1]
                if reference in (module.TAG, module.INDEX):
                    return fixtures.Response(200, index + (b"bad" if corrupt else b""))
                if redirect and reference == first_blob:
                    return fixtures.Response(307, headers={"Location": redirect})
                return fixtures.Response(200, blobs[reference])
            diagnostic = module.Readback("job-secret", "actor", module.TAG, transport)
            self.calls = calls
            with patch.object(module, "INDEX", module.upload.digest(index)):
                diagnostic.run_archive(path)
            return diagnostic

    def test_complete_graph_read_only(self):
        diagnostic = self.exercise()
        self.assertEqual(diagnostic.report["readback"], "complete-graph-bytes-verified")
        self.assertTrue(all(c.method == "GET" for c in self.calls))

    def test_storage_redirect_no_authorization_no_signed_url(self):
        diagnostic = self.exercise(redirect="https://pkg-containers.githubusercontent.com/blobs/INERT-PRIVATE-PATH?sig=INERT-PRIVATE-QUERY")
        self.assertNotIn("INERT-PRIVATE-PATH", json.dumps(diagnostic.report))
        self.assertNotIn("INERT-PRIVATE-QUERY", json.dumps(diagnostic.report))
        self.assertEqual(diagnostic.report["readback"], "complete-graph-bytes-verified")

    def test_wrong_origin_not_followed(self):
        with self.assertRaises(ValueError):
            self.exercise(redirect="https://untrusted.invalid/blob?sig=private")
        self.assertFalse(any(c.full_url.startswith("https://untrusted.invalid") for c in self.calls))

    def test_normal_docker_index_identity_no_push_and_auth_cleanup(self):
        diagnostic = self.exercise()
        directories = []
        commands = []
        image = "ghcr.io/" + module.base.PACKAGE + "@" + module.INDEX
        def process(args, **kwargs):
            commands.append(args)
            directories.append(kwargs["env"]["DOCKER_CONFIG"])
            self.assertTrue(Path(directories[-1]).is_dir())
            self.assertNotIn("push", args)
            output = b""
            if args[1:3] == ["image", "inspect"]:
                output = json.dumps([{"Id": module.INDEX, "RepoDigests": [image],
                                      "Os": "linux", "Architecture": "amd64",
                                      "Config": {"Labels": module.upload.EXPECTED_LABELS}}]).encode()
            if "--version" in args:
                output = b"journal-sdk 1.4.0\n"
            stderr = b""
            if "--evaluate" in args:
                self.assertIn("--network=none", args)
                self.assertIn("--read-only", args)
                self.assertIn("--pull=never", args)
                output = b"3\n"
                stderr = ("wasmer-runtime-attestation evaluator=wasmer-nofuel artifact-sha256=" + module.upload.EXPECTED_LABELS["sync-web.aot-sha256"] + " target=x86_64-linux evaluations=1\n").encode()
            return SimpleNamespace(returncode=0, stdout=output, stderr=stderr)
        with patch.object(module.subprocess, "run", process):
            diagnostic.docker_consumer()
        self.assertFalse(any(Path(p).exists() for p in directories))
        self.assertEqual(sum(c[1] == "pull" for c in commands), 2)
        self.assertEqual(diagnostic.report["normalDocker"]["result"], "authenticated-tag-and-digest-pull-offline-runtime-passed")
        self.assertNotIn("job-secret", json.dumps(diagnostic.report))
        self.assertEqual(diagnostic.report["normalDocker"]["imageIdRole"], "index")
        self.assertTrue(diagnostic.report["normalDocker"]["runtimeAttestation"]["matchesExpected"])

    def test_urls_suppressed_before_short_query_value_redaction(self):
        diagnostic = module.Readback("job-secret", "actor", module.TAG)
        diagnostic.secrets.extend(["r", "b", "https"])
        output = diagnostic.clean("https://example.invalid/INERT-PATH?sig=INERT-SIGNED-QUERY")
        self.assertNotIn("INERT", output)
        self.assertNotIn("example.invalid", output)

    def test_wrong_bytes_fail_closed(self):
        with self.assertRaises(ValueError):
            self.exercise(corrupt=True)


if __name__ == "__main__":
    unittest.main()
