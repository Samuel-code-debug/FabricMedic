"""Bounded, read-only discovery of launcher instances."""
import json
import os
from pathlib import Path

def inspect_instance(folder):
    folder = Path(folder)
    config = folder.parent / (folder.parent.name + '.json')
    try:
        data = json.loads(config.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None
    version = data.get('clientVersion') or data.get('inheritsFrom')
    libraries = ' '.join(x.get('name', '') for x in data.get('libraries', [])).lower()
    if not version:
        for item in data.get('patches', []):
            if item.get('id') == 'game': version = item.get('version')
    # Never interpret a user-customized instance name as a Minecraft version.
    if not version:
        return None
    loader = 'forge' if 'net.minecraftforge:' in libraries else 'fabric' if 'fabric-loader' in libraries else None
    if loader == 'forge' and any('connector' in f.name.lower() for f in folder.glob('*.jar')):
        loader = 'mix'
    return {'path': str(folder.resolve()), 'version': version, 'loader': loader}

def discover(known=(), roots=None):
    if roots is None:
        roots = [Path(os.environ.get('APPDATA', str(Path.home()))) / '.minecraft', Path.home() / 'Desktop', Path.home() / 'Downloads']
        roots += [Path(f'{d}:/') for d in 'CDEFG' if Path(f'{d}:/').exists()]
        roots += [Path(p).parent.parent.parent for p in known]
    found = {}
    pending = [(Path(p), 0) for p in roots]
    seen = set()
    budget = 2500
    while pending and budget:
        root, depth = pending.pop(0)
        key = str(root).lower()
        if key in seen or root.is_symlink(): continue
        seen.add(key)
        budget -= 1
        if root.name.lower() == 'mods':
            record = inspect_instance(root)
            if record: found[record['path'].lower()] = record
            continue
        try:
            children = list(root.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir() or child.is_symlink(): continue
            name = child.name.lower()
            if name in {'windows','program files','program files (x86)','appdata','$recycle.bin','system volume information','.git','node_modules','assets','libraries','logs','saves'}: continue
            if name == 'mods' or depth < 2 or name in {'.minecraft','versions','instances','minecraft'} or root.name.lower() in {'versions','instances'}:
                pending.append((child, depth + 1))
    return sorted(found.values(), key=lambda x: x['path'].lower())
