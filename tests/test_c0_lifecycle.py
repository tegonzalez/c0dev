# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
import unittest
from c0_fixture import Fixture


class Lifecycle(unittest.TestCase):
    def setUp(self): self.f = Fixture()
    def tearDown(self): self.f.close()

    def test_stop_removes_runtime_then_start_uses_current_image_and_attaches(self):
        state = self.f.read()
        current = 'sha256:' + '2' * 64
        self.f.write(state)
        self.f.publish_runtime(current, build='c' * 64)
        stopped = self.f.run('stop')
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        self.assertIn('Stopped', stopped.stdout)
        self.assertEqual(self.f.read()['containers'], [])
        started = self.f.run('start')
        self.assertEqual(started.returncode, 0, started.stderr)
        self.assertNotIn('Already running', started.stdout)
        self.assertIn('Security: ', started.stdout)
        self.assertEqual(self.f.read()['containers'][0]['image'], current)
        self.assertNotEqual(self.f.read()['containers'][0]['id'], 'oneoff-runtime')
        attached = self.f.run('sh')
        self.assertEqual(attached.returncode, 0, attached.stderr)
        calls = self.f.read()['calls']
        self.assertIn(['stop', 'oneoff-runtime'], calls)
        self.assertIn(['rm', 'oneoff-runtime'], calls)
        self.assertTrue(any(c[0] == 'compose' and 'run' in c for c in calls))
        self.assertTrue(any(c[0] == 'exec' and 'new-runtime' in c and 'bash' in c for c in calls))
        self.assertFalse(any(c[0] == 'start' for c in calls))
        self.assertFalse(any(c[0] == 'rm' and ('-v' in c or '--volumes' in c) for c in calls))

    def test_stop_verifies_state_and_removal_and_propagates_failures(self):
        for option in ('ignore_stop', 'fail_ps_after_stop', 'stop_failure', 'ignore_rm', 'rm_failure'):
            with self.subTest(option=option):
                state = self.f.read()
                state.update(ignore_stop=False, fail_ps_after_stop=False, ignore_rm=False, fail={})
                state['containers'] = [self.f.container()]
                if option.endswith('_failure'): state['fail'] = {option[:-8]: 27}
                else: state[option] = True
                self.f.write(state)
                result = self.f.run('stop')
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('✅ Stopped', result.stdout)

    def test_discovery_errors_and_duplicates_do_not_create_or_attach(self):
        for option in ('duplicates', 'docker_failure'):
            state = self.f.read()
            if option == 'duplicates': state['containers'].append(self.f.container('other-runtime', oneoff=False))
            else: state['containers'] = [state['containers'][0]]; state['fail'] = dict(ps=23)
            state['calls'] = []
            self.f.write(state)
            for command in ('start', 'sh'):
                result = self.f.run(command)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertNotIn('Already running', result.stdout)
            self.assertFalse(any(c[0] in ('exec', 'start', 'compose') for c in self.f.read()['calls']))

    def test_stop_refuses_ambiguous_primaries_before_mutation(self):
        state = self.f.read()
        state['containers'].append(self.f.container('duplicate'))
        self.f.write(state)
        result = self.f.run('stop')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(c[0] in ('stop', 'rm', 'compose') for c in self.f.read()['calls']))
        self.assertEqual(len(self.f.read()['containers']), 2)

    def test_stop_removes_workspace_builds_without_touching_other_workspaces_or_modes(self):
        state = self.f.read()
        another_build = self.f.container('other-build')
        another_build['instance'] = self.f.instance + '-another-build'
        another_build['labels'] = {'c0dev.workspace': self.f.workspace,
                                   'c0dev.mode': 'prod', 'c0dev.build': 'b' * 64}
        other_mode = self.f.container('other-mode')
        other_mode['instance'] = 'c0dev-dev-another-workspace'
        other_mode['labels'] = {'c0dev.workspace': 'c0dev-dev-another-workspace',
                                'c0dev.mode': 'dev', 'c0dev.build': 'b' * 64}
        other_folder = self.f.container('other-folder')
        other_folder['instance'] = 'another-folder'
        other_folder['labels'] = {'c0dev.workspace': 'another-folder',
                                  'c0dev.mode': 'prod', 'c0dev.build': 'b' * 64}
        state['containers'] += [another_build, other_mode, other_folder]
        self.f.write(state)
        result = self.f.run('stop')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.f.read()['containers'], [other_mode, other_folder])
        self.assertFalse(any(call[0] == 'rm' and '-v' in call
                             for call in self.f.read()['calls']))
        self.assertFalse((self.f.checkout / '.local/c0').exists())

    def test_stop_does_not_remove_unrelated_container(self):
        state = self.f.read()
        unrelated = self.f.container('unrelated')
        unrelated['instance'] = 'another-checkout'
        state['containers'].append(unrelated)
        self.f.write(state)
        result = self.f.run('stop')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.f.read()['containers'], [unrelated])

    def test_repeated_restart_is_stop_then_start_with_new_containers_and_persistent_data(self):
        state = self.f.read()
        volume = self.f.instance + '-home-overlays'
        persisted = {'upper/local/staged-note': 'keep staged tools', 'launcher/upper/note': 'keep launcher'}
        state['volumes'] = {volume: dict(Labels={}, data=persisted)}
        self.f.write(state)
        previous = 'oneoff-runtime'
        seen = {previous}
        for _ in range(3):
            result = self.f.run('restart')
            self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
            state = self.f.read()
            self.assertEqual(len(state['containers']), 1)
            current = state['containers'][0]['id']
            self.assertNotIn(current, seen)
            seen.add(current)
            changes = [call for call in state['calls'] if call[0] in
                       ('stop', 'start', 'rm', 'rename', 'commit', 'export', 'import', 'create', 'compose')]
            self.assertEqual(changes[-3][:2], ['stop', previous])
            self.assertEqual(changes[-2], ['rm', previous])
            self.assertEqual(changes[-1][0], 'compose')
            self.assertIn('run', changes[-1])
            self.assertEqual(state['volumes'][volume]['data'], persisted)
            previous = current

    def test_noncanonical_volume_survives_stop_start_and_repeated_restart(self):
        state = self.f.read()
        generation = 'd' * 32
        canonical = self.f.instance + '-home-overlays'
        volume = canonical + '-' + generation
        persisted = {'upper/local/staged-note': 'keep tools',
                     'launcher/upper/note': 'keep launcher'}
        state['volumes'] = {
            volume: dict(Labels={'c0dev.instance': self.f.instance,
                                 'c0dev.overlay_generation': generation,
                                 'c0dev.overlay_source': canonical}, data=persisted),
            canonical: dict(Labels={}, data={'canonical-only': 'untouched'}),
        }
        mount = next(m for m in state['containers'][0]['mounts']
                     if m['target'] == '/run/c0/overlay-state')
        mount.update(name=volume, source='/var/lib/docker/volumes/' + volume + '/_data')
        # Docker's actual mount must win over an obsolete container label.
        state['containers'][0]['labels'] = {'c0dev.home_overlays_volume': canonical}
        self.f.write(state)
        previous = 'oneoff-runtime'
        for _ in range(3):
            self.assertEqual(self.f.run('stop').returncode, 0)
            self.assertEqual(self.f.read()['containers'], [])
            self.assertFalse((self.f.checkout / '.local/c0').exists())
            # This is internal storage selection, not a caller-controlled option.
            self.f.env['C0_HOME_OVERLAYS_VOLUME'] = canonical
            started = self.f.run('start')
            self.assertEqual(started.returncode, 0, (started.stdout, started.stderr))
            state = self.f.read()
            current = state['containers'][0]
            self.assertNotEqual(current['id'], previous)
            mounted = next(m for m in current['mounts'] if m['target'] == '/run/c0/overlay-state')
            self.assertEqual(mounted['name'], volume)
            self.assertEqual(state['volumes'][volume]['data'], persisted)
            self.assertEqual(state['volumes'][canonical]['data'], {'canonical-only': 'untouched'})
            previous = current['id']

    def test_restart_stop_failure_does_not_start_or_create(self):
        state = self.f.read(); state['fail'] = dict(stop=27); self.f.write(state)
        result = self.f.run('restart')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('✅ Started', result.stdout)
        self.assertFalse(any(c[0] in ('start', 'compose', 'rm') for c in self.f.read()['calls']))

    def test_restart_start_failure_reports_failure_without_removing_persistent_data(self):
        state = self.f.read()
        volume = self.f.instance + '-home-overlays'
        state['volumes'] = {volume: dict(Labels={}, data={'upper/local/note': 'preserve me'})}
        state['compose_run_status'] = 27
        self.f.write(state)
        result = self.f.run('restart')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('✅ Started', result.stdout)
        state = self.f.read()
        self.assertEqual(state['containers'], [])
        self.assertEqual(state['volumes'][volume]['data'], {'upper/local/note': 'preserve me'})

    def test_obsolete_command_and_option_are_not_exposed(self):
        removed = self.f.run('recover')
        self.assertIn('Usage: c0', removed.stdout)
        self.assertNotIn('recover NAME', removed.stdout)
        self.assertNotEqual(self.f.run('start', '--fresh-image').returncode, 0)
        help_result = self.f.run('help')
        self.assertNotIn('recover NAME', help_result.stdout)
        self.assertNotIn('--fresh-image', help_result.stdout)

    def test_retained_backup_does_not_block_intentional_fresh_start(self):
        state = self.f.read()
        cid = 'a' * 64
        backup = self.f.container(cid)
        backup.update(name=f'c0-recovery-{self.f.instance}-{cid}', state='exited',
                      rootfs={'/home/dev/note': 'backup data'})
        state['containers'] = [backup]
        self.f.write(state)
        result = self.f.run('start')
        self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
        state = self.f.read()
        self.assertEqual(next(c for c in state['containers'] if c['id'] == cid), backup)
        self.assertEqual(len(state['containers']), 2)
        self.assertFalse(any(c[0] in ('start', 'stop', 'rm', 'rename') and cid in c for c in state['calls']))

    def test_restart_leaves_retained_backup_untouched(self):
        state = self.f.read()
        cid = 'a' * 64
        backup = self.f.container(cid)
        backup.update(name=f'c0-recovery-{self.f.instance}-{cid}', state='exited',
                      rootfs={'/home/dev/note': 'backup data'})
        state['containers'].append(backup)
        self.f.write(state)
        result = self.f.run('restart')
        self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
        state = self.f.read()
        self.assertEqual(next(c for c in state['containers'] if c['id'] == cid), backup)
        self.assertFalse(any(c[0] in ('start', 'stop', 'rm', 'rename') and cid in c for c in state['calls']))

    def test_start_does_not_report_success_after_exit_or_empty_creation(self):
        state = self.f.read(); state['containers'][0]['state'] = 'exited'; state['started_state'] = 'exited'; self.f.write(state)
        result = self.f.run('start')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('✅ Started', result.stdout)
        state = self.f.read(); state['containers'] = []; state['compose_up_empty'] = True; self.f.write(state)
        result = self.f.run('start')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('✅ Started', result.stdout)


if __name__ == '__main__': unittest.main()
