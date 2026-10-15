"""Bounded disposable UI test, invoked with houdinifx waitforui (no HIP argument)."""
import json
import os
from pathlib import Path
import time
import traceback

import hou
from PySide6 import QtGui
import moonray_houdini as mr

out = Path(os.environ['MOONRAY_UI_PROBE'])
out.mkdir(parents=True, exist_ok=True)
log = Path(os.environ['MOONRAY_UI_LOG'])
report = {'passed': False, 'steps': [], 'started': time.time()}
state, since, last_poll = 'setup', time.monotonic(), 0.0
viewer, rop = None, None
completed = 0


def record(name, **values):
    report['steps'].append({'name': name, 'time': time.time(), **values})
    (out / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')


def capture(name):
    window = hou.qt.mainWindow()
    QtGui.QGuiApplication.primaryScreen().grabWindow(int(window.winId())).save(str(out / name))


def finish():
    hou.ui.removeEventLoopCallback(tick)
    mr.stop_ipr()
    record('stopped', renderer=viewer.currentHydraRenderer() if viewer else None)
    hou.hipFile.save(str(out / 'Viewport_Test_Backup.hip'))
    report['ready_to_close'] = True
    record('ready_to_close')


def advance(next_state):
    global state, since
    state, since = next_state, time.monotonic()


def tick():
    global viewer, rop, completed, last_poll
    now = time.monotonic()
    if now - last_poll < 0.25:
        return
    last_poll = now
    try:
        if time.time() - report['started'] > 120:
            raise RuntimeError('Viewport check timed out in ' + state)
        if state == 'setup':
            viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
            viewer.setHydraRenderer('Houdini VK')
            hou.hipFile.merge(os.environ['MOONRAY_UI_HIP'], node_pattern='/stage/*',
                              overwrite_on_conflict=True, ignore_load_warnings=True)
            selected = [n for n in hou.selectedNodes() if n.type().name() == 'usdrender_rop']
            rop = selected[-1] if selected else [n for n in hou.node('/stage').children()
                if n.type().name() == 'usdrender_rop'][-1]
            settings = mr.render_settings_node(rop)
            settings.setSelected(True, clear_all_selected=True)
            mr.refresh_settings()
            mr._set(settings, 'moonray:localThreads', 2)
            mr._set(settings, 'moonray:executionMode', 'vectorized')
            rop.setSelected(True, clear_all_selected=True)
            viewer.setPwd(hou.node('/stage'))
            mr.use_render_settings(rop)
            view = hou.ui.curDesktop().name() + '.' + viewer.name() + '.solaris.' + viewer.curViewport().name()
            record('setup', rop=rop.path(), settings=settings.path(),
                   camera=hou.hscript('viewcamera -c /cameras/camera ' + view),
                   package=hou.getenv('MOONRAY_HOUDINI_ROOT'))
            mr.start_ipr()
            record('selected', renderer=viewer.currentHydraRenderer(), paused=viewer.isRendererPaused())
            advance('first_frame')
            return
        text = log.read_text(errors='replace') if log.exists() else ''
        frames = text.count('stage shading complete')
        if state == 'first_frame' and frames > 0 and now - since > 3:
            capture('initial.png')
            record('first_frame', paused=viewer.isRendererPaused(), completed=frames)
            mr.pause_ipr()
            record('pause_requested', paused=viewer.isRendererPaused())
            advance('paused')
        elif state == 'paused' and now - since > 3:
            assert viewer.isRendererPaused(), 'Pause did not persist across idle callbacks'
            capture('paused.png')
            record('pause_confirmed', paused=True)
            mr.start_ipr()
            completed = frames
            advance('resumed')
        elif state == 'resumed' and now - since > 3:
            assert not viewer.isRendererPaused(), 'Resume did not clear user pause'
            record('resume_confirmed', paused=False)
            mr.restart_ipr()
            completed = frames
            advance('restarted')
        elif state == 'restarted' and frames > completed and now - since > 3:
            capture('restarted.png')
            record('restart_confirmed', completed=frames)
            report['passed'] = True
            finish()
    except Exception:
        record('error', state=state, traceback=traceback.format_exc())
        finish()


# Run only when Houdini is idle. Qt timers can execute in the middle of
# Houdini's own temporary render suspension and invalidate pause assertions.
hou.ui.addEventLoopCallback(tick)
