"""Compare CPU/GPU beauty and utility EXR parts and validate crypto separately."""
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
from validate_crypto_outputs import validate

parser = argparse.ArgumentParser()
parser.add_argument('--cpu', nargs='+', required=True, type=Path)
parser.add_argument('--gpu', nargs='+', required=True, type=Path)
parser.add_argument('--report', required=True, type=Path)
args = parser.parse_args()
assert len(args.cpu) == len(args.gpu)
reports, issues = [], []


def parts(path):
    first = oiio.ImageBuf(str(path))
    assert first.read(), first.geterror()
    result = {}
    for i in range(first.nsubimages):
        image = oiio.ImageBuf(str(path), i, 0)
        assert image.read(i, 0, True), image.geterror()
        spec = image.spec()
        name = spec.get_string_attribute('oiio:subimagename') or spec.get_string_attribute('name')
        result[name] = image
    return result


for cpu_file, gpu_file in zip(args.cpu, args.gpu):
    cpu, gpu = parts(cpu_file), parts(gpu_file)
    assert cpu.keys() == gpu.keys(), (list(cpu), list(gpu))
    record = {'cpu': str(cpu_file), 'gpu': str(gpu_file), 'parts': len(cpu), 'comparisons': {}}
    for name in cpu:
        a, b = cpu[name], gpu[name]
        sa, sb = a.spec(), b.spec()
        assert (sa.width, sa.height, sa.nchannels) == (sb.width, sb.height, sb.nchannels)
        if 'crypto' in name.lower():
            # Crypto layers contain bit-cast hashes whose numeric differences
            # have no useful error metric; validate manifests and coverage below.
            continue
        total, maximum, count, outside, same_special = 0., 0., 0, 0, True
        for y in range(sa.y, sa.y + sa.height):
            for x in range(sa.x, sa.x + sa.width):
                for av, bv in zip(a.getpixel(x, y), b.getpixel(x, y)):
                    assert not math.isnan(bv), (name, 'NaN')
                    if math.isfinite(av) and math.isfinite(bv):
                        error = abs(av - bv)
                        total += error
                        maximum = max(maximum, error)
                        outside += error > .001
                        count += 1
                    elif av != bv:
                        same_special = False
        mean = total / count if count else 0
        record['comparisons'][name] = {'mean_absolute_error': mean, 'max_absolute_error': maximum,
                                       'fraction_above_0.001': outside / count if count else 0,
                                       'finite_pixels_match': same_special}
        # Position/normal/UV values have discontinuities at silhouettes. One
        # boundary sample choosing a different triangle can make their maximum
        # error large despite matching interiors. Bound both average error and
        # the fraction of differing components; retain the maxima in the report.
        utility = name in ('P', 'Wp', 'N', 'St', 'normal', 'depth', 'Z')
        within_limit = mean <= 1e-4 and (outside <= count * .001 if utility else maximum <= .01)
        if not same_special or not within_limit:
            issues.append(f'{gpu_file.name}/{name}: mean={mean:.6g}, max={maximum:.6g}')
    if any('crypto' in name.lower() for name in gpu):
        record['crypto'] = validate(gpu_file)
    reports.append(record)
result = {'passed': not issues, 'frames': reports, 'issues': issues,
          'tolerance': {'mean_absolute_error': 1e-4, 'beauty_max_absolute_error': .01,
                        'utility_max_fraction_above_0.001': .001}}
args.report.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({'passed': result['passed'], 'issues': issues,
                  'comparisons': [r['comparisons'] for r in reports]}, indent=2))
assert not issues, issues
