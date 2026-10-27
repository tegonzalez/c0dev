# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Opt-in native credentials; newly owned containers and a dedicated bridge.

C0_CREDENTIAL_DOCKER_TESTS=1 python3 -B -m unittest discover -s tests \
    -p test_c0_credentials_docker.py -v

Requires the pinned cached project runtime, local Unix Docker endpoint, host
OpenSSH, and ssh-keygen. No pulls/builds/images/volumes/shared mounts or agents.
The fixture streams synthetic server/auth files into private guest HOME tmpfs
as UID 1000, with no setup capabilities; client keys and known_hosts stay in the private host fixture. The dedicated
bridge disables outbound IP masquerading and publishes SSH only on host loopback;
complete egress isolation is not established. Entry-point and activation are
deliberately replaced; this does not establish c0 activation.
The retained-authorization case alone binds its newly owned synthetic guest SSH
directory, never host client/trust files, to observe host replacements through
the real mount with StrictModes enabled. It exercises the actual host key
prerequisite, but still does not run the product entrypoint or home overlays.
"""
import hashlib
import csv
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import tarfile
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
CACHED_IMAGE = 'sha256:a3e8073e19fb59acf51c1e5f6f902c7ccfa267909100139bb8b3e93e4c78a077'
LABEL = 'c0dev.credential_native_test'
PYTHON = '/usr/bin/python3'
OBSERVER = r'''
import hashlib,json,os,sys
names=json.loads(sys.argv[1])
print(json.dumps(dict(values={k:hashlib.sha256(os.environ[k].encode()).hexdigest()
 if k in os.environ else None for k in names},
 internal=sorted(k for k in os.environ if k.startswith('C0_SESSION_ENV')),
 stdin=hashlib.sha256(sys.stdin.buffer.read()).hexdigest(),uid=os.getuid(),
 cwd=os.getcwd(),cap_eff=next(line.split()[1] for line in open('/proc/self/status')
 if line.startswith('CapEff:')))))
sys.exit(int(sys.argv[2]))
'''.strip()
# This shim does not read the credential pipe: the actual Docker CLI must read
# the inherited FD itself. It records only hashes/public metadata and then execs
# the real transport. Host SSH has an empty config, no agent and bounded retries.
TRANSPORT = r'''
import base64,hashlib,json,os,re,stat,sys
from pathlib import Path
args=sys.argv[1:]
kind=Path(sys.argv[0]).name
needle=b'fixture-secret-'
def exposed(value):
    raw=value.encode()
    if needle in raw: return True
    for token in re.findall(rb'[A-Za-z0-9_+/=-]{20,}',raw):
        try:
            if needle in base64.urlsafe_b64decode(token+b'='*(-len(token)%4)): return True
        except (ValueError,base64.binascii.Error): pass
    return False
trace=dict(kind=kind,argv_secret=any(exposed(a) for a in args),
 raw_auth_in_host=any(exposed(v) for k,v in os.environ.items() if not k.startswith('C0_SESSION_ENV')),
 host={k:hashlib.sha256(os.environ.get(k,'').encode()).hexdigest()
       for k in ('C0ROOT','DOCKER_HOST','PATH')})
if kind=='docker':
    assert args[0]=='exec' and '--env-file' in args
    path=args[args.index('--env-file')+1]
    trace['envfile_fifo']=stat.S_ISFIFO(os.stat(path).st_mode)
    trace['envfile_fd_path']=bool(re.fullmatch(r'/dev/fd/[0-9]+',path))
    executable=os.environ['TEST_REAL_DOCKER']
elif kind=='ssh':
    trace['identity']=hashlib.sha256(os.path.realpath(args[args.index('-i')+1]).encode()).hexdigest()
    options=[args[i+1] for i,a in enumerate(args[:-1]) if a=='-o']
    trace['knownhosts']=[hashlib.sha256(('UserKnownHostsFile='+os.path.realpath(a.split('=',1)[1])).encode()).hexdigest() for a in options if a.startswith('UserKnownHostsFile=')]
    trace['sendenv']=[a[8:] for a in options if a.startswith('SendEnv=')]
    trace['quiet']='LogLevel=ERROR' in options
    trace['agent_disabled']='IdentityAgent=none' in options
    trace['selected_identity_only']='IdentitiesOnly=yes' in options
    executable=os.environ['TEST_REAL_SSH']
    args=['-F','/dev/null','-o','IdentityAgent=none','-o','IdentitiesOnly=yes',
          '-o','BatchMode=yes','-o','ConnectTimeout=3','-o','ConnectionAttempts=1']+args
else: raise AssertionError('unexpected native transport')
Path(os.environ['TEST_TRANSPORT_TRACE']).write_text(json.dumps(trace))
os.execv(executable,[executable,*args])
'''


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


@unittest.skipUnless(os.environ.get('C0_CREDENTIAL_DOCKER_TESTS') == '1',
                     'opt-in owned native credential transport')
class CredentialsDocker(unittest.TestCase):
    def setUp(self):
        self.docker = shutil.which('docker')
        self.ssh_executable = shutil.which('ssh')
        self.assertTrue(self.docker and self.ssh_executable and shutil.which('ssh-keygen'),
                        'Docker CLI and local OpenSSH prerequisites required')
        self.temp = tempfile.TemporaryDirectory(prefix='c0-native-credentials-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'checkout ; literal $ % ${HOME} " \\ space'
        self.bin = self.root / 'bin'
        self.bin.mkdir(parents=True)
        for name in ('c0-host-io', 'c0-credentials'):
            shutil.copy2(ROOT / 'bin' / name, self.bin / name)
        self.auth = self.root / 'auth/.env'
        self.guest_ssh = self.root / 'auth/ssh'
        self.client = self.root / 'auth/ssh-client'
        self.guest_ssh.mkdir(parents=True, mode=0o700)
        self.token = uuid.uuid4().hex
        self.containers = []
        self.auth_bind_containers = set()
        self.networks = []
        self.addCleanup(self.cleanup_owned)
        # Query only local context metadata if an endpoint was not supplied.
        # All subsequent native calls use a private HOME and explicit local Unix
        # endpoint, with no host account Docker auth/config or agent inheritance.
        endpoint = os.environ.get('C0_CREDENTIAL_DOCKER_HOST')
        if not endpoint:
            selector = dict(PATH=os.environ.get('PATH', os.defpath),
                            HOME=os.environ.get('HOME', str(Path.home())))
            if os.environ.get('DOCKER_CONFIG'):
                selector['DOCKER_CONFIG'] = os.environ['DOCKER_CONFIG']
            context = os.environ.get('DOCKER_CONTEXT')
            if not context and os.environ.get('DOCKER_HOST'):
                endpoint = os.environ['DOCKER_HOST']
            else:
                args = [self.docker, 'context', 'inspect']
                if context:
                    args.append(context)
                result = subprocess.run(args+['--format', '{{.Endpoints.docker.Host}}'],
                                        env=selector, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, 'local Docker endpoint discovery failed')
                endpoint = result.stdout.strip()
        self.assertTrue(endpoint.startswith('unix://'), 'native fixture requires local Unix Docker endpoint')
        self.transport_bin = self.root / 'transport-bin'
        self.transport_bin.mkdir()
        for name in ('docker', 'ssh'):
            path = self.transport_bin / name
            path.write_text('#!'+PYTHON+'\n'+TRANSPORT)
            path.chmod(0o755)
        self.trace_path = self.root / 'transport.json'
        self.env = dict(PATH=str(self.transport_bin)+':'+str(Path(self.docker).parent)+':/usr/bin:/bin',
                        HOME=str(self.root), LANG='C.UTF-8', TERM='xterm-256color',
                        C0ROOT=str(self.root), DOCKER_HOST=endpoint,
                        TEST_REAL_DOCKER=self.docker, TEST_REAL_SSH=self.ssh_executable,
                        TEST_TRANSPORT_TRACE=str(self.trace_path), PYTHONDONTWRITEBYTECODE='1')
        image = self.call('image', 'inspect', CACHED_IMAGE)
        if image.returncode:
            self.skipTest('exact cached project runtime unavailable; refusing to pull')
        config = json.loads(image.stdout)[0]
        self.assertEqual(config['Id'], CACHED_IMAGE)
        self.assertFalse(config.get('Config', {}).get('Volumes'),
                         'fixture refuses image-defined anonymous volumes')
        prepared = subprocess.run([PYTHON, '-I', str(self.bin / 'c0-host-io'), str(self.root),
                                   'prepare-ssh', str(self.guest_ssh), 'native-'+self.token,
                                   str(self.client)], env=self.env, capture_output=True,
                                  text=True, timeout=20)
        self.assertEqual(prepared.returncode, 0, 'synthetic SSH preparation failed')
        self.assertFalse((self.guest_ssh / 'id_ed25519').exists())
        self.assertEqual(self.client.stat().st_mode & 0o777, 0o700)

    def call(self, *args, **kwargs):
        return subprocess.run([self.docker, *args], env=self.env,
                              capture_output=True, text=True, timeout=30, **kwargs)

    def checked(self, *args, **kwargs):
        result = self.call(*args, **kwargs)
        self.assertEqual(result.returncode, 0, 'native fixture operation failed: '+args[0])
        return result.stdout.strip()

    def owned_container(self, cid):
        result = self.call('inspect', cid)
        self.assertEqual(result.returncode, 0, 'owned container unavailable')
        data = json.loads(result.stdout)[0]
        self.assertEqual(data['Id'], cid)
        self.assertEqual(data['Config']['Labels'].get(LABEL), self.token,
                         'refusing operation on unattributed container')
        self.assertEqual(data['Image'], CACHED_IMAGE)
        self.assertTrue(data['HostConfig']['ReadonlyRootfs'])
        self.assertEqual(data['Config']['User'], '1000:1000')
        self.assertIn('ALL', data['HostConfig'].get('CapDrop') or [])
        self.assertTrue(any(value in ('no-new-privileges', 'no-new-privileges:true')
                            for value in data['HostConfig'].get('SecurityOpt') or []))
        allowed_tmpfs = {'/home/dev', '/tmp', '/run/sshd'}
        mounts = data.get('Mounts', [])
        binds = [mount for mount in mounts if mount.get('Type') == 'bind']
        if cid in self.auth_bind_containers:
            self.assertEqual(len(binds), 1, 'only the selected synthetic auth bind is permitted')
            self.assertEqual(binds[0]['Source'], str(self.guest_ssh))
            self.assertEqual(binds[0]['Destination'], '/home/dev/.ssh')
            self.assertTrue(binds[0]['RW'])
        else:
            self.assertEqual(binds, [], 'ordinary native fixture forbids host binds')
        self.assertTrue(all(m in binds or (m.get('Type') == 'tmpfs'
                            and m.get('Destination') in allowed_tmpfs) for m in mounts),
                        'fixture refuses unrelated host data or volumes')
        self.assertFalse(data['HostConfig'].get('Binds'), 'fixture forbids legacy -v bind declarations')
        return data

    def created(self, suffix, network='none', ssh=False, auth_bind=False):
        args = ['create', '--pull=never', '--name', 'c0-credential-'+self.token+'-'+suffix,
                '--label', LABEL+'='+self.token, '--network', network,
                '--read-only', '--user', '1000:1000', '--workdir', '/tmp', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges:true', '--log-driver', 'none',
                '--tmpfs', '/home/dev:rw,uid=1000,gid=1000,mode=0700',
                '--tmpfs', '/tmp:rw,mode=1777', '--env', 'HOME=/home/dev',
                '--entrypoint', '/bin/sleep']
        if ssh:
            args += ['--tmpfs', '/run/sshd:rw,uid=1000,gid=1000,mode=0755',
                     '--publish', '127.0.0.1::2222']
        if auth_bind:
            self.assertTrue(ssh, 'synthetic auth bind requires the dedicated SSH fixture')
            self.assertFalse(self.guest_ssh.is_symlink())
            self.assertEqual(self.guest_ssh.resolve(), self.guest_ssh)
            self.assertTrue(self.guest_ssh.is_relative_to(Path(self.temp.name).resolve()))
            # Docker parses --mount as CSV, independently of shell argv.
            # Preserve punctuation in the real fixture path, including quotes.
            mount = io.StringIO()
            csv.writer(mount).writerow(['type=bind', 'src='+str(self.guest_ssh),
                                       'dst=/home/dev/.ssh'])
            args += ['--mount', mount.getvalue().rstrip('\r\n')]
        created = self.call(*args, CACHED_IMAGE, '180')
        self.assertEqual(created.returncode, 0,
                         'native fixture create failed: '+created.stderr[:4000])
        cid = created.stdout.strip()
        self.assertRegex(cid, r'^[0-9a-f]{64}$')
        self.containers.append(cid)
        if auth_bind:
            self.auth_bind_containers.add(cid)
        self.owned_container(cid)
        self.checked('start', cid)
        return cid

    def cleanup_owned(self):
        errors = []
        for cid in reversed(self.containers):
            result = self.call('inspect', cid)
            if result.returncode:
                errors.append('owned container inspection failed: '+cid)
                continue
            data = json.loads(result.stdout)[0]
            if data.get('Id') != cid or data.get('Config', {}).get('Labels', {}).get(LABEL) != self.token:
                errors.append('retained uncertain container: '+cid)
                continue
            if self.call('rm', '-f', cid).returncode:
                errors.append('owned container removal failed: '+cid)
        for nid in reversed(self.networks):
            result = self.call('network', 'inspect', nid)
            if result.returncode:
                errors.append('owned network inspection failed: '+nid)
                continue
            data = json.loads(result.stdout)[0]
            if data.get('Id') != nid or data.get('Labels', {}).get(LABEL) != self.token:
                errors.append('retained uncertain network: '+nid)
                continue
            if self.call('network', 'rm', nid).returncode:
                errors.append('owned network removal failed: '+nid)
        self.assertEqual(errors, [])

    def auth_values(self, values):
        self.auth.write_text(''.join(k+"='"+v+"'\n" for k, v in values.items()))
        self.auth.chmod(0o600)

    def ssh_bind_diagnostics(self, cid):
        """Only owned daemon logs and file metadata; never key or auth bytes."""
        self.owned_container(cid)
        log = self.call('exec', '--user', '1000:1000', cid, '/bin/cat',
                        '/tmp/native-auth-bind-sshd.log')
        metadata = self.call('exec', '--user', '1000:1000', cid, PYTHON, '-I', '-c', '''
import json,os,pathlib,stat
out={'uid':os.getuid(),'gid':os.getgid(),'paths':{}}
for path in ('/home/dev','/home/dev/.ssh','/home/dev/.ssh/authorized_keys',
             '/home/dev/.ssh/ssh_host_ed25519_key','/home/dev/.ssh/sshd_config'):
    try:
        info=pathlib.Path(path).stat()
        out['paths'][path]=dict(uid=info.st_uid,gid=info.st_gid,
                               mode=oct(stat.S_IMODE(info.st_mode)),readable=os.access(path,os.R_OK))
    except OSError as error:
        out['paths'][path]=dict(error=type(error).__name__,errno=error.errno)
print(json.dumps(out))
''')
        return '\n'+log.stdout+log.stderr+'\n'+metadata.stdout+metadata.stderr

    def invoke(self, mode, *args, stdin='typed native input\n'):
        result = subprocess.run([PYTHON, '-I', str(self.bin / 'c0-credentials'), str(self.root),
                                 mode, str(self.auth), *map(str, args)], env=self.env,
                                input=stdin, capture_output=True, text=True, timeout=20)
        self.assertFalse('fixture-secret-' in result.stdout+result.stderr, 'credential reached native output')
        return result

    def assert_report(self, result, values, uid, status, stdin='typed native input\n', cwd=None):
        self.assertEqual(result.returncode, status, 'native guest returned unexpected status')
        report = json.loads(result.stdout)
        self.assertEqual(report['values'], {k: digest(v) for k, v in values.items()})
        self.assertEqual(report['stdin'], digest(stdin))
        self.assertEqual(report['uid'], uid)
        self.assertEqual(report['cap_eff'], '0000000000000000')
        self.assertEqual(report['internal'], [])
        if cwd is not None:
            self.assertEqual(report['cwd'], cwd)
        trace = json.loads(self.trace_path.read_text())
        self.assertFalse(trace['argv_secret'], 'credential reached native transport argv')
        self.assertFalse(trace['raw_auth_in_host'], 'raw auth reached native host transport environ')
        self.assertEqual(trace['host'], {k: digest(self.env[k]) for k in trace['host']})
        return trace

    def test_actual_docker_fd_envfile_preserves_large_literals_stdin_uid_and_status(self):
        cid = self.created('docker')
        values = dict(AUTH_TOKEN='fixture-secret-native-$() ; `x` ünicode ☃', EMPTY='',
                      LARGE='fixture-secret-native-large-'+('abc123' * 18000),
                      C0ROOT='/fixture-secret-guest-only-root',
                      DOCKER_HOST='tcp://fixture-secret-guest-only-daemon:2375',
                      PATH='/fixture-secret-guest-only-path')
        self.auth_values(values)
        for uid, status in (('1000', 37), ('0', 41)):
            with self.subTest(uid=uid):
                self.owned_container(cid)
                result = self.invoke('docker', cid, uid, '0', '', PYTHON, '-I', '-c',
                                     OBSERVER, json.dumps(list(values)), str(status))
                trace = self.assert_report(result, values, int(uid), status)
                self.assertTrue(trace['envfile_fifo'])
                self.assertTrue(trace['envfile_fd_path'])

    def test_actual_openssh_private_envelope_roundtrip_keeps_client_key_host_only(self):
        nid = self.checked('network', 'create', '--opt',
                           'com.docker.network.bridge.enable_ip_masquerade=false',
                           '--label', LABEL+'='+self.token,
                           'c0-credential-'+self.token)
        self.assertRegex(nid, r'^[0-9a-f]{64}$')
        self.networks.append(nid)
        network = json.loads(self.checked('network', 'inspect', nid))[0]
        self.assertEqual(network.get('Options', {}).get(
            'com.docker.network.bridge.enable_ip_masquerade'), 'false')
        self.assertEqual(network['Labels'].get(LABEL), self.token)
        cid = self.created('ssh', network=nid, ssh=True)
        data = self.owned_container(cid)
        ports = data['NetworkSettings']['Ports']['2222/tcp']
        self.assertEqual(len(ports), 1)
        self.assertEqual(ports[0]['HostIp'], '127.0.0.1')
        port = ports[0]['HostPort']
        payload = self.root / 'guest-payload'
        ssh = payload / '.ssh'
        ssh.mkdir(parents=True, mode=0o700)
        payload.chmod(0o700)
        for name in ('ssh_host_ed25519_key', 'ssh_host_ed25519_key.pub', 'authorized_keys'):
            shutil.copy2(self.guest_ssh / name, ssh / name)
        (ssh / 'sshd_config').write_text('''Port 2222
ListenAddress 0.0.0.0
HostKey /home/dev/.ssh/ssh_host_ed25519_key
AuthorizedKeysFile /home/dev/.ssh/authorized_keys
PidFile /home/dev/.ssh/sshd.pid
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
PubkeyAuthentication yes
PermitRootLogin no
AllowUsers dev
UsePAM no
StrictModes yes
LogLevel INFO
AcceptEnv C0_SESSION_ENV* LANG LC_*
''')
        (payload / 'bin').mkdir()
        (payload / 'bin/activate').write_text('# isolated native fixture; no shared tools\n')
        (payload / '.profile').write_text('# isolated native fixture; no activation\n')
        (payload / 'observe.py').write_text(OBSERVER+'\n')
        project = '/home/dev/projects/project ; $ literal'
        (payload / 'projects/project ; $ literal').mkdir(parents=True)
        self.owned_container(cid)
        # Stream the fixed synthetic payload into the running HOME tmpfs as its
        # ordinary user, preserving the read-only root filesystem;
        # --no-same-owner retains UID 1000 without a setup/root capability.
        archive_bytes = io.BytesIO()
        with tarfile.open(fileobj=archive_bytes, mode='w') as archive:
            archive.add(payload, arcname='.')
        seeded = subprocess.run([self.docker, 'exec', '-i', '--user', '1000:1000', cid,
                                 '/bin/tar', '--no-same-owner', '-C', '/home/dev', '-xf', '-'],
                                env=self.env, input=archive_bytes.getvalue(),
                                capture_output=True, timeout=30)
        self.assertEqual(seeded.returncode, 0, 'owned UID 1000 HOME seeding failed')
        self.checked('exec', '--user', '1000:1000', cid, '/usr/sbin/sshd',
                     '-f', '/home/dev/.ssh/sshd_config', '-E', '/home/dev/.ssh/native-sshd.log')
        # Probe only the owned listener, from inside its dedicated fixture container.
        ready = False
        for _ in range(30):
            probe = self.call('exec', '--user', '1000:1000', cid, PYTHON, '-I', '-c',
                              'import socket;s=socket.create_connection(("127.0.0.1",2222),.2);s.close()')
            if probe.returncode == 0:
                ready = True
                break
            time.sleep(0.1)
        self.assertTrue(ready, 'owned native SSH listener unavailable')
        values = dict(AUTH_TOKEN='fixture-secret-native-ssh-$() ; " ünicode', EMPTY='',
                      LARGE='fixture-secret-native-ssh-large-'+('abcdef' * 13000),
                      C0ROOT='/fixture-secret-guest-only-root',
                      C0_SSH_CLIENT_DIR='/fixture-secret-guest-only-client',
                      DOCKER_HOST='tcp://fixture-secret-guest-only-daemon:2375')
        self.auth_values(values)
        remote = 'cd '+shlex.quote(project)+' && '+shlex.join([
            PYTHON, '-I', '/home/dev/observe.py', json.dumps(list(values)), '43'])
        result = self.invoke('ssh', self.client, port, '0', '0', remote)
        trace = self.assert_report(result, values, 1000, 43, cwd=project)
        self.assertEqual(trace['identity'], digest(str(self.client / 'id_ed25519')))
        self.assertEqual(trace['knownhosts'], [digest('UserKnownHostsFile='+str(self.client / 'known_hosts'))])
        self.assertTrue(trace['quiet'])
        self.assertTrue(trace['agent_disabled'])
        self.assertTrue(trace['selected_identity_only'])
        self.assertTrue(trace['sendenv'])
        self.assertTrue(all(name.startswith('C0_SESSION_ENV') for name in trace['sendenv']))
        self.assertTrue((self.client / 'known_hosts').is_file())
        self.assertEqual(self.client.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.client / 'id_ed25519').stat().st_mode & 0o777, 0o600)
        # Digest only the permitted server private key. No host client or archive
        # is copied/mounted, and ordinary server processes hold zero effective caps.
        inspected = self.checked('exec', '--user', '1000:1000', cid, PYTHON, '-I', '-c',
            'import hashlib,json,pathlib; p=pathlib.Path("/home/dev/.ssh"); '
            'print(json.dumps(dict(server=hashlib.sha256((p/"ssh_host_ed25519_key").read_bytes()).hexdigest(),'
            'client=(p/"id_ed25519").exists(),archive=(p/"legacy-keys").exists())))')
        observed = json.loads(inspected)
        self.assertEqual(observed['server'], hashlib.sha256((self.guest_ssh / 'ssh_host_ed25519_key').read_bytes()).hexdigest())
        self.assertNotEqual(observed['server'], hashlib.sha256((self.client / 'id_ed25519').read_bytes()).hexdigest())
        self.assertFalse(observed['client'])
        self.assertFalse(observed['archive'])
        self.owned_container(cid)

    def test_actual_openssh_retained_auth_bind_observes_host_key_reconciliation(self):
        # Every source file here was created under this test's private temporary
        # checkout. Keep the client directory outside the only allowed bind.
        active = (self.client / 'id_ed25519.pub').read_bytes()
        private = (self.client / 'id_ed25519').read_bytes()
        server = (self.guest_ssh / 'ssh_host_ed25519_key').read_bytes()
        retained = b'# unrelated retained authorization\n'+(
            self.guest_ssh / 'ssh_host_ed25519_key.pub').read_bytes()
        authorized = self.guest_ssh / 'authorized_keys'
        authorized.write_bytes(retained)
        (self.guest_ssh / 'sshd_config').write_text('''Port 2222
ListenAddress 0.0.0.0
HostKey /home/dev/.ssh/ssh_host_ed25519_key
AuthorizedKeysFile /home/dev/.ssh/authorized_keys
PidFile /home/dev/.ssh/sshd.pid
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
PubkeyAuthentication yes
PermitRootLogin no
AllowUsers dev
UsePAM no
StrictModes yes
LogLevel INFO
AcceptEnv C0_SESSION_ENV* LANG LC_*
''')
        nid = self.checked('network', 'create', '--opt',
                           'com.docker.network.bridge.enable_ip_masquerade=false',
                           '--label', LABEL+'='+self.token,
                           'c0-credential-'+self.token+'-auth-bind')
        self.assertRegex(nid, r'^[0-9a-f]{64}$')
        self.networks.append(nid)
        network = json.loads(self.checked('network', 'inspect', nid))[0]
        self.assertEqual(network['Labels'].get(LABEL), self.token)
        self.assertEqual(network.get('Options', {}).get(
            'com.docker.network.bridge.enable_ip_masquerade'), 'false')
        cid = self.created('ssh-auth-bind', network=nid, ssh=True, auth_bind=True)
        data = self.owned_container(cid)
        ports = data['NetworkSettings']['Ports']['2222/tcp']
        self.assertEqual(len(ports), 1)
        self.assertEqual(ports[0]['HostIp'], '127.0.0.1')
        port = ports[0]['HostPort']
        project = '/home/dev/projects/project ; $ literal'
        seeded = self.call('exec', '--user', '1000:1000', cid, PYTHON, '-I', '-c',
            'import pathlib; p=pathlib.Path("/home/dev"); '
            '(p/"bin").mkdir(); (p/"bin/activate").write_text("# native fixture\\n"); '
            '(p/".profile").write_text("# native fixture\\n"); '
            '(p/"observe.py").write_text('+repr(OBSERVER+'\n')+'); '
            'pathlib.Path('+repr(project)+').mkdir(parents=True)')
        self.assertEqual(seeded.returncode, 0, 'owned HOME setup failed: '+seeded.stderr)
        # Deliberately do not chown, copy or relax permissions on the bind.
        # A real UID/StrictModes incompatibility must fail here with its cause.
        daemon = self.call('exec', '--user', '1000:1000', cid, '/usr/sbin/sshd',
                           '-f', '/home/dev/.ssh/sshd_config',
                           '-E', '/tmp/native-auth-bind-sshd.log')
        if daemon.returncode:
            self.fail('host-bind sshd startup failed: '+daemon.stderr+self.ssh_bind_diagnostics(cid))
        ready = False
        for _ in range(30):
            probe = self.call('exec', '--user', '1000:1000', cid, PYTHON, '-I', '-c',
                              'import socket;s=socket.create_connection(("127.0.0.1",2222),.2);s.close()')
            if probe.returncode == 0:
                ready = True
                break
            time.sleep(0.1)
        if not ready:
            self.fail('owned host-bind SSH listener unavailable'+self.ssh_bind_diagnostics(cid))
        pid = self.checked('exec', '--user', '1000:1000', cid, '/bin/cat',
                           '/home/dev/.ssh/sshd.pid')
        self.assertRegex(pid, r'^[0-9]+$')
        self.auth_values({})
        denied = self.invoke('ssh-batch', self.client, port, '0', '0', '/bin/true')
        self.assertEqual(denied.returncode, 255,
                         'stale authorization unexpectedly accepted SSH: '+denied.stderr)
        self.assertIn('Permission denied', denied.stderr)
        self.assertIn('publickey', denied.stderr)
        known_hosts = (self.client / 'known_hosts').read_bytes()

        # Execute the actual shell prerequisite, not merely the lower-level
        # helper. Only these four production functions are needed by it.
        source = (ROOT / 'bin/c0').read_text()
        names = ('c0_host_io', 'c0_ssh_write_sshd_config', 'c0_ssh_keygen', 'c0_ssh_ensure_keys')
        functions = []
        for name in names:
            match = re.search(r'^'+name+r'\(\) \{\n.*?^\}', source, re.M | re.S)
            self.assertIsNotNone(match, 'missing production attachment prerequisite')
            functions.append(match.group())
        ensure_env = dict(self.env, C0_HOST_IO=str(self.bin / 'c0-host-io'),
                          C0_SSH_DIR=str(self.guest_ssh), C0_SSH_CLIENT_DIR=str(self.client),
                          C0_INSTANCE_ID='native-'+self.token, IN_CONTAINER='false',
                          C0_SSH_AUTH_SOCK_PATH='/tmp/disabled-native-agent.sock')
        reconciled = subprocess.run(['/bin/bash', '-c', 'set -e\n'+'\n'.join(functions)+
                                     '\nc0_ssh_ensure_keys\n'], env=ensure_env,
                                    capture_output=True, text=True, timeout=20)
        self.assertEqual(reconciled.returncode, 0, 'host attachment reconciliation failed')
        self.assertFalse('PRIVATE KEY' in reconciled.stdout+reconciled.stderr)
        self.assertIn(retained, authorized.read_bytes())
        self.assertIn(active.strip(), authorized.read_bytes().splitlines())
        self.assertTrue((self.client / 'id_ed25519').read_bytes() == private)
        self.assertTrue((self.guest_ssh / 'ssh_host_ed25519_key').read_bytes() == server)
        mounted = self.checked('exec', '--user', '1000:1000', cid, PYTHON, '-I', '-c',
            'import hashlib,pathlib; print(hashlib.sha256(pathlib.Path('
            '"/home/dev/.ssh/authorized_keys").read_bytes()).hexdigest())')
        self.assertEqual(mounted, hashlib.sha256(authorized.read_bytes()).hexdigest(),
                         'host authorization replacement was not visible through the bind')
        self.assertEqual(self.checked('exec', '--user', '1000:1000', cid, '/bin/cat',
                                     '/home/dev/.ssh/sshd.pid'), pid, 'test replaced its live sshd')
        values = dict(AUTH_TOKEN='fixture-secret-repaired-native-ssh', EMPTY='')
        self.auth_values(values)
        remote = 'cd '+shlex.quote(project)+' && '+shlex.join([
            PYTHON, '-I', '/home/dev/observe.py', json.dumps(list(values)), '43'])
        accepted = self.invoke('ssh-batch', self.client, port, '0', '0', remote)
        if accepted.returncode != 43:
            self.fail('reconciled host-bind SSH failed: '+accepted.stderr+self.ssh_bind_diagnostics(cid))
        trace = self.assert_report(accepted, values, 1000, 43, cwd=project)
        self.assertEqual(trace['identity'], digest(str(self.client / 'id_ed25519')))
        self.assertEqual(trace['knownhosts'], [digest('UserKnownHostsFile='+str(self.client / 'known_hosts'))])
        self.assertTrue((self.client / 'known_hosts').read_bytes() == known_hosts)
        absent = self.checked('exec', '--user', '1000:1000', cid, PYTHON, '-I', '-c',
            'import pathlib; p=pathlib.Path("/home/dev/.ssh"); '
            'print(int(not any((p/n).exists() for n in '
            '("id_ed25519","legacy-keys","known_hosts"))))')
        self.assertEqual(absent, '1', 'host client/trust state reached the guest mount')
        self.owned_container(cid)


if __name__ == '__main__':
    unittest.main()
