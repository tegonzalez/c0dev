# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Compose receives resolved shell values without exporting them to later children.

Only `docker compose config` reaches Docker's real CLI. Runtime/build/port
operations are inert peers, so these checks require no engine or images.
"""
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SOURCE = (REPO / 'bin/c0').read_text()
# An absent helper on the defective baseline must expose the actual wrapper
# failure, rather than turn collection into an unrelated import exception.
FUNCTIONS = '\n'.join(
    match.group() for name in ('c0_command_environment', 'dc', 'dc_build', 'ensure_ssh_port')
    if (match := re.search(r'^' + name + r'\(\) \{\n.*?^\}', SOURCE, re.M | re.S))
)
INPUTS = (
    'SHARED_TOOLS_VOLUME', 'TOOLS_ID', 'TOOLS_PREFIX', 'C0_INSTANCE_ID',
    'C0_WORKSPACE_ID', 'C0_BUILD_ID', 'C0_RECIPE_ID', 'C0_MODE_KEY',
    'C0_RUNTIME_IMAGE', 'C0_BUILD_CONTEXT', 'DOCKERFILE_RUNTIME_BUILD',
    'C0DEV_WEB_PORT', 'C0DEV_SSH_PORT', 'C0_SECURITY',
    'C0_HOME_OVERLAYS_VOLUME', 'C0_HOME_OVERLAYS_EXTERNAL', 'TERM',
)
DOCKER = r'''
import json, os, subprocess, sys
args = sys.argv[1:]
names = json.loads(os.environ['TEST_INPUT_NAMES'])
with open(os.environ['TEST_DOCKER_LOG'], 'a') as log:
    log.write(json.dumps(dict(argv=args, environment={name: os.environ.get(name) for name in names}))+'\n')
if not args or args[0] != 'compose': sys.exit(97)
operation = next((index for index, value in enumerate(args) if value in ('build', 'config', 'ps')), None)
if operation is None: sys.exit(98)
if args[operation] == 'ps':
    print('private-test-container')
    sys.exit(0)
if os.environ.get('TEST_CONFIG') == '1':
    # Parse the exact files and child environment selected by c0. Never run the
    # build requested of this peer, contact an engine, or resolve an image.
    parsed = subprocess.run([os.environ['TEST_REAL_DOCKER'], *args[:operation], 'config', '--format', 'json'],
                            capture_output=True, text=True, timeout=20)
    sys.stdout.write(parsed.stdout)
    sys.stderr.write(parsed.stderr)
    sys.exit(parsed.returncode)
sys.exit(int(os.environ.get('TEST_CHILD_STATUS', '0')))
'''


class CommandEnvironment(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='c0-command-environment-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.checkout = self.root / """checkout with $literal and "quotes" and 'apostrophe'"""
        self.compose = self.checkout / 'docker'
        self.compose.mkdir(parents=True)
        for name in ('volumes-folders.yaml', 'volumes-files.yaml', 'docker-compose.public.yaml',
                     'docker-compose.security-guest-admin.yaml'):
            shutil.copy2(REPO / 'docker' / name, self.compose / name)
        self.context = self.root / """build context with $literal and "quotes" and 'apostrophe'"""
        self.context.mkdir()
        (self.context / 'runtime-image.yaml').write_text('services:\n  c0dev:\n    image: private-build:fixture\n')
        self.values = dict(
            SHARED_TOOLS_VOLUME='private-tools', TOOLS_ID='a'*64, TOOLS_PREFIX='/tools/current',
            C0_INSTANCE_ID='private-instance', C0_WORKSPACE_ID='private-workspace',
            C0_BUILD_ID='b'*64, C0_RECIPE_ID='c'*64, C0_MODE_KEY='prod',
            C0_RUNTIME_IMAGE='private-runtime:fixture', C0_BUILD_CONTEXT=str(self.context),
            DOCKERFILE_RUNTIME_BUILD=str(self.context / 'Dockerfile with $literal and "quotes"'),
            C0DEV_WEB_PORT='3017', C0DEV_SSH_PORT='2237', C0_SECURITY='guest-admin',
            C0_HOME_OVERLAYS_VOLUME='private-home', C0_HOME_OVERLAYS_EXTERNAL='false', TERM='xterm-256color')
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.docker_config = self.root / 'docker-config'
        self.docker_config.mkdir()
        # A user-installed Compose plugin can otherwise disappear with a
        # private Docker config. Reuse only its executable, never user config.
        compose_cli = shutil.which('docker-compose')
        if compose_cli:
            plugins = self.docker_config / 'cli-plugins'
            plugins.mkdir()
            (plugins / 'docker-compose').symlink_to(compose_cli)
        docker = self.bin / 'docker'
        docker.write_text('#!' + sys.executable + '\n' + DOCKER)
        docker.chmod(0o755)
        self.log = self.root / 'docker.log'
        self.real_docker = shutil.which('docker')

    def run_shell(self, command, *, parse=False, unset=(), status=0, agent=False):
        if parse and not self.real_docker:
            self.skipTest('Docker Compose CLI is required for its offline config parser')
        env = dict(os.environ, PATH=str(self.bin)+os.pathsep+os.environ['PATH'],
                   HOME=str(self.home), DOCKER_CONFIG=str(self.docker_config),
                   TEST_DOCKER_LOG=str(self.log), TEST_INPUT_NAMES=json.dumps(INPUTS),
                   TEST_CONFIG='1' if parse else '0', TEST_REAL_DOCKER=self.real_docker or '',
                   TEST_CHILD_STATUS=str(status), C0_TEST_AUTH_SECRET='AUTH_MUST_NOT_BE_DISPLAYED')
        for name in (*INPUTS, 'BASH_ENV'):
            env.pop(name, None)
        variables = dict(self.values, VOLUMES_FOLDERS_FILE=str(self.compose / 'volumes-folders.yaml'),
                         VOLUMES_FILES_FILE=str(self.compose / 'volumes-files.yaml'),
                         COMPOSE_PUBLIC_FILE=str(self.compose / 'docker-compose.public.yaml'),
                         MAIN_SERVICE='c0dev', IN_CONTAINER='false')
        setup = '\n'.join(name+'='+shlex.quote(value) for name, value in variables.items())
        setup += '\n' + '\n'.join('unset '+name for name in unset)
        script = FUNCTIONS + '\n' + setup + '\n' + '''
ensure_c0_security_resolved() { :; }
c0_security_compose_file() { printf '%s\\n' "$TEST_SECURITY_FILE"; }
c0_ssh_agent_enabled() { return 1; }
get_mapped_ssh_port_from_container() { printf '2241\\n'; }
''' + ('c0_ssh_agent_enabled() { return 0; }\n'
       'ensure_ssh_auth_compose_fragment() { printf "services: {}\\n"; }\n' if agent else '') + command
        env['TEST_SECURITY_FILE'] = str(self.compose / 'docker-compose.security-guest-admin.yaml')
        result = subprocess.run(['/bin/bash', '-c', script], env=env, capture_output=True,
                                text=True, timeout=25)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []
        return result, calls

    def test_runtime_and_build_receive_same_literal_resolved_inputs(self):
        for command in ('dc config', 'dc_build --pull'):
            with self.subTest(command=command):
                self.log.unlink(missing_ok=True)
                result, calls = self.run_shell(command)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls[0]['environment'], self.values)
                self.assertNotIn('AUTH_MUST_NOT_BE_DISPLAYED', result.stdout + result.stderr)

    def test_agent_fragment_runtime_branch_receives_same_resolved_inputs(self):
        result, calls = self.run_shell('dc config', agent=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[0]['environment'], self.values)
        self.assertEqual(calls[0]['argv'][-1], 'config')
        self.assertRegex(calls[0]['argv'][-2], r'^/(dev/fd|proc/self/fd)/[0-9]+$')

    def test_runtime_and_build_config_are_warning_free_with_exact_identity(self):
        for command in ('dc config', 'dc_build --pull'):
            with self.subTest(command=command):
                self.log.unlink(missing_ok=True)
                result, _ = self.run_shell(command, parse=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn('variable is not set', result.stderr)
                config = json.loads(result.stdout)
                service = config['services']['c0dev']
                for label, name in (('mode', 'C0_MODE_KEY'), ('recipe', 'C0_RECIPE_ID'),
                                    ('build', 'C0_BUILD_ID'), ('instance', 'C0_INSTANCE_ID'),
                                    ('workspace', 'C0_WORKSPACE_ID'), ('tools_hash', 'TOOLS_ID')):
                    self.assertEqual(service['labels']['c0dev.'+label], self.values[name])
                # Compose escapes literal dollars when rendering reusable
                # config; the child-environment check above observes raw bytes.
                self.assertEqual(service['build']['context'], str(self.context).replace('$', '$$'))
                self.assertEqual(service['build']['dockerfile'], self.values['DOCKERFILE_RUNTIME_BUILD'].replace('$', '$$'))
                self.assertEqual(config['volumes']['home-overlays']['name'], 'private-home')
                self.assertEqual(service['environment']['TERM'], 'xterm-256color')

    def test_unset_optionals_keep_compose_fallbacks_without_warnings(self):
        optional = ('TOOLS_PREFIX', 'C0_BUILD_ID', 'C0_RUNTIME_IMAGE', 'C0_BUILD_CONTEXT',
                    'DOCKERFILE_RUNTIME_BUILD', 'C0DEV_WEB_PORT', 'C0DEV_SSH_PORT', 'C0_SECURITY',
                    'C0_HOME_OVERLAYS_VOLUME', 'C0_HOME_OVERLAYS_EXTERNAL')
        result, calls = self.run_shell('dc config', parse=True, unset=optional)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('variable is not set', result.stderr)
        for name in optional:
            self.assertEqual(calls[0]['environment'][name], '', name)
        config = json.loads(result.stdout)
        service = config['services']['c0dev']
        self.assertEqual(service['labels']['c0dev.build'], 'legacy')
        self.assertEqual(service['labels']['c0dev.security_mode'], 'guest-admin')
        self.assertEqual(service['image'], 'c0dev-unbuilt')
        self.assertEqual(service['environment']['TOOLS_PREFIX'], '/tools/opt/default')
        self.assertEqual(service['build']['dockerfile'], 'Dockerfile.runtime')
        self.assertEqual({p['published'] for p in service['ports']}, {'3000', '2222'})
        self.assertEqual(config['volumes']['home-overlays']['name'], 'private-instance-home-overlays')

    def test_commands_do_not_export_values_to_subsequent_children(self):
        observe = shlex.quote('import json, os; print(json.dumps({key: os.environ.get(key) for key in '+repr(INPUTS)+'}))')
        for command in ('dc config', 'dc_build --pull'):
            with self.subTest(command=command):
                result, _ = self.run_shell(command+'\n'+shlex.quote(sys.executable)+' -c '+observe)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), dict.fromkeys(INPUTS))

    def test_existing_ssh_port_lookup_receives_resolved_identity(self):
        result, calls = self.run_shell('ensure_ssh_port\nprintf "%s\\n" "$C0DEV_SSH_PORT"', unset=('C0DEV_SSH_PORT',))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '2241\n')
        for name in ('C0_MODE_KEY', 'C0_RECIPE_ID', 'C0_WORKSPACE_ID'):
            self.assertEqual(calls[0]['environment'][name], self.values[name])
        self.assertEqual(calls[0]['environment']['C0DEV_SSH_PORT'], '')

    def test_display_has_same_allowlisted_literal_values_and_no_auth(self):
        for unset in ((), ('C0_BUILD_ID', 'C0_BUILD_CONTEXT')):
            with self.subTest(unset=unset):
                result, calls = self.run_shell('c0_command_environment show', unset=unset)
                self.assertEqual(result.returncode, 0, result.stderr)
                shown = {}
                for line in result.stdout.splitlines():
                    fields = shlex.split(line)
                    self.assertEqual(len(fields), 1, line)
                    name, value = fields[0].split('=', 1)
                    self.assertNotIn(name, shown)
                    shown[name] = value
                self.assertEqual(shown, dict(self.values, **dict.fromkeys(unset, '')))
                self.assertEqual(calls, [])
                self.assertNotIn('AUTH_MUST_NOT_BE_DISPLAYED', result.stdout + result.stderr)

    def test_wrappers_preserve_argument_boundaries_and_failure_status(self):
        argument = 'literal argument with $dollar and "quotes"'
        for command in ('dc config ', 'dc_build '):
            with self.subTest(command=command):
                invocation = command+shlex.quote(argument)
                self.log.unlink(missing_ok=True)
                result, calls = self.run_shell(invocation, status=29)
                self.assertEqual(result.returncode, 29, result.stderr)
                self.assertEqual(calls[0]['argv'][-1], argument)

    def test_malformed_helper_calls_refuse_without_displaying_environment(self):
        for command in ('c0_command_environment run',
                        'c0_command_environment show "$C0_TEST_AUTH_SECRET"'):
            with self.subTest(command=command):
                result, calls = self.run_shell(command)
                # Keep failure diagnostics value-free even if a regression
                # invokes bare `env` and returns inherited private variables.
                self.assertEqual(result.returncode, 2)
                self.assertTrue(result.stdout == '', 'malformed invocation produced stdout')
                output = result.stdout + result.stderr
                self.assertTrue('AUTH_MUST_NOT_BE_DISPLAYED' not in output,
                                'malformed invocation exposed the private sentinel')
                self.assertTrue('C0_TEST_AUTH_SECRET' not in output,
                                'malformed invocation exposed an inherited variable name')
                self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
