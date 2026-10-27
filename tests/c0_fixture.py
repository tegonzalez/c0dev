# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Run the actual c0 CLI against a stateful Docker double and an isolated checkout."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
DOCKER = r'''
import copy, fcntl, hashlib, json, os, re, sys
from pathlib import Path
args = sys.argv[1:]
state_path = Path(os.environ['TEST_DOCKER_STATE'])
lock = open(str(state_path)+'.lock', 'w')
fcntl.flock(lock, fcntl.LOCK_EX)
state = json.loads(state_path.read_text())
state.setdefault('calls', []).append(args)
def finish(code=0, output=''):
    state_path.write_text(json.dumps(state))
    if output: print(output, file=sys.stderr if code else sys.stdout)
    sys.exit(code)
def flags(names):
    return [args[i+1] for i, a in enumerate(args[:-1]) if a in names]
def labels(c):
    result = copy.deepcopy(c.get('config', {}).get('Labels') or {})
    result.update({'c0dev.instance': c['instance'], 'c0dev.tools_hash': c['tools'],
                 'c0dev.tools_volume': c.get('volume', 'c0dev-tools-shared'),
                 'c0dev.security_mode': c.get('security', 'permissive'),
                 'com.docker.compose.project': c['instance'],
                 'com.docker.compose.service': 'c0dev'})
    result.update(c.get('labels', {}))
    return result
def specification(c):
    mounts = [dict(Type=m['type'], Source=m['source'], Destination=m['target'],
                   RW=m['rw'], Name=m.get('name', '')) for m in c['mounts']]
    config = dict(User='dev', Hostname=c['instance'], Image=c.get('image', 'fixture-runtime:latest'),
                  Env=['HOME=/home/dev', 'TOOLS_PREFIX=/tools/current'],
                  Entrypoint=['/bin/bash', '/usr/local/bin/docker-entrypoint.sh'], Cmd=[])
    config.update(copy.deepcopy(c.get('config', {})))
    config['Labels'] = labels(c)
    return dict(Id=c['id'], Name='/'+c['name'], Image=c.get('image', 'sha256:'+'1'*64),
                ImageManifestDescriptor=dict(platform=dict(os='linux', architecture='arm64')),
                State=dict(Status=c['state'], Running=c['state']=='running', Paused=c['state']=='paused',
                           StartedAt='2026-10-24T00:00:00Z'),
                Config=config,
                Mounts=mounts, HostConfig=dict(PortBindings={
                    '2222/tcp':[dict(HostIp='127.0.0.1', HostPort='2223')],
                    '3000/tcp':[dict(HostIp='', HostPort='3001')]}))
def selected():
    result = list(state['containers'])
    for expr in flags(('-f', '--filter')):
        if expr.startswith('label='):
            key, separator, value = expr[6:].partition('=')
            result = [c for c in result if (labels(c).get(key) == value if separator else key in labels(c))]
    if not any(a in args for a in ('-a', '-aq', '-qa', '--all')):
        result = [c for c in result if c['state'] in ('running', 'paused', 'restarting')]
    return result
op = args[0]
if state.get('fail', {}).get(op): finish(state['fail'][op])
if op == 'version': finish(output='test-server')
if op == 'ps':
    if state.get('fail_ps_after_stop') and state.get('stopped'): finish(23)
    containers = selected()
    if '--format' in args:
        fmt = flags(('--format',))[0]
        if '.ID' in fmt and '.Names' in fmt:
            finish(output='\n'.join(c['id']+'\t'+c['name'] for c in containers))
        if fmt == '{{.ID}}': finish(output='\n'.join(c['id'] for c in containers))
        if fmt == '{{.Names}}': finish(output='\n'.join(c['name'] for c in containers))
        finish(output='\n'.join(c['name']+' ('+c['instance']+', '+c['state']+')' for c in containers))
    finish(output='\n'.join(c['id'] for c in containers))
if op == 'inspect':
    selector = next((a for a in args[1:] if any(a in (c['id'], c['name'], '/'+c['name'])
                                              for c in state['containers'])), None)
    c = next((c for c in state['containers'] if selector in (c['id'], c['name'], '/'+c['name'])), None)
    if not c: finish(1)
    formats = flags(('-f', '--format'))
    if not formats: finish(output=json.dumps([specification(c)]))
    fmt = formats[0]
    if fmt == '{{json .}}': finish(output=json.dumps(specification(c)))
    if fmt == '{{.Id}}': finish(output=c['id'])
    if fmt == '{{.Image}}': finish(output=c.get('image', 'sha256:'+'1'*64))
    if '.State.StartedAt' in fmt: finish(output='2026-10-24T00:00:00Z')
    if '.State.Status' in fmt: finish(output=c['state'])
    if fmt == '{{.Name}}': finish(output='/'+c['name'])
    if '.Config.User' in fmt: finish(output='dev')
    if 'c0dev.home_overlays_volume' in fmt: finish(output=c.get('labels', {}).get('c0dev.home_overlays_volume', ''))
    if 'c0dev.instance' in fmt: finish(output=c['instance'])
    if 'c0dev.security_mode' in fmt: finish(output=c.get('security', 'seccomp'))
    if 'c0dev.tools_hash' in fmt: finish(output=c['tools'])
    if '3000/tcp' in fmt: finish(output='3001')
    if '2222/tcp' in fmt: finish(output='2223')
    if '.NetworkSettings.Networks' in fmt: finish(output='192.0.2.10')
    if '.HostConfig.Mounts' in fmt: finish(output=c.get('subpath', 'opt/'+c['tools']))
    if '.Mounts' in fmt:
        if 'printf' in fmt:
            finish(output='\n'.join('\t'.join((m['type'], m['source'], m['target'], str(m['rw']).lower(), m.get('name', '-'))) for m in c['mounts']))
        if '/run/c0/overlay-state' in fmt:
            mount = next((m for m in c['mounts'] if m['target'] == '/run/c0/overlay-state'), None)
            if not mount: finish()
            finish(output=mount.get('name', '') if '.Name' in fmt else str(mount['rw']).lower())
    finish(98, 'unhandled inspect template: '+fmt)
if op == 'image' and args[1] == 'inspect':
    tag = next((arg for arg in args[2:] if arg in state.get('images', {})), args[-1])
    image = state.get('images', {}).get(tag)
    if not image:
        image = next((value for value in state.get('images', {}).values() if value['id'] == tag), None)
    if not image:
        # Runtime availability is independent of the optional toolchain build.
        image = dict(id='sha256:'+'1'*64, Config=dict(Labels={}))
        state.setdefault('images', {})[tag] = image
    if '--format' in args or '-f' in args:
        finish(output=image['id'] if image else 'sha256:'+'1'*64)
    result = dict(Id=image['id'] if image else 'sha256:'+'1'*64,
                  Config=image.get('Config', dict(Labels={})) if image else dict(Labels={}))
    if image:
        for key in ('RootFS', 'Os', 'Architecture', 'Variant'):
            if key in image: result[key] = image[key]
    finish(output=json.dumps([result]))
if op == 'image' and args[1] == 'tag':
    source = state.get('images', {}).get(args[-2])
    if not source:
        source = next((value for value in state.get('images', {}).values() if value['id'] == args[-2]), None)
    if not source: finish(1)
    state.setdefault('images', {})[args[-1]] = copy.deepcopy(source)
    finish()
if op in ('stop', 'start', 'unpause', 'pause', 'rm'):
    for cid in args[1:]:
        c = next((c for c in state['containers'] if c['id'] == cid), None)
        if not c: finish(1)
        if op == 'stop':
            state['stopped'] = True
            if not state.get('ignore_stop'): c['state'] = 'exited'
        elif op in ('start', 'unpause'):
            c['state'] = state.get('started_state_by_id', {}).get(c['id'], state.get('started_state', 'running'))
        elif op == 'pause': c['state'] = 'paused'
        elif c['state'] == 'running' and '-f' not in args and '--force' not in args: finish(1)
        elif not state.get('ignore_rm'): state['containers'].remove(c)
    finish()
if op == 'compose':
    if 'config' in args:
        finish(state.get('compose_config_status', 0),
               state.get('compose_image', 'fixture-runtime:latest') if '--images' in args else '')
    if 'up' in args or 'run' in args:
        if state.get('compose_run_status'): finish(state['compose_run_status'])
        if state.get('compose_up_empty'): finish()
        c = copy.deepcopy(state['new_container'])
        state['creations'] = state.get('creations', 0) + 1
        if state['creations'] > 1 or any(container['id'] == c['id'] for container in state['containers']):
            c['id'] = hashlib.sha256((c['id'] + str(state['creations'])).encode()).hexdigest()
        if '--name' in args: c['name'] = flags(('--name',))[0]
        c['labels'] = dict(c.get('labels', {}))
        for label in flags(('--label',)):
            key, value = label.split('=', 1)
            c['labels'][key] = value
        for file in flags(('-f',)):
            for line in Path(file).read_text().splitlines() if Path(file).exists() else ():
                if line.strip().startswith('image:'):
                    image = line.split(':', 1)[1].strip().strip('\"\'')
                    if image in state.get('images', {}):
                        saved = state['images'][image]
                        c['image'] = saved['id']
        overlay = os.environ.get('C0_HOME_OVERLAYS_VOLUME')
        if overlay:
            for mount in c['mounts']:
                if mount['target'] == '/run/c0/overlay-state':
                    mount['name'] = overlay
                    mount['source'] = '/var/lib/docker/volumes/' + overlay + '/_data'
        if os.environ.get('TOOLS_ID'): c['tools'] = os.environ['TOOLS_ID']
        c['state'] = state.get('started_state', 'running')
        c['security'] = os.environ.get('C0_SECURITY', 'permissive')
        state['containers'].append(c)
        finish()
    if 'logs' in args or 'ps' in args:
        if 'ps' in args: finish(output='\n'.join(c['id'] for c in selected()))
        finish()
    finish(99, 'unexpected compose operation: '+repr(args))
if op == 'volume' and args[1] == 'inspect':
    name = args[-1]
    volume = state.get('volumes', {}).get(name)
    if volume is None:
        if re.search(r'-home-overlays-[0-9a-f]{32}$', name): finish(1)
        if not state.get('volume_exists', True): finish(1)
        volume = dict(Labels={}, data={})
    formats = flags(('-f', '--format'))
    if formats:
        for key in ('c0dev.instance', 'c0dev.overlay_generation'):
            if key in formats[0]: finish(output=volume.get('Labels', {}).get(key, ''))
        finish(98, 'unhandled volume inspection')
    finish(output=json.dumps([dict(Name=name, **volume)]))
if op == 'volume' and args[1] == 'create':
    name = args[-1]
    values = dict(value.split('=', 1) for value in flags(('--label',)))
    state.setdefault('volumes', {})[name] = dict(Labels=values, data={})
    finish(output=name)
if op == 'run':
    mounts = flags(('--mount',))
    if 'rm -rf /state/upper /state/work' in ' '.join(args):
        state_volume = next((value.split('src=', 1)[1].split(',', 1)[0] for value in mounts
                             if 'dst=/state' in value), None)
        for name in flags(('-v',)):
            if name.endswith(':/state'):
                state_volume = name[:-7]
        if state_volume:
            data = state.setdefault('volumes', {}).setdefault(state_volume, dict(Labels={}, data={}))['data']
            for key in list(data):
                relative = key.lstrip('/')
                if relative in ('upper', 'work') or relative.startswith(('upper/', 'work/')):
                    del data[key]
    finish()
if op == 'exec':
    cid = next((a for a in args[1:] if any(c['id'] == a for c in state['containers'])), None)
    c = next((c for c in state['containers'] if c['id'] == cid), None)
    if not c or c['state'] != 'running': finish(1)
    if 'c0-mount-check' in args:
        if c.get('bad_guest'):
            finish(1, 'error: inaccessible guest path '+c['bad_guest'])
        if c.get('exit_after_probe'): c['state'] = 'exited'
        finish()
    finish(state.get('shell_status', 0))
if op == 'logs':
    c = next((c for c in state['containers'] if c['id'] in args), None)
    finish(output='' if c and c.get('not_ready') else 'c0dev ready')
finish(99, 'unexpected docker operation: '+repr(args))
'''


