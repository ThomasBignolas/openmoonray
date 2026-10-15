"""Generate the native deep output LOP using Houdini's asset writer."""
from pathlib import Path
import sys
import hou

assets = Path(__file__).with_name('assets')
sys.path.insert(0, str(assets / 'python3.11libs'))
import moonray_deep

target = assets / 'otls/moonray_deep.hda'
existing = hou.lopNodeTypeCategory().nodeTypes().get('moonray::deep::1.0')
if existing and existing.definition():
    hou.hda.uninstallFile(existing.definition().libraryFilePath())
if target.exists():
    target.unlink()
subnet = hou.node('/stage').createNode('subnet', 'moonray_deep_build')
script = subnet.createNode('pythonscript', 'author_deep')
script.setInput(0, subnet.indirectInputs()[0])
script.parm('python').set('import moonray_deep\nmoonray_deep.cook(hou.pwd(), hou.pwd().parent())')
script.setDisplayFlag(True)
for child in subnet.children():
    if child.type().name() == 'output':
        child.setInput(0, script)
subnet.setParmTemplateGroup(moonray_deep.parameters())
asset = subnet.createDigitalAsset(name='moonray::deep::1.0', hda_file_name=str(target),
    description='MoonRay Deep Output', min_num_inputs=1, max_num_inputs=1,
    ignore_external_references=True, change_node_type=True)
definition = asset.type().definition()
definition.updateFromNode(asset)
definition.setParmTemplateGroup(moonray_deep.parameters())
definition.setIcon('LOP_renderproduct')
definition.addSection('Help', '''= MoonRay Deep Output =

Connect after Render Settings and before the USD Render ROP.
Writes a separate native deep EXR alongside existing flat products.
Beauty, alpha and front/back depth are included. N, P and UV are optional.
Choose OpenEXR deep for ordinary deep compositing, or OpenDCX for subpixel masks.
Use $F4 in the output filename for sequences.

Supported by the local CPU worker. Deep files are saved at frame completion.
Use Uniform Sampling in MoonRay Render Settings. Adaptive deep sampling is not supported.
This node does not enable deep checkpoint/resume or distributed deep merging.
''')
definition.save(str(target))
assert asset.children() and definition.parmTemplateGroup().find('filename')
print('Created', target, flush=True)
