"""Merge the official ALab base/camera ZIPs into a separate asset checkout."""
import argparse
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import time
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument('--assets', type=Path, required=True)
parser.add_argument('--downloads', type=Path, required=True)
args = parser.parse_args()
root = args.assets.resolve()
assert root.is_dir() and (root / 'entry.usda').is_file(), 'Expected the official ALab asset structure'
report = {'assets': str(root), 'packages': []}
for filename, strip in [('alab-techvars.v2.2.0.zip', 'techvar_assets/'),
                        ('alab-cameras.v2.2.0.zip', '')]:
    archive = args.downloads / filename
    started = time.monotonic()
    count, total = 0, 0
    with zipfile.ZipFile(archive) as source:
        for item in source.infolist():
            name = item.filename
            if strip:
                if not name.startswith(strip):
                    raise ValueError('Unexpected archive prefix: ' + name)
                name = name[len(strip):]
            relative = PurePosixPath(name)
            if not name or item.is_dir():
                continue
            if (relative.is_absolute() or '..' in relative.parts or ':' in name or '\\' in name
                    or stat.S_ISLNK(item.external_attr >> 16)):
                raise ValueError('Unsafe archive entry: ' + name)
            target = (root / Path(*relative.parts)).resolve()
            if not target.is_relative_to(root):
                raise ValueError('Archive entry escapes destination: ' + name)
            target.parent.mkdir(parents=True, exist_ok=True)
            # Reading each member completely verifies its ZIP CRC.
            with source.open(item) as input_file, target.open('wb') as output_file:
                shutil.copyfileobj(input_file, output_file, 1024 * 1024)
            count += 1
            total += item.file_size
    record = {'archive': str(archive.resolve()), 'files': count, 'expanded_bytes': total,
              'seconds': round(time.monotonic() - started, 2), 'member_crcs_verified': True}
    report['packages'].append(record)
    print(json.dumps(record), flush=True)
(args.downloads / 'extraction.json').write_text(json.dumps(report, indent=2) + '\n')
