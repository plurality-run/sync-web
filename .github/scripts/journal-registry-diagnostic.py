#!/usr/bin/env python3
"""Inspect immutable Journal manifests and conditionally test one fresh tag."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request

CANDIDATE = "a47ac0f27045dfff361eaca481eda3190d5d5590"
PACKAGE = "plurality-run/sync-web/journal-sdk"
DIGESTS = {
    "platform": "sha256:1d8fb46788b1e8ec77738b20b5ed18f6892f6707b29dce4756b5b2f1a0bce9c8",
    "config": "sha256:84921668ebbf0df71a7b6befaf51ce2949087e6c856e13b53f32d8214eac380d",
    "attestation": "sha256:7e1eec79c1bf66886635044e7775836ebf24593bcfe611bf4a417ee289b5c3d9",
    "index": "sha256:9636cf7f8d472c02689823499dcf22263567da039753ada5b0b0c895832551c3",
}
ACCEPT = ", ".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Diagnostic:
    def __init__(self, job_token, actor, tag, transport=None):
        if not re.fullmatch(r"diagnostic-c2-[0-9]+-[0-9]+", tag):
            raise ValueError("Invalid diagnostic tag")
        self.secrets = [job_token]
        self.job_token = job_token
        self.actor = actor
        self.tag = tag
        self.bearer = None
        self.output = None
        self.transport = transport or urllib.request.build_opener(NoRedirect()).open
        self.report = {"candidate": CANDIDATE, "package": PACKAGE, "tag": tag,
                       "operations": [], "objects": {}, "publication": "not-attempted"}

    def record(self):
        if self.output:
            self.output.write_text(json.dumps(self.report, indent=2) + "\n")

    def clean(self, value):
        text = str(value)
        for secret in self.secrets:
            if secret:
                text = text.replace(secret, "[REDACTED]")
        text = re.sub(r"(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)", "[REDACTED]", text)
        text = re.sub(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED]", text)
        text = re.sub(r"(?i)(?:Bearer|Basic)\s+[^\s,;]+", "[REDACTED]", text)
        text = re.sub(r"https?://[^\s\"<>]+", lambda m: self.safe_url(m[0]), text)
        return text[:500]

    def redact_location(self, value):
        self.secrets.extend([value, urllib.parse.unquote(value)])
        parsed = urllib.parse.urlsplit(value)
        self.secrets.extend(v for _, v in urllib.parse.parse_qsl(parsed.query) if v)
        self.secrets.extend(v for v in [parsed.path, urllib.parse.unquote(parsed.path),
                                        urllib.parse.unquote(parsed.path).rsplit("/", 1)[-1]] if v)
        if "/blobs/" in parsed.path:
            tail = parsed.path.split("/blobs/", 1)[1]
            self.secrets.extend(v for v in [tail, urllib.parse.unquote(tail)] if v)
            self.secrets.extend(v for v in urllib.parse.unquote(tail).split("/") if v)

    @staticmethod
    def safe_url(value):
        return "[URL-REDACTED]"

    def call(self, method, path, *, data=None, content_type=None, auth=False, url=None, resource=None):
        target = url or "https://ghcr.io" + path
        headers = {"User-Agent": "journal-publication-diagnostic", "Accept": ACCEPT}
        if auth:
            basic = base64.b64encode((self.actor + ":" + self.job_token).encode()).decode()
            self.secrets.append(basic)
            headers["Authorization"] = "Basic " + basic
        elif url is None:
            headers["Authorization"] = "Bearer " + self.bearer
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(target, method=method, headers=headers, data=data)
        row = {"method": method, "resource": resource or path}
        self.report["operations"].append(row)
        self.record()
        try:
            try:
                response = self.transport(request, timeout=60)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                status = response.code
                body = response.read(1024 * 1024 + 1)
                response_headers = response.headers
            row["status"] = status
            if len(body) > 1024 * 1024:
                raise ValueError("Response exceeded diagnostic bound")
            # Learn opaque session identifiers before serializing echoed headers or errors.
            if response_headers.get("Location"):
                self.redact_location(response_headers["Location"])
            row["headers"] = {name: self.clean(response_headers[name]) for name in
                              ["Content-Type", "Docker-Content-Digest", "X-GitHub-Request-Id", "X-Request-Id"]
                              if response_headers.get(name)}
            if status >= 400:
                row["bodySha256"] = hashlib.sha256(body).hexdigest()
                try:
                    errors = json.loads(body).get("errors", [])
                    row["errors"] = [{key: self.clean(e[key]) for key in ["code", "message"] if key in e}
                                     for e in errors[:5] if isinstance(e, dict)]
                except (ValueError, AttributeError, TypeError):
                    row["errors"] = "nonstandard-error-body-not-emitted"
            self.record()
            return status, body, response_headers
        except Exception as error:
            row["transportError"] = type(error).__name__
            self.record()
            raise

    def authenticate(self):
        scope = "repository:" + PACKAGE + ":pull,push"
        query = urllib.parse.urlencode({"service": "ghcr.io", "scope": scope})
        status, body, _ = self.call("GET", "/token", auth=True, url="https://ghcr.io/token?" + query)
        if status != 200:
            self.report["phase"] = "token-exchange-failed"
            return False
        grant = json.loads(body)
        self.bearer = grant.get("token") or grant["access_token"]
        self.secrets.append(self.bearer)
        # Inspect only permission claims, never serialize the credential itself.
        try:
            payload = self.bearer.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            self.report["registryTokenAccessClaims"] = [
                {"name": self.clean(item.get("name", "")), "actions": [self.clean(a) for a in item.get("actions", [])]}
                for item in claims.get("access", []) if item.get("name") == PACKAGE]
        except (IndexError, ValueError, TypeError):
            self.report["registryTokenAccessClaims"] = "opaque-or-unavailable"
        return True

    def run(self):
        if not self.authenticate():
            return
        objects = {}
        for kind in ["platform", "attestation", "index", "config"]:
            resource = "blobs" if kind == "config" else "manifests"
            path = "/v2/" + PACKAGE + "/" + resource + "/" + DIGESTS[kind]
            status, body, headers = self.call("GET", path)
            if status in (301, 302, 307) and kind == "config":
                location = urllib.parse.urlsplit(headers.get("Location", ""))
                if location.scheme != "https" or location.hostname != "pkg-containers.githubusercontent.com" or location.username or location.password:
                    raise ValueError("Unexpected config redirect")
                status, body, _ = self.call("GET", "config-blob-storage-redirect", url=location.geturl())
            self.report["objects"][kind] = {"digest": DIGESTS[kind], "status": status}
            if status in (401, 403):
                self.report["phase"] = "registry-read-denied"
                return
            if status == 404:
                continue
            if status != 200:
                self.report["phase"] = "unexpected-registry-response"
                return
            if "sha256:" + hashlib.sha256(body).hexdigest() != DIGESTS[kind]:
                raise ValueError("Object digest mismatch")
            objects[kind] = (json.loads(body), body)
            if kind == "config":
                config = objects[kind][0]
                labels = config.get("config", {}).get("Labels") or {}
                self.report["configMetadata"] = {"architecture": self.clean(config.get("architecture", "")),
                    "os": self.clean(config.get("os", "")), "labels": {k: self.clean(labels[k]) for k in
                    ["org.opencontainers.image.source", "org.opencontainers.image.revision", "org.opencontainers.image.version"] if k in labels}}
        if set(objects) != set(DIGESTS):
            self.report["phase"] = "exact-existing-inputs-unavailable-no-publication"
            return
        index = objects["index"][0]
        children = {item["digest"]: item for item in index["manifests"]}
        if set(children) != {DIGESTS["platform"], DIGESTS["attestation"]}:
            raise ValueError("Unexpected index child set")
        for kind in ["platform", "attestation"]:
            if children[DIGESTS[kind]]["size"] != len(objects[kind][1]):
                raise ValueError("Index child size mismatch")
        if objects["platform"][0]["config"]["digest"] != DIGESTS["config"]:
            raise ValueError("Platform config mismatch")
        config = objects["config"][0]
        if config["os"] != "linux" or config["architecture"] != "amd64":
            raise ValueError("Unexpected platform")
        self.report["publication"] = "attempting-one-fresh-tag"
        status, _, _ = self.call("PUT", "/v2/" + PACKAGE + "/manifests/" + self.tag,
                                 data=objects["index"][1], content_type=index["mediaType"])
        self.report["publication"] = "accepted" if status == 201 else "unconfirmed"
        self.report["phase"] = "fresh-tag-http-response-no-retry"


def main():
    output = Path(os.environ["DIAGNOSTIC_OUTPUT"])
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise SystemExit("Existing diagnostic receipt; do not replay")
    diagnostic = Diagnostic(os.environ["GH_TOKEN"], os.environ["GITHUB_ACTOR"], os.environ["DIAGNOSTIC_TAG"])
    diagnostic.output = output
    try:
        diagnostic.run()
    except Exception as error:
        diagnostic.report["errorType"] = type(error).__name__
    finally:
        output.write_text(json.dumps(diagnostic.report, indent=2) + "\n")
        print(json.dumps(diagnostic.report, indent=2))


if __name__ == "__main__":
    main()
