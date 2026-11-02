# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Construction inputs and desired mappings do not redefine a retained guest.

The real CLI runs against Fixture's synthetic Docker metadata. These cases prove
selection, refusal, and preservation decisions, not native mount/kernel behavior.
"""
import copy
import hashlib
import subprocess
import unittest

from c0_fixture import Fixture


class RuntimeInputChanges(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()

    def tearDown(self):
        self.f.close()

    def modern_guest(self, status='running'):
        state = self.f.read()
        guest = state['containers'][0]
        keyed = 'c0dev-' + hashlib.sha256(
            (':' + self.f.build + ':' + str(self.f.checkout)).encode()
        ).hexdigest()[:8]
        guest.update(instance=keyed, name=keyed + '-c0dev-retained', state=status,
                     image='sha256:' + '1' * 64)
        guest['labels'] = {
            'c0dev.workspace': self.f.workspace,
            'c0dev.build': self.f.build,
            'c0dev.recipe': self.f.recipe,
            'c0dev.mode': 'prod',
        }
        overlay = self.f.workspace + '-home-overlays'
        state['volumes'][overlay]['data'] = {'upper/.local/retained': 'keep'}
        state['volumes']['c0dev-tools-shared']['data'] = {'opt/retained': 'keep'}
        self.f.write(state)
        return state

    def assert_no_construction_or_replacement(self, before, command):
        after = self.f.read()
        self.assertEqual(after['volumes'], before['volumes'])
        self.assertEqual(after.get('creations', 0), 0)
        self.assertFalse(any(call[0] in ('build', 'commit', 'import', 'export', 'create')
                             or call[0] == 'compose'
                             for call in after['calls']), after['calls'])
        if command != 'stop':
            self.assertEqual(len(after['containers']), 1)
            for key in ('id', 'instance', 'image', 'tools', 'mounts'):
                self.assertEqual(after['containers'][0][key], before['containers'][0][key], key)
            self.assertFalse(any(call[0] in ('rm', 'rename') for call in after['calls']))

    def test_modern_running_guest_survives_real_recipe_edit_for_all_retained_commands(self):
        before = self.modern_guest()
        recipe = self.f.checkout / 'docker/Dockerfile.runtime'
        recipe.write_text(recipe.read_text() + '\nLABEL c0dev.input_change=runtime\n')
        # The retained guest must remain usable even after publication disappears.
        before['images'] = {}
        for command in ('sh', 'root', 'start', 'logs', 'stop'):
            with self.subTest(command=command):
                self.f.write(copy.deepcopy(before))
                result = self.f.run(command)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assert_no_construction_or_replacement(before, command)
                calls = self.f.read()['calls']
                if command in ('sh', 'root'):
                    self.assertTrue(any(call[0] == 'exec' and 'oneoff-runtime' in call
                                        for call in calls))
                elif command == 'logs':
                    self.assertIn(['logs', '-f', 'oneoff-runtime'], calls)
                elif command == 'stop':
                    self.assertTrue(any(call[0] == 'stop' and 'oneoff-runtime' in call
                                        for call in calls))

    def test_modern_stopped_guest_resumes_same_identity_after_tools_recipe_edit(self):
        before = self.modern_guest('exited')
        recipe = self.f.checkout / 'docker/Dockerfile.tools'
        recipe.write_text(recipe.read_text() + '\nLABEL c0dev.input_change=tools\n')
        result = self.f.run('start')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_no_construction_or_replacement(before, 'start')
        self.assertEqual(self.f.read()['containers'][0]['state'], 'running')
        self.assertIn(['start', 'oneoff-runtime'], self.f.read()['calls'])

    def test_retained_guest_needs_no_draft_dockerfile_for_lifecycle_commands(self):
        before = self.modern_guest()
        before['images'] = {}
        for name in ('Dockerfile.base', 'Dockerfile.tools', 'Dockerfile.runtime'):
            path = self.f.checkout / 'docker' / name
            original = path.read_bytes()
            try:
                path.unlink()
                for command in ('sh', 'root', 'start', 'stop'):
                    with self.subTest(missing=name, command=command):
                        self.f.write(copy.deepcopy(before))
                        result = self.f.run(command)
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assert_no_construction_or_replacement(before, command)
                        self.assertFalse(path.exists())
            finally:
                path.write_bytes(original)

    def test_older_guest_retains_external_operator_mounts_without_new_assistant_roster(self):
        # No modern workspace/build labels or saved creation manifest: actual
        # Docker mounts still describe the operator's retained configuration.
        before = self.f.read()
        guest = before['containers'][0]
        guest['image'] = 'sha256:' + '1' * 64
        guest['mounts'] = [m for m in guest['mounts']
                           if m['target'] != '/home/dev/.kimi-code']
        sources = []
        for target, readonly in (('/home/dev/.cache', False), ('/home/dev/.config', True)):
            source = self.f.root / ('operator-' + target.rsplit('/', 1)[-1].lstrip('.'))
            source.mkdir()
            (source / 'retained').write_text('keep')
            sources.append(source)
            mount = next(m for m in guest['mounts'] if m['target'] == target)
            mount.update(source=str(source), rw=not readonly)
        folders = self.f.checkout / 'docker/volumes-folders.yaml'
        folders.write_text(folders.read_text().replace('  volumes:\n',
            '  volumes:\n    - ../new-missing-mnt:/mnt\n', 1))
        for command in ('sh', 'root', 'start', 'stop'):
            with self.subTest(command=command):
                self.f.write(copy.deepcopy(before))
                result = self.f.run(command)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assert_no_construction_or_replacement(before, command)
                for source in sources:
                    self.assertEqual((source / 'retained').read_text(), 'keep')
                self.assertFalse((self.f.checkout / 'new-missing-mnt').exists())

    def two_completed_publications(self):
        state = self.f.read()
        state['containers'] = []
        first = copy.deepcopy(state['images'][self.f.runtime_ref])
        second = copy.deepcopy(first)
        second['id'] = 'sha256:' + '2' * 64
        second['Config']['Labels'].update({
            'c0dev.recipe': 'b' * 64, 'c0dev.build': 'c' * 64,
            'c0dev.tools_hash': 'd' * 64, 'c0dev.base_image': 'c0dev-base-prod:' + 'c' * 64,
        })
        state['images']['c0dev-runtime-prod:current'] = second
        state['images']['c0dev-runtime-prod:recipe-' + 'b' * 64] = second
        # A differently named staging image must not displace either publication.
        staging = copy.deepcopy(second)
        staging['id'] = 'sha256:' + '3' * 64
        staging['Created'] = '2099-01-01T00:00:00Z'
        state['images']['c0dev-runtime-prod-build:unpublished'] = staging
        return state, first, second

    def test_fresh_creation_prefers_exact_recipe_to_another_current_publication(self):
        before, first, _ = self.two_completed_publications()
        self.f.write(before)
        result = self.f.run('start')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        after = self.f.read()
        self.assertEqual(len(after['containers']), 1)
        self.assertEqual(after['containers'][0]['image'], first['id'])
        self.assertEqual(after['containers'][0]['labels']['c0dev.build'], self.f.build)
        self.assertEqual(after['images'], before['images'])
        self.assertEqual(after.get('creations'), 1)
        self.assertFalse(any(call[0] in ('build', 'commit', 'import', 'create')
                             or call[0] == 'compose' and 'build' in call
                             for call in after['calls']))

    def test_edited_source_without_exact_recipe_can_create_explicit_current_publication(self):
        before, _, second = self.two_completed_publications()
        path = self.f.checkout / 'docker/Dockerfile.runtime'
        path.write_text(path.read_text() + '\nLABEL c0dev.input_change=draft\n')
        self.f.write(before)
        result = self.f.run('start')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        after = self.f.read()
        self.assertEqual(len(after['containers']), 1)
        self.assertEqual(after['containers'][0]['image'], second['id'])
        self.assertEqual(after['containers'][0]['labels']['c0dev.build'], 'c' * 64)
        self.assertEqual(after['images'], before['images'])
        self.assertEqual(after.get('creations'), 1)
        self.assertFalse(any(call[0] in ('build', 'commit', 'import', 'create')
                             or call[0] == 'compose' and 'build' in call
                             for call in after['calls']))

    def test_unpublished_inventory_is_not_enumerated_as_completed_recipe_publications(self):
        # Fixture does not implement Docker's reference-filter semantics. This
        # observes the filter requested and refusal with no publication; mixed
        # staging/completed inventory behavior remains a native-Docker check.
        before = self.f.read()
        before.update(containers=[], images={})
        self.f.write(before)
        result = self.f.run('start')
        self.assertNotEqual(result.returncode, 0)
        calls = self.f.read()['calls']
        listings = [call for call in calls if call[:2] == ['image', 'ls']]
        self.assertTrue(listings, calls)
        for call in listings:
            self.assertIn('reference=c0dev-runtime-prod:recipe-*', call)
            self.assertNotIn('--sort', call)
        self.assertFalse(any(call[0] in ('create', 'run', 'compose') for call in calls))

    def test_changed_desired_custom_mappings_do_not_rewrite_retained_mounts(self):
        folders = self.f.checkout / 'docker/volumes-folders.yaml'
        original = folders.read_text()
        old_source = self.f.checkout / 'old-mnt'
        old_source.mkdir()
        (old_source / 'retained').write_text('keep')
        initial = self.modern_guest()
        for change in ('added-missing', 'removed', 'repointed-missing'):
            with self.subTest(change=change):
                self.f.write(copy.deepcopy(initial))
                before = self.modern_guest()
                if change != 'added-missing':
                    before['containers'][0]['mounts'].append(dict(
                        type='bind', source=str(old_source), target='/mnt', rw=True))
                desired = original
                if change != 'removed':
                    desired = desired.replace('  volumes:\n',
                        '  volumes:\n    - ../new-missing-mnt:/mnt\n', 1)
                folders.write_text(desired)
                for command in ('sh', 'root', 'start', 'logs', 'stop'):
                    with self.subTest(command=command):
                        self.f.write(copy.deepcopy(before))
                        result = self.f.run(command)
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assert_no_construction_or_replacement(before, command)
                        self.assertEqual((old_source / 'retained').read_text(), 'keep')
                        self.assertFalse((self.f.checkout / 'new-missing-mnt').exists())

    def test_retained_control_mount_violations_still_refuse_before_guest_execution(self):
        baseline = self.modern_guest()
        cases = ('foreign-control-source', 'writable-control', 'wrong-tools-subpath',
                 'duplicate-target', 'docker-socket')
        for issue in cases:
            for command in ('sh', 'root', 'start'):
                with self.subTest(issue=issue, command=command):
                    before = copy.deepcopy(baseline)
                    guest = before['containers'][0]
                    mounts = guest['mounts']
                    control = next(m for m in mounts if m['target'] == '/run/c0/host-bin')
                    if issue == 'foreign-control-source':
                        other = self.f.root / 'foreign-bin'
                        other.mkdir(exist_ok=True)
                        control['source'] = str(other)
                    elif issue == 'writable-control':
                        control['rw'] = True
                    elif issue == 'wrong-tools-subpath':
                        guest['subpath'] = 'opt/' + 'f' * 64
                    elif issue == 'duplicate-target':
                        mounts.append(dict(control))
                    else:
                        mounts.append(dict(type='bind', source='/var/run/docker.sock',
                                           target='/var/run/docker.sock', rw=True))
                    self.f.write(before)
                    result = self.f.run(command)
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    expected = {'foreign-control-source': '/run/c0/host-bin',
                                'writable-control': '/run/c0/host-bin',
                                'wrong-tools-subpath': 'subpath',
                                'duplicate-target': 'duplicate',
                                'docker-socket': 'docker.sock'}[issue]
                    self.assertIn(expected, result.stderr)
                    after = self.f.read()
                    self.assertEqual(after['containers'], before['containers'])
                    self.assertEqual(after['volumes'], before['volumes'])
                    self.assertFalse(any(call[0] in ('exec', 'run', 'compose', 'start', 'rm')
                                         for call in after['calls']), after['calls'])

    def test_custom_mount_source_aliases_cannot_expose_protected_host_inputs(self):
        baseline = self.modern_guest()
        # All paths and file contents below belong to this disposable fixture.
        # Source classification must inspect metadata, never credential contents.
        synthetic_env = self.f.checkout / 'auth/.env'
        synthetic_env.write_text('C0_SYNTHETIC_VERIFICATION=1\n')
        bin_alias = self.f.root / 'bin-alias'
        bin_alias.symlink_to(self.f.checkout / 'bin', target_is_directory=True)
        cases = (
            ('launcher', self.f.checkout / 'bin', True),
            ('checkout-parent', self.f.checkout, True),
            ('control-file', self.f.checkout / 'docker/c0-overlay-check', True),
            ('launcher-symlink', bin_alias, True),
            ('gitconfig', self.f.home / '.gitconfig', True),
            ('private-client', self.f.checkout / 'auth/ssh-client', False),
            ('private-parent', self.f.checkout / 'auth', False),
            ('synthetic-env', synthetic_env, False),
        )
        for issue, source, writable in cases:
            for command in ('sh', 'start'):
                with self.subTest(issue=issue, command=command):
                    before = copy.deepcopy(baseline)
                    before['containers'][0]['mounts'].append(dict(
                        type='bind', source=str(source), target='/mnt/source-alias',
                        rw=writable))
                    self.f.write(before)
                    result = self.f.run(command)
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn('/mnt/source-alias', result.stderr)
                    after = self.f.read()
                    self.assertEqual(after['containers'], before['containers'])
                    self.assertEqual(after['volumes'], before['volumes'])
                    self.assertFalse(any(call[0] in ('exec', 'run', 'compose', 'start', 'rm')
                                         for call in after['calls']), after['calls'])

    def identities(self):
        result = subprocess.run(['/bin/bash', '-c', '''
source "$TEST_C0" help >/dev/null
printf '%s\n%s\n' "$C0_RECIPE_ID" "$TOOLS_RECIPE_ID"
'''], env=dict(self.f.env, TEST_C0=str(self.f.checkout / 'bin/c0')),
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        runtime, tools = result.stdout.splitlines()
        return runtime, tools

    def test_runtime_configuration_and_unconsumed_files_never_change_build_identity(self):
        baseline = self.identities()
        for relative in ('docker/volumes-folders.yaml', 'docker/volumes-files.yaml',
                         'docker/docker-compose.public.yaml',
                         'docker/docker-compose.security-guest-admin.yaml',
                         'docker/docker-compose.security-least-privilege.yaml',
                         'docker/home-overlays.conf', 'docker/c0-overlay-check'):
            with self.subTest(input=relative):
                path = self.f.checkout / relative
                original = path.read_bytes()
                if relative.endswith('volumes-folders.yaml'):
                    changed = original.replace(b'  volumes:\n',
                        b'  volumes:\n    - ../new-uncreated:/mnt\n', 1)
                elif relative.endswith('volumes-files.yaml'):
                    changed = original.replace(b'  volumes:\n',
                        b'  volumes:\n    - ../new-uncreated-file:/home/dev/custom-file:ro\n', 1)
                elif relative.endswith('.yaml'):
                    changed = original + b'\nx-runtime-input-change: true\n'
                elif relative.endswith('.conf'):
                    changed = original + b'custom-home|custom-tools\n'
                else:
                    changed = original + b'\nprintf "runtime-only input changed\\n"\n'
                try:
                    path.write_bytes(changed)
                    self.assertEqual(self.identities(), baseline)
                finally:
                    path.write_bytes(original)
        (self.f.checkout / 'docker/unconsumed-input').write_text('unrelated\n')
        (self.f.checkout / 'docker/Dockerfile.unused').write_text('FROM synthetic-unused\n')
        self.assertEqual(self.identities(), baseline)

    def test_actual_runtime_copied_bytes_change_runtime_but_not_tools_identity(self):
        baseline = self.identities()
        for relative in ('docker/1password.asc', 'docker/cloud.google.gpg',
                         'docker/install-orca.sh', 'docker/docker-entrypoint.sh'):
            with self.subTest(input=relative):
                path = self.f.checkout / relative
                original = path.read_bytes()
                try:
                    path.write_bytes(original + b'\n# synthetic changed copied bytes\n')
                    changed = self.identities()
                    self.assertNotEqual(changed[0], baseline[0])
                    self.assertEqual(changed[1], baseline[1])
                finally:
                    path.write_bytes(original)
        path = self.f.checkout / 'docker/Dockerfile.runtime'
        path.write_text(path.read_text() + '\nLABEL c0dev.input_change=runtime\n')
        changed = self.identities()
        self.assertNotEqual(changed[0], baseline[0])
        self.assertEqual(changed[1], baseline[1])

    def test_tools_and_base_construction_changes_also_invalidate_runtime_dependency(self):
        baseline = self.identities()
        for relative in ('docker/Dockerfile.tools', 'docker/Dockerfile.base',
                         'docker/c0-security.py'):
            with self.subTest(input=relative):
                path = self.f.checkout / relative
                original = path.read_bytes()
                suffix = (b'\n# synthetic changed copied helper bytes\n' if relative.endswith('.py')
                          else b'\nLABEL c0dev.input_change=construction\n')
                try:
                    path.write_bytes(original + suffix)
                    changed = self.identities()
                    self.assertNotEqual(changed[0], baseline[0])
                    self.assertNotEqual(changed[1], baseline[1])
                finally:
                    path.write_bytes(original)
                self.assertEqual(self.identities(), baseline)


if __name__ == '__main__':
    unittest.main()
