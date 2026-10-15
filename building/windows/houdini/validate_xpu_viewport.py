"""Disposable UI test: houdinifx waitforui demo.hip validate_xpu_viewport.py.

Do not invoke from 456.py: startup callbacks can run before the viewer is ready.
"""
import json
import os
from pathlib import Path
import time
import traceback
import hou
from PySide6 import QtCore, QtGui

out = Path(os.environ['MOONRAY_XPU_VIEWPORT_TEST'])
out.mkdir(parents=True, exist_ok=True)
report = {'started': time.time(), 'steps': [], 'passed': False}
viewer = None
edit_started = 0.


def capture(name):
    # QWidget.grab() does not include Houdini's native OpenGL viewport.
    window = hou.qt.mainWindow()
    QtGui.QGuiApplication.primaryScreen().grabWindow(int(window.winId())).save(str(out / name))


def record(name, **values):
    report['steps'].append({'name': name, 'time': time.time(), **values})
    (out / 'viewport-validation.json').write_text(json.dumps(report, indent=2) + '\n')


def fail():
    record('error', traceback=traceback.format_exc())
    ready_to_close()


def ready_to_close():
    # Quit from outside the Python/Qt callback: destroying the application
    # while this callback is on the stack crashes Houdini 21 on this machine.
    hou.hipFile.save(str(out / 'Viewport_Test_Backup.hip'))
    report['ready_to_close'] = True
    (out / 'viewport-validation.json').write_text(json.dumps(report, indent=2) + '\n')


def finish():
    try:
        capture('resumed.png')
        viewer.setRendererPaused(True)
        record('finished', paused=viewer.isRendererPaused())
        viewer.setHydraRenderer('Houdini VK')
        report['ui_passed'] = True
        # External validation also requires actual XPU frames in the worker log.
        (out / 'viewport-validation.json').write_text(json.dumps(report, indent=2) + '\n')
        ready_to_close()
    except Exception:
        fail()


def resume():
    try:
        assert viewer.isRendererPaused(), 'Pause did not reach the delegate'
        record('pause_confirmed', paused=True)
        viewer.setRendererPaused(False)
        record('resumed', paused=viewer.isRendererPaused())
        QtCore.QTimer.singleShot(12000, finish)
    except Exception:
        fail()


def pause():
    try:
        capture('edited.png')
        viewer.setRendererPaused(True)
        record('paused', paused=viewer.isRendererPaused())
        QtCore.QTimer.singleShot(2000, resume)
    except Exception:
        fail()


def edit():
    global edit_started
    try:
        capture('initial.png')
        hou.node('/stage/moonray_materials/ceramic').parmTuple('albedo').set((.08, .35, .07))
        hou.setFrame(2)
        hou.ui.triggerUpdate()
        # Programmatic cooking may leave Solaris paused; resume the edited
        # scene after the UI has processed the cook.
        QtCore.QTimer.singleShot(1000, lambda: viewer.setRendererPaused(False))
        record('material_and_frame_edited')
        edit_started = time.time()
        QtCore.QTimer.singleShot(2000, wait_for_edit)
    except Exception:
        fail()


def wait_for_edit():
    try:
        path = Path(os.environ['HDM_LOG_FILE'].replace('-hydra.log', '-stdout.log'))
        text = path.read_text(errors='replace') if path.exists() else ''
        last_start = text.rfind('Starting Rendering (syncId:')
        complete = last_start >= 0 and 'shading complete 1' in text[last_start:]
        if 'Starting Rendering (syncId:2)' in text and complete:
            record('edited_frame_complete')
            pause()
        elif time.time() - edit_started > 120:
            raise RuntimeError('Edited viewport frame did not complete within 120 seconds')
        else:
            QtCore.QTimer.singleShot(2000, wait_for_edit)
    except Exception:
        fail()


def start():
    global viewer
    try:
        viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
        assert viewer is not None
        viewer.setPwd(hou.node('/stage'))
        viewer.setIsCurrentTab()
        settings = hou.node('/stage/moonray_settings1')
        assert settings.evalParm(hou.text.encodeParm('moonray:executionMode')) == 'xpu'
        config = hou.node('/stage/xpu_view_settings')
        assert config is not None, 'Regenerate the XPU demo with explicit stage render settings'
        assert config.stage().GetMetadata('renderSettingsPrimPath') == '/Render/MoonRay/settings'
        config.setDisplayFlag(True)
        settings.setCurrent(True, clear_all_selected=True)
        viewport = viewer.curViewport()
        viewport.frameAll()
        # HIP files can restore a paused renderer before its delegate exists.
        # Initialize a fresh viewport delegate, then resume on the next UI turn.
        viewer.setHydraRenderer('Houdini VK')
        record('viewer_ready', settings=settings.path())
        QtCore.QTimer.singleShot(2000, select_moonray)
    except Exception:
        fail()


def select_moonray():
    try:
        renderer = 'HdMoonrayRendererPlugin' if 'HdMoonrayRendererPlugin' in viewer.hydraRenderers() else 'Moonray'
        viewer.setHydraRenderer(renderer)
        QtCore.QTimer.singleShot(3000, initial_resume)
    except Exception:
        fail()


def initial_resume():
    try:
        viewer.setRendererPaused(False)
        hou.ui.triggerUpdate()
        record('selected_xpu', renderer=viewer.currentHydraRenderer(), paused=viewer.isRendererPaused())
        QtCore.QTimer.singleShot(20000, edit)
    except Exception:
        fail()


QtCore.QTimer.singleShot(3000, start)
