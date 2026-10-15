"""Validate actual Houdini EXRs without requiring NumPy."""
import json, os, sys
from pathlib import Path
handles = []
for folder in os.environ['PATH'].split(os.pathsep):
    try:
        handles.append(os.add_dll_directory(folder))
    except OSError:
        pass
import OpenImageIO as oiio

directory = Path(sys.argv[1]).resolve()
report, images = {}, {}
for name in ('moonray_demo.exr', 'animation.0001.exr', 'animation.0002.exr'):
    filename = str(directory / name)
    first = oiio.ImageBuf(filename)
    assert first.read(), first.geterror()
    parts, buffers = {}, {}
    for index in range(first.nsubimages):
        image = oiio.ImageBuf(filename, index, 0)
        assert image.read(index, 0, True), image.geterror()
        spec = image.spec()
        key = spec.get_string_attribute('oiio:subimagename') or spec.get_string_attribute('name')
        stats = oiio.ImageBufAlgo.computePixelStats(image)
        parts[key] = {'channels': spec.nchannels, 'min': list(stats.min), 'max': list(stats.max),
                      'average': list(stats.avg), 'stddev': list(stats.stddev),
                      'nan_count': list(stats.nancount), 'inf_count': list(stats.infcount)}
        buffers[key] = image
    assert {'beauty', 'normal', 'depth'} <= set(parts), parts.keys()
    beauty = parts['beauty']
    assert beauty['channels'] == 4
    assert not any(beauty['nan_count']) and not any(beauty['inf_count'])
    assert 0 <= beauty['min'][3] <= beauty['max'][3] <= 1.0001
    assert beauty['max'][3] > 0.99
    assert max(beauty['stddev'][:3]) > 0.01
    normal = parts['normal']
    assert normal['channels'] == 3
    assert not any(normal['nan_count']) and not any(normal['inf_count'])
    assert max(abs(v) for v in normal['min'] + normal['max']) <= 1.01
    depth = parts['depth']
    assert not any(depth['nan_count']) and min(depth['min']) > 0
    if name.startswith('animation'):
        assert 'all_light' in parts
        light = parts['all_light']
        assert not any(light['nan_count']) and not any(light['inf_count'])
        assert max(light['max']) > 0.1
    spec = buffers['beauty'].spec()
    report[name] = {'resolution': [spec.width, spec.height], 'parts': parts}
    images[name] = buffers['beauty']
delta = oiio.ImageBufAlgo.compare(images['animation.0001.exr'], images['animation.0002.exr'], 1e-6, 1e-6)
assert delta.maxerror > 0.1 and delta.meanerror > 0.005
report['animation_update'] = {'mean_absolute_difference': delta.meanerror, 'max_difference': delta.maxerror}
(directory / 'image-validation.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({name: value.get('resolution', value) for name, value in report.items()}, indent=2))
