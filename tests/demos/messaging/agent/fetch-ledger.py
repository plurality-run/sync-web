"""Install the released amd64 Ledger and its matching kernel, verifying checksums."""
import hashlib
from pathlib import Path
import sys
import urllib.request


def install(version, destination):
    base = f"https://github.com/plurality-run/sync-web/releases/download/ledger-v{version}"
    with urllib.request.urlopen(f"{base}/SHA256SUMS", timeout=60) as response:
        checksums = dict((name.lstrip('*'), digest) for digest, name in
                         (line.split() for line in response.read().decode().splitlines()))
    destination.mkdir(parents=True, exist_ok=True)
    for name, local in [("ledger-linux-x86_64-musl", "ledger"),
                        ("kernel-linux-x86_64-musl.wasmer", "kernel.wasmer")]:
        with urllib.request.urlopen(f"{base}/{name}", timeout=120) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != checksums[name]:
            raise ValueError(f"Release checksum mismatch: {name}")
        (destination / local).write_bytes(data)
    (destination / "ledger").chmod(0o755)
    (destination / "kernel.sha256").write_text(checksums["kernel-linux-x86_64-musl.wasmer"])


if __name__ == "__main__":
    install(sys.argv[1], Path("/opt/ledger"))
