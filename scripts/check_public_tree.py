#!/usr/bin/env python3
"""Check tracked publication inputs; report paths, never matched secret values."""
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
blocked_parts = {'.runtime', '.venv', '.tools', '.arduino', '__pycache__', '.pytest_cache', 'build', 'artifacts'}
blocked_names = {'credentials.json', 'access-code.txt', 'tunnel-token', 'service.env'}
patterns = [
    rb'gh[pousr]_[A-Za-z0-9]{30,}',
    rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    rb'eyJ[A-Za-z0-9_=-]{100,}',
    rb'AKIA[A-Z0-9]{16}',
]
errors = []
for name in filter(None, names):
    path = Path(name)
    if (set(path.parts) & blocked_parts or path.name in blocked_names
            or '.sqlite3' in path.name or (path.name.startswith('.env') and path.name != '.env.example')):
        errors.append(f'{name}: private/generated file is tracked')
    data = (ROOT / path).read_bytes()
    if any(re.search(pattern, data) for pattern in patterns):
        errors.append(f'{name}: possible credential; inspect locally')
    if path.suffix == '.md':
        # Check local Markdown links, including Unicode file names. Anchors and web URLs are excluded.
        for target in re.findall(r'\]\(([^)]+)\)', data.decode()):
            target = target.strip('<>').split('#', 1)[0]
            if not target or re.match(r'[A-Za-z]+:', target):
                continue
            if not (ROOT / path.parent / unquote(target)).exists():
                errors.append(f'{name}: missing local link {target}')
if errors:
    raise SystemExit('\n'.join(errors))
print(f'Public tree and local Markdown links checked: {len(list(filter(None, names)))} files')
