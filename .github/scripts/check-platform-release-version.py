#!/usr/bin/env python3
"""Check existing platform version source binding before any producer starts."""
import json
import os
import sys
import urllib.error
import urllib.request


class InspectionError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        return None


def read_api(path, token):
    request = urllib.request.Request(
        'https://api.github.com' + path,
        headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                 'X-GitHub-Api-Version': '2022-11-28'},
    )
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
            payload = json.load(response)
            if not isinstance(payload, dict):
                raise InspectionError('Published-version inspection returned a non-object payload; absence is unconfirmed.')
            return payload
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise InspectionError(f'Published-version inspection failed (HTTP {error.code}); not a fresh version.') from None


def check_published_version(commit, version, repository, read):
    prefix = '/repos/' + repository
    repo = read(prefix)
    if not repo or repo.get('full_name') != repository:
        raise InspectionError('Repository visibility was not established; version absence is unconfirmed.')
    tag = 'ledger-v' + version
    reference = read(prefix + '/git/ref/tags/' + tag)
    release = read(prefix + '/releases/tags/' + tag)
    if release is not None and release.get('tag_name') != tag:
        raise InspectionError('Release metadata does not match the selected version.')
    if reference is None:
        if release is not None:
            raise InspectionError('Existing release has no readable tag source; publication is blocked.')
        return
    target = reference['object']
    while target['type'] == 'tag':
        annotated = read(prefix + '/git/tags/' + target['sha'])
        if annotated is None:
            raise InspectionError('Annotated release tag source could not be read.')
        target = annotated['object']
    if target['type'] != 'commit' or target['sha'] != commit:
        raise InspectionError('This platform version is already bound to another source; choose a new VERSION.')


if __name__ == '__main__':
    try:
        check_published_version(sys.argv[1], sys.argv[2], os.environ['GITHUB_REPOSITORY'],
                                lambda path: read_api(path, os.environ['GH_TOKEN']))
    except InspectionError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
    except Exception as error:
        print('Published-version inspection unconfirmed: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
