#!/usr/bin/env python3
"""Offline release-event/source guards; no registry, dispatch or release writes."""
import importlib.util
import io
import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
import unittest
from unittest.mock import Mock, patch
import urllib.error

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / '.github/workflows'
SPEC = importlib.util.spec_from_file_location('release_version', ROOT / '.github/scripts/check-platform-release-version.py')
RELEASE_VERSION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RELEASE_VERSION)


def expression(text, values):
    """Evaluate the small boolean subset used by these workflow guards."""
    text = text.strip().removeprefix('${{').removesuffix('}}').strip()
    pattern = r"'[^']*'|[A-Za-z_][A-Za-z0-9_.-]*|&&|\|\||==|!=|[!()]"
    tokens = re.findall(pattern, text)
    if ''.join(tokens) != re.sub(r'\s+', '', text):
        raise ValueError(text)
    operators = {'&&': 'and', '||': 'or', '!': 'not', 'true': 'True', 'false': 'False'}
    result = []
    for token in tokens:
        if token in operators:
            result.append(operators[token])
        elif token.startswith("'") or token in ('(', ')', '==', '!='):
            result.append(token)
        else:
            result.append(repr(values.get(token, '')))
    return bool(eval(' '.join(result), {'__builtins__': {}}, {}))


def named_step(source, name):
    marker = '      - name: ' + name + '\n'
    return source.split(marker, 1)[1].split('\n      - ', 1)[0]


def condition(block):
    return next(line.strip()[4:] for line in block.splitlines() if line.strip().startswith('if: '))


