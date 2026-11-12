#!/usr/bin/env python3
import hashlib
import pathlib
import subprocess
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]
LOCK_SHA256 = "d69e38d29ecabd5ae3d62cf2a7c018b292a9e3a40102a0547971bf0d03e34854"
STATIC_GUARD_SHA256 = "90775d6adb7c4db8a04dfd6562def4dbe95b62625741cd92e61a80f752f707b1"
LLVM_WRAPPER_SHA256 = "65774a4a2cbbfd94451610a7904f4d5d6c4f3597e185dbd146dd23b8c2dea644"
manifest = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))

def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)

def target(section: str, dependency_kind: str, name: str):
    try:
        return manifest["target"][section][dependency_kind][name]
    except KeyError:
        fail(f"missing {name} in target {section} {dependency_kind}")

lock_path = ROOT / "Cargo.lock"
if not lock_path.is_file():
    fail("Cargo.lock must be available in every fresh source path")
lock_bytes = lock_path.read_bytes()
lock_digest = hashlib.sha256(lock_bytes).hexdigest()
if lock_digest != LOCK_SHA256:
    fail(f"Cargo.lock digest changed: {lock_digest}")
lock = tomllib.loads(lock_bytes.decode("utf-8"))
clang_sys = [package for package in lock["package"] if package["name"] == "clang-sys"]
if len(clang_sys) != 1 or clang_sys[0]["version"] != "1.9.1":
    fail("Cargo.lock must contain exact clang-sys 1.9.1")
try:
    subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--is-inside-work-tree"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
except (FileNotFoundError, subprocess.CalledProcessError):
    pass
else:
    tracked = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--error-unmatch", "Cargo.lock"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if tracked.returncode != 0:
        fail("Cargo.lock exists locally but is not tracked")

if "bindgen" in manifest.get("build-dependencies", {}):
    fail("bindgen must be target-specific")
if "rocksdb" in manifest.get("dependencies", {}):
    fail("rocksdb must be target-specific")

non_musl = 'cfg(not(target_env = "musl"))'
musl = 'cfg(target_env = "musl")'
if target(non_musl, "build-dependencies", "bindgen") != "0.72.1":
    fail("non-musl bindgen defaults changed")
if target(non_musl, "dependencies", "rocksdb") != "0.24.0":
    fail("non-musl RocksDB defaults changed")

musl_bindgen = target(musl, "build-dependencies", "bindgen")
if musl_bindgen.get("version") != "0.72.1" or musl_bindgen.get("default-features") is not False:
    fail("musl bindgen must pin 0.72.1 with defaults disabled")
if set(musl_bindgen.get("features", [])) != {"logging", "prettyplease", "static"}:
    fail("musl bindgen must preserve default helpers while selecting static linkage")

musl_rocksdb = target(musl, "dependencies", "rocksdb")
if musl_rocksdb.get("version") != "0.24.0" or musl_rocksdb.get("default-features") is not False:
    fail("musl RocksDB must pin 0.24.0 with defaults explicitly reconstructed")
expected_rocksdb = {"snappy", "lz4", "zstd", "zlib", "bzip2", "bindgen-static"}
if set(musl_rocksdb.get("features", [])) != expected_rocksdb:
    fail("musl RocksDB codecs or static bindgen selection changed")

dockerfile = (ROOT / "Dockerfile.musl").read_text(encoding="utf-8")
dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
if "Cargo.lock" in {line.strip() for line in dockerignore}:
    fail("Docker context must include Cargo.lock")
for package in (
    "clang21=21.1.2-r2",
    "clang21-dev=21.1.2-r2",
    "clang21-static=21.1.2-r2",
    "gcc=15.2.0-r2",
    "libffi-dev=3.5.2-r0",
    "libstdc++-dev=15.2.0-r2",
    "libxml2-dev=2.13.9-r1",
    "libxml2-static=2.13.9-r1",
    "llvm21-dev=21.1.2-r1",
    "llvm21-static=21.1.2-r1",
    "musl-dev=1.2.5-r23",
    "ncurses-dev=6.5_p20251123-r0",
    "ncurses-static=6.5_p20251123-r0",
    "xz-static=5.8.4-r0",
    "zlib-dev=1.4-r0",
    "zlib-static=1.4-r0",
    "zstd-dev=1.5.7-r2",
    "zstd-static=1.5.7-r2",
):
    if package not in dockerfile:
        fail(f"Dockerfile does not pin {package}")
if "LLVM_CONFIG_PATH=/src/scripts/llvm-config-musl-static" not in dockerfile:
    fail("musl Dockerfile does not confine the llvm-config wrapper")
static_guard = ROOT / "scripts" / "check-clang-static-toolchain.sh"
if not static_guard.is_file():
    fail("static clang/LLVM prerequisite guard is missing")
if hashlib.sha256(static_guard.read_bytes()).hexdigest() != STATIC_GUARD_SHA256:
    fail("static clang/LLVM prerequisite guard digest changed")
llvm_wrapper = ROOT / "scripts" / "llvm-config-musl-static"
if not llvm_wrapper.is_file():
    fail("musl llvm-config wrapper is missing")
if hashlib.sha256(llvm_wrapper.read_bytes()).hexdigest() != LLVM_WRAPPER_SHA256:
    fail("musl llvm-config wrapper digest changed")
wrapper_copy = "COPY journal/scripts/llvm-config-musl-static /src/scripts/llvm-config-musl-static"
guard_copy = "COPY journal/scripts/check-clang-static-toolchain.sh /src/scripts/check-clang-static-toolchain.sh"
if wrapper_copy not in dockerfile or guard_copy not in dockerfile:
    fail("musl Dockerfile does not copy the static wrapper and prerequisite guard")
if dockerfile.index("RUN /src/scripts/check-clang-static-toolchain.sh") > dockerfile.index("cargo build --release"):
    fail("musl Dockerfile does not enforce wrapper closure before compilation")
for guard in (
    "scripts/check-musl-linkage-config.py",
    "scripts/check-journal-image-config.py",
    "scripts/check-clang-feature-graph.sh musl",
):
    if guard not in dockerfile or dockerfile.index(guard) > dockerfile.index("cargo build --release"):
        fail(f"musl Dockerfile does not enforce {guard} before compilation")

print(
    "musl linkage manifest and provenance inputs are exact; "
    f"Cargo.lock sha256={lock_digest}; static guard sha256={STATIC_GUARD_SHA256}; "
    f"llvm-config wrapper sha256={LLVM_WRAPPER_SHA256}"
)
