"""Frame the prepared ALab HIP in a visible Houdini Solaris session.

Launch as: houdinifx waitforui ALab_MoonRay.hip open_alab_ui.py
"""
import json
from pathlib import Path
import traceback
import time

import hou
from PySide6 import QtCore


def setup():
    started = time.monotonic()
    report = {'hip': hou.hipFile.path()}
    destination = Path(hou.hipFile.path()).parent / 'ui-report.json'
    try:
        stage = hou.node('/stage')
        settings = stage.node('moonray_settings')
        assert settings, 'The prepared ALab render settings are missing'
        viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
        assert viewer, 'No Scene Viewer is available'
        viewer.setIsCurrentTab()
        viewer.setPwd(stage)
        viewer.setHydraRenderer('Houdini VK')
        viewer.setStageControlsPlaybar(True)
        hou.setFrame(1004)
        viewer.curViewport().setCamera('/root/camera01/GEO/renderCam_hrc/renderCam_buffer/renderCam_srt/renderCam')
        viewer.referencePlane().setIsVisible(False)
        for pane in hou.ui.paneTabs():
            if pane.type() == hou.paneTabType.NetworkEditor:
                pane.setPwd(stage)
                pane.homeToSelection()
        settings.setSelected(True, clear_all_selected=True)
        report.update(ready=True, camera=viewer.curViewport().cameraPath(),
                      renderer=viewer.currentHydraRenderer(), renderers=list(viewer.hydraRenderers()))
        import moonray_houdini as mr
        settings_stage = settings.stage()
        prim = settings_stage.GetPrimAtPath(settings.evalParm('primpath'))
        report.update(execution_mode=prim.GetAttribute('moonray:executionMode').Get(),
                      cpu_threads=prim.GetAttribute('moonray:localThreads').Get(),
                      package=hou.getenv('MOONRAY_HOUDINI_ROOT'))
        # Persist the camera and network layout in the new demo file.
        hou.hipFile.save()
    except Exception:
        report.update(ready=False, error=traceback.format_exc())
    report['setup_seconds'] = round(time.monotonic() - started, 2)
    destination.write_text(json.dumps(report, indent=2) + '\n')
    if report.get('ready'):
        def capture():
            hou.qt.mainWindow().grab().save(str(destination.with_name('houdini-open.png')))
        QtCore.QTimer.singleShot(5000, capture)


QtCore.QTimer.singleShot(3000, setup)
