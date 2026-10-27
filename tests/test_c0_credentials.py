# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Synthetic credential transport regressions; no daemon, SSH service, or live auth.

Oracles: docs/spec.md#attachments,#containment,#private-data, docs/constraints.md,
plus the 2026-10-25 request to remove argv secrets, preserve guest environments,
prevent auth overriding host controls, and separate host client keys from guests.
Peers execute the production guest bootstrap locally, with a fresh guest environ;
they establish transport composition, not Docker/OpenSSH/kernel isolation.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import select
import shlex
import shutil
import signal
import subprocess
import tempfile
import termios
import time
import unittest

ROOT = Path(os.environ.get('C0_CREDENTIAL_TEST_ROOT', Path(__file__).resolve().parents[1]))
PYTHON = '/usr/bin/python3'


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def definitions():
    source = (ROOT / 'bin/c0').read_text()
    functions = []
    for start in re.finditer(r'^\w+\(\) \{\n', source, re.M):
        for end in re.finditer(r'^\}', source[start.end():], re.M):
            candidate = source[start.start():start.end() + end.end()]
            parsed = subprocess.run(['/bin/bash', '-n'], input=candidate,
                                    capture_output=True, text=True, timeout=3)
            if parsed.returncode == 0:
                functions.append(candidate)
                break
        else:
            raise AssertionError('incomplete production function')
    return '\n'.join(functions)


# Never record raw transport argv or environ. A violating peer records only a
# boolean; even baseline RED cannot turn a transport leak into a fixture log.
PEER = r'''
import base64, hashlib, json, os, re, signal, stat, subprocess, sys
from pathlib import Path
args = sys.argv[1:]
kind = Path(sys.argv[0]).name
needle = b'fixture-secret-'
def contains_secret(value):
    raw = value.encode()
    if needle in raw:
        return True
    for token in re.findall(rb'[A-Za-z0-9_+/=-]{20,}', raw):
        try:
            if needle in base64.urlsafe_b64decode(token + b'=' * (-len(token) % 4)):
                return True
        except (ValueError, base64.binascii.Error):
            pass
    return False
trace = dict(kind=kind, argv_secret=any(contains_secret(a) for a in args),
             raw_auth_in_host=any(contains_secret(v) for k, v in os.environ.items()
                                  if not k.startswith('C0_SESSION_ENV')),
             host={k: hashlib.sha256(os.environ.get(k, '').encode()).hexdigest()
                   for k in ('C0ROOT', 'C0_RUNTIME_CID', 'C0_SSH_DIR',
                             'C0_SSH_CLIENT_DIR', 'DOCKER_HOST', 'PATH')},
             stdin_tty=os.isatty(0), stdout_tty=os.isatty(1))
guest = dict(PATH='/usr/bin:/bin', HOME=os.environ['TEST_GUEST_HOME'],
             LANG='C.UTF-8', TERM='guest-inherited-term')
if kind == 'docker':
    assert args[0] == 'exec', 'inert Docker peer accepts exec only'
    i = 1
    envfile = None
    while i < len(args):
        a = args[i]
        if a in ('-i', '-t', '--interactive', '--tty'):
            trace.setdefault('flags', []).append(a); i += 1
        elif a in ('-u', '--user'):
            trace['uid'] = args[i+1]; i += 2
        elif a in ('-e', '--env'):
            key, _, value = args[i+1].partition('=')
            guest[key] = value
            trace.setdefault('raw_env_names', []).append(key); i += 2
        elif a == '--env-file':
            envfile = args[i+1]; i += 2
        else:
            break
    trace['cid'] = args[i]
    command = args[i+1:]
    if envfile is not None:
        with open(envfile, 'rb') as source:
            trace['envfile_fifo'] = stat.S_ISFIFO(os.fstat(source.fileno()).st_mode)
            payload = source.read()
        lines = payload.splitlines()
        trace['max_envfile_line'] = max(map(len, lines), default=0)
        trace['envfile_bytes'] = len(payload)
        trace['envfile_raw_secret'] = needle in payload
        for line in lines:
            key, value = line.decode().split('=', 1)
            guest[key] = value
        trace['envfile_names'] = sorted(line.decode().split('=', 1)[0] for line in lines)
    else:
        trace['envfile_fifo'] = False
elif kind == 'ssh':
    trace['x11'] = '-Y' in args
    trace['tty_flag'] = '-t' in args or '-tt' in args
    trace['identity'] = hashlib.sha256(os.path.realpath(args[args.index('-i')+1]).encode()).hexdigest()
    trace['port'] = args[args.index('-p')+1]
    options = [args[i+1] for i, a in enumerate(args[:-1]) if a == '-o']
    trace['knownhosts'] = [hashlib.sha256(('UserKnownHostsFile='+os.path.realpath(a.split('=',1)[1])).encode()).hexdigest() for a in options if a.startswith('UserKnownHostsFile=')]
    trace['sendenv'] = [a[8:] for a in options if a.startswith('SendEnv=')]
    trace['quiet_env_logging'] = 'LogLevel=ERROR' in options
    trace['agent_disabled'] = 'IdentityAgent=none' in options
    trace['selected_identity_only'] = 'IdentitiesOnly=yes' in options
    trace['destination'] = args[-2]
    for name in trace['sendenv']:
        if name.endswith('*'):
            guest.update((k, v) for k, v in os.environ.items() if k.startswith(name[:-1]))
        elif name in os.environ:
            guest[name] = os.environ[name]
    # The remote script is authored by this test. Auth data must remain inside
    # the envelope and cannot be interpreted by this shell or the host peer.
    command = ['/bin/bash', '-c', args[-1]]
else:
    raise AssertionError('unknown inert peer')
Path(os.environ['TEST_TRACE']).write_text(json.dumps(trace))
if os.environ.get('TEST_PEER_WAIT'):
    signal.signal(signal.SIGTERM, lambda number, frame: sys.exit(128+number))
    Path(os.environ['TEST_TRACE']+'.ready').write_text('ready')
    signal.pause()
if os.environ.get('TEST_PEER_EXIT'):
    sys.exit(int(os.environ['TEST_PEER_EXIT']))
try:
    result = subprocess.run(command, env=guest)
    sys.exit(result.returncode if result.returncode >= 0 else 128-result.returncode)
except (OSError, ValueError):
    print('inert peer could not execute guest command', file=sys.stderr)
    sys.exit(90)
'''


class CredentialFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='c0-credentials-')
        self.addCleanup(self.temp.cleanup)
        self.root = (Path(self.temp.name) / 'checkout ; literal $ % ${HOME} " \\ space').resolve()
        self.bin = self.root / 'bin'
        self.bin.mkdir(parents=True)
        for name in ('c0-host-io', 'c0-credentials'):
            path = ROOT / 'bin' / name
            if path.exists():
                shutil.copy2(path, self.bin / name)
        (self.bin / 'c0-terminfo').write_text('#!/bin/sh\nexit 0\n')
        (self.bin / 'c0-terminfo').chmod(0o755)
        self.auth = self.root / 'auth/.env'
        self.auth.parent.mkdir()
        self.ssh = self.root / 'auth/ssh'
        self.client = self.root / 'auth/ssh-client'
        self.ssh.mkdir()
        self.client.mkdir(mode=0o700)
        self.home = self.root / 'guest home'
        self.project = self.home / 'projects/project ; $ literal'
        self.project.mkdir(parents=True)
        self.peer = self.root / 'inert peers'
        self.peer.mkdir()
        for name in ('docker', 'ssh'):
            path = self.peer / name
            path.write_text('#!' + PYTHON + '\n' + PEER)
            path.chmod(0o755)
        self.trace_path = self.root / 'transport.json'
        # Deliberately exclude ambient account credentials and loader variables.
        self.env = dict(PATH=str(self.peer)+':/usr/bin:/bin:/usr/sbin:/sbin',
                        HOME=str(self.home), LANG='C.UTF-8', TERM='fixture-term',
                        C0ROOT=str(self.root), C0_HOST_IO=str(self.bin / 'c0-host-io'),
                        C0_AUTH_ENV_FILE=str(self.auth), C0_SSH_DIR=str(self.ssh),
                        C0_SSH_CLIENT_DIR=str(self.client), C0_RUNTIME_CID='fixture-cid',
                        DOCKER_HOST='unix:///fixture-host-daemon.sock',
                        C0_INSTANCE_ID='fixture-instance', CONTAINER_DEV_HOME=str(self.home),
                        C0_SSH_AUTH_SOCK_PATH='/fixture/agent.sock',
                        TEST_GUEST_HOME=str(self.home), TEST_TRACE=str(self.trace_path),
                        PYTHONDONTWRITEBYTECODE='1', IN_CONTAINER='false')

    def auth_values(self, values):
        # Single-quoted literal input intentionally includes shell metacharacters.
        self.auth.write_text(''.join(k+"='"+v+"'\n" for k, v in values.items()))
        self.auth.chmod(0o600)

    def observer(self, names, status=0):
        path = self.root / 'observe guest ; literal.py'
        path.write_text('import hashlib,json,os,sys\n'
                        'names='+repr(list(names))+'\n'
                        'print(json.dumps(dict(values={k:hashlib.sha256(os.environ[k].encode()).hexdigest() '
                        'if k in os.environ else None for k in names},'
                        'internal=sorted(k for k in os.environ if k.startswith("C0_SESSION_ENV")),'
                        'stdin=hashlib.sha256(sys.stdin.buffer.read()).hexdigest(),'
                        'stdin_tty=os.isatty(0),stdout_tty=os.isatty(1),cwd=os.getcwd())))\n'
                        'sys.exit('+str(status)+')\n')
        return path

    def invoke(self, args, stdin='typed input\n', cwd=None, env=None):
        proc = subprocess.Popen(args, cwd=cwd or self.root, env=env or self.env,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            out, err = proc.communicate(stdin, timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            self.fail('credential operation blocked with inert peer')
        return subprocess.CompletedProcess(args, proc.returncode, out, err)

    def call_function(self, command, setup=''):
        script = self.root / 'exercise.sh'
        script.write_text('set -e\n'+definitions()+r'''
c0_require_container_running() { :; }
c0_validate_container_mounts() { :; }
c0_ssh_ensure_keys() { :; }
get_project_path() { printf '%s\n' 'project ; $ literal'; }
get_current_ssh_port() { printf '%s\n' 2223; }
print_web_port_mapping() { :; }
'''+setup+'\n'+command+'\n')
        return self.invoke(['/bin/bash', str(script)])

    def seed_inert_client(self):
        # The SSH peer does no authentication; this is deliberately not a key.
        (self.client / 'id_ed25519').write_text('inert fixture identity; not a private key\n')
        (self.client / 'id_ed25519').chmod(0o600)

    def wrapper(self, kind, *args):
        return [PYTHON, '-I', str(self.bin / 'c0-credentials'), str(self.root), kind,
                str(self.auth), *map(str, args)]

    def report(self, result):
        self.assertFalse('fixture-secret-' in result.stdout+result.stderr,
                         'credential value reached captured output')
        return json.loads(next(line for line in result.stdout.splitlines() if line.startswith('{')))

    def trace(self):
        return json.loads(self.trace_path.read_text())

    def assert_transport_private(self, trace):
        self.assertFalse(trace['argv_secret'], 'credential reached transport argv')
        self.assertFalse(trace['raw_auth_in_host'], 'raw auth reached host child environ')
        for name, actual in trace['host'].items():
            self.assertEqual(actual, digest(self.env.get(name, '')), name+' host control changed')

    def assert_values(self, report, expected, stdin='typed input\n'):
        self.assertEqual(report['values'], {k: digest(v) for k, v in expected.items()})
        self.assertEqual(report['internal'], [], 'transport envelope survived into guest program')
        self.assertEqual(report['stdin'], digest(stdin))

    def assert_no_transport_secret_files(self, values):
        for path in self.root.rglob('*'):
            if not path.is_file() or path == self.auth:
                continue
            data = path.read_bytes()
            for value in values:
                if len(value) >= 16:
                    self.assertFalse(value.encode() in data, 'secret-bearing transport file created')


class CredentialWrapper(CredentialFixture):
    def test_docker_literal_values_large_envelope_host_controls_and_stdin(self):
        expected = dict(AUTH_TOKEN='fixture-secret-dollar-$() `x`; | < > & ünicode ☃',
                        C0ROOT='/fixture-secret-wrong-root', PATH='/fixture-secret-wrong-path',
                        DOCKER_HOST='tcp://fixture-secret-wrong-host:2375',
                        C0_RUNTIME_CID='fixture-secret-wrong-cid',
                        EMPTY='', DUPLICATE='fixture-secret-last',
                        TRAILING_CR='fixture-secret-trailing-cr\r',
                        TRAILING_SPACE='fixture-secret-trailing-space ',
                        LITERAL_ESCAPE=r'fixture-secret-literal-\x00',
                        LARGE='fixture-secret-large-'+('abc123' * 18000),
                        DOUBLE='fixture-secret-double-" \\ $ ` \\q',
                        UNQUOTED='fixture-secret-unquoted:=+,./@%#-')
        self.auth_values({k: v for k, v in expected.items() if k not in ('DOUBLE', 'DUPLICATE', 'UNQUOTED')})
        with self.auth.open('a') as stream:
            stream.write('export DOUBLE="fixture-secret-double-\\" \\\\ \\$ \\` \\q"\n'
                         'DUPLICATE=fixture-secret-first\n'
                         "export DUPLICATE='fixture-secret-last'\n"
                         'UNQUOTED=fixture-secret-unquoted:=+,./@%#-\n'
                         'INVALID=fixture-secret-invalid;command\n'
                         'not-an-assignment fixture-secret-invalid-line\n')
        program = self.observer([*expected, 'INVALID'])
        result = self.invoke(self.wrapper('docker', 'fixture-cid', '1000', '0',
                                          'fixture-term', PYTHON, program))
        self.assertEqual(result.returncode, 0, 'credential operation returned unexpected status')
        report = self.report(result)
        invalid = report['values'].pop('INVALID')
        self.assertIsNone(invalid)
        self.assert_values(report, expected)
        trace = self.trace()
        self.assert_transport_private(trace)
        self.assertEqual(trace['cid'], 'fixture-cid')
        self.assertEqual(trace['uid'], '1000')
        self.assertIn('-i', trace['flags'])
        self.assertNotIn('-t', trace['flags'])
        self.assertTrue(trace['envfile_fifo'], 'Docker credential env-file must be an anonymous pipe')
        self.assertGreater(trace['envfile_bytes'], 65536)
        self.assertLessEqual(trace['max_envfile_line'], 65536)
        self.assertFalse(trace['envfile_raw_secret'])
        self.assertTrue(all(n.startswith('C0_SESSION_ENV') for n in trace['envfile_names']))
        self.assertTrue('warning:' in result.stderr, 'invalid auth lines need generic warnings')
        self.assert_no_transport_secret_files(expected.values())

    def test_docker_uid_term_tty_flags_and_guest_exit_status(self):
        values = dict(AUTH_TOKEN='fixture-secret-root-token')
        self.auth_values(values)
        program = self.observer([*values, 'TERM'], status=37)
        result = self.invoke(self.wrapper('docker', 'fixture-cid', '0', '1',
                                          'fixture-term', PYTHON, program))
        self.assertEqual(result.returncode, 37, 'credential operation returned unexpected status')
        self.assert_values(self.report(result), dict(values, TERM='fixture-term'))
        trace = self.trace()
        self.assert_transport_private(trace)
        self.assertEqual(trace['uid'], '0')
        self.assertIn('-t', trace['flags'])

    def test_ssh_private_sendenv_host_controls_remote_quoting_stdin_and_status(self):
        self.seed_inert_client()
        values = dict(AUTH_TOKEN='fixture-secret-ssh-$() ; " ünicode',
                      C0ROOT='/fixture-secret-wrong-root',
                      C0_SSH_DIR='/fixture-secret-wrong-key',
                      C0_SSH_CLIENT_DIR='/fixture-secret-wrong-client',
                      DOCKER_HOST='tcp://fixture-secret-wrong-host:2375',
                      EMPTY='', LARGE='fixture-secret-ssh-large-'+('abcdef' * 13000))
        self.auth_values(values)
        program = self.observer(values, status=41)
        remote = 'cd '+shlex.quote(str(self.project))+' && '+PYTHON+' '+shlex.quote(str(program))
        result = self.invoke(self.wrapper('ssh', self.client, '2223', '1', '0', remote))
        self.assertEqual(result.returncode, 41, 'credential operation returned unexpected status')
        report = self.report(result)
        self.assert_values(report, values)
        self.assertEqual(report['cwd'], str(self.project))
        trace = self.trace()
        self.assert_transport_private(trace)
        self.assertTrue(trace['x11'])
        self.assertFalse(trace['tty_flag'])
        self.assertEqual(trace['port'], '2223')
        self.assertEqual(trace['identity'], digest(str(self.client / 'id_ed25519')))
        self.assertEqual(trace['knownhosts'], [digest('UserKnownHostsFile='+str(self.client / 'known_hosts'))])
        self.assertEqual(trace['destination'], 'dev@127.0.0.1')
        self.assertTrue(trace['quiet_env_logging'])
        self.assertTrue(trace['agent_disabled'])
        self.assertTrue(trace['selected_identity_only'])
        self.assertTrue(trace['sendenv'])
        self.assertTrue(all(n.startswith('C0_SESSION_ENV') for n in trace['sendenv']))
        self.assert_no_transport_secret_files(values.values())

    def test_ssh_tty_preserves_terminal_descriptors_and_interactive_input(self):
        self.seed_inert_client()
        values = dict(AUTH_TOKEN='fixture-secret-tty-token')
        self.auth_values(values)
        observer = self.observer([*values, 'TERM'])
        remote = PYTHON+' '+shlex.quote(str(observer))
        master, slave = os.openpty()
        # Keep canonical terminal input but disable local echo, including macOS
        # ECHOCTL's ^D/backspace display, so it cannot prefix the guest report.
        attributes = termios.tcgetattr(slave)
        attributes[3] &= ~termios.ECHO
        termios.tcsetattr(slave, termios.TCSANOW, attributes)
        proc = subprocess.Popen(self.wrapper('ssh', self.client, '2223', '0', '1', remote),
                                cwd=self.root, env=self.env, stdin=slave, stdout=slave,
                                stderr=subprocess.PIPE, start_new_session=True)
        os.close(slave)
        output = bytearray()
        typed = 'interactive tty input\n'
        try:
            os.write(master, typed.encode()+b'\x04')
            deadline = time.monotonic()+5
            while time.monotonic() < deadline:
                readable, _, _ = select.select([master], [], [], 0.1)
                if readable:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    output.extend(chunk)
                elif proc.poll() is not None:
                    break
            _, err = proc.communicate(timeout=2)
            result = subprocess.CompletedProcess(proc.args, proc.returncode,
                                                 output.decode(), err.decode())
            self.assertEqual(result.returncode, 0, 'TTY credential operation failed')
            report = self.report(result)
            self.assert_values(report, dict(values, TERM='fixture-term'), stdin=typed)
            self.assertTrue(report['stdin_tty'])
            self.assertTrue(report['stdout_tty'])
            trace = self.trace()
            self.assertTrue(trace['tty_flag'])
            self.assertTrue(trace['stdin_tty'])
            self.assertTrue(trace['stdout_tty'])
            self.assert_transport_private(trace)
        finally:
            os.close(master)
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.communicate()

    def test_missing_auth_file_still_delivers_stdin_and_guest_result(self):
        program = self.observer(['AUTH_TOKEN'], status=17)
        result = self.invoke(self.wrapper('docker', 'fixture-cid', '1000', '0', '', PYTHON, program))
        self.assertEqual(result.returncode, 17, 'credential operation returned unexpected status')
        report = self.report(result)
        self.assertIsNone(report['values']['AUTH_TOKEN'])
        self.assertEqual(report['stdin'], digest('typed input\n'))
        self.assert_transport_private(self.trace())

    def test_reserved_envelope_names_refuse_before_transport_and_accept_corrected_name(self):
        for name in ('C0_SESSION_ENV', 'C0_SESSION_ENV_0000', 'C0_SESSION_ENV_ATTACK'):
            with self.subTest(name=name):
                self.trace_path.unlink(missing_ok=True)
                self.auth_values({name: 'fixture-secret-reserved'})
                result = self.invoke(self.wrapper('docker', 'fixture-cid', '1000', '0', '', '/bin/true'))
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse('fixture-secret-' in result.stdout+result.stderr, 'credential reached output')
                self.assertFalse(self.trace_path.exists(), 'refused auth still reached transport')
        values = {'SESSION_TOKEN': 'fixture-secret-reserved'}
        self.auth_values(values)
        program = self.observer(values)
        result = self.invoke(self.wrapper('docker', 'fixture-cid', '1000', '0', '', PYTHON, program))
        self.assertEqual(result.returncode, 0, 'credential operation returned unexpected status')
        self.assert_values(self.report(result), values)

    def test_redirected_auth_is_refused_without_reading_neighbor(self):
        neighbor = self.root / 'private-neighbor'
        neighbor.write_text("AUTH_TOKEN='fixture-secret-neighbor'\n")
        before = neighbor.read_bytes()
        for kind in ('symlink', 'hardlink', 'fifo', 'ancestor'):
            with self.subTest(kind=kind):
                saved = self.auth.parent.with_name('saved-auth')
                if kind == 'symlink':
                    self.auth.symlink_to(neighbor)
                elif kind == 'hardlink':
                    os.link(neighbor, self.auth)
                elif kind == 'fifo':
                    os.mkfifo(self.auth)
                else:
                    self.auth.parent.rename(saved)
                    self.auth.parent.symlink_to(saved, target_is_directory=True)
                    (saved / '.env').write_bytes(before)
                try:
                    result = self.invoke(self.wrapper('docker', 'fixture-cid', '1000', '0', '', '/bin/true'))
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse('fixture-secret-' in result.stdout+result.stderr, 'credential reached output')
                    self.assertFalse(self.trace_path.exists())
                    self.assertEqual(neighbor.read_bytes(), before)
                finally:
                    if kind == 'ancestor':
                        self.auth.parent.unlink()
                        saved.rename(self.auth.parent)
                    self.auth.unlink()

    def test_transport_failure_preserves_status_without_guest_or_secret_file(self):
        values = dict(AUTH_TOKEN='fixture-secret-failure-token',
                      LARGE='fixture-secret-failure-large-'+('abcdef' * 13000))
        self.auth_values(values)
        env = dict(self.env, TEST_PEER_EXIT='52')
        result = self.invoke(self.wrapper('docker', 'fixture-cid', '1000', '0', '', '/bin/true'), env=env)
        self.assertEqual(result.returncode, 52, 'credential operation returned unexpected status')
        self.assertFalse('fixture-secret-' in result.stdout+result.stderr, 'credential reached output')
        self.assert_transport_private(self.trace())
        self.assert_no_transport_secret_files(values.values())


    def test_cancellation_reaches_only_owned_transport_and_preserves_status(self):
        self.auth_values(dict(AUTH_TOKEN='fixture-secret-cancel-token',
                              LARGE='fixture-secret-cancel-large-'+('abcdef' * 13000)))
        unrelated = subprocess.Popen([PYTHON, '-I', '-c', 'import time;time.sleep(30)'],
                                     env=self.env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: unrelated.poll() is None and unrelated.kill())
        proc = subprocess.Popen(self.wrapper('docker', 'fixture-cid', '1000', '0', '', '/bin/true'),
                                env=dict(self.env, TEST_PEER_WAIT='1'), cwd=self.root,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            deadline = time.monotonic()+5
            ready = Path(str(self.trace_path)+'.ready')
            while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(ready.exists(), 'inert transport did not become ready')
            proc.send_signal(signal.SIGTERM)
            out, err = proc.communicate(timeout=5)
            self.assertEqual(proc.returncode, 143)
            self.assertFalse('fixture-secret-' in out+err, 'credential reached cancellation output')
            self.assertIsNone(unrelated.poll(), 'cancellation signaled an unrelated process')
            self.assert_transport_private(self.trace())
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.communicate()
            if unrelated.poll() is None:
                unrelated.terminate()
            unrelated.wait(timeout=5)


class LauncherIntegration(CredentialFixture):
    def test_shell_credentials_never_reach_docker_argv(self):
        self.auth_values(dict(AUTH_TOKEN='fixture-secret-shell-token'))
        # Do not execute an interactive shell in the host fixture. The peer's
        # transport result is a sufficient observation for this argv claim.
        self.env['TEST_PEER_EXIT'] = '0'
        result = self.call_function("c0_exec_shell 1000 ' -l'")
        self.assertEqual(result.returncode, 0, 'credential operation returned unexpected status')
        trace = self.trace()
        self.assertFalse(trace['argv_secret'], 'c0 shell placed credential value in Docker argv')
        self.assert_transport_private(trace)
        self.assertEqual(trace['uid'], '1000')
        self.assertEqual(trace['cid'], 'fixture-cid')

    def test_ssh_auth_cannot_replace_host_key_directory_or_launcher_controls(self):
        self.seed_inert_client()
        self.auth_values(dict(AUTH_TOKEN='fixture-secret-ssh-token',
                              C0ROOT='/fixture-secret-wrong-root',
                              C0_SSH_DIR='/fixture-secret-wrong-key',
                              C0_SSH_CLIENT_DIR='/fixture-secret-wrong-client'))
        self.env['TEST_PEER_EXIT'] = '0'
        result = self.call_function('cmd_ssh -Y -- /bin/true')
        self.assertEqual(result.returncode, 0, 'credential operation returned unexpected status')
        trace = self.trace()
        self.assertEqual(trace['host']['C0ROOT'], digest(self.env['C0ROOT']), 'auth replaced host C0ROOT')
        self.assertEqual(trace['identity'], digest(str(self.client / 'id_ed25519')), 'auth replaced host client key selection')
        self.assertEqual(trace['knownhosts'], [digest('UserKnownHostsFile='+str(self.client / 'known_hosts'))])
        self.assert_transport_private(trace)
        self.assertTrue(trace['x11'])

    def test_ssh_command_preserves_project_cwd_arguments_and_stdin(self):
        self.seed_inert_client()
        values = dict(AUTH_TOKEN='fixture-secret-project-token')
        self.auth_values(values)
        observer = self.observer(values)
        # Multi-argument c0 ssh must quote the literal path into one remote
        # command, including its spaces, semicolon, and dollar sign.
        result = self.call_function('cmd_ssh '+PYTHON+' '+shlex.quote(str(observer)))
        self.assertEqual(result.returncode, 0, 'credential operation returned unexpected status')
        report = self.report(result)
        self.assert_values(report, values)
        self.assertEqual(report['cwd'], str(self.project))
        self.assert_transport_private(self.trace())


@unittest.skipUnless(shutil.which('ssh-keygen'), 'local ssh-keygen required for temporary fixture keys')
class ClientKeySeparation(CredentialFixture):
    def keypair(self, path, comment):
        result = subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-f', str(path),
                                 '-N', '', '-C', comment], stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=10, env=self.env)
        self.assertEqual(result.returncode, 0, 'temporary fixture key generation failed')
        return path.read_bytes(), path.with_suffix('.pub').read_bytes()

    def prepare(self):
        return self.call_function('c0_ssh_keygen')

    def ensure(self):
        # Exercise the actual attachment prerequisite, without the transport
        # fixture's deliberate c0_ssh_ensure_keys stub.
        script = self.root / 'ensure-keys.sh'
        script.write_text('set -e\n'+definitions()+'\nc0_ssh_ensure_keys\n')
        return self.invoke(['/bin/bash', str(script)])

    def test_attachment_reconciles_existing_client_with_missing_authorization(self):
        result = self.prepare()
        self.assertEqual(result.returncode, 0, 'fixture key preparation failed')
        client_private = (self.client / 'id_ed25519').read_bytes()
        server_private = (self.ssh / 'ssh_host_ed25519_key').read_bytes()
        active_public = (self.client / 'id_ed25519.pub').read_bytes()
        _, unrelated = self.keypair(self.root / 'unrelated-attachment-key',
                                    'fixture-retained-authorization')
        # All existence checks succeed, but a retained guest auth directory
        # authorizes an earlier client. A new attachment must reconcile this.
        authorized = self.ssh / 'authorized_keys'
        retained = b'# retained guest authorization\nno-agent-forwarding '+unrelated
        authorized.write_bytes(retained)
        result = self.ensure()
        self.assertEqual(result.returncode, 0, 'attachment key reconciliation failed')
        self.assertIn(active_public.strip(), authorized.read_bytes().splitlines(),
                      'attachment left its selected management key unauthorized')
        self.assertIn(retained, authorized.read_bytes(), 'unrelated authorization changed')
        self.assertTrue((self.client / 'id_ed25519').read_bytes() == client_private,
                        'attachment replaced the selected private key')
        self.assertTrue((self.ssh / 'ssh_host_ed25519_key').read_bytes() == server_private,
                        'attachment replaced the guest server identity')

    def test_preparation_repairs_cached_public_key_to_held_client_private_identity(self):
        # c0-managed client keys are generated without a passphrase. The held
        # private key fixes the signing identity; its .pub is a repairable cache.
        client_private, client_public = self.keypair(self.client / 'id_ed25519',
                                                      'fixture-active-management')
        _, unrelated_public = self.keypair(self.root / 'unrelated-cached-public-key',
                                          'fixture-unrelated-authorization')
        (self.client / 'id_ed25519.pub').write_bytes(unrelated_public)
        authorized = self.ssh / 'authorized_keys'
        authorized.write_bytes(b'no-agent-forwarding '+unrelated_public)
        result = self.prepare()
        self.assertEqual(result.returncode, 0, 'cached public key reconciliation failed')
        expected_identity = client_public.split()[:2]
        self.assertEqual((self.client / 'id_ed25519.pub').read_bytes().split()[:2],
                         expected_identity, 'cached public key still differs from signing identity')
        self.assertTrue((self.client / 'id_ed25519').read_bytes() == client_private,
                        'reconciliation replaced the held client private key')
        identities = [line.split()[:2] for line in authorized.read_bytes().splitlines()]
        self.assertIn(expected_identity, identities,
                      'reconciliation failed to authorize the actual signing identity')
        self.assertIn(b'no-agent-forwarding '+unrelated_public, authorized.read_bytes(),
                      'reconciliation removed unrelated authorization')

    def test_attachment_repairs_existing_management_private_key_mode(self):
        result = self.prepare()
        self.assertEqual(result.returncode, 0, 'fixture key preparation failed')
        private = self.client / 'id_ed25519'
        before = private.read_bytes()
        private.chmod(0o644)
        result = self.ensure()
        self.assertEqual(result.returncode, 0, 'private key mode reconciliation failed')
        self.assertEqual(private.stat().st_mode & 0o777, 0o600,
                         'attachment retained a key OpenSSH refuses as nonprivate')
        self.assertTrue(private.read_bytes() == before, 'mode repair replaced the private key')

    def test_attachment_refuses_invalid_signing_identity_without_disclosing_it(self):
        result = self.prepare()
        self.assertEqual(result.returncode, 0, 'fixture key preparation failed')
        invalid = b'fixture-secret-invalid-managed-private-key\n'
        private = self.client / 'id_ed25519'
        private.write_bytes(invalid)
        result = self.ensure()
        self.assertNotEqual(result.returncode, 0, 'attachment accepted an invalid signing identity')
        self.assertNotIn(invalid.decode().strip(), result.stdout+result.stderr)
        self.assertTrue(private.read_bytes() == invalid, 'refusal discarded the retained private input')

    def test_conditional_attachment_propagates_config_write_refusal_after_preflight(self):
        result = self.prepare()
        self.assertEqual(result.returncode, 0, 'fixture key preparation failed')
        paths = [self.client / 'id_ed25519', self.client / 'id_ed25519.pub',
                 self.ssh / 'ssh_host_ed25519_key', self.ssh / 'authorized_keys']
        retained = {path: path.read_bytes() for path in paths}
        config = self.ssh / 'sshd_config'
        config.unlink()
        # The corrected counterpart can create an absent config, including
        # when the caller uses a conditional that disables Bash errexit.
        script = self.root / 'conditional-ensure.sh'
        script.write_text('set -e\n'+definitions()+
                          '\nif c0_ssh_ensure_keys; then exit 0; else exit 73; fi\n')
        accepted = self.invoke(['/bin/bash', str(script)])
        self.assertEqual(accepted.returncode, 0, 'missing configuration was not created')
        self.assertTrue(config.is_file())
        neighbor = self.root / 'unrelated-config-neighbor'
        neighbor.mkdir(mode=0o700)
        sentinel = neighbor / 'private-content'
        sentinel.write_bytes(b'fixture-secret-config-neighbor\n')
        wrapper = self.bin / 'race-host-io'
        wrapper.write_text('''import os,subprocess,sys
from pathlib import Path
result=subprocess.run([sys.executable,'-I',os.environ['TEST_REAL_HOST_IO'],*sys.argv[1:]])
if result.returncode==0 and sys.argv[2]=='prepare-ssh':
    config=Path(os.environ['TEST_RACE_CONFIG'])
    if os.environ['TEST_RACE_KIND']=='fifo':
        os.mkfifo(config,0o600)
    else:
        config.symlink_to(os.environ['TEST_RACE_TARGET'],target_is_directory=True)
sys.exit(result.returncode)
''')
        for kind in ('symlink', 'fifo'):
            with self.subTest(unsafe_config=kind):
                config.unlink()
                environment = dict(self.env, C0_HOST_IO=str(wrapper),
                                   TEST_REAL_HOST_IO=str(self.bin / 'c0-host-io'),
                                   TEST_RACE_CONFIG=str(config), TEST_RACE_KIND=kind,
                                   TEST_RACE_TARGET=str(neighbor))
                # Run the real preparation before injecting the unsafe leaf.
                # A pre-existing unsafe config would refuse during preflight
                # and would never exercise the config writer's failure status.
                refused = self.invoke(['/bin/bash', str(script)], env=environment)
                self.assertEqual(refused.returncode, 73,
                                 'conditional attachment masked configuration write failure')
                self.assertTrue({path: path.read_bytes() for path in paths} == retained,
                                'configuration refusal changed retained key material')
                self.assertTrue(sentinel.read_bytes() == b'fixture-secret-config-neighbor\n')
                self.assertNotIn('fixture-secret-config-neighbor', refused.stdout+refused.stderr)

    def test_fresh_management_private_key_is_host_only_and_repeat_is_stable(self):
        result = self.prepare()
        self.assertEqual(result.returncode, 0, 'credential operation returned unexpected status')
        self.assertTrue((self.client / 'id_ed25519').is_file(), 'host-only client key missing')
        self.assertFalse((self.ssh / 'id_ed25519').exists(), 'host client private key is guest-visible')
        self.assertTrue((self.ssh / 'ssh_host_ed25519_key').is_file())
        public = (self.client / 'id_ed25519.pub').read_bytes()
        self.assertIn(public.strip(), (self.ssh / 'authorized_keys').read_bytes().splitlines())
        self.assertEqual(self.client.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.client / 'id_ed25519').stat().st_mode & 0o777, 0o600)
        paths = [self.client / 'id_ed25519', self.client / 'id_ed25519.pub',
                 self.ssh / 'ssh_host_ed25519_key', self.ssh / 'authorized_keys']
        original = {p: p.read_bytes() for p in paths}
        repeated = self.prepare()
        self.assertEqual(repeated.returncode, 0, 'repeated key preparation failed')
        self.assertTrue({p: p.read_bytes() for p in paths} == original, 'retained key material changed')
        self.assertFalse('PRIVATE KEY' in result.stdout+result.stderr+repeated.stdout+repeated.stderr, 'private key reached output')

    def test_legacy_client_is_retained_host_only_and_unrelated_authorization_survives(self):
        legacy, legacy_public = self.keypair(self.ssh / 'id_ed25519', 'fixture-legacy-management')
        server, _ = self.keypair(self.ssh / 'ssh_host_ed25519_key', 'fixture-retained-server')
        unrelated_path = self.root / 'unrelated-fixture-key'
        _, unrelated_public = self.keypair(unrelated_path, 'fixture-unrelated-authorization')
        _, active_public = self.keypair(self.client / 'id_ed25519', 'fixture-active-management')
        authorized = self.ssh / 'authorized_keys'
        unrelated_line = b'no-agent-forwarding '+unrelated_public.strip()+b'\n'
        # authorized_keys identity is the actual key after optional options. Its
        # trailing comment is freeform, even if it names another real identity.
        unrelated_identity = b' '.join(unrelated_public.split()[:2])
        legacy_identity = b' '.join(legacy_public.split()[:2])
        active_identity = b' '.join(active_public.split()[:2])
        legacy_option_line = b'command="printf legacy",no-port-forwarding '+legacy_public.strip()+b'\n'
        legacy_comment_line = unrelated_identity+b' retained legacy reference '+legacy_identity+b'\n'
        active_comment_line = unrelated_identity+b' retained active reference '+active_identity+b'\n'
        apostrophe_comment = b" user's old client\n"
        quote_backslash_comment = b' old "unmatched quote with trailing backslash\\\n'
        legacy_apostrophe_line = legacy_identity+apostrophe_comment
        legacy_quoted_line = b'no-agent-forwarding '+legacy_identity+quote_backslash_comment
        unrelated_apostrophe_line = unrelated_identity+apostrophe_comment
        unrelated_quoted_line = b'no-agent-forwarding '+unrelated_identity+quote_backslash_comment
        authorized.write_bytes(b'# fixture retained comment\n'+legacy_public+legacy_option_line+
                               legacy_apostrophe_line+legacy_quoted_line+unrelated_line+
                               legacy_comment_line+active_comment_line+
                               unrelated_apostrophe_line+unrelated_quoted_line)
        result = self.prepare()
        self.assertEqual(result.returncode, 0, 'credential operation returned unexpected status')
        self.assertFalse((self.ssh / 'id_ed25519').exists(), 'legacy host private key remains guest-visible')
        self.assertFalse((self.ssh / 'id_ed25519.pub').exists())
        self.assertTrue((self.ssh / 'ssh_host_ed25519_key').read_bytes() == server, 'server private key changed')
        archives = [p for p in (self.client / 'legacy-keys').rglob('*') if p.is_file()]
        self.assertTrue(any(p.read_bytes() == legacy for p in archives), 'legacy private key not retained')
        self.assertTrue(any(p.read_bytes() == legacy_public for p in archives), 'legacy public key not retained')
        content = authorized.read_bytes()
        self.assertIn(b'# fixture retained comment\n', content)
        self.assertIn(unrelated_line, content)
        self.assertNotIn(legacy_public.strip(), content.splitlines())
        self.assertNotIn(legacy_option_line.strip(), content.splitlines())
        with self.subTest(authorization='legacy key with apostrophe in freeform comment'):
            self.assertNotIn(legacy_apostrophe_line.strip(), content.splitlines())
        with self.subTest(authorization='option-prefixed legacy key with quote and backslash comment'):
            self.assertNotIn(legacy_quoted_line.strip(), content.splitlines())
        self.assertIn(unrelated_apostrophe_line, content)
        self.assertIn(unrelated_quoted_line, content)
        with self.subTest(authorization='unrelated key with legacy identity in comment'):
            self.assertIn(legacy_comment_line, content)
        self.assertIn(active_comment_line, content)
        new_public = (self.client / 'id_ed25519.pub').read_bytes()
        self.assertEqual(new_public, active_public)
        with self.subTest(authorization='active key requires an actual authorization entry'):
            self.assertIn(new_public.strip(), content.splitlines())
        self.assertFalse((self.client / 'id_ed25519').read_bytes() == legacy, 'legacy client key reused')
        for p in self.ssh.rglob('*'):
            if p.is_file() and p.name != 'ssh_host_ed25519_key':
                self.assertFalse(b'PRIVATE KEY' in p.read_bytes(), 'host private key exposed in guest SSH tree')
        retained = {str(p.relative_to(self.client)): p.read_bytes() for p in archives}
        repeated = self.prepare()
        self.assertEqual(repeated.returncode, 0, 'repeated key preparation failed')
        self.assertTrue({str(p.relative_to(self.client)): p.read_bytes() for p in archives} == retained, 'legacy archive changed')
        self.assertEqual(authorized.read_bytes(), content)

    def test_legacy_retirement_uses_held_private_identity_not_guest_public_key(self):
        _, legacy_public = self.keypair(self.ssh / 'id_ed25519', 'fixture-legacy-management')
        unrelated_path = self.root / 'other-authorized-fixture-key'
        _, unrelated_public = self.keypair(unrelated_path, 'fixture-unrelated-authorization')
        # A writable guest public-key sidecar must not identify which unrelated
        # authorization is removed while retiring the held management private key.
        (self.ssh / 'id_ed25519.pub').write_bytes(unrelated_public)
        authorized = self.ssh / 'authorized_keys'
        authorized.write_bytes(legacy_public+unrelated_public)
        result = self.prepare()
        self.assertEqual(result.returncode, 0, 'credential operation returned unexpected status')
        content = authorized.read_bytes()
        self.assertIn(unrelated_public.strip(), content.splitlines())
        self.assertNotIn(legacy_public.split()[1], content)
        self.assertFalse((self.ssh / 'id_ed25519').exists())
        self.assertIn((self.client / 'id_ed25519.pub').read_bytes().strip(), content.splitlines())

    def test_client_key_redirect_refuses_without_overwriting_neighbor(self):
        neighbor = self.root / 'unrelated-private-neighbor'
        neighbor.write_bytes(b'fixture unrelated private file\n')
        target = self.client / 'id_ed25519'
        target.symlink_to(neighbor)
        before = neighbor.read_bytes()
        result = self.prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(neighbor.read_bytes(), before)
        self.assertFalse((self.ssh / 'id_ed25519').exists())
        self.assertFalse('fixture unrelated private file' in result.stdout+result.stderr, 'neighbor content reached output')


if __name__ == '__main__':
    unittest.main()
