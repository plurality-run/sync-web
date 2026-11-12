#!/usr/bin/env python3
"""One stock Docker push of a retained complete image, without a rebuild."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone

PACKAGE = 'ghcr.io/plurality-run/sync-web/journal-sdk'
SOURCE = PACKAGE + ':sha-3fb619382432e160ba029c493439f3432cad2ea2-musl'
ARCHIVE = '64d8b344e380794829cd8dfee5a24abc270e9032408798df8fc94d0632e79cc6'
INDEX = 'b904392872dfba85e7e734d3e33e16b19623f68876e3e89743d08ec9596b6ce0'
PLATFORM = '624d5907c8c282bcb973780b11299c1a41007c2c6464db8a64c5b136f17a467a'
ATTESTATION = 'aa8fdfaa79659777c14e5d99b55c543481ebe9caa6d7aecb764b0d788d9fa1ce'
CONFIG = '81385fa74db6aa56a24223003a47f52c6fd1613b54a57db492e8a73a575ea82c'


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def graph(path):
    with tarfile.open(path) as archive:
        blobs = {}
        for member in archive.getmembers():
            match = re.fullmatch(r'blobs/sha256/([a-f0-9]{64})', member.name)
            if match:
                data = archive.extractfile(member).read()
                digest = match[1]
                assert digest not in blobs and sha(data) == digest
                blobs[digest] = data
        outer = json.loads(archive.extractfile('index.json').read())
    assert any(d['digest'] == 'sha256:' + INDEX for d in outer['manifests'])
    index = json.loads(blobs[INDEX])
    assert {d['digest'] for d in index['manifests']} == {
        'sha256:' + PLATFORM, 'sha256:' + ATTESTATION}
    for digest in [INDEX, PLATFORM, ATTESTATION]:
        node = json.loads(blobs[digest])
        for descriptor in node.get('manifests', []) + node.get('layers', []) + (
                [node['config']] if 'config' in node else []):
            body = blobs[descriptor['digest'].removeprefix('sha256:')]
            assert len(body) == descriptor['size']
    config = json.loads(blobs[CONFIG])
    assert config['os'] == 'linux' and config['architecture'] == 'amd64'
    return blobs


def evidence(process):
    # Raw client output never reaches logs/artifacts: errors can contain sessions.
    raw = (process.stdout or b'') + b'\n' + (process.stderr or b'')
    text = raw.decode('utf-8', 'replace')
    return {
        'exit': process.returncode,
        'stdoutSha256': sha(process.stdout or b''),
        'stderrSha256': sha(process.stderr or b''),
        'denied': bool(re.search(r'\bdenied\b', text, re.I)),
        'unauthorized': bool(re.search(r'\bunauthorized\b', text, re.I)),
        'operations': sorted(set(re.findall(
            r'\b(?:unexpected status from|failed to do request:)\s+(GET|HEAD|POST|PUT|PATCH|DELETE)\b', text))),
        'httpStatuses': sorted(set(re.findall(
            r'\b(?:HTTP/[0-9.]+\s+|status(?: code)?[ :=]+)([1-5][0-9]{2})\b', text, re.I))),
        'requestIds': sorted(set(re.findall(
            r'^\s*(?:X-GitHub-Request-Id|X-Request-Id):\s*([A-F0-9:]{8,128})\s*$', text, re.I | re.M))),
        'pushedLines': len(re.findall(r'(?m)^[a-f0-9]{12}: Pushed\s*$', text)),
        'existingLines': len(re.findall(r'(?m)^[a-f0-9]{12}: Layer already exists\s*$', text)),
    }


def main():
    out = Path('stock-docker-evidence')
    out.mkdir(exist_ok=False)
    receipt = out / 'result.json'
    result = {'startedAt': utc(), 'archiveSha256': ARCHIVE,
              'index': 'sha256:' + INDEX, 'platform': 'sha256:' + PLATFORM,
              'attestation': 'sha256:' + ATTESTATION, 'config': 'sha256:' + CONFIG,
              'source': '3fb619382432e160ba029c493439f3432cad2ea2',
              'pushAttempts': 0, 'engineRetryPolicy': 'unchanged-stock-default',
              'phase': 'preflight', 'rawOutputPersisted': False}
    temp = tempfile.TemporaryDirectory(prefix='stock-docker-auth-')
    env = dict(os.environ, DOCKER_CONFIG=temp.name)
    token = env.pop('GITHUB_TOKEN')
    tag = 'diagnostic-stock-docker-' + os.environ['GITHUB_RUN_ID'] + '-1'
    target = PACKAGE + ':' + tag
    result['tag'] = target

    def save():
        receipt.write_text(json.dumps(result, indent=2) + '\n')

    def run(args, *, data=None, timeout=180):
        return subprocess.run(['docker', *args], input=data, env=env,
                              capture_output=True, timeout=timeout)

    try:
        save()
        assert os.environ['GITHUB_RUN_ATTEMPT'] == '1'
        version = run(['version', '--format', '{{json .}}'])
        assert version.returncode == 0
        versions = json.loads(version.stdout)
        result['versions'] = {side: {key: versions[side].get(key) for key in
                              ['Version', 'ApiVersion', 'MinAPIVersion', 'GitCommit',
                               'GoVersion', 'Os', 'Arch', 'KernelVersion', 'BuildTime',
                               'Components']} for side in ['Client', 'Server']}
        info = run(['info', '--format', '{{json .DriverStatus}}'])
        assert info.returncode == 0
        result['driverStatus'] = json.loads(info.stdout)
        archive = Path('retained/image.tar')
        assert sha(archive.read_bytes()) == ARCHIVE
        original = graph(archive)
        assert len(original) == 24
        result['archiveGraphVerified'] = True
        loaded = run(['load', '--input', str(archive)])
        result['load'] = evidence(loaded)
        assert loaded.returncode == 0
        tagged = run(['tag', SOURCE, target])
        assert tagged.returncode == 0
        saved = Path(temp.name) / 'loaded.tar'
        exported = run(['image', 'save', '--output', str(saved), target])
        assert exported.returncode == 0
        assert graph(saved) == original
        result['dockerLoadSaveExactFullGraph'] = True
        saved.unlink()
        save()
        login = run(['login', 'ghcr.io', '--username', os.environ['GITHUB_ACTOR'],
                     '--password-stdin'], data=token.encode() + b'\n')
        result['login'] = evidence(login)
        assert login.returncode == 0
        result['phase'] = 'one-stock-docker-push-starting'
        result['pushStartedAt'] = utc()
        result['pushAttempts'] = 1
        save()
        print('ONE_STOCK_DOCKER_PUSH_START ' + result['pushStartedAt'], flush=True)
        try:
            pushed = run(['push', target], timeout=300)
        except subprocess.TimeoutExpired as error:
            result['phase'] = 'push-interrupted-unconfirmed-no-retry'
            result['partialStdoutSha256'] = sha(error.stdout or b'')
            result['partialStderrSha256'] = sha(error.stderr or b'')
            raise
        result['pushFinishedAt'] = utc()
        result['push'] = evidence(pushed)
        match = re.search(re.escape(tag).encode() +
                          rb': digest: sha256:([a-f0-9]{64})\s+size:\s+([0-9]+)',
                          pushed.stdout + b'\n' + pushed.stderr)
        result['reportedRootDigest'] = match[1].decode() if match else None
        result['phase'] = 'client-success' if pushed.returncode == 0 else 'client-failure-may-have-accepted-pieces'
        save()
        assert pushed.returncode == 0
        assert match and match[1].decode() == INDEX
        result['reportedRootMatchesRetainedIndex'] = True
    except Exception as error:
        result['errorType'] = type(error).__name__
        if result['pushAttempts'] == 0:
            result['phase'] = 'pre-push-prerequisite-failure-no-push'
        raise SystemExit(1) from None
    finally:
        try:
            logout = run(['logout', 'ghcr.io'], timeout=30)
            result['logoutExit'] = logout.returncode
        except Exception as error:
            result['logoutErrorType'] = type(error).__name__
        temp.cleanup()
        result['temporaryAuthDirectoryRemoved'] = not Path(temp.name).exists()
        result['finishedAt'] = utc()
        save()
        print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
