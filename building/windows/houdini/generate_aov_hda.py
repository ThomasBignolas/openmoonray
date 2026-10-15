"""Generate the MoonRay AOVs Solaris asset with Houdini's own HDA writer."""
from pathlib import Path
import sys
import hou

assets = Path(__file__).with_name('assets')
sys.path.insert(0, str(assets / 'python3.11libs'))
import moonray_aovs

target = assets / 'otls/moonray_aovs.hda'
target.parent.mkdir(exist_ok=True)
existing = hou.lopNodeTypeCategory().nodeTypes().get('moonray::aovs::1.0')
if existing and existing.definition():
    hou.hda.uninstallFile(existing.definition().libraryFilePath())
if target.exists():
    target.unlink()
subnet = hou.node('/stage').createNode('subnet', 'moonray_aovs_build')
python = subnet.createNode('pythonscript', 'author_aovs')
python.setInput(0, subnet.indirectInputs()[0])
python.parm('python').set('import moonray_aovs\nmoonray_aovs.cook(hou.pwd(), hou.pwd().parent())')
python.setDisplayFlag(True)
for child in subnet.children():
    if child.type().name() == 'output':
        child.setInput(0, python)
subnet.setParmTemplateGroup(moonray_aovs.parameters())
asset = subnet.createDigitalAsset(name='moonray::aovs::1.0', hda_file_name=str(target),
    description='MoonRay AOVs', min_num_inputs=1, max_num_inputs=1,
    ignore_external_references=True, change_node_type=True)
definition = asset.type().definition()
definition.updateFromNode(asset)
definition.setParmTemplateGroup(moonray_aovs.parameters())
definition.setIcon('LOP_rendervar')
definition.addSection('Help', '''= MoonRay AOVs =

Connect after a Render Product to add MoonRay compositing passes.
The Cryptomatte tab exposes object IDs and per-ID P, P0, N, beauty, reference P/N and UV data.
Reflection and refraction variants are optional. ID depth controls layers per pixel.

Cryptomatte layers are written to EXR at frame completion by the local worker.
The primary Cryptomatte plane previews coverage; use the numbered layers in compositing.
Reference passes need ref_P / ref_N primvars. CryptoS writes fragment data only.
Use standard Render Var LOPs for additional material AOVs and light path expressions.
''')
definition.save(str(target))
assert asset.children(), 'Missing asset contents'
assert definition.parmTemplateGroup().find('crypto'), 'Missing AOV controls'
print('Created', target, flush=True)
