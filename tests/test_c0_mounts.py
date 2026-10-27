# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Accept supported existing layouts; reject forked or incoherent mount metadata."""
import re
import subprocess
import unittest
from c0_fixture import Fixture, REPO

SOURCE = (REPO / 'bin/c0').read_text()
VALIDATION = '\n'.join(re.search(r'^' + name + r'\(\) \{\n.*?^\}', SOURCE,
                                re.M | re.S).group()
                       for name in ('get_tools_hash_label', 'resolve_volume_host_path',
                                    'is_docker_volume', 'to_display_path', 'parse_folder_mappings',
                                    'parse_file_mappings', 'c0_validate_overlay_volume', 'c0_overlay_volume_for_container',
                                    'c0_validate_container_mounts'))


class Mounts(unittest.TestCase):
    def setUp(self): self.f = Fixture()
    def tearDown(self): self.f.close()

    def validate(self, allow_legacy=True, check_guest=False):
        script = VALIDATION + r'''
C0ROOT="$TEST_ROOT"
C0_INSTANCE_ID="$TEST_INSTANCE"
SHARED_TOOLS_VOLUME=c0dev-tools-shared
TOOLS_PREFIX=/tools/current
VOLUMES_FOLDERS_FILE="$C0ROOT/docker/volumes-folders.yaml"
VOLUMES_FILES_FILE="$C0ROOT/docker/volumes-files.yaml"
c0_validate_container_mounts oneoff-runtime "$TEST_CHECK_GUEST" "$TEST_ALLOW_LEGACY"
status=$?
printf 'LAYOUT=%s\nTOOLS=%s\n' "$C0_CONTAINER_LAYOUT" "$C0_CONTAINER_TOOLS_ID"
exit "$status"
'''
        env = dict(self.f.env, TEST_ROOT=str(self.f.checkout), TEST_INSTANCE=self.f.instance,
                   TEST_ALLOW_LEGACY=str(allow_legacy).lower(), TEST_CHECK_GUEST=str(check_guest).lower())
        return subprocess.run(['/bin/bash', '-c', script], env=env,
                              text=True, capture_output=True, timeout=10)

    def legacy(self):
        state = self.f.read()
        mounts = state['containers'][0]['mounts']
        next(m for m in mounts if m['target'] == '/run/c0/host-bin').update(
            target='/home/dev/bin', rw=True)
        next(m for m in mounts if m['target'] == '/home/dev/.gitconfig')['rw'] = True
        self.f.write(state)
        return state

    def rejected(self, target):
        for command in ('start', 'sh', 'root'):
            with self.subTest(command=command):
                result = self.f.run(command)
                self.assertNotEqual(result.returncode, 0, (result.stdout, result.stderr))
                self.assertIn(target, result.stderr)
                self.assertNotIn('✅ Already running', result.stdout)
                self.assertNotIn('🐚 Shell:', result.stdout)
        self.assertFalse(any(c[0] == 'exec' and 'bash' in c for c in self.f.read()['calls']))

    def test_missing_rules_bind_mount(self):
        state = self.f.read()
        state['containers'][0]['mounts'] = [m for m in state['containers'][0]['mounts'] if m['target'] != '/home/dev/rules']
        self.f.write(state)
        self.rejected('/home/dev/rules')
        self.assertFalse(any(c[0] == 'run' for c in self.f.read()['calls']))

    def test_bind_from_a_different_fork(self):
        other = self.f.root/'another-fork'; other.mkdir()
        state = self.f.read()
        next(m for m in state['containers'][0]['mounts'] if m['target'] == '/home/dev/projects')['source'] = str(other)
        self.f.write(state)
        self.rejected('/home/dev/projects')

    def test_wrong_mount_permissions_and_volume_names(self):
        for target, field, value in (
            ('/home/dev/rules', 'rw', False),
            ('/home/dev/.gitconfig', 'rw', True),
            ('/run/c0/host-bin', 'rw', True),
            ('/usr/local/bin/docker-entrypoint.sh', 'rw', True),
            ('/tools/current', 'name', 'wrong-tools-volume'),
            ('/run/c0/overlay-state', 'name', 'another-instance-home-overlays')):
            with self.subTest(target=target):
                state = self.f.read(); state['containers'] = [self.f.container()]; state['calls'] = []
                next(m for m in state['containers'][0]['mounts'] if m['target'] == target)[field] = value
                self.f.write(state)
                self.rejected(target)

    def test_wrong_tools_subpath_or_invalid_snapshot_identity(self):
        state = self.f.read(); state['containers'][0]['subpath'] = 'opt/another-snapshot'; self.f.write(state)
        self.rejected('subpath')
        state = self.f.read(); state['containers'][0]['tools'] = 'invalid'; self.f.write(state)
        self.rejected('snapshot identity')

    def test_deleted_host_source_is_not_recreated(self):
        (self.f.checkout/'rules').rmdir()
        self.rejected('rules')
        self.assertFalse((self.f.checkout/'rules').exists())

    def test_correct_metadata_but_inaccessible_guest_or_broken_home_entry(self):
        for target in ('/home/dev/rules', '/home/dev/packages'):
            state = self.f.read(); state['containers'][0]['bad_guest'] = target; self.f.write(state)
            self.rejected(target)

    def test_invalid_stopped_container_is_not_started(self):
        state = self.f.read(); state['containers'][0]['state'] = 'exited'
        state['containers'][0]['mounts'] = []; self.f.write(state)
        result = self.f.run('start')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(c[0] == 'start' for c in self.f.read()['calls']))

    def test_failed_guest_probe_after_resume_rolls_back_and_reports_failure(self):
        state = self.f.read(); state['containers'][0].update(state='exited', bad_guest='/home/dev/rules'); self.f.write(state)
        result = self.f.run('start')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('✅ Started', result.stdout)
        self.assertEqual(self.f.read()['containers'][0]['state'], 'exited')

    def test_failed_guest_probe_after_create_stops_failed_container(self):
        state = self.f.read(); state['containers'] = []; state['new_container']['bad_guest'] = '/home/dev/rules'; self.f.write(state)
        result = self.f.run('start')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('✅ Started', result.stdout)
        self.assertEqual(self.f.read()['containers'][0]['state'], 'exited')

    def test_exit_during_initialization_is_not_reported_as_running(self):
        state = self.f.read(); state['containers'][0]['exit_after_probe'] = True; self.f.write(state)
        result = self.f.run('start')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('✅ Already running', result.stdout)

    def test_attach_verification_uses_existing_container_without_helper_image(self):
        result = self.f.run('sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.f.read()['calls']
        self.assertFalse(any(c[0] in ('run', 'compose', 'start') for c in calls))
        self.assertTrue(any(c[0] == 'exec' and 'c0-mount-check' in c for c in calls))

    def test_existing_snapshot_drives_overlay_setup(self):
        state = self.f.read(); state['containers'][0]['tools'] = 'b'*64; self.f.write(state)
        result = self.f.run('start')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.f.read()['calls']
        self.assertTrue(any(c[0] == 'run' and c[-1] == 'b'*64 for c in calls))

    def test_launcher_overlay_is_mounted_from_readonly_host_bin(self):
        result = self.f.run('start')
        self.assertEqual(result.returncode, 0, result.stderr)
        helpers = [c for c in self.f.read()['calls'] if c[0] == 'run']
        self.assertTrue(any('bin' in c and '/run/c0/host-bin' in ' '.join(c) for c in helpers))

    def test_old_writable_launcher_bind_is_rejected(self):
        state = self.f.read()
        mount = next(m for m in state['containers'][0]['mounts'] if m['target'] == '/run/c0/host-bin')
        mount.update(target='/home/dev/bin', rw=True)
        self.f.write(state)
        self.rejected('/run/c0/host-bin')

    def test_current_contract_is_classified_without_mutations_or_guest_execution(self):
        result = self.validate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('LAYOUT=current\nTOOLS=' + self.f.tools, result.stdout)
        self.assertEqual(result.stderr, '')
        self.assertFalse(any(call[0] in ('exec', 'start', 'run', 'compose')
                             for call in self.f.read()['calls']))

    def test_exact_old_contract_is_recognized_only_when_requested(self):
        self.legacy()
        result = self.validate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('LAYOUT=legacy\nTOOLS=' + self.f.tools, result.stdout)
        self.assertEqual(result.stderr, '')
        strict = self.validate(allow_legacy=False)
        self.assertNotEqual(strict.returncode, 0)
        self.assertIn('LAYOUT=\nTOOLS=\n', strict.stdout)
        for command in ('start', 'sh', 'root'):
            result = self.f.run(command)
            self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
        self.assertEqual(len(self.f.read()['containers']), 1)
        self.assertFalse(any(call[0] in ('compose', 'rm', 'rename', 'commit', 'export', 'import')
                             for call in self.f.read()['calls']))

    def test_legacy_contract_still_requires_this_checkout_and_all_mounts(self):
        for issue in ('other_bin', 'other_gitconfig', 'missing_rules', 'wrong_tools_subpath'):
            with self.subTest(issue=issue):
                state = self.f.read()
                state['containers'] = [self.f.container()]
                self.f.write(state)
                state = self.legacy()
                mounts = state['containers'][0]['mounts']
                if issue == 'other_bin':
                    other = self.f.root / 'other-bin'
                    other.mkdir(exist_ok=True)
                    next(m for m in mounts if m['target'] == '/home/dev/bin')['source'] = str(other)
                elif issue == 'other_gitconfig':
                    other = self.f.root / 'other-gitconfig'
                    other.write_text('[user]\n')
                    next(m for m in mounts if m['target'] == '/home/dev/.gitconfig')['source'] = str(other)
                elif issue == 'missing_rules':
                    state['containers'][0]['mounts'] = [m for m in mounts if m['target'] != '/home/dev/rules']
                else:
                    state['containers'][0]['subpath'] = 'opt/another-snapshot'
                self.f.write(state)
                result = self.validate()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('LAYOUT=\nTOOLS=\n', result.stdout)

    def test_mixed_duplicate_or_undeclared_mounts_are_rejected(self):
        for issue in ('mixed_launchers', 'duplicate', 'nested_launcher', 'docker_socket'):
            with self.subTest(issue=issue):
                state = self.f.read()
                state['containers'] = [self.f.container()]
                self.f.write(state)
                state = self.legacy()
                mounts = state['containers'][0]['mounts']
                if issue == 'mixed_launchers':
                    mount = dict(next(m for m in mounts if m['target'] == '/home/dev/bin'))
                    mount.update(target='/run/c0/host-bin', rw=False)
                    mounts.append(mount)
                elif issue == 'duplicate':
                    mounts.append(dict(next(m for m in mounts if m['target'] == '/home/dev/rules')))
                else:
                    target = '/home/dev/bin/c0' if issue == 'nested_launcher' else '/var/run/docker.sock'
                    mounts.append(dict(type='bind', source='/unrelated', target=target, rw=True))
                self.f.write(state)
                result = self.validate()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('LAYOUT=\nTOOLS=\n', result.stdout)

    def test_known_ssh_agent_relay_is_allowed_but_another_source_is_not(self):
        state = self.legacy()
        relay = '/run/host-services/ssh-auth.sock'
        state['containers'][0]['mounts'].append(dict(type='bind', source=relay, target=relay, rw=True))
        self.f.write(state)
        self.assertEqual(self.validate().returncode, 0)
        state['containers'][0]['mounts'][-1]['source'] = '/another-agent.sock'
        self.f.write(state)
        result = self.validate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unexpected container mount', result.stderr)


if __name__ == '__main__': unittest.main()
