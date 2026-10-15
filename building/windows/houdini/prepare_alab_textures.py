"""Prepare ALab's ASCII texture layers without scanning its geometry payloads.

Run with the standalone MoonRay worker's Python after sourcing Setup.ps1.
The asset checkout is a disposable working copy; original downloads stay intact.
"""
import argparse
from pathlib import Path
import re
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--assets', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
parser.add_argument('--converters', type=int, default=4)
args = parser.parse_args()
pattern = re.compile(r'@[^@]*\.(?:jpg|jpeg|png|exr|tif|tiff|hdr)@', re.I)
# The entity preview layers contain optional billboard cards, which are not
# used by the render-purpose geometry in this test.
layers = [p for p in (args.assets.resolve() / 'fragment').rglob('*.usda')
          if pattern.search(p.read_text(encoding='utf-8'))]
args.out.mkdir(parents=True, exist_ok=True)
entry = args.out.resolve() / 'texture_layers.usda'
entry.write_text('#usda 1.0\n(\n    subLayers = [\n' +
                 ',\n'.join('        @' + p.as_posix() + '@' for p in sorted(layers)) +
                 '\n    ]\n)\n', encoding='utf-8')
print(f'Preparing textures from {len(layers)} image-bearing layers', flush=True)
tool = Path(__file__).resolve().parents[3] / 'moonray/hydra/hdMoonray/cmd/usd_mipmap_images/usd_mipmap_images'
raise SystemExit(subprocess.call([sys.executable, str(tool), str(entry),
                                 '--max_threads', str(args.converters)]))
