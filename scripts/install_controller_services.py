#!/usr/bin/env python3
"""Install per-user launchd services for this Mac's USB controller."""
import argparse
from pathlib import Path
import plistlib
import subprocess
import os

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--tunnel', action='store_true', help='Also install the tunnel after its token is provisioned')
args = parser.parse_args()
runtime = ROOT / '.runtime/controller'
runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
agents = Path.home() / 'Library/LaunchAgents'
agents.mkdir(parents=True, exist_ok=True)
services = [('com.66ccff.ir-controller', 'run.sh')]
if args.tunnel:
    if not (runtime / 'tunnel-token').is_file():
        parser.error('Provision the controller tunnel token first')
    services.append(('com.66ccff.ir-controller-tunnel', 'tunnel.sh'))
for label, script in services:
    target = agents / (label + '.plist')
    spec = {
        'Label': label,
        'ProgramArguments': ['/bin/sh', str(ROOT / 'controller' / script)],
        'WorkingDirectory': str(ROOT),
        'RunAtLoad': True,
        'KeepAlive': True,
        'ThrottleInterval': 10,
        'StandardOutPath': str(runtime / (label + '.log')),
        'StandardErrorPath': str(runtime / (label + '.error.log')),
        'Umask': 0o077,
    }
    if target.exists() and plistlib.loads(target.read_bytes()) != spec:
        parser.error(f'Refusing to replace a different existing service: {target}')
    target.write_bytes(plistlib.dumps(spec))
    target.chmod(0o600)
    domain = f'gui/{os.getuid()}'
    loaded = subprocess.run(['launchctl', 'print', domain + '/' + label], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if loaded.returncode:
        subprocess.run(['launchctl', 'bootstrap', domain, str(target)], check=True)
    print(f'Installed {label}')
