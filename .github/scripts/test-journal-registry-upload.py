#!/usr/bin/env python3
"""Offline tests for canonical graph validation and staged registry capture."""
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("upload", Path(__file__).with_name("journal-registry-upload.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Response(io.BytesIO):
    def __init__(self, status, body=b"", headers=None):
        super().__init__(body)
        self.code = status
        self.headers = headers or {}


class UploadTests(unittest.TestCase):
    def graph(self, path, *, labels=None, attest=True):
        blobs = {}
        def add(value):
            body = value if isinstance(value, bytes) else json.dumps(value).encode()
            key = module.digest(body)
            blobs[key] = body
            return {"digest": key, "size": len(body)}
        config = add({"architecture": "amd64", "os": "linux", "config": {"Labels": labels or module.EXPECTED_LABELS}})
        layer = add(b"runtime-layer")
        platform = add({"config": config, "layers": [layer]})
        platform.update(mediaType="application/vnd.oci.image.manifest.v1+json", platform={"architecture": "amd64", "os": "linux"})
        statement = add({"subject": [{"digest": {"sha256": platform["digest"].removeprefix("sha256:")}}]})
        statement["mediaType"] = "application/vnd.in-toto+json"
        attestation = add({"config": add(b"{}"), "layers": [statement]})
        attestation.update(mediaType="application/vnd.oci.image.manifest.v1+json", annotations={"vnd.docker.reference.type": "attestation-manifest"})
        root = add({"mediaType": "application/vnd.oci.image.index.v1+json", "manifests": [platform, attestation] if attest else [platform]})
        files = {"index.json": json.dumps({"manifests": [root]}).encode(), "oci-layout": b'{"imageLayoutVersion":"1.0.0"}'}
        files.update({"blobs/sha256/" + key.removeprefix("sha256:"): body for key, body in blobs.items()})
        with tarfile.open(path, "w") as archive:
            for name, body in files.items():
                info = tarfile.TarInfo(name)
                info.size = len(body)
                archive.addfile(info, io.BytesIO(body))
        return root

    def run_upload(self, path, *, missing_blobs=False, reject=None, timeout=False, receipt=None):
        calls = []
        simulate_timeout = timeout
        def transport(request, timeout=60):
            calls.append(request)
            if "/token?" in request.full_url:
                return Response(200, b'{"token":"registry-secret"}')
            if request.method == "HEAD":
                return Response(404 if missing_blobs else 200)
            if request.method == "POST":
                return Response(202, headers={"Location": "https://ghcr.io/v2/" + module.base.PACKAGE + "/blobs/uploads/session?upload_state=opaque-private-session"})
            if simulate_timeout:
                raise TimeoutError("never-emit-private-detail")
            if reject and "/manifests/" in request.full_url:
                return Response(reject, b'{"errors":[{"code":"DENIED","message":"Bearer registry-secret"}]}')
            return Response(201)
        upload = module.Upload("ghs_job-secret", "actor", "diagnostic-c2-123-1", transport)
        upload.output = receipt
        upload.run_archive(path)
        return upload, calls

    def test_complete_attested_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"image.tar"
            root = self.graph(path)
            upload, calls = self.run_upload(path)
            self.assertEqual(upload.report["publication"], "accepted")
            self.assertEqual(upload.report["graph"]["indexDigest"], root["digest"])
            puts = [c for c in calls if c.method == "PUT"]
            self.assertEqual(len(puts), 3)
            self.assertTrue(puts[-1].full_url.endswith("diagnostic-c2-123-1"))

    def test_missing_attestation_stops_before_network(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"image.tar"
            self.graph(path, attest=False)
            with self.assertRaises(ValueError):
                self.run_upload(path)

    def test_wrong_frozen_identity_stops_before_network(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"image.tar"
            self.graph(path, labels={**module.EXPECTED_LABELS, "sync-web.aot-sha256": "wrong"})
            with self.assertRaises(ValueError):
                self.run_upload(path)

    def test_upload_sessions_are_not_emitted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"image.tar"
            self.graph(path)
            upload, calls = self.run_upload(path, missing_blobs=True)
            self.assertEqual(upload.report["publication"], "accepted")
            output = json.dumps(upload.report)
            self.assertNotIn("opaque-private-session", output)
            self.assertNotIn("registry-secret", output)
            self.assertTrue(any(c.method == "POST" for c in calls))

    def test_manifest_denial_stops_and_is_sanitized(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"image.tar"
            self.graph(path)
            upload, calls = self.run_upload(path, reject=403)
            self.assertEqual(upload.report["phase"], "child-manifest-rejected")
            self.assertEqual(sum(c.method == "PUT" for c in calls), 1)
            self.assertNotIn("registry-secret", json.dumps(upload.report))
            self.assertEqual(upload.report["operations"][-1]["status"], 403)

    def test_ambiguous_mutation_checkpointed_without_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"image.tar"
            receipt = Path(directory)/"receipt.json"
            self.graph(path)
            with self.assertRaises(TimeoutError):
                self.run_upload(path, timeout=True, receipt=receipt)
            saved = json.loads(receipt.read_text())
            self.assertEqual(saved["operations"][-1]["method"], "PUT")
            self.assertEqual(saved["operations"][-1]["transportError"], "TimeoutError")
            self.assertNotIn("never-emit-private-detail", receipt.read_text())


if __name__ == "__main__":
    unittest.main()
