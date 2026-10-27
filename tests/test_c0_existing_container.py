# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Exercise existing-container commands through the actual CLI."""
import json
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
            self.assertIn('TEST_TOKEN=value with spaces', call)
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
        for security in ('permissive', 'cap-drop-all'):
            state = self.f.read(); state['containers'] = []; state['calls'] = []; self.f.write(state)
            self.f.env['C0_SECURITY'] = security
            result = self.f.run('start')
            self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
            calls = self.f.read()['calls']
            self.assertTrue(any(c[0] == 'compose' and any('security-'+security+'.yaml' in a for a in c) for c in calls))

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
        self.assertIn('/bin/bash -lc ', args[-1])
        # Decode the quoting OpenSSH passes to the remote user's shell.
        import shlex
        remote = shlex.split(args[-1])
        self.assertEqual(remote[:2], ['/bin/bash', '-lc'])
        self.assertEqual(remote[2], 'cd /home/dev/projects/project\\ with\\ spaces && id -u && pwd')
        calls = self.f.read()['calls']
        self.assertFalse(any(c[0] in ('run', 'compose', 'start') for c in calls))

    def test_ssh_attach_propagates_ssh_failure(self):
        self.f.env['TEST_SSH_STATUS'] = '27'
        result = self.f.run('ssh', 'id -u')
        self.assertEqual(result.returncode, 27, result.stderr)


if __name__ == '__main__': unittest.main()
