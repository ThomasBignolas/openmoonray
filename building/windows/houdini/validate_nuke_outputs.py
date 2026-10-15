"""Run with Nuke --safe -t -i -m 2 -c 256M; never opens or edits a user's script."""
import json
import math
import os
from pathlib import Path
import traceback
import nuke

root = Path(os.environ['MOONRAY_NUKE_TEST_ROOT'])
out = root / 'nuke-check'
out.mkdir(parents=True, exist_ok=True)
report = {'passed': False, 'nuke': nuke.NUKE_VERSION_STRING, 'checks': []}


def save():
    (out / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')


def read(path, deep=False):
    node = (nuke.nodes.DeepRead if deep else nuke.nodes.Read)(file=path.as_posix())
    if node.knob('raw'):
        node['raw'].setValue(True)
    return node


try:
    source = read(root / 'all-crypto-check/all-crypto.0001.exr')
    metadata = source.metadata()
    names = [key for key in metadata if 'cryptomatte/' in key and key.endswith('/name')]
    assert len(names) >= 3, ('Missing regular/reflected/refracted metadata', names)
    channels = source.channels()
    report['flat_channels'] = channels
    for prefix in ('CryptoP00.', 'CryptoN00.', 'CryptoUV00.'):
        assert any(c.startswith(prefix) for c in channels), ('Missing channels', prefix)
    for key in names:
        manifest = json.loads(metadata[key[:-4] + 'manifest'])
        matte = nuke.nodes.Cryptomatte(inputs=[source])
        matte.channels()  # Populate the layer choices from the input metadata.
        name = metadata[key]
        # Nuke's native node populates its menu only when a panel is open.
        # This persisted knob also selects the layer during headless rendering.
        matte['lastSelectedCryptoLayerName'].setValue(name)
        matte['matteList'].setValue(', '.join(manifest))
        values = [matte.sample('alpha', x + .5, y + .5)
                  for y in range(2, source.height(), 8) for x in range(2, source.width(), 8)]
        assert all(math.isfinite(v) and -1e-6 <= v <= 1.00001 for v in values)
        assert max(values) > 0.1, ('Cryptomatte selection is empty', name)
        matte['matteList'].setValue('/__MoonRay_nonexistent_object__')
        empty = [matte.sample('alpha', x + .5, y + .5)
                 for y in range(2, source.height(), 8) for x in range(2, source.width(), 8)]
        assert max(map(abs, empty)) < 1e-6, ('Unknown ID did not produce an empty matte', name)
        report['checks'].append({'cryptomatte': name, 'manifest_objects': len(manifest),
                                 'sampled_max_coverage': max(values), 'unknown_id_is_empty': True})
        nuke.delete(matte)
    save()

    deep = read(root / 'deep-final-check/deep.0001.exr', deep=True)
    flattened = nuke.nodes.DeepToImage(inputs=[deep])
    flat = read(root / 'deep-final-check/flat.0001.exr')
    report['deep_channels'] = deep.channels()
    deltas = []
    energy = 0.0
    for y in range(2, flat.height(), 5):
        for x in range(2, flat.width(), 5):
            for channel in ('red', 'green', 'blue', 'alpha'):
                a = flattened.sample(channel, x + .5, y + .5)
                b = flat.sample(channel, x + .5, y + .5)
                assert math.isfinite(a) and math.isfinite(b)
                deltas.append(abs(a - b))
                energy += abs(a)
    assert energy > 1, 'DeepToImage output is empty'
    mean, maximum = sum(deltas) / len(deltas), max(deltas)
    report['checks'].append({'deep_to_image': True, 'sampled_mean_error': mean,
                             'sampled_max_error': maximum, 'samples': len(deltas)})
    assert mean < 1e-4 and maximum < .003, report['checks'][-1]
    nuke.scriptSaveAs((out / 'MoonRay_Compositing_Check.nk').as_posix(), overwrite=1)
    report['passed'] = True
    save()
    print(json.dumps({'passed': True, 'nuke': report['nuke'], 'checks': report['checks']}), flush=True)
except Exception:
    report['error'] = traceback.format_exc()
    save()
    raise
