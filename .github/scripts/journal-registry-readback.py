#!/usr/bin/env python3
"""Read back the admitted C2 graph, then separately qualify normal Docker consumption."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import urllib.parse

spec = importlib.util.spec_from_file_location("registry_upload", Path(__file__).with_name("journal-registry-upload.py"))
upload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upload)
base = upload.base
TAG = "diagnostic-c2-43127602226-1"
INDEX = "sha256:fea586b1b0cd22179d0db84028923d2ccecab4d9465f0a68a77892a36121ced1"


class Readback(base.Diagnostic):
    def checked_get(self, path, expected, *, blob=False):
        limit = max(len(expected), 1024 * 1024)
        status, body, headers = self.call("GET", path, body_limit=limit)
        if blob and status in (302, 307):
            location = headers.get("Location", "")
            parsed = urllib.parse.urlsplit(location)
            if parsed.scheme != "https" or parsed.netloc != "pkg-containers.githubusercontent.com":
                raise ValueError("Unexpected blob storage origin")
            status, body, _ = self.call("GET", "verified-blob-storage-redirect", url=location,
                                       resource="verified-blob-storage-redirect", body_limit=limit)
        if status != 200 or body != expected:
            raise ValueError("Readback status or bytes mismatch")
        self.report["objects"][path] = {"bytes": len(body), "sha256": upload.digest(body)}

    def run_archive(self, path):
        index, manifests, required, blobs = upload.read_graph(path)
        if upload.digest(index) != INDEX:
            raise ValueError("Unexpected retained index")
        self.expected_config = json.loads(blobs[manifests[0]["digest"]])["config"]["digest"]
        self.report["publication"] = "read-only-no-mutations"
        self.report["phase"] = "authenticating-read-only"
        if not self.authenticate(pull_only=True):
            return False
        prefix = "/v2/" + base.PACKAGE
        self.checked_get(prefix + "/manifests/" + TAG, index)
        self.checked_get(prefix + "/manifests/" + INDEX, index)
        for descriptor in manifests:
            key = descriptor["digest"]
            self.checked_get(prefix + "/manifests/" + key, blobs[key])
        for key in required:
            self.checked_get(prefix + "/blobs/" + key, blobs[key], blob=True)
        self.report["readback"] = "complete-graph-bytes-verified"
        self.report["phase"] = "readback-complete"
        return True

    def docker_consumer(self):
        image = "ghcr.io/" + base.PACKAGE
        receipt = self.report["normalDocker"] = {"commands": [], "result": "not-qualified"}
        with tempfile.TemporaryDirectory(prefix="registry-readback-auth-") as config:
            env = dict(os.environ, DOCKER_CONFIG=config)
            def run(args, *, stdin=None, record_output=True):
                result = subprocess.run(args, input=stdin, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, env=env, timeout=90)
                receipt["commands"].append({"args": args, "exit": result.returncode,
                                            "stdout": self.clean(result.stdout.decode(errors="replace")) if record_output else "inspected-fields-projected",
                                            "stderr": self.clean(result.stderr.decode(errors="replace"))})
                if result.returncode:
                    raise ValueError("Normal Docker command failed")
                return result.stdout.decode()
            try:
                run(["docker", "login", "ghcr.io", "-u", self.actor, "--password-stdin"],
                    stdin=(self.job_token + "\n").encode())
                run(["docker", "pull", image + ":" + TAG])
                run(["docker", "pull", image + "@" + INDEX])
                info = json.loads(run(["docker", "image", "inspect", image + "@" + INDEX], record_output=False))[0]
                if info["Id"] != self.expected_config or image + "@" + INDEX not in info["RepoDigests"]:
                    raise ValueError("Normal Docker digest mismatch")
                if info["Os"] != "linux" or info["Architecture"] != "amd64":
                    raise ValueError("Normal Docker platform mismatch")
                if not all(info["Config"]["Labels"].get(k) == v for k, v in upload.EXPECTED_LABELS.items()):
                    raise ValueError("Normal Docker labels mismatch")
                receipt["imageId"] = info["Id"]
                receipt["repoDigests"] = info["RepoDigests"]
                common = ["docker", "run", "--rm", "--pull=never", "--network=none", "--read-only",
                          "--cap-drop=all", "--security-opt=no-new-privileges", "--tmpfs",
                          "/tmp:rw,nosuid,nodev,size=64m", image + "@" + INDEX]
                if run(common + ["--version"]).strip() != "journal-sdk 1.4.0":
                    raise ValueError("Normal Docker SDK version mismatch")
                if run(common + ["--evaluate", "(+ 1 2)"]).strip() != "3":
                    raise ValueError("Offline evaluation mismatch")
                expected = "artifact-sha256=" + upload.EXPECTED_LABELS["sync-web.aot-sha256"]
                if expected not in receipt["commands"][-1]["stderr"]:
                    raise ValueError("Runtime AOT attestation mismatch")
                receipt["result"] = "authenticated-tag-and-digest-pull-offline-runtime-passed"
            finally:
                result = subprocess.run(["docker", "logout", "ghcr.io"], env=env,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
                receipt["logoutExit"] = result.returncode


def main():
    diagnostic = Readback(os.environ["GH_TOKEN"], os.environ["GITHUB_ACTOR"], TAG)
    output = Path(os.environ["DIAGNOSTIC_OUTPUT"])
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        if diagnostic.run_archive(os.environ["DIAGNOSTIC_ARCHIVE"]):
            diagnostic.docker_consumer()
    except Exception as exc:
        diagnostic.report["errorType"] = type(exc).__name__
    finally:
        output.write_text(json.dumps(diagnostic.report, indent=2) + "\n")
    print(json.dumps(diagnostic.report, indent=2))


if __name__ == "__main__":
    main()
