"""Run in the existing Houdini Python Shell; preserve scene nodes and edits."""
import json
from pathlib import Path
import time

import hou

out = Path('D:/MISC/Codex/Moonray/build/windows/houdini/alab-check/xpu-interactive')
viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
assert viewer is not None
report = {'hip': hou.hipFile.path(), 'renderer_before': viewer.currentHydraRenderer(),
          'frame': hou.frame(), 'viewer': viewer.name(),
          'desktop': hou.ui.curDesktop().name(), 'time': time.time()}
try:
    viewer.setRendererPaused(True)
except Exception as error:
    report['pause_error'] = str(error)
viewer.setHydraRenderer('Houdini VK')
report['renderer_after'] = viewer.currentHydraRenderer()
report['viewport_detail'] = viewer.curViewport().settings().levelOfDetail()
report['help'] = {name: hou.hscript('help ' + name) for name in
                  ('viewls', 'viewdisplay', 'viewoptrender', 'viewlod', 'viewlayout')}
report['views'] = hou.hscript('viewls')
(out/'live-recovery.json').write_text(json.dumps(report, indent=2)+'\n')
print('MoonRay failed session stopped; scene edits preserved.', flush=True)
