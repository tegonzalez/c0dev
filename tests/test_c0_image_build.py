# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Exercise the supervised build path with runtime security state unavailable."""
import json
import os
import pty
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

SOURCE = (Path(__file__).resolve().parents[1] / 'bin/c0').read_text()
FUNCTIONS = '\n'.join(
    re.search(r'^' + name + r'\(\) \{\n.*?^\}', SOURCE, re.M | re.S).group()
    for name in ('c0_build_wait_group', 'c0_build_cancel_group', 'cmd_build',
                 'c0_build_steps', 'dc_build', 'c0_build_base_image',
                 'c0_base_image_matches', 'c0_validate_base_image', 'c0_runtime_image_matches',
                 'c0_build_runtime_image', 'c0_validate_runtime_image',
                 'c0_docker_content_failure', 'c0_publish_runtime_image',
                 'c0_runtime_recipe_ref', 'c0_command_environment')
)
DOCKER = '''
import json, os, sys
args = sys.argv[1:]
with open(os.environ['TEST_DOCKER_LOG'], 'a') as log:
    log.write(json.dumps(args)+'\\n')
if args[0] == 'ps':
    if os.environ['TEST_CONTAINER_EXISTS'] == '1': print('existing-runtime')
elif args[:2] == ['image', 'inspect']:
    if os.environ['TEST_REUSE'] == '1' and '--format' in args and 'c0dev.mode' in args[args.index('--format')+1]:
        fields = ['prod', 'c'*64, 'b'*64]
        if args[-1].startswith('c0dev-runtime-prod:'):
            fields += ['build-tools-id', 'test-tools', 'c0dev-base-prod:'+'b'*64]
        print('\\t'.join(fields))
    else:
        print('sha256:'+'a'*64)
elif args[:2] == ['image', 'tag']:
    if ':recipe-' in args[-1]: sys.exit(int(os.environ['TEST_PUBLISH_STATUS']))
elif args[:2] == ['image', 'rm']:
    pass
elif args[0] == 'build':
    sys.exit(int(os.environ['TEST_BASE_STATUS']))
elif args[0] == 'run':
    if any(arg.startswith('c0dev-base-prod') for arg in args): sys.exit(0)
    previous = [json.loads(line) for line in open(os.environ['TEST_DOCKER_LOG'])]
    runs = sum(call[0] == 'run' and not any(arg.startswith('c0dev-base-prod') for arg in call) for call in previous)
    if os.environ['TEST_CACHE_FAILURE'] == '1' and runs == 1:
        print('content digest sha256:123: not found', file=sys.stderr)
        sys.exit(1)
    sys.exit(int(os.environ['TEST_SMOKE_STATUS']))
elif args[0] == 'compose' and 'build' in args:
    print('BUILD_STDERR_ISATTY='+str(os.isatty(2)), file=sys.stderr)
    sys.exit(int(os.environ['TEST_BUILD_STATUS']))
else:
    sys.exit(99)
'''


