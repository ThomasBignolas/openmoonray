"""Disposable live USD shadow-link edit test; launch in a new Houdini window.

The caller sets MOONRAY_LINKING_UI and HDMOONRAY_RDLA_OUTPUT and captures
stdout to MOONRAY_UI_LOG. After ready_to_close, close only this test process.
"""
import json
import os
from pathlib import Path
import shutil
import time
import traceback

import hou
from PySide6 import QtGui

out = Path(os.environ['MOONRAY_LINKING_UI'])
out.mkdir(parents=True, exist_ok=True)
log = Path(os.environ['MOONRAY_UI_LOG'])
rdla = Path(os.environ['HDMOONRAY_RDLA_OUTPUT'])
report = {'passed': False, 'steps': [], 'package': hou.getenv('MOONRAY_HOUDINI_ROOT')}
started, last_poll = time.monotonic(), 0
state, completed, since = 'setup', 0, started
viewer, edit = None, None


def record(name, **values):
    report['steps'].append({'name': name, **values})
    (out / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')


def code(excluded):
    return '\n'.join([
        'from pxr import Usd',
        'stage = hou.pwd().editableStage()',
        'link = Usd.CollectionAPI(stage.GetPrimAtPath("/light"), "shadowLink")',
        'link.CreateExcludesRel().SetTargets(' + repr(['/blocker'] if excluded else []) + ')',
    ])


def finish():
    hou.ui.removeEventLoopCallback(tick)
    if viewer:
        viewer.setPwd(hou.node('/stage'))
        viewer.setHydraRenderer('Houdini VK')
    hou.hipFile.save(str(out / 'Shadow_Linking_Live_Test.hip'))
    report['ready_to_close'] = True
    record('finished')


def tick():
    global viewer, edit, state, completed, last_poll, since
    now = time.monotonic()
    if now - last_poll < .25:
        return
    last_poll = now
    try:
        if now - started > 100:
            raise RuntimeError('Live linking check timed out: ' + state)
        if state == 'setup':
            stage = hou.node('/stage')
            viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
            viewer.setPwd(stage)
            viewer.setHydraRenderer('Houdini VK')
            source = stage.createNode('sublayer', 'test_scene')
            source.parm('filepath1').set((out.parent / 'complete/casts.usda').as_posix())
            edit = stage.createNode('pythonscript', 'shadow_link_edit')
            edit.setInput(0, source)
            edit.parm('python').set(code(False))
            assert edit.stage() and not edit.errors(), edit.errors()
            config = stage.createNode('configurelayer', 'render_settings')
            config.setInput(0, edit)
            config.parm('setrendersettings').set(True)
            config.parm('rendersettings').set('/Render/settings')
            config.setDisplayFlag(True)
            viewer.setPwd(stage)
            viewer.curViewport().setCamera('/camera')
            viewer.referencePlane().setIsVisible(False)
            viewer.setHydraRenderer('Moonray')
            viewer.setRendererPaused(False)
            state, since = 'casts', now
            record('started')
            return
        frames = log.read_text(errors='replace').count('stage shading complete') if log.exists() else 0
        if frames <= completed or now - since < 3:
            return
        text = rdla.read_text()
        assignment = next(line for line in text.splitlines() if '{RdlMeshGeometry("/blocker"), "",' in line)
        excluded = 'ShadowSet(' in assignment
        assert excluded == (state == 'excluded'), (state, assignment)
        shutil.copyfile(rdla, out / (state + '.rdla'))
        window = hou.qt.mainWindow()
        assert QtGui.QGuiApplication.primaryScreen().grabWindow(int(window.winId())).save(str(out / (state + '.png')))
        record(state, completed_frames=frames, shadow_excluded=excluded)
        completed = frames
        if state == 'restored':
            report['passed'] = True
            finish()
        else:
            state = 'excluded' if state == 'casts' else 'restored'
            edit.parm('python').set(code(state == 'excluded'))
            assert edit.stage() and not edit.errors(), edit.errors()
            since = now
    except Exception:
        record('error', traceback=traceback.format_exc())
        finish()


hou.ui.addEventLoopCallback(tick)