class EventGuards(unittest.TestCase):
    def values(self, event='push', ref='refs/heads/main', release=False, version=True, service=True):
        return {'github.event_name': event, 'github.ref': ref, 'inputs.release': release,
                'steps.filter.outputs.version': str(version).lower(),
                'steps.filter.outputs.service': str(service).lower(),
                'needs.build-journal-sdk.result': 'success', 'needs.compose-smoke.result': 'success'}

    def test_release_intent_defaults_false_and_ci_isolated(self):
        for name in ['journal.yml', 'ledger.yml', 'tests-social-agent.yml'] + [p.name for p in WORKFLOWS.glob('services-*.yml')]:
            source = (WORKFLOWS / name).read_text()
            self.assertIn('type: boolean\n        default: false', source, name)
            self.assertIn("inputs.release && 'release' || 'ci'", source, name)
            self.assertIn('cancel-in-progress: ${{ !inputs.release }}', source, name)

    def test_numbered_release_jobs_require_owner_intent(self):
        for file, job in [('journal.yml', 'tag-version'), ('ledger.yml', 'publish-release')]:
            block = (WORKFLOWS / file).read_text().split('  ' + job + ':\n')[1]
            guard = condition(block)
            for event in ['push', 'pull_request', 'workflow_dispatch']:
                for ref in ['refs/heads/main', 'refs/heads/feature']:
                    for release in [False, True]:
                        self.assertEqual(expression(guard, self.values(event, ref, release)),
                                         event == 'workflow_dispatch' and ref == 'refs/heads/main' and release,
                                         (file, event, ref, release))

    def test_ledger_publication_preserves_successful_build_dependency(self):
        block = (WORKFLOWS / 'ledger.yml').read_text().split('  publish-release:\n')[1]
        self.assertIn('needs: [metadata, build]', block)
        self.assertNotIn('always()', block)
        self.assertIn('check-platform-release.sh', block)
        self.assertIn('target_commitish: ${{ github.sha }}', block)

    def test_journal_cannot_promote_failed_or_skipped_build_or_smoke(self):
        source = (WORKFLOWS / 'journal.yml').read_text()
        native = source.split('  test-journal:\n')[1].split('\n  build-journal-sdk:')[0]
        self.assertNotIn('    if:', native)
        guard = condition(source.split('  tag-version:\n')[1])
        for dependency in ['needs.build-journal-sdk.result', 'needs.compose-smoke.result']:
            for state in ['failure', 'skipped', 'cancelled']:
                values = self.values('workflow_dispatch', release=True)
                values[dependency] = state
                self.assertFalse(expression(guard, values), (dependency, state))
        smoke = source.split('  compose-smoke:\n')[1].split('\n  tag-version:')[0]
        self.assertNotIn("github.ref != 'refs/heads/main'", smoke)
        self.assertIn('cargo test --locked', source)
        self.assertIn('check-wasmer-kernel-provenance.py', source)

    def test_six_services_release_and_main_version_ci(self):
        for file in WORKFLOWS.glob('services-*.yml'):
            source = file.read_text()
            promotion = condition(named_step(source, 'Promote validated image'))
            self.assertFalse(expression(promotion, self.values()))
            self.assertFalse(expression(promotion, self.values('workflow_dispatch')))
            self.assertTrue(expression(promotion, self.values('workflow_dispatch', release=True)))
            self.assertFalse(expression(promotion, self.values('workflow_dispatch', 'refs/heads/feature', True)))
            validation = condition(named_step(source, 'Build merge or pull request validation image'))
            self.assertTrue(expression(validation, self.values(service=False)))
            self.assertTrue(expression(validation, self.values('pull_request', 'refs/pull/1/merge', service=False)))
            self.assertFalse(expression(validation, self.values('workflow_dispatch', release=True)))
            sha = condition(named_step(source, 'Build and push SHA-tagged validation image'))
            self.assertTrue(expression(sha, self.values('workflow_dispatch', release=True, version=False, service=False)))
            self.assertTrue(expression(sha, self.values(ref='refs/heads/feature')))
            self.assertFalse(expression(sha, self.values('pull_request', 'refs/pull/1/merge')))
            latest = condition(named_step(source, 'Build and push latest image for direct main service changes'))
            self.assertTrue(expression(latest, self.values(version=False)))
            self.assertFalse(expression(latest, self.values()))
            self.assertFalse(expression(latest, self.values('workflow_dispatch', release=True, version=False)))

    def test_workflow_only_edits_validate_without_broadening_service_publication(self):
        for file in WORKFLOWS.glob('services-*.yml'):
            source = file.read_text()
            for ref in ['refs/heads/main', 'refs/heads/feature']:
                values = self.values(ref=ref, version=False, service=False)
                values['steps.filter.outputs.workflow'] = 'true'
                self.assertTrue(expression(condition(named_step(source, 'Build merge or pull request validation image')), values))
                self.assertFalse(expression(condition(named_step(source, 'Build and push SHA-tagged validation image')), values))
                self.assertFalse(expression(condition(named_step(source, 'Build and push latest image for direct main service changes')), values))

    def test_one_entry_point_requires_source_approval_before_all_producers(self):
        source = (WORKFLOWS / 'platform-release.yml').read_text()
        self.assertIn('  workflow_dispatch:', source)
        self.assertNotIn('\n  push:', source)
        self.assertNotIn('\n  pull_request:', source)
        self.assertEqual(source.count('    needs: approve-source'), 9)
        self.assertEqual(source.count('      release: true'), 9)
        self.assertIn('"$SELECTED_COMMIT" "$SELECTED_VERSION"', source)
        self.assertIn('cancel-in-progress: false', source)
        self.assertNotIn('secrets: inherit', source)
        self.assertNotIn('lookup_head_sha', (ROOT / '.github/scripts/promote-image.sh').read_text())
        approval = source.split('  approve-source:\n')[1].split('\n  journal:')[0]
        self.assertIn('python3 .github/scripts/check-platform-release-version.py "$SELECTED_COMMIT" "$SELECTED_VERSION"', approval)
        self.assertNotIn('continue-on-error', approval)
        self.assertNotIn('always()', source)

    def test_social_numbered_tags_are_conditional_but_development_latest_remains(self):
        source = (WORKFLOWS / 'tests-social-agent.yml').read_text()
        block = named_step(source, 'Resolve version')
        self.assertIn('if [ "${{ inputs.release }}" = true ]; then', block)
        self.assertIn('social-agent:latest', block)
        self.assertIn('social-agent:$(cat VERSION)', block)
        self.assertIn('tags: ${{ steps.version.outputs.tags }}', source)


