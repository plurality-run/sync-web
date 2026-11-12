#!/usr/bin/env python3
"""Qualify one admitted Journal image with the reviewed read-only consumer."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import urllib.request

SCRIPTS = Path(__file__).resolve().parent
REVISION = "3fb619382432e160ba029c493439f3432cad2ea2"
ARCHIVE_SHA256 = "64d8b344e380794829cd8dfee5a24abc270e9032408798df8fc94d0632e79cc6"
INDEX = "sha256:b904392872dfba85e7e734d3e33e16b19623f68876e3e89743d08ec9596b6ce0"
LABELS = {
    "org.opencontainers.image.revision": REVISION,
    "sync-web.source-tree": "9e33d4b02a3fdbcecbb90be4f398828320b4e4d8",
    "sync-web.source-inputs-sha256": "cf9a67dcb2385c74308a7a0aafc6bce270fe2ed95d6be9b1eb2aa6595eafa3bc",
    "sync-web.lock-sha256": "d69e38d29ecabd5ae3d62cf2a7c018b292a9e3a40102a0547971bf0d03e34854",
    "sync-web.aot-sha256": "0c6b7fb7f94e1465e96617c28ebe6e216b4a71687062c8ca283bf4a10ad7416f",
}
REVIEWED = {
    "journal-registry-diagnostic.py": "c7c9a95d592c352cc9076d87b738c21a138efa13949be5e00216902a2afc175b",
    "journal-registry-upload.py": "c3bedae88e69a3ec3882cdac606d871c758b459b89b7670816b5f17d863f0520",
    "journal-registry-readback.py": "8135a019b91f9d36b3e961a88eceafe588ee7cb91e029e42a636fbf736684c6b",
}
for name, expected in REVIEWED.items():
    if hashlib.sha256((SCRIPTS / name).read_bytes()).hexdigest() != expected:
        raise ValueError("Reviewed consumer bytes differ")
spec = importlib.util.spec_from_file_location("readback", SCRIPTS / "journal-registry-readback.py")
readback = importlib.util.module_from_spec(spec)
spec.loader.exec_module(readback)
readback.TAG = "sha-" + REVISION + "-musl"
readback.INDEX = INDEX
readback.upload.EXPECTED_LABELS = LABELS.copy()


class ReadOnlyReadback(readback.Readback):
    def __init__(self, token, actor, transport=None):
        # Keep the original publishing constructor's diagnostic-tag guard intact.
        self.secrets = [token]
        self.job_token, self.actor, self.tag = token, actor, readback.TAG
        self.bearer, self.output = None, None
        self.transport = transport or urllib.request.build_opener(readback.base.NoRedirect()).open
        self.report = {"candidate": REVISION, "package": readback.base.PACKAGE, "tag": self.tag,
                       "operations": [], "objects": {}, "publication": "read-only-no-mutations"}

    def call(self, method, *args, **kwargs):
        if method != "GET":
            raise ValueError("Consumer HTTP must be read-only")
        return super().call(method, *args, **kwargs)


def main():
    output = Path(os.environ["DIAGNOSTIC_OUTPUT"])
    if output.exists():
        raise SystemExit("Existing consumer receipt; do not replay")
    output.parent.mkdir(parents=True, exist_ok=True)
    consumer = ReadOnlyReadback(os.environ["GH_TOKEN"], os.environ["GITHUB_ACTOR"])
    consumer.output = output
    try:
        archive = Path(os.environ["DIAGNOSTIC_ARCHIVE"])
        if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
            raise ValueError("Current retained archive identity mismatch")
        if consumer.run_archive(archive):
            consumer.docker_consumer()
    except Exception as exc:
        consumer.report["errorType"] = type(exc).__name__
    finally:
        output.write_text(json.dumps(consumer.report, indent=2) + "\n")
    print(json.dumps(consumer.report, indent=2))
    return 0 if (consumer.report.get("readback") == "complete-graph-bytes-verified"
                 and consumer.report.get("normalDocker", {}).get("result") ==
                 "authenticated-tag-and-digest-pull-offline-runtime-passed"
                 and "errorType" not in consumer.report) else 1


if __name__ == "__main__":
    sys.exit(main())
