#!/usr/bin/env python3
"""Publish a fresh, verified canonical OCI graph with sanitized HTTP receipts."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tarfile
import urllib.parse

spec = importlib.util.spec_from_file_location("diagnostic", Path(__file__).with_name("journal-registry-diagnostic.py"))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

EXPECTED_LABELS = {
    "org.opencontainers.image.revision": base.CANDIDATE,
    "sync-web.source-tree": "3c4a3f5c2c7b26f7de61eb0205b77fda7d2ac35c",
    "sync-web.source-inputs-sha256": "cf70b91b245385de12d12f4faf8a3fba8fef46d08275b8f0846a93bb61c5b29e",
    "sync-web.lock-sha256": "d69e38d29ecabd5ae3d62cf2a7c018b292a9e3a40102a0547971bf0d03e34854",
    "sync-web.aot-sha256": "0c6b7fb7f94e1465e96617c28ebe6e216b4a71687062c8ca283bf4a10ad7416f",
}


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def read_graph(path):
    blobs = {}
    with tarfile.open(path) as archive:
        outer = archive.extractfile("index.json").read()
        layout = json.load(archive.extractfile("oci-layout"))
        if layout != {"imageLayoutVersion": "1.0.0"}:
            raise ValueError("Unexpected OCI layout")
        for item in archive.getmembers():
            if item.isfile() and item.name.startswith("blobs/sha256/"):
                if item.size > 512 * 1024 * 1024:
                    raise ValueError("Unexpected blob size")
                data = archive.extractfile(item).read()
                key = "sha256:" + item.name.removeprefix("blobs/sha256/")
                if digest(data) != key or key in blobs:
                    raise ValueError("Blob digest mismatch or duplicate")
                blobs[key] = data
    index = json.loads(outer)
    if len(index["manifests"]) == 1:
        root = blobs[index["manifests"][0]["digest"]]
        index = json.loads(root)
    else:
        root = outer
    children = index["manifests"]
    if len(children) != 2:
        raise ValueError("Attested index requires two children")
    attestation = [c for c in children if c.get("annotations", {}).get("vnd.docker.reference.type") == "attestation-manifest"]
    if len(attestation) != 1:
        raise ValueError("Attestation missing or ambiguous")
    attestation = attestation[0]
    platform = next(c for c in children if c is not attestation)
    if platform["platform"] != {"architecture": "amd64", "os": "linux"}:
        raise ValueError("Unexpected platform")
    manifests = [platform, attestation]
    required = {}
    for descriptor in manifests:
        data = blobs[descriptor["digest"]]
        if len(data) != descriptor["size"]:
            raise ValueError("Manifest size mismatch")
        manifest = json.loads(data)
        for item in [manifest["config"]] + manifest["layers"]:
            content = blobs[item["digest"]]
            if len(content) != item["size"]:
                raise ValueError("Referenced blob size mismatch")
            required[item["digest"]] = content
    image_manifest = json.loads(blobs[platform["digest"]])
    config = json.loads(blobs[image_manifest["config"]["digest"]])
    labels = config["config"]["Labels"]
    if config["os"] != "linux" or config["architecture"] != "amd64" or any(labels.get(k) != v for k, v in EXPECTED_LABELS.items()):
        raise ValueError("Frozen source/AOT/lock identity mismatch")
    attestation_manifest = json.loads(blobs[attestation["digest"]])
    subjects = []
    for item in attestation_manifest["layers"]:
        if item["mediaType"] != "application/vnd.in-toto+json":
            raise ValueError("Unexpected attestation layer")
        statement = json.loads(blobs[item["digest"]])
        subjects.extend(subject.get("digest", {}).get("sha256") for subject in statement["subject"])
    if not subjects or any(s != platform["digest"].removeprefix("sha256:") for s in subjects):
        raise ValueError("Attestation subject mismatch")
    return root, manifests, required, blobs


class Upload(base.Diagnostic):
    def run_archive(self, path, *, probe_only=False):
        root, manifests, required, blobs = read_graph(path)
        self.report["graph"] = {"indexDigest": digest(root), "platformDigest": manifests[0]["digest"],
                                "attestationDigest": manifests[1]["digest"], "blobCount": len(required),
                                "verifiedLabels": EXPECTED_LABELS}
        if not self.authenticate():
            return
        prefix = "/v2/" + base.PACKAGE
        for key, data in required.items():
            status, _, _ = self.call("HEAD", prefix + "/blobs/" + key)
            if status == 200:
                continue
            if status != 404:
                self.report["phase"] = "blob-head-not-authorized-or-unexpected"
                return
            self.report["publication"] = "uploading-fresh-graph-blobs"
            status, _, headers = self.call("POST", prefix + "/blobs/uploads/", data=b"")
            if status != 202:
                self.report["publication"] = "unconfirmed"
                self.report["phase"] = "blob-upload-start-not-confirmed"
                return
            location = urllib.parse.urlsplit(urllib.parse.urljoin("https://ghcr.io", headers.get("Location", "")))
            self.report["uploadLocationValidation"] = {
                "https": location.scheme == "https",
                "sameRegistryOrigin": location.netloc == "ghcr.io",
                "expectedUploadPrefix": location.path.startswith(prefix + "/blobs/uploads/"),
                "singularUploadPrefix": location.path.startswith(prefix + "/blobs/upload/"),
                "expectedPackagePrefix": location.path.startswith(prefix + "/"),
                "registryV2Prefix": location.path.startswith("/v2/"),
                "queryPresent": bool(location.query),
                "digestQueryPresent": any(k == "digest" for k, _ in urllib.parse.parse_qsl(location.query)),
            }
            if probe_only:
                self.report["publication"] = "session-start-acknowledged-no-content-puts"
                self.report["phase"] = "location-shape-probe-complete-no-put"
                return
            if location.scheme != "https" or location.netloc != "ghcr.io" or not location.path.startswith(prefix + "/blobs/uploads/"):
                raise ValueError("Unexpected upload location")
            query = urllib.parse.parse_qsl(location.query, keep_blank_values=True)
            self.secrets.extend(value for _, value in query if value)
            if any(k == "digest" for k, _ in query):
                raise ValueError("Unexpected upload digest parameter")
            path = location.path + "?" + urllib.parse.urlencode(query + [("digest", key)])
            status, _, _ = self.call("PUT", path, data=data, content_type="application/octet-stream",
                                     resource=prefix + "/blobs/uploads/<session>?digest=" + key)
            if status != 201:
                self.report["publication"] = "unconfirmed"
                self.report["phase"] = "blob-upload-completion-not-confirmed"
                return
        # Preserve the attestation and capture the runnable-manifest operation separately.
        for descriptor in reversed(manifests):
            self.report["publication"] = "uploading-fresh-manifests"
            status, _, _ = self.call("PUT", prefix + "/manifests/" + descriptor["digest"],
                                     data=blobs[descriptor["digest"]], content_type=descriptor["mediaType"])
            if status != 201:
                self.report["publication"] = "unconfirmed"
                self.report["phase"] = "child-manifest-not-confirmed"
                self.report["unconfirmedManifestDigest"] = descriptor["digest"]
                return
        self.report["publication"] = "attempting-one-fresh-tag"
        status, _, _ = self.call("PUT", prefix + "/manifests/" + self.tag, data=root,
                                 content_type=json.loads(root)["mediaType"])
        self.report["publication"] = "accepted" if status == 201 else "unconfirmed"
        self.report["phase"] = "fresh-tag-http-response-no-retry"


def main():
    output = Path(os.environ["DIAGNOSTIC_OUTPUT"])
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise SystemExit("Existing receipt; do not replay")
    diagnostic = Upload(os.environ["GH_TOKEN"], os.environ["GITHUB_ACTOR"], os.environ["DIAGNOSTIC_TAG"])
    diagnostic.output = output
    try:
        diagnostic.run_archive(os.environ["DIAGNOSTIC_ARCHIVE"],
                               probe_only=os.environ.get("DIAGNOSTIC_LOCATION_PROBE") == "1")
    except Exception as error:
        diagnostic.report["errorType"] = type(error).__name__
    finally:
        output.write_text(json.dumps(diagnostic.report, indent=2) + "\n")
        print(json.dumps(diagnostic.report, indent=2))


if __name__ == "__main__":
    main()
