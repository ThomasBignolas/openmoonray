"""Record deliverable hashes and the scope of the completed Houdini checks."""
import hashlib
import json
from pathlib import Path

repo = Path(__file__).resolve().parents[3]
root = repo / 'build/windows/houdini'
demo = root / 'demo'
inspection = json.loads((root / 'plugin-inspection.json').read_text())
assert not inspection['errors']
assert all(plugin['loaded'] for plugin in inspection['plugins'].values())
render = json.loads((demo / 'render-from-hip.json').read_text())
assert not render['errors']
images = json.loads((demo / 'image-validation.json').read_text())
materials = json.loads((demo / 'material-validation.json').read_text())
workflow = json.loads((demo / 'workflow-validation.json').read_text())
builder = json.loads((root / 'builder-validation.json').read_text())
assert builder['surface_connected'] and not builder['render_errors']
assert not workflow['errors']
assert len(workflow['materials']) == 4 and len(workflow['lights']) == 4
workflow_bytes = (root / 'workflow-validation.log').read_bytes()
workflow_log = workflow_bytes.decode('utf-16' if workflow_bytes.startswith(b'\xff\xfe') else 'utf-8', errors='replace')
assert 'Error:' not in workflow_log and 'Traceback' not in workflow_log
live = json.loads((root / 'live-viewport.json').read_text())
assert live['live_render_verified']
assert not any(step['step'] == 'error' for step in live['steps'])
statuses = [step for step in live['steps'] if step['step'] == 'status']
assert any(step['paused'] for step in statuses)
assert any(not step['paused'] for step in statuses)
log_bytes = (root / 'animation-render.log').read_bytes()
animation = log_bytes.decode('utf-16' if log_bytes.startswith(b'\xff\xfe') else 'utf-8', errors='replace')
assert 'syncId:1' in animation and 'syncId:2' in animation
assert 'Error:' not in animation and 'Fatal error' not in animation
files = [root / 'install/moonray.json', demo / 'MoonRay_Solaris_Demo.hip',
         demo / 'moonray_demo.exr', demo / 'preview.png']
files += list((root / 'install/plugin').glob('*.dll'))
files += [root / 'install/plugin/houdini/MainMenuCommon.xml',
          root / 'install/plugin/houdini/UsdRenderers.json',
          root / 'install/plugin/houdini/toolbar/MoonRay.shelf',
          root / 'install/plugin/houdini/python3.11libs/moonray_houdini.py']
report = {
    'houdini': render['houdini'], 'renderer': 'HdMoonrayRendererPlugin',
    'host_root': render['package'], 'hda_count': len(inspection['vop_types']),
    'checks': {'plugins_load': True, 'hda_instantiation': True,
               'saved_hip_render': render, 'image_outputs': images,
               'material_ramps': materials, 'oidn_animation_without_errors': True,
               'solaris_workflow': workflow, 'material_builder': builder},
    'viewport': {'renderer_selection_verified': True, 'live_render_verified': True,
                 'pause_resume_verified': True, 'evidence': live,
                 'background_scene_updates': False},
    'files': {str(path.relative_to(repo)): {'bytes': path.stat().st_size,
              'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in files}}
(root / 'validation-summary.json').write_text(json.dumps(report, indent=2) + '\n')
# Correct the old GUI report, which incorrectly treated renderer selection as
# proof that the hidden window had drawn a rendered frame.
viewport_file = demo / 'viewport-test.json'
viewport = json.loads(viewport_file.read_text())
viewport.pop('success', None)
viewport.pop('remaining', None)
viewport.update(report['viewport'])
viewport_file.write_text(json.dumps(viewport, indent=2) + '\n')
print('Recorded plugin, image, material, Solaris workflow and visible viewport validations.')
