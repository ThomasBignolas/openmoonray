"""Validate Cryptomatte manifests, lossless IDs, coverage and extra data in EXRs.

Run with the standalone worker's Python after sourcing its Setup.ps1.
"""
import argparse
import json
import math
import os
from pathlib import Path
import struct

handles = []
for folder in os.environ['PATH'].split(os.pathsep):
    try:
        handles.append(os.add_dll_directory(folder))
    except OSError:
        pass
import OpenImageIO as oiio


def validate(filename, all_extensions=False):
    first = oiio.ImageBuf(str(filename))
    assert first.read(), first.geterror()
    parts, stats = {}, {}
    for index in range(first.nsubimages):
        image = oiio.ImageBuf(str(filename), index, 0)
        assert image.read(index, 0, True), image.geterror()
        spec = image.spec()
        name = spec.get_string_attribute('oiio:subimagename') or spec.get_string_attribute('name')
        parts[name] = image
        stat = oiio.ImageBufAlgo.computePixelStats(image)
        stats[name] = {'channels': spec.nchannels, 'min': list(stat.min), 'max': list(stat.max),
                       'nan_count': list(stat.nancount), 'inf_count': list(stat.infcount)}
        assert not any(stat.nancount), (name, 'NaNs')
        if name not in ('depth', 'Z') and not name.endswith('_depth'):
            assert not any(stat.infcount), (name, 'infinities')
    beauty = next((image for name, image in parts.items() if name == 'beauty' or name.endswith('_beauty')), None)
    if beauty is not None:
        assert beauty.spec().nchannels == 4, 'Beauty must preserve RGBA'
    metadata = {p.name: p.value for p in first.spec().extra_attribs}
    layers = {}
    for key, name in metadata.items():
        if not key.startswith('cryptomatte/') or not key.endswith('/name'):
            continue
        prefix = key[:-4]
        assert metadata[prefix + 'hash'] == 'MurmurHash3_32'
        assert metadata[prefix + 'conversion'] == 'uint32_to_float32'
        manifest = json.loads(metadata[prefix + 'manifest'])
        expected = {}
        for obj, value in manifest.items():
            bits = int(value, 16)
            if ((bits >> 23) & 255) in (0, 255):
                bits ^= 1 << 23
            expected[bits] = obj
        images = [parts[k] for k in sorted(parts) if k.startswith(name)
                  and len(k) == len(name) + 2 and k[-2:].isdigit()]
        assert images, ('Missing layers', name)
        for image in images:
            assert image.spec().nchannels == 4
            assert str(image.spec().format) == 'float', (name, image.spec().format)
        seen, mixed, max_alpha_error = set(), 0, 0.0
        w, h = first.spec().width, first.spec().height
        for y in range(h):
            for x in range(w):
                coverage, active = 0.0, 0
                for image in images:
                    pixel = image.getpixel(x, y)
                    for i in (0, 2):
                        value, weight = pixel[i:i + 2]
                        assert -1e-6 <= weight <= 1.00001, (name, x, y, weight)
                        if weight > 0:
                            bits = struct.unpack('<I', struct.pack('<f', value))[0]
                            assert bits in expected, (name, x, y, hex(bits), 'ID absent from manifest')
                            seen.add(expected[bits])
                            active += 1
                        coverage += weight
                assert coverage <= 1.00001, (name, coverage)
                mixed += active > 1
                if name == 'Cryptomatte' and beauty is not None:
                    max_alpha_error = max(max_alpha_error, abs(coverage - beauty.getpixel(x, y)[3]))
        if name == 'Cryptomatte':
            assert len(seen) >= 3, seen
            assert mixed > 0, 'No mixed coverage samples'
            assert max_alpha_error < 1e-5, max_alpha_error
        layers[name] = {'visible_objects': sorted(seen), 'mixed_pixels': mixed,
                        'max_alpha_error': max_alpha_error, 'manifest': manifest}
    assert layers, 'Missing Cryptomatte metadata'
    case_path = filename.parent / 'test-case.json'
    if case_path.exists():
        case = json.loads(case_path.read_text())
        if case.get('geometry'):
            expected_geometry = {'/groom'} | {'/scatter/instance_' + str(i) for i in range(4)}
            assert expected_geometry <= set(layers['Cryptomatte']['visible_objects']), layers['Cryptomatte']['visible_objects']
        if case.get('optics'):
            assert '/copper/mesh_0' not in layers['CryptomatteReflect']['visible_objects']
            assert '/ceramic/mesh_0' not in layers['CryptomatteRefract']['visible_objects']
            assert '/floor/mesh_0' in layers['CryptomatteReflect']['visible_objects']
            assert '/floor/mesh_0' in layers['CryptomatteRefract']['visible_objects']
    if all_extensions:
        for kind in ('', 'Reflect', 'Refract'):
            for suffix, channels in [('P', 4), ('P0', 4), ('N', 4), ('B', 4), ('RefP', 4), ('RefN', 4), ('UV', 2), ('S', 2)]:
                for index in range(4):  # Depth three has two padded pairs.
                    key = 'Crypto' + kind + suffix + f'{index:02d}'
                    assert key in stats, ('Missing extension', key)
                    assert stats[key]['channels'] == channels, key
        for key in ('CryptoP000', 'CryptoRefP00', 'CryptoRefN00', 'CryptoN00', 'CryptoUV00', 'CryptoB00'):
            assert any(abs(v) > 0.01 for v in stats[key]['min'] + stats[key]['max']), ('Empty extension', key)
        for key in ('CryptoN00', 'CryptoRefN00'):
            assert max(abs(v) for v in stats[key]['min'] + stats[key]['max']) <= 1.0001
    for key in ('P', 'Wp', 'CryptoP00'):
        if key in stats:
            assert max(stats[key]['max'][:3]) - min(stats[key]['min'][:3]) > 1
    return {'image': str(filename), 'resolution': [first.spec().width, first.spec().height],
            'parts': stats, 'cryptomatte': layers, 'passed': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('images', nargs='+', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--all-extensions', action='store_true')
    args = parser.parse_args()
    reports = [validate(path, args.all_extensions) for path in args.images]
    if len(args.images) == 2:
        def crypto_position(path):
            image = oiio.ImageBuf(str(path))
            image.read()
            for index in range(image.nsubimages):
                part = oiio.ImageBuf(str(path), index, 0)
                part.read(index, 0, True)
                if part.spec().get_string_attribute('name') == 'CryptoP00':
                    return part
            raise AssertionError('Missing CryptoP00')
        delta = oiio.ImageBufAlgo.compare(crypto_position(args.images[0]), crypto_position(args.images[1]), 1e-6, 1e-6)
        assert delta.meanerror > 0.01, ('CryptoP did not update', delta.meanerror)
        reports[1]['position_animation_mean_change'] = delta.meanerror
    args.report.write_text(json.dumps(reports, indent=2) + '\n')
    print(json.dumps([{'image': r['image'], 'layers': len(r['parts']), 'passed': r['passed'],
                       'cryptomatte': r['cryptomatte']} for r in reports], indent=2))
