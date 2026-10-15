"""Check deep samples, depth ordering, channels, animation and flat beauty parity."""
import argparse
import json
import math
import os
from pathlib import Path

handles = []
for folder in os.environ['PATH'].split(os.pathsep):
    try:
        handles.append(os.add_dll_directory(folder))
    except OSError:
        pass
import OpenImageIO as oiio

parser = argparse.ArgumentParser()
parser.add_argument('images', nargs='+', type=Path)
parser.add_argument('--report', required=True, type=Path)
parser.add_argument('--samples-only', action='store_true', help='Validate deep-only products without a flat comparison.')
args = parser.parse_args()
reports = []
issues = []
for filename in args.images:
    image = oiio.ImageBuf(str(filename))
    assert image.read(), image.geterror()
    spec = image.spec()
    assert spec.deep, 'Output is not deep'
    names = list(spec.channelnames)
    formats = list(map(str, spec.channelformats)) if spec.channelformats else [str(spec.format)] * len(names)
    assert all(name in names for name in ('R', 'G', 'B', 'A', 'Z', 'ZBack'))
    assert all(fmt == 'float' for name, fmt in zip(names, formats) if name.startswith(('P.', 'N.', 'St.'))), formats
    dcx = 'deepabuf.sp1' in names
    total, multi, maximum, occupied = 0, 0, 0, 0
    position_sum, position_count = 0., 0
    native_ids = set()
    beauty_energy = 0.
    for y in range(spec.y, spec.y + spec.height):
        for x in range(spec.x, spec.x + spec.width):
            count = image.deep_samples(x, y)
            total += count
            multi += count > 1
            maximum = max(maximum, count)
            occupied += count > 0
            for sample in range(count):
                values = {name: image.deep_value(x, y, 0, channel, sample) for channel, name in enumerate(names)}
                # DCX mask channels encode raw bits, which may be NaN as floats.
                assert all(math.isfinite(v) for k, v in values.items() if not k.startswith('deepabuf.')), (x, y, sample, values)
                assert 0 <= values['A'] <= 1.001, values
                assert values['Z'] >= 0 and values['ZBack'] + 1e-5 >= values['Z'], values
                beauty_energy += abs(values['R']) + abs(values['G']) + abs(values['B'])
                if 'P.Y' in values:
                    position_sum += values['P.Y']
                    position_count += 1
                if 'deep.prim_id' in values:
                    native_ids.add(values['deep.prim_id'])
    assert total > 0 and occupied > 0
    assert beauty_energy > 0, 'Deep beauty is black'
    if 'deep.prim_id' in names:
        assert any(value != 0 for value in native_ids), 'Missing native object IDs'
    if args.samples_only:
        reports.append({'file': str(filename), 'format': 'dcx' if dcx else 'openexr', 'channels': names,
                        'channel_formats': formats, 'samples': total, 'occupied_pixels': occupied,
                        'multiple_sample_pixels': multi, 'max_samples': maximum,
                        'native_id_count': len(native_ids), 'beauty_energy': beauty_energy,
                        'mean_position_y': position_sum / position_count if position_count else None,
                        'flatten_compared': False})
        continue
    flat = oiio.ImageBufAlgo.flatten(image)
    beauty_path = filename.with_name(filename.name.replace('deep.', 'flat.', 1))
    beauty = oiio.ImageBuf(str(beauty_path))
    assert beauty.read(), beauty.geterror()
    assert (spec.width, spec.height, spec.x, spec.y) == (beauty.spec().width, beauty.spec().height, beauty.spec().x, beauty.spec().y)
    mean_delta, max_delta = [0.] * 4, [0.] * 4
    for y in range(spec.y, spec.y + spec.height):
        for x in range(spec.x, spec.x + spec.width):
            a, b = flat.getpixel(x, y), beauty.getpixel(x, y)
            for c in range(4):
                delta = abs(a[names.index('RGBA'[c])] - b[c])
                mean_delta[c] += delta / (spec.width * spec.height)
                max_delta[c] = max(max_delta[c], delta)
    # OIIO flatten does not interpret DCX subpixel masks. Compare ordinary EXR only.
    if not dcx and (max(mean_delta) >= 1e-4 or max(max_delta) >= 0.003):
        issues.append({'file': str(filename), 'issue': 'Flattened deep differs from flat beauty',
                       'mean_delta': mean_delta, 'max_delta': max_delta})
    reports.append({'file': str(filename), 'format': 'dcx' if dcx else 'openexr', 'channels': names,
                    'channel_formats': formats, 'samples': total, 'occupied_pixels': occupied, 'multiple_sample_pixels': multi,
                    'max_samples': maximum, 'mean_position_y': position_sum / position_count if position_count else None,
                    'native_id_count': len(native_ids),
                    'flatten_mean_delta': mean_delta, 'flatten_max_delta': max_delta,
                    'flatten_compared': not dcx})
if len(reports) > 1 and all(report['mean_position_y'] is not None for report in reports):
    assert abs(reports[0]['mean_position_y'] - reports[1]['mean_position_y']) > .001, 'Animation did not update deep samples'
args.report.write_text(json.dumps({'passed': not issues, 'frames': reports, 'issues': issues}, indent=2) + '\n')
print(json.dumps(reports, indent=2))
assert not issues, issues
