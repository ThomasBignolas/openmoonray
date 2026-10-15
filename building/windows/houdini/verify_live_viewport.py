"""Visible, user-approved live check. Leaves Houdini open and never saves the HIP.

Commands are JSON files in the report folder so checks can be inspected between
steps without blocking Houdini's UI thread.
"""
import json
from pathlib import Path
import time
import traceback
import hou
from PySide6 import QtCore, QtGui

root = Path(hou.getenv('MOONRAY_HOUDINI_ROOT')).parent
report_path = root / 'live-viewport.json'
command_path = root / 'live-viewport-command.json'
report = {'started': time.time(), 'steps': [], 'live_render_verified': False}
viewer = None
original_albedo = None


def record(step, **data):
    report['steps'].append({'step': step, 'time': time.time(), **data})
    report_path.write_text(json.dumps(report, indent=2) + '\n')


def capture(name):
    window = hou.qt.mainWindow()
    pixmap = QtGui.QGuiApplication.primaryScreen().grabWindow(int(window.winId()))
    destination = root / ('live-' + name + '.png')
    if pixmap.isNull() or not pixmap.save(str(destination)):
        raise RuntimeError('Could not capture the Houdini window')
    record('screenshot', file=str(destination))


def poll():
    if not command_path.is_file():
        return
    try:
        command = json.loads(command_path.read_text(encoding='utf-8-sig'))
        command_path.unlink()
        action = command['action']
        if action == 'capture':
            capture(command.get('name', 'viewport'))
        elif action == 'edit':
            hou.node('/stage/moonray_materials/ceramic').parmTuple('albedo').set((0.08, 0.35, 0.07))
            record('material_edited')
        elif action == 'restore':
            hou.node('/stage/moonray_materials/ceramic').parmTuple('albedo').set(original_albedo)
            record('material_restored')
        elif action == 'pause':
            viewer.setRendererPaused(True)
            record('pause_requested')
        elif action == 'resume':
            viewer.setRendererPaused(False)
            record('resume_requested')
        elif action == 'switch':
            viewer.setHydraRenderer(command['renderer'])
            record('renderer_selected', renderer=viewer.currentHydraRenderer())
        elif action == 'camera':
            viewer.curViewport().setCamera('/cameras/camera')
            viewer.referencePlane().setIsVisible(False)
            record('camera_selected', camera=viewer.curViewport().cameraPath())
        elif action == 'reload_tools':
            import importlib
            import moonray_houdini
            importlib.reload(moonray_houdini)
            hou.shelves.loadFile(str(root / 'install/plugin/houdini/toolbar/MoonRay.shelf'))
            record('tools_reloaded')
        elif action == 'show_shelf':
            shelf = hou.shelves.shelves()['moonray']
            sets = hou.ui.curDesktop().shelfDock().shelfSets()
            if shelf not in sets[0].shelves():
                sets[0].setShelves(sets[0].shelves() + (shelf,))
            record('shelf_available', tools=[tool.name() for tool in shelf.tools()])
        elif action == 'close':
            # Preserve any edits made by the user before restarting the host.
            backup = root / 'demo/Live_Viewport_Session_Backup.hip'
            hou.hipFile.save(str(backup))
            record('session_saved_before_close', file=str(backup))
            hou.hscript('quit -f')
        elif action == 'status':
            record('status', renderer=viewer.currentHydraRenderer(), paused=viewer.isRendererPaused(),
                   camera=viewer.curViewport().cameraPath(), stage=viewer.pwd().path())
        elif action == 'finish':
            report['live_render_verified'] = command['verified']
            record('finished', **command.get('evidence', {}))
            hou.ui.removeEventLoopCallback(poll)
        else:
            raise ValueError(action)
    except Exception:
        record('error', traceback=traceback.format_exc())


def setup():
    global viewer, original_albedo
    try:
        viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
        assert viewer is not None, 'No Scene Viewer found'
        viewer.setIsCurrentTab()
        viewer.setPwd(hou.node('/stage'))
        hou.setUpdateMode(hou.updateMode.AutoUpdate)
        hou.node('/stage/moonray_settings').setDisplayFlag(True)
        original_albedo = hou.node('/stage/moonray_materials/ceramic').parmTuple('albedo').eval()
        try:
            viewer.curViewport().setCamera('/cameras/camera')
        except TypeError:
            viewer.curViewport().frameAll()
        viewer.setHydraRenderer('Moonray')
        viewer.setRendererPaused(False)
        def camera_ready():
            viewer.curViewport().setCamera('/cameras/camera')
            viewer.curViewport().settings().enableGuide(hou.viewportGuide.XZPlane, False)
            viewer.referencePlane().setIsVisible(False)
            viewer.setRendererPaused(False)
        QtCore.QTimer.singleShot(8000, camera_ready)
        record('ready', renderer=viewer.currentHydraRenderer(), camera=viewer.curViewport().cameraPath(),
               available=list(viewer.hydraRenderers()))
        hou.ui.addEventLoopCallback(poll)
    except Exception:
        record('error', traceback=traceback.format_exc())


timer = QtCore.QTimer(hou.qt.mainWindow())
timer.timeout.connect(poll)
QtCore.QTimer.singleShot(3000, setup)
