# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Exercise existing-container commands through the actual CLI."""
import json
import hashlib
import unittest
from c0_fixture import Fixture


class ExistingContainer(unittest.TestCase):
    def setUp(self): self.f = Fixture()
    def tearDown(self): self.f.close()

    def test_shell_and_root_attach_preserve_user_auth_umask_and_project(self):
        (self.f.checkout/'auth/.env').write_text("export TEST_TOKEN='value with spaces'\n")
        project = self.f.checkout/'projects/project with spaces'; project.mkdir()
        for command, user in (('sh', '1000'), ('root', '0')):
            result = self.f.run(command, cwd=str(project))
            self.assertEqual(result.returncode, 0, result.stderr)
            call = [c for c in self.f.read()['calls'] if c[0] == 'exec'][-1]
            self.assertEqual(call[call.index('-u')+1], user)
            self.assertNotIn('TEST_TOKEN=value with spaces', call)
            self.assertEqual(self.f.read()['exec_env_sha256']['TEST_TOKEN'],
                             hashlib.sha256(b'value with spaces').hexdigest())
            self.assertIn('umask ', call[-1])
            self.assertIn('project\\ with\\ spaces', call[-1])
            self.assertIn('oneoff-runtime', call)

    def test_unrecognized_label_alone_does_not_block_attach(self):
        result = self.f.run('sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any('security_mode' in ' '.join(c) for c in self.f.read()['calls']))

    def test_logs_stop_and_terminfo_do_not_resolve_creation_policy(self):
        self.f.env['C0_SECURITY'] = 'seccomp'
        for command in ('logs', 'cp-term', 'stop'):
            result = self.f.run(command)
            self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.f.read()['calls']
        self.assertFalse(any(c[0] == 'compose' for c in calls))
        self.assertFalse(any('security_mode' in ' '.join(c) for c in calls))
        self.assertIn(['logs', '-f', 'oneoff-runtime'], calls)

    def test_creation_still_rejects_unsupported_policy_before_compose(self):
        state = self.f.read(); state['containers'] = []; self.f.write(state)
        self.f.env['C0_SECURITY'] = 'seccomp'
        result = self.f.run('start')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("got: 'seccomp'", result.stderr)
        self.assertFalse(any(c[0] == 'compose' for c in self.f.read()['calls']))

    def test_creation_still_applies_supported_policy(self):
        for security in ('guest-admin', 'least-privilege'):
            state = self.f.read(); state['containers'] = []; state['calls'] = []; self.f.write(state)
            self.f.env['C0_SECURITY'] = security
            result = self.f.run('start')
            self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
            calls = self.f.read()['calls']
            self.assertTrue(any(c[0] == 'compose' and any('security-'+security+'.yaml' in a for a in c) for c in calls))

    def test_legacy_attach_remains_usable_without_a_published_image(self):
        state = self.f.read()
        state['images'] = {}
        self.f.write(state)
        result = self.f.run('sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('oneoff-runtime', self.f.read()['calls'][-1])
        self.assertFalse((self.f.checkout / '.local/c0').exists())

    def test_fresh_creation_requires_a_published_docker_artifact(self):
        state = self.f.read()
        state['images'] = {}
        state['containers'] = []
        self.f.write(state)
        result = self.f.run('start')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("run 'c0 build'", result.stderr)
        self.assertFalse(any(call[0] in ('run', 'compose') for call in self.f.read()['calls']))
        self.assertFalse((self.f.checkout / '.local/c0').exists())

    def test_attach_propagates_docker_failure(self):
        state = self.f.read(); state['shell_status'] = 27; self.f.write(state)
        result = self.f.run('sh')
        self.assertEqual(result.returncode, 27, result.stderr)

    def test_ssh_attach_preserves_dev_user_project_and_remote_command(self):
        project = self.f.checkout/'projects/project with spaces'; project.mkdir()
        result = self.f.run('ssh', 'id -u && pwd', cwd=str(project))
        self.assertEqual(result.returncode, 0, result.stderr)
        args = json.loads((self.f.root/'ssh-args.json').read_text())
        self.assertEqual(args[args.index('-p')+1], '2223')
        self.assertIn('dev@127.0.0.1', args)
        # Decode the quoting OpenSSH passes to the remote user's shell.
        import shlex
        remote = shlex.split(args[-1])
        self.assertEqual(remote[-3:-1], ['/bin/bash', '-lc'])
        self.assertEqual(remote[-1], 'cd /home/dev/projects/project\\ with\\ spaces && id -u && pwd')
        calls = self.f.read()['calls']
        self.assertFalse(any(c[0] in ('run', 'compose', 'start') for c in calls))

    def test_ssh_attach_propagates_ssh_failure(self):
        self.f.env['TEST_SSH_STATUS'] = '27'
        result = self.f.run('ssh', 'id -u')
        self.assertEqual(result.returncode, 27, result.stderr)

    def test_retained_runtime_commands_reconcile_management_authorization_without_recreation(self):
        ssh = self.f.checkout / 'auth/ssh'
        client = self.f.checkout / 'auth/ssh-client'
        active = (client / 'id_ed25519.pub').read_bytes()
        private = (client / 'id_ed25519').read_bytes()
        server = (ssh / 'ssh_host_ed25519_key').read_bytes()
        retained = b'# retained guest entry\n'+(ssh / 'ssh_host_ed25519_key.pub').read_bytes()
        original_containers = self.f.read()['containers']
        for command, arguments in (('ssh', ('id -u',)), ('start', ())):
            with self.subTest(command=command):
                (ssh / 'authorized_keys').write_bytes(retained)
                state = self.f.read(); state['calls'] = []; self.f.write(state)
                result = self.f.run(command, *arguments)
                self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
                self.assertIn(active.strip(), (ssh / 'authorized_keys').read_bytes().splitlines(),
                              'retained runtime command skipped management key reconciliation')
                self.assertIn(retained, (ssh / 'authorized_keys').read_bytes())
                self.assertTrue((client / 'id_ed25519').read_bytes() == private)
                self.assertTrue((ssh / 'ssh_host_ed25519_key').read_bytes() == server)
                current = self.f.read()
                self.assertEqual(current['containers'], original_containers)
                self.assertFalse(any(c[0] in ('compose', 'start', 'stop', 'rm')
                                     for c in current['calls']))
                # Existing start also checks home overlays through short-lived
                # helpers in the selected runtime's PID namespace.
                for call in (c for c in current['calls'] if c[0] == 'run'):
                    self.assertIn('--pid=container:oneoff-runtime', call)
                    self.assertIn('--rm', call)
                if command == 'start':
                    self.assertIn('Already running:', result.stdout,
                                  'retained start returned without its operator status')


if __name__ == '__main__': unittest.main()
