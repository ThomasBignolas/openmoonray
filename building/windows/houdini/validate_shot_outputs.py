"""Check shot-probe images and measurable volume / motion-blur effects."""
import json
from pathlib import Path
import sys
from validate_crypto_outputs import oiio

directory = Path(sys.argv[1])
images, report = {}, {}
for name in ('shot', 'no_volume', 'no_motion_blur'):
    image = oiio.ImageBuf(str(directory / (name + '.exr')))
    assert image.read(), image.geterror()
    assert image.spec().nchannels == 4
    stats = oiio.ImageBufAlgo.computePixelStats(image)
    assert not any(stats.nancount) and not any(stats.infcount), name
    assert max(stats.stddev[:3]) > .01, name
    assert 0 <= stats.min[3] <= stats.max[3] <= 1.00001
    images[name] = image
    report[name] = {'resolution': [image.spec().width, image.spec().height],
                    'finite': True, 'min': list(stats.min), 'max': list(stats.max)}
for name, lhs, rhs, minimum in [('cached_volume_effect', 'shot', 'no_volume', .001),
                               ('motion_blur_effect', 'no_volume', 'no_motion_blur', .0001)]:
    delta = oiio.ImageBufAlgo.compare(images[lhs], images[rhs], 1e-6, 1e-6)
    assert delta.meanerror > minimum, (name, delta.meanerror)
    report[name] = {'mean_absolute_change': delta.meanerror, 'max_change': delta.maxerror}
report['scope'] = 'Small representative render only; not a complex production-shot stress test.'
(directory / 'image-validation.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
