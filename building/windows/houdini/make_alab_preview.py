"""Make a display preview of the actual MoonRay EXR without altering its data."""
import argparse
import json
from pathlib import Path

import OpenImageIO as oiio

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('image', type=Path)
parser.add_argument('output', type=Path)
args = parser.parse_args()
first = oiio.ImageBuf(str(args.image))
assert first.read(), first.geterror()
for index in range(first.nsubimages):
    part = oiio.ImageBuf(str(args.image), index, 0)
    assert part.read(index, 0, True), part.geterror()
    name = part.spec().get_string_attribute('name') or part.spec().get_string_attribute('oiio:subimagename')
    if name == 'beauty':
        break
else:
    raise RuntimeError('No beauty part in the EXR')
rgb = oiio.ImageBufAlgo.channels(part, (0, 1, 2))
preview = oiio.ImageBufAlgo.colorconvert(rgb, 'linear', 'sRGB')
assert not preview.has_error, preview.geterror()
preview.specmod().attribute('Copyright', 'Netflix Animation Studios ALab Copyright 2025 Netflix, Inc. All rights reserved.')
preview.specmod().attribute('ImageDescription', 'MoonRay CPU render; ALab 1K preview materials; linear to sRGB, no exposure adjustment.')
assert preview.write(str(args.output)), preview.geterror()
print(json.dumps({'preview': str(args.output), 'width': preview.spec().width, 'height': preview.spec().height}))