class SourceGuards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        subprocess.run(['git', 'init', '-q'], cwd=self.directory, check=True)
        (self.directory / 'VERSION').write_text('0.1.0\n')
        subprocess.run(['git', 'add', 'VERSION'], cwd=self.directory, check=True)
        subprocess.run(['git', '-c', 'user.name=Release fixture', '-c', 'user.email=fixture@example.org',
                        'commit', '-qm', 'fixture'], cwd=self.directory, check=True)
        self.sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=self.directory, text=True).strip()
        self.environment = dict(os.environ, GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_REF='refs/heads/main',
                                PLATFORM_RELEASE='true', GITHUB_SHA=self.sha, GITHUB_REPOSITORY='example/project')
        self.helper = ROOT / '.github/scripts/check-platform-release.sh'

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, sha=None, version='0.1.0', **environment):
        return subprocess.run([str(self.helper), sha or self.sha, version], cwd=self.directory,
                              env=dict(self.environment, **environment), capture_output=True, text=True)

    def test_exact_manual_main_source_version_accepted(self):
        self.assertEqual(self.invoke().returncode, 0)

    def test_wrong_event_ref_intent_and_checkout_rejected(self):
        for changes in [{'GITHUB_EVENT_NAME': 'push'}, {'GITHUB_EVENT_NAME': 'pull_request'},
                        {'GITHUB_REF': 'refs/heads/feature'}, {'PLATFORM_RELEASE': 'false'},
                        {'PLATFORM_RELEASE': ''}, {'GITHUB_SHA': 'f' * 40}]:
            self.assertNotEqual(self.invoke(**changes).returncode, 0, changes)

    def test_wrong_selected_source_version_and_uncommitted_version_rejected(self):
        for sha in ['f' * 40, 'main', self.sha[:7]]:
            self.assertNotEqual(self.invoke(sha=sha).returncode, 0)
        for version in ['0.2.0', '', '$(touch unexpected)', '0.1.0\nother']:
            self.assertNotEqual(self.invoke(version=version).returncode, 0)
        (self.directory / 'VERSION').write_text('0.2.0\n')
        self.assertNotEqual(self.invoke(version='0.2.0').returncode, 0)
        self.assertFalse((self.directory / 'unexpected').exists())

    def test_already_released_A_blocks_later_B_with_unchanged_version_before_producers(self):
        released = self.sha
        subprocess.run(['git', 'tag', 'ledger-v0.1.0'], cwd=self.directory, check=True)
        (self.directory / 'other').write_text('later development\n')
        subprocess.run(['git', 'add', 'other'], cwd=self.directory, check=True)
        subprocess.run(['git', '-c', 'user.name=Release fixture', '-c', 'user.email=fixture@example.org',
                        'commit', '-qm', 'later development'], cwd=self.directory, check=True)
        self.sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=self.directory, text=True).strip()
        self.environment['GITHUB_SHA'] = self.sha
        self.assertEqual(self.invoke().returncode, 0)
        self.assertEqual((self.directory / 'VERSION').read_text(), '0.1.0\n')
        responses = {'/repos/example/project': {'full_name': 'example/project'},
                     '/repos/example/project/git/ref/tags/ledger-v0.1.0': {'object': {'type': 'commit', 'sha': released}},
                     '/repos/example/project/releases/tags/ledger-v0.1.0': {'tag_name': 'ledger-v0.1.0'}}
        producer, promotion = Mock(), Mock()
        with self.assertRaisesRegex(RELEASE_VERSION.InspectionError, 'already bound'):
            RELEASE_VERSION.check_published_version(self.sha, '0.1.0', 'example/project', responses.__getitem__)
            producer()
            promotion()
        producer.assert_not_called()
        promotion.assert_not_called()

    def test_social_actual_tag_output_is_latest_only_without_release_intent(self):
        block = named_step((WORKFLOWS / 'tests-social-agent.yml').read_text(), 'Resolve version')
        shell = textwrap.dedent(block.split('        run: |\n', 1)[1])
        output = self.directory / 'output'
        for intent, count in [('', 1), ('false', 1), ('true', 2)]:
            output.write_text('')
            subprocess.run(['bash', '-euc', shell.replace('${{ inputs.release }}', intent)],
                           cwd=self.directory, env=dict(self.environment, GITHUB_OUTPUT=str(output)), check=True)
            tags = output.read_text().split('tags<<EOF\n')[1].split('\nEOF')[0].splitlines()
            self.assertEqual(len(tags), count)
            self.assertIn('ghcr.io/example/project/social-agent:latest', tags)
            self.assertEqual('ghcr.io/example/project/social-agent:0.1.0' in tags, intent == 'true')

    def test_promotion_uses_selected_main_sha_and_no_registry_calls_on_denial(self):
        binary = self.directory / 'bin'
        binary.mkdir()
        log = self.directory / 'docker.log'
        docker = binary / 'docker'
        docker.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$DOCKER_LOG"\n')
        docker.chmod(0o755)
        environment = dict(self.environment, PATH=str(binary) + os.pathsep + os.environ['PATH'], DOCKER_LOG=str(log))
        command = [str(ROOT / '.github/scripts/promote-image.sh'), 'journal-sdk', 'VERSION', 'musl', 'preferred']
        valid = subprocess.run(command, cwd=self.directory, env=environment, capture_output=True)
        self.assertEqual(valid.returncode, 0)
        calls = log.read_text()
        self.assertIn('sha-' + self.sha + '-musl', calls)
        self.assertIn(':0.1.0-musl', calls)
        self.assertIn(':0.1.0 ', calls)
        log.unlink()
        environment['PLATFORM_RELEASE'] = 'false'
        self.assertNotEqual(subprocess.run(command, cwd=self.directory, env=environment, capture_output=True).returncode, 0)
        self.assertFalse(log.exists())