class ImageBuild(unittest.TestCase):
    def build(self, security='', existing=True, build_status=0, force=False, resolve_status=0,
              smoke_status=0, cache_failure=False, publish_status=0, base_status=0, terminal=False, reuse=False):
        with tempfile.TemporaryDirectory(prefix='c0-image-build-') as temp:
            root = Path(temp)
            (root / 'bin').mkdir()
            docker = root / 'bin' / 'docker'
            docker.write_text('#!' + sys.executable + '\n' + DOCKER)
            docker.chmod(0o755)
            log = root / 'docker.log'
            script = root / 'build.sh'
            script.write_text('set -e\n' + FUNCTIONS + '''
C0ROOT="$TEST_ROOT"
MAIN_SERVICE=c0dev
C0_INSTANCE_ID=test-instance
C0_MODE_KEY=prod
C0_RECIPE_ID=cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
C0_BUILD_ID=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
C0_RUNTIME_IMAGE=c0dev-runtime-prod:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
C0_BASE_IMAGE=c0dev-base-prod:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
DOCKERFILE_BASE="$TEST_ROOT/Dockerfile.base"
SHARED_TOOLS_VOLUME=test-tools
TOOLS_BUILD_ID=build-tools-id
TOOLS_ID=build-tools-id
TOOLS_PREFIX=/tools/current
VOLUMES_FOLDERS_FILE="$TEST_ROOT/volumes-folders.yaml"
VOLUMES_FILES_FILE="$TEST_ROOT/volumes-files.yaml"
COMPOSE_PUBLIC_FILE="$TEST_ROOT/docker-compose.public.yaml"
COMPOSE_SECURITY_GUEST_ADMIN="$TEST_ROOT/security-guest-admin.yaml"
COMPOSE_SECURITY_LEAST_PRIVILEGE="$TEST_ROOT/security-least-privilege.yaml"
COMPOSE_SSH_AUTH_FILE="$TEST_ROOT/ssh-fragment.yaml"
IN_CONTAINER=false
C0_MODE=""
require_host() { :; }
verify_moby_seccomp_profile() { :; }
maybe_notify_seccomp_update_available() { echo OPTIONAL_SECCOMP_NOTICE >&2; }
c0_ssh_ensure_keys() { :; }
validate_host_paths() { :; }
c0_resolve_toolchain() {
    echo RELEASES_RESOLVED
    [[ "$TEST_RESOLVE_STATUS" == 0 ]] || return "$TEST_RESOLVE_STATUS"
    C0_TOOLCHAIN_BUILD_ARGS=(--build-arg BUN_VERSION=1.4.4 --build-arg NODE_VERSION=22.23.4 --build-arg PIP_VERSION=26.2.2)
}
build_tools_volume() { echo TOOLS_VALID; }
infocmp() { :; }
c0_prepare_terminfo() { :; }
c0_prepare_build_context() { mkdir -p "$C0_BUILD_CONTEXT"; }
c0_prepare_runtime_dockerfile() { :; }
gc_tools_hashes() { echo GC_COMPLETED; }
cmd_build "$@"
''')
            fragment = root / 'ssh-fragment.yaml'
            fragment.write_text('existing runtime fragment\n')
            env = dict(os.environ, PATH=str(root/'bin')+os.pathsep+os.environ['PATH'],
                       TEST_ROOT=str(root), TEST_DOCKER_LOG=str(log),
                       TEST_CONTAINER_EXISTS='1' if existing else '0',
                       TEST_BUILD_STATUS=str(build_status), TEST_RESOLVE_STATUS=str(resolve_status), TEST_REUSE='1' if reuse else '0',
                       TEST_SMOKE_STATUS=str(smoke_status), TEST_PUBLISH_STATUS=str(publish_status), TEST_BASE_STATUS=str(base_status), TEST_CACHE_FAILURE='1' if cache_failure else '0', TERM='xterm',
                       C0_SSH_AGENT='0')
            env.pop('C0_SECURITY_RESOLVED', None)
            env.pop('C0_SECURITY', None)
            if security: env['C0_SECURITY'] = security
            command = ['/bin/bash', str(script)] + (['-f'] if force else [])
            if terminal:
                master, slave = pty.openpty()
                try:
                    result = subprocess.run(command, env=env, stdout=slave, stderr=slave, timeout=5)
                    os.set_blocking(master, False)
                    chunks = []
                    while True:
                        try:
                            chunk = os.read(master, 65536)
                        except OSError:
                            break
                        if not chunk:
                            break
                        chunks.append(chunk)
                    result.stdout = result.stderr = b''.join(chunks).decode()
                finally:
                    os.close(slave)
                    os.close(master)
            else:
                result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=5)
            if resolve_status:
                self.assertFalse(log.exists())
                return result, None
            self.assertTrue(log.exists(), (result.returncode, result.stdout, result.stderr))
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            # Image construction must neither inspect runtime labels nor invoke
            # runtime preparation; even an obsolete label cannot gate this path.
            builds = [call for call in calls if call[0] == 'compose']
            if base_status:
                self.assertEqual(builds, [])
                self.assertNotIn('TOOLS_VALID', result.stdout)
                return result, None
            expected_builds = 0 if reuse and not force and not smoke_status else (2 if cache_failure and not force else 1)
            self.assertEqual(len(builds), expected_builds, calls)
            if not builds:
                self.assertIn('Image: valid', result.stdout)
                self.assertTrue(any(call[:2] == ['image', 'tag'] for call in calls))
                return result, None
            build = builds[0]
            self.assertIn('build', build)
            self.assertEqual(build[build.index('-p')+1], 'c0dev-build-prod-'+'b'*64)
            self.assertIn('--pull', build)
            descriptors = [build[i+1] for i, arg in enumerate(build[:-1]) if arg == '-f']
            self.assertEqual(len(descriptors), 1)
            self.assertTrue(descriptors[0].endswith('/runtime-image.yaml'))
            self.assertNotIn(str(root/'security-guest-admin.yaml'), build)
            self.assertNotIn(str(root/'security-least-privilege.yaml'), build)
            self.assertNotIn(str(fragment), build)
            published = [call for call in calls if call[:2] == ['image', 'tag'] and call[-1].startswith('c0dev-runtime-')]
            if result.returncode == 0:
                self.assertEqual(published, [
                    ['image', 'tag', 'sha256:'+'a'*64, 'c0dev-runtime-prod:'+'b'*64],
                    ['image', 'tag', 'sha256:'+'a'*64, 'c0dev-runtime-prod:recipe-'+'c'*64],
                    ['image', 'tag', 'sha256:'+'a'*64, 'c0dev-runtime-prod:current']])
                smoke = [call for call in calls if call[0] == 'run'][-1]
                for required in ('--network', 'none', '--read-only', '--cap-drop', 'ALL',
                                 '--user', '1000:1000', 'sha256:'+'a'*64):
                    self.assertIn(required, smoke)
            elif not publish_status:
                self.assertEqual(published, [])
            self.assertEqual(fragment.read_text(), 'existing runtime fragment\n')
            self.assertIn('OPTIONAL_SECCOMP_NOTICE', result.stderr)
            return result, builds[-1]

    def test_existing_runtime_with_seccomp_label_does_not_block_build(self):
        result, _ = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Build complete', result.stdout)
        self.assertIn('BUILD_STDERR_ISATTY=False', result.stdout)
        self.assertIn('GC_COMPLETED', result.stdout)

    def test_interactive_build_preserves_dockers_terminal(self):
        result, _ = self.build(terminal=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('BUILD_STDERR_ISATTY=True', result.stdout)

    def test_interactive_build_failure_does_not_publish_success(self):
        result, _ = self.build(terminal=True, build_status=27)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('BUILD_STDERR_ISATTY=True', result.stdout)
        self.assertNotIn('Build complete', result.stdout)

    def test_matching_shared_images_are_reused_without_building(self):
        result, build = self.build(reuse=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(build)
        self.assertIn('Base: valid', result.stdout)
        self.assertIn('Image: valid', result.stdout)

    def test_force_rebuild_skips_existing_image_reuse(self):
        result, build = self.build(reuse=True, force=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--no-cache', build)
        self.assertNotIn('Image: valid', result.stdout)

    def test_unhealthy_cached_image_rebuilds_but_never_reports_success(self):
        result, build = self.build(reuse=True, smoke_status=17)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('build', build)
        self.assertNotIn('Build complete', result.stdout)

    def test_base_failure_prevents_tools_and_runtime_publication(self):
        result, _ = self.build(base_status=34)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('base image build or validation failed', result.stderr)
        self.assertNotIn('Build complete', result.stdout)

    def test_runtime_environment_does_not_gate_image_construction(self):
        for security in ('seccomp', 'least-privilege', 'guest-admin'):
            with self.subTest(security=security):
                result, _ = self.build(security=security, existing=False)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_force_rebuild_reaches_compose(self):
        result, call = self.build(force=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(call[call.index('build')+1:], [
            '--pull', '--no-cache', '--build-arg', 'BUN_VERSION=1.4.4',
            '--build-arg', 'NODE_VERSION=22.23.4', '--build-arg', 'PIP_VERSION=26.2.2', 'c0dev'])

    def test_image_failure_prevents_publication_and_gc(self):
        result, _ = self.build(build_status=27)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('image build failed', result.stderr)
        self.assertNotIn('Build complete', result.stdout)
        self.assertNotIn('GC_COMPLETED', result.stdout)

    def test_release_failure_prevents_all_docker_builds(self):
        result, _ = self.build(resolve_status=28)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('TOOLS_VALID', result.stdout)
        self.assertNotIn('Build complete', result.stdout)
        self.assertNotIn('GC_COMPLETED', result.stdout)

    def test_runtime_build_receives_the_resolved_exact_versions(self):
        result, call = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('RELEASES_RESOLVED', result.stdout)
        self.assertEqual(call[call.index('build')+1:], [
            '--pull', '--build-arg', 'BUN_VERSION=1.4.4',
            '--build-arg', 'NODE_VERSION=22.23.4', '--build-arg', 'PIP_VERSION=26.2.2', 'c0dev'])

    def test_publication_failure_is_reported_as_build_failure(self):
        result, _ = self.build(publish_status=23)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('Build complete', result.stdout)
        self.assertIn('image build failed', result.stderr)

    def test_invalid_built_image_never_replaces_published_image(self):
        result, _ = self.build(smoke_status=17)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('Build complete', result.stdout)
        self.assertNotIn('Build complete', result.stdout)
        self.assertIn('previous shared image retained', result.stderr)

    def test_missing_cached_content_retries_once_without_cache(self):
        result, call = self.build(cache_failure=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--no-cache', call)
        self.assertIn('retrying without cache', result.stderr)

    def test_forced_build_does_not_repeat_an_already_uncached_failure(self):
        result, _ = self.build(cache_failure=True, force=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('Build complete', result.stdout)

    def test_tools_build_pulls_base_for_normal_and_force_builds(self):
        build_tools = re.search(r'^build_tools_volume\(\) \{\n.*?^\}',
                                SOURCE, re.M | re.S).group()
        for force in (False, True):
            with self.subTest(force=force):
                script = build_tools + '''
TOOLS_BUILD_ID=test-tools
SHARED_TOOLS_VOLUME=test-volume
MAIN_SERVICE=c0dev
DOCKERFILE_TOOLS_BUILD=/tmp/test.Dockerfile
C0_BUILD_CONTEXT=/tmp/test-context
C0_TOOLCHAIN_BUILD_ARGS=(--build-arg NODE_VERSION=22.23.4)
verify_moby_seccomp_profile() { :; }
maybe_promote_staged_next() { :; }
tools_volume_build_matches() { return 1; }
c0_prepare_tools_dockerfile() { :; }
docker() {
    if [[ "$1" == build ]]; then
        printf 'BUILD_ARG=%s\\n' "$@"
        return 27
    fi
}
build_tools_volume "$1" "$2"
'''
                result = subprocess.run(
                    ['/bin/bash', '-c', script, 'test',
                     'true' if force else 'false', '--no-cache' if force else ''],
                    capture_output=True, text=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
                args = [line.removeprefix('BUILD_ARG=')
                        for line in result.stdout.splitlines()
                        if line.startswith('BUILD_ARG=')]
                self.assertEqual(args[:2], ['build', '--pull'])
                self.assertEqual('--no-cache' in args, force)
                self.assertEqual(args[args.index('--build-arg')+1], 'NODE_VERSION=22.23.4')


if __name__ == '__main__':
    unittest.main()
