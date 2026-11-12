#!/usr/bin/env python3
"""Inert graph, authority-boundary and no-retry tests for the CI publisher."""
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location("publisher", Path(__file__).with_name("publish-journal-image.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
LABELS = {"org.opencontainers.image.revision": "a" * 40, "sync-web.source-tree": "b" * 40,
          "sync-web.source-inputs-sha256": "c" * 64, "sync-web.lock-sha256": "d" * 64,
          "sync-web.aot-sha256": "e" * 64}


class Response:
    def __init__(self, code, body=b"", headers=None):
        self.code, self.body, self.headers = code, body, headers or {}
    def read(self, count):
        return self.body[:count]
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.stdout_patch = patch("sys.stdout", new_callable=io.StringIO)
        self.stdout = self.stdout_patch.start()
        self.addCleanup(self.stdout_patch.stop)

    def graph(self, path, *, fault=None):
        blobs = {}
        def blob(value, media):
            if media in ("application/vnd.oci.image.index.v1+json", "application/vnd.oci.image.manifest.v1+json"):
                value = {"schemaVersion": 2, "mediaType": media, **value}
            data = json.dumps(value, sort_keys=True).encode()
            key = module.digest(data)
            blobs[key] = data
            return {"digest": key, "size": len(data), "mediaType": media}
        labels = dict(LABELS)
        if fault == "labels":
            labels["sync-web.aot-sha256"] = "f" * 64
        config = blob({"architecture": "amd64", "os": "linux", "config": {"Labels": labels}}, "application/vnd.oci.image.config.v1+json")
        layer = blob({"inert": True}, "application/vnd.oci.image.layer.v1.tar+gzip")
        if fault == "content-size":
            layer["size"] += 1
        platform = blob({"config": config, "layers": [layer]}, "application/vnd.oci.image.manifest.v1+json")
        platform["platform"] = {"os": "linux", "architecture": "amd64"}
        statement = blob({"subject": [{"digest": {"sha256": "0" * 64 if fault == "subject" else platform["digest"][7:]}}]}, "application/vnd.in-toto+json")
        attestation = blob({"config": blob({}, "application/vnd.oci.image.config.v1+json"), "layers": [statement]}, "application/vnd.oci.image.manifest.v1+json")
        attestation["annotations"] = {"vnd.docker.reference.type": "attestation-manifest"}
        if fault == "manifest-size":
            platform["size"] += 1
        if fault == "mediaType":
            platform["mediaType"] = "application/octet-stream"
        root = blob({"schemaVersion": 2, "manifests": [platform] if fault == "missing-attestation" else [platform, attestation]}, "application/vnd.oci.image.index.v1+json")
        if fault == "index-size":
            root["size"] += 1
        if fault == "blob-hash":
            blobs[config["digest"]] += b"tampered"
        with tarfile.open(path, "w") as archive:
            entries = {"oci-layout": b'{"imageLayoutVersion":"1.0.0"}',
                       "index.json": json.dumps({"manifests": [root]}).encode()}
            entries.update({"blobs/sha256/" + k[7:]: v for k, v in blobs.items()})
            for name, data in entries.items():
                item = tarfile.TarInfo(name)
                item.size = len(data)
                archive.addfile(item, io.BytesIO(data))

    def exercise(self, *, missing=False, location=None, fail=None, timeout_failure=False):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"image.tar"
            self.graph(path)
            self.calls = []
            def transport(request, timeout=60):
                self.calls.append(request)
                if "/token?" in request.full_url:
                    return Response(200, b'{"token":"inert-registry-secret"}')
                if request.method == "HEAD":
                    return Response(404 if missing else 200)
                if request.method == "POST":
                    return Response(202, headers={"Location": location, "X-GitHub-Request-Id": "abcdef0123456789"})
                if request.method == "PUT" and request.full_url.endswith("/sha-" + "a" * 40 + "-musl"):
                    if timeout_failure:
                        raise TimeoutError("INERT-PRIVATE-URI-MUST-NOT-BE-EMITTED")
                    return Response(fail or 201, b'{"errors":[{"message":"INERT-PRIVATE-BODY"}]}')
                return Response(201)
            publisher = module.Publisher("example/repository", "actor", "inert-job-secret", transport)
            self.publisher = publisher
            publisher.publish(path, LABELS)
            return publisher

    def test_complete_graph_and_fresh_tag(self):
        publisher = self.exercise()
        self.assertEqual(publisher.report["publication"], "accepted")
        puts = [c for c in self.calls if c.method == "PUT"]
        self.assertEqual(len(puts), 3)
        self.assertTrue(puts[-1].full_url.endswith("sha-" + "a" * 40 + "-musl"))
        self.assertEqual(module.digest(puts[0].data), publisher.report["attestation"])
        self.assertEqual(module.digest(puts[1].data), publisher.report["platform"])
        self.assertEqual(module.digest(puts[2].data), publisher.report["index"])

    def test_both_verified_upload_prefixes_and_secret_projection(self):
        for prefix in ["uploads", "upload"]:
            with self.subTest(prefix=prefix):
                location = "https://ghcr.io/v2/example/repository/journal-sdk/blobs/" + prefix + "/abcdef0123456789?state=INERT-SESSION-QUERY"
                publisher = self.exercise(missing=True, location=location)
                self.assertEqual(publisher.report["publication"], "accepted")
                output = json.dumps(publisher.report) + self.stdout.getvalue()
                for secret in ["abcdef0123456789", "INERT-SESSION-QUERY", "inert-job-secret", "inert-registry-secret", "INERT-PRIVATE-BODY"]:
                    self.assertNotIn(secret, output)
                for call in self.calls:
                    self.assertTrue(call.full_url.startswith("https://ghcr.io/"))
                    if call.method == "PUT" and "?" in call.full_url:
                        key = module.urllib.parse.parse_qs(module.urllib.parse.urlsplit(call.full_url).query)["digest"][0]
                        self.assertEqual(module.digest(call.data), key)

    def test_wrong_origin_package_or_digest_query_never_put(self):
        for location in ["https://untrusted.invalid/v2/example/repository/journal-sdk/blobs/upload/private",
                         "https://ghcr.io/v2/other/repository/journal-sdk/blobs/upload/private",
                         "https://ghcr.io/v2/example/repository/journal-sdk/blobs/upload/private?digest=wrong",
                         "https://ghcr.io/v2/example/repository/journal-sdk/blobs/upload/private?digest="]:
            with self.subTest(location=location), self.assertRaises(ValueError):
                self.exercise(missing=True, location=location)
            self.assertFalse(any(c.method == "PUT" for c in self.calls))

    def test_http_error_projection_never_serializes_body_or_location(self):
        error = module.urllib.error.HTTPError("https://ghcr.io/inert", 503, "INERT-PRIVATE-ERROR",
                                             {"Location": "/opaque/abcdef0123456789", "X-GitHub-Request-Id": "abcdef0123456789"},
                                             io.BytesIO(b"INERT-PRIVATE-BODY"))
        transport = Mock(side_effect=error)
        publisher = module.Publisher("example/repository", "actor", "secret", transport)
        publisher.bearer = "inert"
        status, _, _ = publisher.call("PUT", "/v2/example/repository/journal-sdk/manifests/inert", data=b"inert")
        self.assertEqual(status, 503)
        self.assertEqual(publisher.report["publication"], "unconfirmed")
        self.assertEqual(transport.call_count, 1)
        for secret in ["abcdef0123456789", "INERT-PRIVATE-ERROR", "INERT-PRIVATE-BODY"]:
            self.assertNotIn(secret, self.stdout.getvalue() + json.dumps(publisher.report))

    def test_redirect_handler_refuses_credential_forwarding(self):
        self.assertIsNone(module.NoRedirect().redirect_request(None, None, 307, "redirect", {}, "https://untrusted.invalid"))

    def test_503_is_unconfirmed_and_not_retried(self):
        with self.assertRaises(ValueError):
            self.exercise(fail=503)
        self.assertEqual(self.publisher.report["publication"], "unconfirmed")
        self.assertEqual(self.publisher.report["operations"][-1]["status"], 503)
        self.assertEqual(sum(c.full_url.endswith("/sha-" + "a" * 40 + "-musl") for c in self.calls), 1)

    def test_timeout_is_unconfirmed_and_not_retried(self):
        with self.assertRaises(TimeoutError):
            self.exercise(timeout_failure=True)
        self.assertEqual(self.publisher.report["publication"], "unconfirmed")
        self.assertNotIn("INERT-PRIVATE-URI", json.dumps(self.publisher.report))
        self.assertEqual(sum(c.full_url.endswith("/sha-" + "a" * 40 + "-musl") for c in self.calls), 1)

    def test_known_202_survives_response_body_timeout(self):
        class BodyTimeout(Response):
            def read(self, count):
                raise TimeoutError("INERT-PRIVATE-SAS")
        transport = Mock(return_value=BodyTimeout(202))
        publisher = module.Publisher("example/repository", "actor", "secret", transport)
        publisher.bearer = "inert"
        with self.assertRaises(TimeoutError):
            publisher.call("POST", "/v2/example/repository/journal-sdk/blobs/uploads/", data=b"")
        self.assertEqual(publisher.report["operations"][-1]["status"], 202)
        self.assertEqual(publisher.report["publication"], "unconfirmed")
        self.assertEqual(transport.call_count, 1)
        self.assertIn('"status": 202', self.stdout.getvalue())
        self.assertNotIn("INERT-PRIVATE-SAS", json.dumps(publisher.report) + self.stdout.getvalue())

    def test_graph_negatives_before_any_authentication(self):
        for fault in ["labels", "subject", "content-size", "manifest-size", "index-size", "blob-hash", "missing-attestation", "mediaType"]:
            with tempfile.TemporaryDirectory() as directory, self.subTest(fault=fault):
                path = Path(directory)/"image.tar"
                self.graph(path, fault=fault)
                calls = []
                publisher = module.Publisher("example/repository", "actor", "secret", lambda *a, **k: calls.append(a))
                with self.assertRaises((ValueError, KeyError)):
                    publisher.publish(path, LABELS)
                self.assertEqual(calls, [])

    def test_expected_labels_bound_to_actual_builder_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/"journal").mkdir()
            (root/"journal/Cargo.lock").write_bytes(b"inert-lock")
            (root/"kernel").write_bytes(b"inert-kernel")
            (root/"musl-context-files.sha256").write_bytes(b"inert-context")
            source = {"commit": "a" * 40, "tree": "b" * 40,
                      "lock_sha256": module.digest(b"inert-lock")[7:],
                      "aot_sha256": module.digest(b"inert-kernel")[7:],
                      "source_inputs_sha256": module.digest(b"inert-context")[7:]}
            (root/"musl-source.txt").write_text("".join(k + "=" + v + "\n" for k, v in source.items()))
            with patch.object(module, "ROOT", root), patch.dict(os.environ, {"GITHUB_SHA": "a" * 40}), patch.object(module.subprocess, "check_output", return_value="b" * 40 + "\n"):
                self.assertEqual(module.expected_labels(root, root/"kernel")["sync-web.aot-sha256"], module.digest(b"inert-kernel")[7:])
                (root/"kernel").write_bytes(b"changed")
                with self.assertRaises(ValueError):
                    module.expected_labels(root, root/"kernel")


if __name__ == "__main__":
    unittest.main()
