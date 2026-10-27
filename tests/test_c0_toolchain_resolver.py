# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Toolchain release selection, failure boundaries, and offline build arguments."""
import contextlib
import copy
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / 'bin/c0-toolchain'
loader = importlib.machinery.SourceFileLoader('c0_toolchain', str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
resolver = importlib.util.module_from_spec(spec)
loader.exec_module(resolver)


PBS_RELEASE = 'https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest'
UV_PYTHON_CATALOG = 'https://raw.githubusercontent.com/astral-sh/uv/0.13.5/crates/uv-python-managed/download-metadata.json'
DOWNLOAD_ROOT = 'https://github.com/astral-sh/python-build-standalone/releases/download/'
PYTHON_SHA256 = 'a' * 64


def python_asset(patch=2, build='20261026'):
    """Official GitHub release asset shape; expectations do not use IUT helpers."""
    name = f'cpython-3.15.{patch}+{build}-aarch64-unknown-linux-gnu-install_only_stripped.tar.gz'
    return {'name': name, 'browser_download_url': DOWNLOAD_ROOT + build + '/' + name.replace('+', '%2B'),
            'digest': 'sha256:' + PYTHON_SHA256}


def python_source(patch=2, build='20261026'):
    return python_asset(patch, build)['browser_download_url'] + '#sha256=' + PYTHON_SHA256


def published_python(patch, **changes):
    return dict({'name': f'Python 3.15.{patch}', 'is_published': True, 'pre_release': False}, **changes)


def supported_manifest():
    # Contract fixture, including all nine existing keys, independent of resolve.
    return {
        'schema': 1,
        'versions': dict(bun='1.4.4', uv='0.13.5', fnm='1.39.0', node='22.23.4',
                         python='3.15.2', pip='26.2.2', npm='12.2.1', pnpm='12.15.0', semgrep='1.182.1'),
        'sources': {
            'bun': 'https://github.com/oven-sh/bun/releases/tag/bun-v1.4.4',
            'uv': 'https://github.com/astral-sh/uv/releases/tag/0.13.5',
            'fnm': 'https://github.com/Schniz/fnm/releases/tag/v1.39.0',
            'node': 'https://nodejs.org/en/blog/release/v22.23.4',
            'python': python_source(),
            'pip': 'https://pypi.org/project/pip/26.2.2/',
            'npm': 'https://registry.npmjs.org/npm/12.2.1',
            'pnpm': 'https://registry.npmjs.org/pnpm/12.15.0',
            'semgrep': 'https://pypi.org/project/semgrep/1.182.1/',
        },
    }


def metadata():
    return {
        resolver.SOURCES['bun']: {'tag_name': 'bun-v1.4.4', 'draft': False, 'prerelease': False},
        resolver.SOURCES['uv']: {'tag_name': '0.13.5', 'draft': False, 'prerelease': False},
        resolver.SOURCES['fnm']: {'tag_name': 'v1.39.0', 'draft': False, 'prerelease': False},
        resolver.SOURCES['node']: [{'version': 'v22.23.4', 'files': ['linux-arm64']}],
        resolver.SOURCES['python']: [published_python(1), published_python(2)],
        resolver.SOURCES['pip']: {'info': {'version': '26.2.2', 'requires_python': '>=3.9'}},
        resolver.SOURCES['npm']: {'version': '12.2.1', 'engines': {'node': '^22.22.2 || ^24.15.0 || >=26.0.0'}},
        resolver.SOURCES['pnpm']: {'version': '12.15.0', 'engines': {'node': '>=22.0.0'}},
        resolver.SOURCES['semgrep']: {'info': {'version': '1.182.1', 'requires_python': '>=3.10'}},
        PBS_RELEASE: {'tag_name': '20261026', 'draft': False, 'prerelease': False,
                      'assets': [python_asset(1), python_asset(2)]},
    }


class ToolchainResolver(unittest.TestCase):
    def resolve(self, fixtures=None):
        data = fixtures or metadata()
        return resolver.resolve(lambda url: copy.deepcopy(data[url]))

    def test_published_security_patch_uses_standalone_asset_despite_frozen_uv_catalog(self):
        data = metadata()
        # uv 0.13.5 shipped before this security fix. Its frozen index is not
        # an authority for whether a newer official standalone build exists.
        requested = []
        def fetch(url):
            requested.append(url)
            if url == UV_PYTHON_CATALOG:
                self.fail('resolution must not consult the frozen uv Python catalog')
            return copy.deepcopy(data[url])
        result = resolver.resolve(fetch)
        self.assertEqual(result['versions']['python'], '3.15.2')
        self.assertEqual(result['sources']['python'], python_source())
        self.assertIn(PBS_RELEASE, requested)
        self.assertEqual(set(result), {'schema', 'versions', 'sources'})
        self.assertEqual(result['schema'], 1)
        expected_tools = {'bun', 'uv', 'fnm', 'node', 'python', 'pip', 'npm', 'pnpm', 'semgrep'}
        self.assertEqual(set(result['versions']), expected_tools)
        self.assertEqual(set(result['sources']), expected_tools)

    def test_selects_latest_numeric_patch_on_fixed_language_branches(self):
        data = metadata()
        data[resolver.SOURCES['node']] += [
            {'version': 'v26.99.0', 'files': ['linux-arm64']},
            {'version': 'v22.24.1', 'files': ['linux-arm64']},
            {'version': 'v22.99.0-rc.1', 'files': ['linux-arm64']},
            {'version': 'v22.9.9', 'files': ['linux-arm64']},
        ]
        data[resolver.SOURCES['python']] += [
            {'name': 'Python 3.16.0', 'is_published': True, 'pre_release': False},
            published_python(10), published_python(99, is_published=False),
            published_python(11, pre_release=True),
        ]
        data[PBS_RELEASE]['assets'] += [python_asset(10), python_asset(99), python_asset(11)]
        result = self.resolve(data)
        self.assertEqual(result['versions']['node'], '22.24.1')
        self.assertEqual(result['versions']['python'], '3.15.10')
        self.assertEqual(result['sources']['python'], python_source(10))
        self.assertIn('/v22.24.1', result['sources']['node'])

    def test_new_metadata_without_new_versions_does_not_change_identity(self):
        data = metadata()
        first = resolver.canonical_json(self.resolve(data))
        data[resolver.SOURCES['bun']].update(download_count=999, body='edited release notes')
        data[PBS_RELEASE].update(download_count=999, body='edited standalone release notes')
        second = resolver.canonical_json(self.resolve(data))
        self.assertEqual(first, second)
        self.assertEqual(first, json.dumps(json.loads(first), sort_keys=True, separators=(',', ':')) + '\n')

    def test_new_tool_release_changes_manifest(self):
        before = resolver.canonical_json(self.resolve())
        data = metadata()
        data[resolver.SOURCES['uv']]['tag_name'] = '0.13.6'
        after = self.resolve(data)
        self.assertEqual(after['versions']['python'], '3.15.2')
        self.assertNotEqual(before, resolver.canonical_json(after))

    def test_distribution_build_or_checksum_change_changes_manifest_identity(self):
        before = resolver.canonical_json(self.resolve())
        for change in ('build', 'checksum'):
            with self.subTest(change=change):
                data = metadata()
                if change == 'build':
                    data[PBS_RELEASE].update(tag_name='20261027', assets=[python_asset(2, '20261027')])
                else:
                    data[PBS_RELEASE]['assets'][1]['digest'] = 'sha256:' + 'b' * 64
                after = self.resolve(data)
                self.assertEqual(after['versions']['python'], '3.15.2')
                self.assertNotEqual(before, resolver.canonical_json(after))

    def test_standalone_catalog_cannot_promote_unpublished_prerelease_or_unlisted_python(self):
        data = metadata()
        data[resolver.SOURCES['python']] += [published_python(3, is_published=False),
                                            published_python(4, pre_release=True)]
        data[PBS_RELEASE]['assets'] += [python_asset(3), python_asset(4), python_asset(5)]
        self.assertEqual(self.resolve(data)['versions']['python'], '3.15.2')

    def test_official_python_release_flags_require_json_boolean_values(self):
        for changes in ({'is_published': 1}, {'pre_release': 0}):
            with self.subTest(changes=changes):
                data = metadata()
                data[resolver.SOURCES['python']] = [published_python(2, **changes)]
                with self.assertRaisesRegex(resolver.ResolutionError, 'published final'):
                    self.resolve(data)
                data[resolver.SOURCES['python']] = [published_python(2)]
                self.assertEqual(self.resolve(data)['versions']['python'], '3.15.2')

    def test_published_new_patch_without_standalone_asset_keeps_available_fixed_patch(self):
        data = metadata()
        data[resolver.SOURCES['python']].append(published_python(3))
        self.assertEqual(self.resolve(data)['versions']['python'], '3.15.2')

    def test_wrong_arch_libc_or_variant_cannot_satisfy_security_floor(self):
        for suffix in ('x86_64-unknown-linux-gnu', 'aarch64-unknown-linux-musl',
                       'aarch64-apple-darwin', 'aarch64-unknown-linux-gnu-freethreaded',
                       'aarch64-unknown-linux-gnu-debug'):
            with self.subTest(suffix=suffix):
                data = metadata()
                asset = python_asset()
                for key in ('name', 'browser_download_url'):
                    asset[key] = asset[key].replace('aarch64-unknown-linux-gnu', suffix)
                data[PBS_RELEASE]['assets'] = [python_asset(1), asset]
                with self.assertRaisesRegex(resolver.ResolutionError, '[Pp]ython'):
                    self.resolve(data)
                data[PBS_RELEASE]['assets'].append(python_asset())
                self.assertEqual(self.resolve(data)['versions']['python'], '3.15.2')

    def test_malformed_selected_download_refuses_instead_of_falling_back(self):
        asset = python_asset(3)
        url = asset['browser_download_url']
        corruptions = [
            {'browser_download_url': url.replace('https:', 'http:')},
            {'browser_download_url': url.replace('github.com', 'github.com.untrusted.example')},
            {'browser_download_url': url.replace('github.com', 'user@github.com')},
            {'browser_download_url': url.replace('github.com', 'github.com:443')},
            {'browser_download_url': url.replace('astral-sh/', 'other-owner/')},
            {'browser_download_url': url.replace('3.15.3', '3.15.2')},
            {'browser_download_url': url.replace('/20261026/', '/20261025/')},
            {'browser_download_url': url.replace('%2B20261026', '%2B20261025')},
            {'browser_download_url': url.replace('%2B', '+')},
            {'browser_download_url': url + '?download=1'},
            {'browser_download_url': url + '#sha256=' + PYTHON_SHA256},
            {'digest': None}, {'digest': 'sha256:' + 'A' * 64},
            {'digest': 'sha256:' + 'a' * 63}, {'digest': 'sha512:' + 'a' * 64},
        ]
        for changes in corruptions:
            with self.subTest(changes=changes):
                data = metadata()
                data[resolver.SOURCES['python']].append(published_python(3))
                selected = dict(asset, **changes)
                data[PBS_RELEASE]['assets'].append(selected)
                with self.assertRaises(resolver.ResolutionError):
                    self.resolve(data)
                data[PBS_RELEASE]['assets'][-1] = asset
                self.assertEqual(self.resolve(data)['versions']['python'], '3.15.3')

    def test_standalone_release_must_be_final_and_unambiguous(self):
        for changes in ({'draft': True}, {'draft': 0}, {'prerelease': True}, {'prerelease': 0},
                        {'tag_name': '20261026rc1'},
                        {'tag_name': True}, {'assets': None},
                        {'assets': [python_asset(), python_asset()]}):
            with self.subTest(changes=changes):
                data = metadata()
                data[PBS_RELEASE].update(changes)
                with self.assertRaises(resolver.ResolutionError):
                    self.resolve(data)
        self.assertEqual(self.resolve()['versions']['python'], '3.15.2')

    def test_python_security_floor_refuses_old_or_missing_download(self):
        for assets in ([], [python_asset(1)], [python_asset(0)]):
            with self.subTest(assets=assets):
                data = metadata()
                data[PBS_RELEASE]['assets'] = assets
                with self.assertRaisesRegex(resolver.ResolutionError, 'security floor'):
                    self.resolve(data)
        data = metadata()
        data[resolver.SOURCES['python']] = [published_python(1)]
        with self.assertRaisesRegex(resolver.ResolutionError, 'security floor'):
            self.resolve(data)

    def test_python_standalone_fetch_failure_refuses_resolution(self):
        data = metadata()
        def fetch(url):
            if url == PBS_RELEASE:
                raise resolver.ResolutionError('standalone catalog unavailable')
            return copy.deepcopy(data[url])
        with self.assertRaisesRegex(resolver.ResolutionError, 'standalone catalog unavailable'):
            resolver.resolve(fetch)

    def test_node_arm64_build_must_exist_for_latest_patch(self):
        data = metadata()
        data[resolver.SOURCES['node']].append({'version': 'v22.24.0', 'files': ['linux-x64']})
        with self.assertRaisesRegex(resolver.ResolutionError, 'arm64'):
            self.resolve(data)

    def test_no_published_python_branch_fails_instead_of_advancing_minor(self):
        data = metadata()
        data[resolver.SOURCES['python']] = [{'name': 'Python 3.16.0', 'is_published': True, 'pre_release': False}]
        with self.assertRaisesRegex(resolver.ResolutionError, 'Python 3.15'):
            self.resolve(data)

    def test_github_draft_prerelease_and_bad_versions_fail(self):
        for patch in ({'draft': True}, {'prerelease': True}, {'tag_name': 'bun-v1.5.0-beta.1'},
                      {'tag_name': 'bun-v1.5.0;touch /tmp/no'}):
            with self.subTest(patch=patch):
                data = metadata()
                data[resolver.SOURCES['bun']].update(patch)
                with self.assertRaises(resolver.ResolutionError):
                    self.resolve(data)

    def test_latest_incompatible_package_selects_highest_compatible_release(self):
        for tool in ('npm', 'pnpm'):
            with self.subTest(tool=tool):
                data = metadata()
                data[resolver.SOURCES[tool]] = {'version': '13.0.0', 'engines': {'node': '>=24'}}
                data['https://registry.npmjs.org/' + tool] = {'versions': {
                    '12.16.0': {'version': '12.16.0', 'engines': {'node': '>=22.0.0 <23'}},
                    '12.17.0': {'version': '12.17.0', 'engines': {'node': '>=24'}},
                    '12.18.0': {'version': '12.18.0', 'engines': {'node': '>=22'}, 'deprecated': 'unsafe'},
                    '13.0.0': {'version': '13.0.0', 'engines': {'node': '>=24'}},
                    '14.0.0': {'version': '14.0.0', 'engines': {'node': '>=22'}},
                    '12.99.0-beta.1': {'version': '12.99.0-beta.1', 'engines': {'node': '>=22'}},
                }}
                self.assertEqual(self.resolve(data)['versions'][tool], '12.16.0')

    def test_incompatible_history_cannot_fall_back_below_security_floor(self):
        data = metadata()
        data[resolver.SOURCES['npm']] = {'version': '13.0.0', 'engines': {'node': '>=24'}}
        data['https://registry.npmjs.org/npm'] = {'versions': {
            '10.9.9': {'version': '10.9.9', 'engines': {'node': '>=18'}},
        }}
        with self.assertRaisesRegex(resolver.ResolutionError, 'security floor'):
            self.resolve(data)

    def test_unknown_or_missing_engine_metadata_fails_closed(self):
        for engine in ('banana', '>=22.0.0-0', '22.x.3', '', None):
            with self.subTest(engine=engine):
                data = metadata()
                data[resolver.SOURCES['npm']]['engines']['node'] = engine
                with self.assertRaises(resolver.ResolutionError):
                    self.resolve(data)

    def test_semgrep_must_support_selected_python(self):
        data = metadata()
        data[resolver.SOURCES['semgrep']]['info']['requires_python'] = '>=3.10,<3.15'
        with self.assertRaisesRegex(resolver.ResolutionError, 'semgrep.*Python'):
            self.resolve(data)

    def test_pip_release_changes_identity_without_a_python_release(self):
        before = self.resolve()
        data = metadata()
        data[resolver.SOURCES['pip']]['info']['version'] = '26.2.3'
        after = self.resolve(data)
        self.assertEqual(before['versions']['python'], after['versions']['python'])
        self.assertEqual(after['versions']['pip'], '26.2.3')
        self.assertNotEqual(resolver.canonical_json(before), resolver.canonical_json(after))

    def test_pip_prerelease_or_python_incompatibility_fails_closed(self):
        for patch in ({'version': '27.0.0b1'}, {'requires_python': '>=3.16'}):
            with self.subTest(patch=patch):
                data = metadata()
                data[resolver.SOURCES['pip']]['info'].update(patch)
                with self.assertRaises(resolver.ResolutionError):
                    self.resolve(data)

    def test_pip_allows_stable_two_component_and_post_releases(self):
        for release, normalized in (('26.2.2', (26, 2, 2, 0)),
                                    ('26.3', (26, 3, 0, 0)),
                                    ('26.2.2.post1', (26, 2, 2, 1)),
                                    ('26.3.post1', (26, 3, 0, 1))):
            with self.subTest(release=release):
                data = metadata()
                data[resolver.SOURCES['pip']]['info']['version'] = release
                manifest = self.resolve(data)
                self.assertEqual(resolver.pip_version(release), normalized)
                self.assertEqual(manifest['versions']['pip'], release)
                self.assertEqual(manifest['sources']['pip'], 'https://pypi.org/project/pip/' + release + '/')
                resolver.validate_manifest(json.loads(resolver.canonical_json(manifest)))

    def test_pip_rejects_prerelease_epoch_local_dev_and_ambiguous_numbers(self):
        for release in ('26.3a1', '26.3b1', '26.3rc1', '26.3.dev1', '26.3+local',
                        '1!26.3', '026.3', '26.03', '26.3.00', '26.3.post01', '26'):
            with self.subTest(release=release):
                with self.assertRaises(resolver.ResolutionError):
                    resolver.pip_version(release)
        self.assertLess(resolver.pip_version('26.2.post9'), resolver.pip_version('26.2.2'))
        self.assertEqual(resolver.pip_version('26.3'), resolver.pip_version('26.3.0.post0'))
        with self.assertRaises(resolver.ResolutionError):
            resolver.version('26.3')  # Other tools retain their three-component contract.

    def test_all_tools_have_security_floors(self):
        for tool in resolver.FLOORS:
            with self.subTest(tool=tool):
                manifest = self.resolve()
                manifest['versions'][tool] = '0.0.1'
                manifest['sources'] = resolver.source_urls(manifest['versions'])
                with self.assertRaisesRegex(resolver.ResolutionError, 'security floor'):
                    resolver.validate_manifest(manifest)

    def test_offline_manifest_rejects_wrong_branches_and_unofficial_sources(self):
        for tool, release in (('node', '24.22.1'), ('python', '3.16.0')):
            manifest = self.resolve()
            manifest['versions'][tool] = release
            manifest['sources'] = resolver.source_urls(manifest['versions'])
            with self.assertRaisesRegex(resolver.ResolutionError, 'Node 22 and Python 3.15'):
                resolver.validate_manifest(manifest)
        manifest = self.resolve()
        manifest['sources']['node'] = 'https://untrusted.example/22.23.4'
        with self.assertRaisesRegex(resolver.ResolutionError, 'official'):
            resolver.validate_manifest(manifest)

    def test_offline_manifest_accepts_bound_security_fix_and_later_build(self):
        for build in ('20261026', '20261027'):
            with self.subTest(build=build):
                manifest = supported_manifest()
                manifest['sources']['python'] = python_source(build=build)
                self.assertEqual(resolver.validate_manifest(manifest), manifest)

    def test_offline_manifest_refuses_vulnerable_python_even_with_legacy_release_source(self):
        manifest = supported_manifest()
        manifest['versions']['python'] = '3.15.1'
        manifest['sources']['python'] = 'https://www.python.org/downloads/release/python-3151/'
        with self.assertRaisesRegex(resolver.ResolutionError, 'security floor'):
            resolver.validate_manifest(manifest)

    def test_offline_manifest_requires_exact_distribution_version_build_and_sha256(self):
        valid = python_source()
        for source in (
                'https://www.python.org/downloads/release/python-3152/',
                valid.split('#')[0], valid.replace('3.15.2', '3.15.1'),
                valid.replace('/20261026/', '/20261025/'),
                valid.replace('github.com', 'github.com.untrusted.example'),
                valid.replace('https:', 'http:'), valid.replace('%2B', '+'),
                valid.replace('aarch64-', 'x86_64-'),
                valid.replace('install_only_stripped', 'install_only'),
                valid.replace('sha256=', 'sha512='), valid[:-1],
                valid[:-64] + 'A' * 64, valid + '&other=1'):
            with self.subTest(source=source):
                manifest = supported_manifest()
                manifest['sources']['python'] = source
                with self.assertRaises(resolver.ResolutionError):
                    resolver.validate_manifest(manifest)
                manifest['sources']['python'] = valid
                resolver.validate_manifest(manifest)

    def test_offline_manifest_keeps_exact_schema_and_tool_membership(self):
        for change in ('bool-schema', 'extra-field', 'missing-source', 'extra-tool', 'bool-version'):
            with self.subTest(change=change):
                manifest = supported_manifest()
                if change == 'bool-schema':
                    manifest['schema'] = True
                elif change == 'extra-field':
                    manifest['distribution'] = {}
                elif change == 'missing-source':
                    del manifest['sources']['python']
                elif change == 'extra-tool':
                    manifest['versions']['other'] = '1.2.3'
                else:
                    manifest['versions']['python'] = True
                with self.assertRaises(resolver.ResolutionError):
                    resolver.validate_manifest(manifest)

    def test_failed_resolution_preserves_prior_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest.json'
            path.write_text('prior valid build manifest\n')
            with mock.patch.object(resolver, 'resolve', side_effect=resolver.ResolutionError('network unavailable')):
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(resolver.main(['--output', str(path)]), 1)
            self.assertEqual(path.read_text(), 'prior valid build manifest\n')

    def test_offline_build_arguments_validate_and_never_fetch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest.json'
            path.write_text(resolver.canonical_json(self.resolve()))
            output = io.StringIO()
            with mock.patch.object(resolver, 'resolve', side_effect=AssertionError('network not allowed')):
                with contextlib.redirect_stdout(output):
                    self.assertEqual(resolver.main(['--build-args', str(path)]), 0)
            expected = [
                'BUN_VERSION=1.4.4', 'UV_VERSION=0.13.5', 'FNM_VERSION=1.39.0',
                'NODE_VERSION=22.23.4', 'PYTHON_VERSION=3.15.2', 'PIP_VERSION=26.2.2',
                'NPM_VERSION=12.2.1', 'PNPM_VERSION=12.15.0', 'SEMGREP_VERSION=1.182.1',
                'PYTHON_DOWNLOAD_URL=' + python_asset()['browser_download_url'],
                'PYTHON_DOWNLOAD_SHA256=' + PYTHON_SHA256,
            ]
            self.assertEqual(output.getvalue().splitlines(), expected)

    def test_network_failure_does_not_produce_a_manifest(self):
        def fail(url):
            raise resolver.ResolutionError('no network: ' + url)
        with self.assertRaisesRegex(resolver.ResolutionError, 'no network'):
            resolver.resolve(fail)

    def test_semver_range_boundaries(self):
        cases = [
            ('22.23.4', '^22.22.2 || ^24.15.0 || >=26.0.0', True),
            ('22.23.4', '>=24.0.0', False), ('22.23.4', '>=22 <23', True),
            ('22.23.4', '22.x', True), ('22.23.4', '~22.22.0', False),
            ('3.15.1', '>=3.10, <4, !=3.15.0', True),
            ('0.13.5', '^0.13.4', True), ('0.14.0', '^0.13.4', False),
            ('22.23.4', '22 - 22.23', True), ('22.24.0', '22 - 22.23', False),
        ]
        for release, requirement, expected in cases:
            with self.subTest(release=release, requirement=requirement):
                self.assertEqual(resolver.satisfies(release, requirement), expected)

    def test_help_is_available_without_network(self):
        result = subprocess.run([str(SCRIPT), '--help'], text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--build-args', result.stdout)


class ResolverTLS(unittest.TestCase):
    def setUp(self):
        resolver.tls_context.cache_clear()

    def tearDown(self):
        resolver.tls_context.cache_clear()

    def context_fixture(self, names):
        host = mock.Mock()
        host.get_ca_certs.return_value = list(names)
        filtered = mock.Mock()
        loaded = []

        def create_default_context(**kwargs):
            if not kwargs:
                return host
            loaded.append(kwargs)
            return filtered

        def single_context(protocol):
            self.assertEqual(protocol, resolver.ssl.PROTOCOL_TLS_CLIENT)
            context = mock.Mock()

            def load_verify_locations(*, cadata):
                name = names[cadata.encode()]
                subject = ((('commonName', name),),) if name else ((('organizationName', 'Private CA'),),)
                context.get_ca_certs.return_value = [{'subject': subject}]

            context.load_verify_locations.side_effect = load_verify_locations
            return context

        return host, filtered, loaded, create_default_context, single_context

    def test_filters_affected_roots_and_preserves_host_enterprise_roots(self):
        names = {b'public': 'Public Root CA', b'enterprise': 'Enterprise TLS Proxy',
                 b'emsign': 'emSign ECC Root CA - G3', b'aaa': 'AAA Certificate Services',
                 b'private-without-cn': None}
        host, filtered, loaded, create, single = self.context_fixture(names)
        with mock.patch.object(resolver.ssl, 'create_default_context', side_effect=create) as defaults:
            with mock.patch.object(resolver.ssl, 'SSLContext', side_effect=single):
                with mock.patch.object(resolver.ssl, 'DER_cert_to_PEM_cert', side_effect=lambda der: der.decode()):
                    self.assertIs(resolver.tls_context(), filtered)
                    self.assertIs(resolver.tls_context(), filtered)
        self.assertEqual(defaults.call_count, 2)  # Host anchors read once; explicit filtered context once.
        self.assertEqual(loaded, [{'cadata': 'public\nenterprise\nprivate-without-cn'}])
        host.get_ca_certs.assert_called_once_with(binary_form=True)
        filtered.load_default_certs.assert_not_called()
        filtered.load_verify_locations.assert_not_called()

    def test_empty_or_entirely_distrusted_host_store_fails_closed(self):
        for names in ({}, {b'emsign': 'emSign ECC Root CA - G3', b'aaa': 'AAA Certificate Services'}):
            with self.subTest(names=names):
                resolver.tls_context.cache_clear()
                _, _, loaded, create, single = self.context_fixture(names)
                with mock.patch.object(resolver.ssl, 'create_default_context', side_effect=create):
                    with mock.patch.object(resolver.ssl, 'SSLContext', side_effect=single):
                        with mock.patch.object(resolver.ssl, 'DER_cert_to_PEM_cert', side_effect=lambda der: der.decode()):
                            with self.assertRaisesRegex(resolver.ResolutionError, 'no safe host TLS'):
                                resolver.tls_context()
                self.assertEqual(loaded, [])

    def test_uninspectable_anchor_fails_closed(self):
        host = mock.Mock()
        host.get_ca_certs.return_value = [b'unknown']
        single = mock.Mock()
        single.get_ca_certs.return_value = []
        with mock.patch.object(resolver.ssl, 'create_default_context', return_value=host):
            with mock.patch.object(resolver.ssl, 'SSLContext', return_value=single):
                with mock.patch.object(resolver.ssl, 'DER_cert_to_PEM_cert', return_value='unknown'):
                    with self.assertRaisesRegex(resolver.ResolutionError, 'cannot inspect'):
                        resolver.tls_context()

    def test_fetch_uses_explicit_verified_context(self):
        context = mock.Mock()
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"version":"1.2.3"}'
        response.__enter__.return_value.geturl.return_value = resolver.SOURCES['npm']
        with mock.patch.object(resolver, 'tls_context', return_value=context):
            with mock.patch.object(resolver.urllib.request, 'urlopen', return_value=response) as urlopen:
                self.assertEqual(resolver.fetch_json(resolver.SOURCES['npm']), {'version': '1.2.3'})
        self.assertEqual(urlopen.call_args.kwargs['context'], context)
        self.assertEqual(urlopen.call_args.kwargs['timeout'], resolver.TIMEOUT)

    def test_metadata_redirect_cannot_downgrade_or_change_source(self):
        for target in ('http://registry.npmjs.org/npm/latest',
                       'https://untrusted.example/npm/latest',
                       'https://registry.npmjs.org:8443/npm/latest'):
            with self.subTest(target=target):
                response = mock.MagicMock()
                response.__enter__.return_value.geturl.return_value = target
                with mock.patch.object(resolver, 'tls_context', return_value=mock.Mock()):
                    with mock.patch.object(resolver.urllib.request, 'urlopen', return_value=response):
                        with self.assertRaisesRegex(resolver.ResolutionError, 'HTTPS source'):
                            resolver.fetch_json(resolver.SOURCES['npm'])
                response.__enter__.return_value.read.assert_not_called()


if __name__ == '__main__':
    unittest.main()
