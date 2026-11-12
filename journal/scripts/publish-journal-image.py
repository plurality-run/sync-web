#!/usr/bin/env python3
"""CI-only Journal SHA-image publication from the retained complete OCI archive."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[2]


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def expected_labels(evidence, kernel):
    source = dict(line.split("=", 1) for line in (evidence / "musl-source.txt").read_text().splitlines())
    if source != {
        "commit": os.environ["GITHUB_SHA"],
        "tree": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip(),
        "lock_sha256": digest((ROOT / "journal/Cargo.lock").read_bytes())[7:],
        "aot_sha256": digest(kernel.read_bytes())[7:],
        "source_inputs_sha256": digest((evidence / "musl-context-files.sha256").read_bytes())[7:],
    }:
        raise ValueError("Builder evidence identity mismatch")
    return {"org.opencontainers.image.revision": source["commit"],
            "sync-web.source-tree": source["tree"],
            "sync-web.source-inputs-sha256": source["source_inputs_sha256"],
            "sync-web.lock-sha256": source["lock_sha256"],
            "sync-web.aot-sha256": source["aot_sha256"]}


def read_graph(path, labels):
    blobs = {}
    with tarfile.open(path) as archive:
        outer = archive.extractfile("index.json").read()
        if json.load(archive.extractfile("oci-layout")) != {"imageLayoutVersion": "1.0.0"}:
            raise ValueError("Expected complete OCI archive")
        for item in archive.getmembers():
            if item.isfile() and item.name.startswith("blobs/sha256/"):
                if item.size > 512 * 1024 * 1024:
                    raise ValueError("Unexpected blob size")
                data = archive.extractfile(item).read()
                key = "sha256:" + item.name.removeprefix("blobs/sha256/")
                if digest(data) != key or key in blobs:
                    raise ValueError("Blob identity mismatch")
                blobs[key] = data
    index = json.loads(outer)
    root = outer
    if len(index["manifests"]) == 1:
        descriptor = index["manifests"][0]
        root = blobs[descriptor["digest"]]
        if len(root) != descriptor["size"]:
            raise ValueError("Index descriptor size mismatch")
        index = json.loads(root)
    if index["mediaType"] != "application/vnd.oci.image.index.v1+json":
        raise ValueError("Expected OCI index")
    children = index["manifests"]
    attestation = [c for c in children if c.get("annotations", {}).get("vnd.docker.reference.type") == "attestation-manifest"]
    if len(children) != 2 or len(attestation) != 1:
        raise ValueError("Complete platform and attestation required")
    attestation = attestation[0]
    platform = next(c for c in children if c is not attestation)
    if platform["platform"] != {"architecture": "amd64", "os": "linux"}:
        raise ValueError("Unexpected platform")
    required = {}
    for descriptor in (platform, attestation):
        data = blobs[descriptor["digest"]]
        if len(data) != descriptor["size"]:
            raise ValueError("Manifest size mismatch")
        manifest = json.loads(data)
        if descriptor["mediaType"] != "application/vnd.oci.image.manifest.v1+json" or manifest["mediaType"] != descriptor["mediaType"]:
            raise ValueError("Unexpected manifest role")
        for item in [manifest["config"]] + manifest["layers"]:
            content = blobs[item["digest"]]
            if len(content) != item["size"]:
                raise ValueError("Content descriptor size mismatch")
            required[item["digest"]] = content
    image_manifest = json.loads(blobs[platform["digest"]])
    config = json.loads(blobs[image_manifest["config"]["digest"]])
    if config["os"] != "linux" or config["architecture"] != "amd64" or any(config["config"]["Labels"].get(k) != v for k, v in labels.items()):
        raise ValueError("Builder provenance mismatch")
    subjects = []
    for layer in json.loads(blobs[attestation["digest"]])["layers"]:
        if layer["mediaType"] != "application/vnd.in-toto+json":
            raise ValueError("Unexpected attestation layer")
        subjects.extend(s["digest"]["sha256"] for s in json.loads(blobs[layer["digest"]])["subject"])
    if not subjects or any(s != platform["digest"][7:] for s in subjects):
        raise ValueError("Attestation subject mismatch")
    return root, platform, attestation, required, blobs


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Publisher:
    def __init__(self, repository, actor, token, transport=None):
        self.package = repository + "/journal-sdk"
        self.actor, self.token = actor, token
        self.bearer = None
        self.secrets = [token]
        self.transport = transport or urllib.request.build_opener(NoRedirect()).open
        self.report = {"publication": "not-started", "operations": []}

    def call(self, method, resource, *, data=None, media=None, target=None, auth=False):
        headers = {}
        if auth:
            encoded = base64.b64encode((self.actor + ":" + self.token).encode()).decode()
            self.secrets.append(encoded)
            headers["Authorization"] = "Basic " + encoded
        else:
            headers["Authorization"] = "Bearer " + self.bearer
        if media:
            headers["Content-Type"] = media
        row = {"method": method, "resource": resource}
        self.report["operations"].append(row)
        if method in ("POST", "PUT"):
            self.report["publication"] = "unconfirmed"
        request = urllib.request.Request(target or "https://ghcr.io" + resource,
                                         method=method, headers=headers, data=data)
        print(json.dumps({"request": row}), flush=True)
        try:
            response = self.transport(request, timeout=60)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            row["status"] = response.code
            location = response.headers.get("Location", "")
            # Register opaque server values before projecting any response header.
            if location:
                parsed = urllib.parse.urlsplit(location)
                self.secrets.extend([location, urllib.parse.unquote(location), parsed.path,
                                     urllib.parse.unquote(parsed.path)])
                self.secrets.extend(v for v in urllib.parse.unquote(parsed.path).split("/") if v)
                self.secrets.extend(v for _, v in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True) if v)
            request_id = response.headers.get("X-GitHub-Request-Id", "")
            if not auth and re.fullmatch(r"[0-9A-Fa-f:.-]{1,128}", request_id) and not any(s and s in request_id for s in self.secrets):
                row["requestId"] = request_id
            print(json.dumps({"response": row}), flush=True)
            body = response.read(1024 * 1024 + 1)
        if len(body) > 1024 * 1024:
            raise ValueError("Registry response exceeded bound")
        return response.code, body, location

    def publish(self, archive, labels):
        root, platform, attestation, required, blobs = read_graph(archive, labels)
        revision = labels["org.opencontainers.image.revision"]
        tag = "sha-" + revision + "-musl"
        self.report.update({"index": digest(root), "platform": platform["digest"],
                            "attestation": attestation["digest"], "tag": tag})
        scope = urllib.parse.urlencode({"service": "ghcr.io", "scope": "repository:" + self.package + ":pull,push"})
        status, body, _ = self.call("GET", "/token?" + scope, auth=True)
        if status != 200:
            raise ValueError("Registry authentication failed")
        self.bearer = json.loads(body)["token"]
        self.secrets.append(self.bearer)
        prefix = "/v2/" + self.package
        for key, content in required.items():
            status, _, _ = self.call("HEAD", prefix + "/blobs/" + key)
            if status == 200:
                continue
            if status != 404:
                raise ValueError("Unexpected blob HEAD status")
            status, _, location = self.call("POST", prefix + "/blobs/uploads/", data=b"")
            if status != 202:
                raise ValueError("Upload session unconfirmed")
            parsed = urllib.parse.urlsplit(urllib.parse.urljoin("https://ghcr.io", location))
            if parsed.scheme != "https" or parsed.netloc != "ghcr.io" or not parsed.path.startswith((prefix + "/blobs/uploads/", prefix + "/blobs/upload/")):
                raise ValueError("Unexpected upload location")
            if any(k == "digest" for k, _ in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)):
                raise ValueError("Unexpected upload digest query")
            query = parsed.query + ("&" if parsed.query else "") + urllib.parse.urlencode({"digest": key})
            target = parsed._replace(query=query, fragment="").geturl()
            status, _, _ = self.call("PUT", prefix + "/blobs/uploads/<session>?digest=" + key,
                                      data=content, media="application/octet-stream", target=target)
            if status != 201:
                raise ValueError("Blob PUT unconfirmed")
        for descriptor in (attestation, platform):
            status, _, _ = self.call("PUT", prefix + "/manifests/" + descriptor["digest"],
                                      data=blobs[descriptor["digest"]], media=descriptor["mediaType"])
            if status != 201:
                raise ValueError("Manifest PUT unconfirmed")
        self.report["phase"] = "index-put-no-retry"
        status, _, _ = self.call("PUT", prefix + "/manifests/" + tag,
                                  data=root, media="application/vnd.oci.image.index.v1+json")
        if status != 201:
            raise ValueError("Index PUT unconfirmed")
        self.report["publication"] = "accepted"


def main():
    archive, evidence, kernel = map(Path, sys.argv[1:])
    publisher = Publisher(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_ACTOR"], os.environ["GITHUB_TOKEN"])
    try:
        publisher.publish(archive, expected_labels(evidence, kernel))
    except Exception as exc:
        publisher.report["errorType"] = type(exc).__name__
        returncode = 1
    else:
        returncode = 0
    print(json.dumps(publisher.report, indent=2))
    return returncode


if __name__ == "__main__":
    sys.exit(main())