class Fixture:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(prefix='c0-lifecycle-')
        self.root = Path(self.temp.name).resolve()
        self.checkout = self.root/'checkout'
        (self.checkout/'bin').mkdir(parents=True)
        shutil.copytree(REPO/'docker', self.checkout/'docker', ignore=shutil.ignore_patterns('.terminfo', '.Dockerfile*', '.compose.*'))
        for name in ('c0', 'docker-hash', 'dockerfile-concat', 'activate', 'list-listening-ports'):
            shutil.copy2(REPO/'bin'/name, self.checkout/'bin'/name)
        for name in ('c0-terminfo', 'c0-toolchain'):
            if (REPO/'bin'/name).exists():
                shutil.copy2(REPO/'bin'/name, self.checkout/'bin'/name)
        self.home = self.root/'home'
        self.home.mkdir()
        (self.home/'.gitconfig').write_text('[user]\n name = fixture\n')
        for name in ('.claude', '.cache', '.codex', '.kimi-code', '.config', '.local', 'rules', 'projects', 'bin', 'auth/ssh'):
            (self.checkout/name).mkdir(parents=True, exist_ok=True)
        (self.checkout/'.claude.json').write_text('{}')
        for name in ('authorized_keys', 'id_ed25519', 'id_ed25519.pub', 'ssh_host_ed25519_key'):
            (self.checkout/'auth/ssh'/name).write_text('fixture\n')
        self.tools = subprocess.check_output([str(self.checkout/'bin/docker-hash'), str(self.checkout/'docker/Dockerfile.base'), str(self.checkout/'docker/Dockerfile.tools')], text=True).strip()
        self.instance = 'c0dev-'+__import__('hashlib').sha256(str(self.checkout).encode()).hexdigest()[:8]
        mock_bin = self.root/'mock-bin'
        mock_bin.mkdir()
        (mock_bin/'docker').write_text('#!'+sys.executable+'\n'+DOCKER)
        (mock_bin/'docker').chmod(0o755)
        (mock_bin/'ssh').write_text('#!'+sys.executable+'\n'
            'import json, os, sys\n'
            'from pathlib import Path\n'
            'Path(os.environ["TEST_SSH_ARGS"]).write_text(json.dumps(sys.argv[1:]))\n'
            'sys.exit(int(os.environ.get("TEST_SSH_STATUS", "0")))\n')
        (mock_bin/'ssh').chmod(0o755)
        self.state_path = self.root/'state.json'
        self.env = dict(os.environ, PATH=str(mock_bin)+os.pathsep+os.environ['PATH'], HOME=str(self.home),
                        TEST_DOCKER_STATE=str(self.state_path), TEST_SSH_ARGS=str(self.root/'ssh-args.json'),
                        C0_MODE='', C0_SSH_AGENT='0',
                        C0_SECCOMP_NOTIFY='0', C0DEV_WEB_PORT='3001', C0DEV_SSH_PORT='2223', TERM='xterm')
        self.env.pop('C0_SECURITY', None)
        self.env.pop('C0_SECURITY_RESOLVED', None)
        container = self.container()
        self.write(dict(containers=[container], new_container=self.container('new-runtime', oneoff=False), calls=[]))

    def close(self): self.temp.cleanup()
    def read(self): return json.loads(self.state_path.read_text())
    def write(self, state): self.state_path.write_text(json.dumps(state))

    def container(self, cid='oneoff-runtime', oneoff=True, state='running'):
        mounts = []
        for relative, target, ro in (
            ('.claude', '.claude', False), ('.cache', '.cache', False), ('.codex', '.codex', False),
            ('.kimi-code', '.kimi-code', False), ('.config', '.config', False), ('.local', '.local-rw', False),
            ('rules', 'rules', False), ('projects', 'projects', False), ('auth/ssh', '.ssh', False),
            ('.claude.json', '.claude.json', False)):
            mounts.append(dict(type='bind', source=str(self.checkout/relative), target='/home/dev/'+target, rw=not ro))
        mounts.append(dict(type='bind', source=str(self.home/'.gitconfig'), target='/home/dev/.gitconfig', rw=False))
        mounts.append(dict(type='bind', source=str(self.checkout/'bin'), target='/run/c0/host-bin', rw=False))
        for source, target in (('docker/docker-entrypoint.sh', '/usr/local/bin/docker-entrypoint.sh'),
                               ('docker/home-overlays.conf', '/etc/c0dev/home-overlays.conf'),
                               ('docker/c0-overlay-check', '/usr/local/bin/c0-overlay-check')):
            mounts.append(dict(type='bind', source=str(self.checkout/source), target=target, rw=False))
        for name, target, rw in (('c0dev-tools-shared', '/tools/current', False), (self.instance+'-home-overlays', '/run/c0/overlay-state', True)):
            mounts.append(dict(type='volume', name=name, source='/var/lib/docker/volumes/'+name+'/_data', target=target, rw=rw))
        return dict(id=cid, instance=self.instance, name=self.instance+('-c0dev-run-123' if oneoff else '-c0dev-1'),
                    oneoff=oneoff, state=state, tools=self.tools, security='seccomp', volume='c0dev-tools-shared', mounts=mounts)

    def run(self, *args, **kwargs):
        return subprocess.run(['/bin/bash', str(self.checkout/'bin/c0'), *args], env=self.env,
                              cwd=kwargs.pop('cwd', str(self.checkout)), capture_output=True, text=True, timeout=10, **kwargs)

    def legacy_container(self, cid='a'*64, state='running'):
        container = self.container(cid, oneoff=False, state=state)
        container['security'] = 'permissive'
        for mount in container['mounts']:
            if mount['target'] == '/run/c0/host-bin':
                mount.update(target='/home/dev/bin', rw=True)
            elif mount['target'] == '/home/dev/.gitconfig':
                mount['rw'] = True
        return container