class PublishedVersionGuards(unittest.TestCase):
    def responses(self, tag=None, release=None):
        return {'/repos/example/project': {'full_name': 'example/project'},
                '/repos/example/project/git/ref/tags/ledger-v0.1.0': tag,
                '/repos/example/project/releases/tags/ledger-v0.1.0': release}

    def test_first_release_and_same_source_recovery(self):
        commit = 'a' * 40
        for tag, release in [(None, None),
                             ({'object': {'type': 'commit', 'sha': commit}}, None),
                             ({'object': {'type': 'commit', 'sha': commit}}, {'tag_name': 'ledger-v0.1.0'})]:
            RELEASE_VERSION.check_published_version(commit, '0.1.0', 'example/project', self.responses(tag, release).__getitem__)

    def test_tag_alone_from_other_source_also_blocks(self):
        responses = self.responses({'object': {'type': 'commit', 'sha': 'a' * 40}})
        with self.assertRaises(RELEASE_VERSION.InspectionError):
            RELEASE_VERSION.check_published_version('b' * 40, '0.1.0', 'example/project', responses.__getitem__)

    def test_annotated_tags_resolve_to_source_commit(self):
        responses = self.responses({'object': {'type': 'tag', 'sha': 'c' * 40}}, {'tag_name': 'ledger-v0.1.0'})
        responses['/repos/example/project/git/tags/' + 'c' * 40] = {'object': {'type': 'commit', 'sha': 'a' * 40}}
        RELEASE_VERSION.check_published_version('a' * 40, '0.1.0', 'example/project', responses.__getitem__)
        with self.assertRaises(RELEASE_VERSION.InspectionError):
            RELEASE_VERSION.check_published_version('b' * 40, '0.1.0', 'example/project', responses.__getitem__)

    def test_unreadable_repository_and_release_without_tag_are_not_fresh(self):
        for responses in [self.responses(None, {'tag_name': 'ledger-v0.1.0'}),
                          dict(self.responses(), **{'/repos/example/project': None})]:
            with self.assertRaises(RELEASE_VERSION.InspectionError):
                RELEASE_VERSION.check_published_version('a' * 40, '0.1.0', 'example/project', responses.__getitem__)

    def test_only_actual_404_is_absence_not_forbidden_or_server_failure(self):
        for status in [401, 403, 404, 500, 503]:
            error = urllib.error.HTTPError('https://api.github.com/fixture', status, 'fixture', {}, None)
            with patch.object(RELEASE_VERSION.urllib.request, 'build_opener') as opener:
                opener.return_value.open.side_effect = error
                if status == 404:
                    self.assertIsNone(RELEASE_VERSION.read_api('/fixture', 'fixture-token'))
                else:
                    with self.assertRaises(RELEASE_VERSION.InspectionError):
                        RELEASE_VERSION.read_api('/fixture', 'fixture-token')

    def test_successful_nonobject_payload_is_not_absence(self):
        for body in [b'null', b'[]', b'"fixture"', b'0', b'false']:
            with self.subTest(body=body), patch.object(RELEASE_VERSION.urllib.request, 'build_opener') as opener:
                opener.return_value.open.return_value = io.BytesIO(body)
                with self.assertRaises(RELEASE_VERSION.InspectionError):
                    RELEASE_VERSION.read_api('/fixture', 'fixture-token')
        with patch.object(RELEASE_VERSION.urllib.request, 'build_opener') as opener:
            opener.return_value.open.return_value = io.BytesIO(b'{}')
            self.assertEqual(RELEASE_VERSION.read_api('/fixture', 'fixture-token'), {})

    def test_transport_read_failure_never_reaches_producers(self):
        responses = self.responses()
        for failing_path in list(responses):
            producer = Mock()
            def read(path):
                if path == failing_path:
                    raise urllib.error.URLError('fixture unavailable')
                return responses[path]
            with self.assertRaises(urllib.error.URLError):
                RELEASE_VERSION.check_published_version('a' * 40, '0.1.0', 'example/project', read)
                producer()
            producer.assert_not_called()


if __name__ == '__main__':
    unittest.main()
