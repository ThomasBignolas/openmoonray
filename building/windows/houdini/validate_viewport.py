"""Run after waitforui in a disposable Houdini GUI process; never save the hip."""
import json
from pathlib import Path
import time
import traceback
import hou
from PySide6 import QtCore

directory = Path(hou.hipFile.path()).parent
report = {'started': time.time(), 'ui_available': hou.isUIAvailable(), 'steps': [],
          'render_verified': False}
path = directory / 'viewport-test.json'


def record(name, **data):
    report['steps'].append({'name': name, 'time': time.time(), **data})
    path.write_text(json.dumps(report, indent=2))


def finish():
    try:
        viewer.setRendererPaused(True)
        record('paused', paused=viewer.isRendererPaused())
        viewer.setHydraRenderer('Houdini VK')
        record('switched_back', renderer=viewer.currentHydraRenderer())
        report['ui_selection_passed'] = True
        # UI selection alone does not prove rendering. Require independent
        # worker/frame evidence from HDM_LOG_FILE before accepting this test.
        path.write_text(json.dumps(report, indent=2))
    except Exception:
        record('error', traceback=traceback.format_exc())
    finally:
        hou.hscript('quit -f')


def update():
    try:
        hou.node('/stage/moonray_materials/ceramic').parmTuple('albedo').set((0.08, 0.35, 0.07))
        record('material_updated', renderer=viewer.currentHydraRenderer())
        QtCore.QTimer.singleShot(30000, finish)
    except Exception:
        record('error', traceback=traceback.format_exc())
        hou.hscript('quit -f')


try:
    viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
    if viewer is None:
        raise RuntimeError('No Scene Viewer in desktop')
    viewer.setPwd(hou.node('/stage'))
    viewer.setIsCurrentTab()
    hou.node('/stage/moonray_settings').setDisplayFlag(True)
    viewer.curViewport().frameAll()
    renderers = viewer.hydraRenderers()
    selected = 'HdMoonrayRendererPlugin' if 'HdMoonrayRendererPlugin' in renderers else 'Moonray'
    viewer.setHydraRenderer(selected)
    viewer.setRendererPaused(False)
    record('moonray_selected', available=renderers, renderer=viewer.currentHydraRenderer())
    QtCore.QTimer.singleShot(30000, update)
except Exception:
    record('error', traceback=traceback.format_exc())
    hou.hscript('quit -f')
