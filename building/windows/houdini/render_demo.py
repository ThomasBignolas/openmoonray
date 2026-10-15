"""Exercise the saved Houdini scene through its USD Render ROP."""
import json
from pathlib import Path
import sys
import time
import hou

directory = Path(sys.argv[1]).resolve()
hou.hipFile.load(str(directory / 'MoonRay_Solaris_Demo.hip'), suppress_save_prompt=True, ignore_load_warnings=True)
assert hou.getenv('MOONRAY_HOUDINI_ROOT'), 'MoonRay user package was not loaded'
rop = hou.node('/stage/RENDER_MOONRAY')
assert rop.evalParm('renderer') == 'HdMoonrayRendererPlugin'
start = time.monotonic()
rop.render()
output = directory / 'moonray_demo.exr'
assert output.is_file() and output.stat().st_size > 10000
report = {'houdini': hou.applicationVersionString(), 'package': hou.getenv('MOONRAY_HOUDINI_ROOT'),
          'rop': rop.path(), 'errors': rop.errors(), 'output': str(output),
          'bytes': output.stat().st_size, 'seconds': time.monotonic() - start}
(directory / 'render-from-hip.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2), flush=True)
if rop.errors():
    raise RuntimeError(rop.errors())
