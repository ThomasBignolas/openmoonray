"""Build the Solaris MoonRay Geometry Settings asset with Houdini."""
from pathlib import Path
import sys
import hou

assets = Path(__file__).with_name('assets')
sys.path.insert(0, str(assets / 'python3.11libs'))
import moonray_geometry

target = assets / 'otls/moonray_geometry.hda'
existing = hou.lopNodeTypeCategory().nodeTypes().get('moonray::geometry::1.0')
if existing and existing.definition():
    hou.hda.uninstallFile(existing.definition().libraryFilePath())
if target.exists():
    target.unlink()
subnet = hou.node('/stage').createNode('subnet', 'moonray_geometry_build')
python = subnet.createNode('pythonscript', 'author_geometry')
python.setInput(0, subnet.indirectInputs()[0])
python.parm('python').set('import moonray_geometry\nmoonray_geometry.cook(hou.pwd(), hou.pwd().parent())')
python.setDisplayFlag(True)
for child in subnet.children():
    if child.type().name() == 'output':
        child.setInput(0, python)
subnet.setParmTemplateGroup(moonray_geometry.parameters())
asset = subnet.createDigitalAsset(name='moonray::geometry::1.0', hda_file_name=str(target),
    description='MoonRay Geometry Settings', min_num_inputs=1, max_num_inputs=1,
    ignore_external_references=True, change_node_type=True)
definition = asset.type().definition()
definition.updateFromNode(asset)
definition.setParmTemplateGroup(moonray_geometry.parameters())
definition.setIcon('LOP_rendergeometrysettings')
definition.addSection('Help', '''= MoonRay Geometry Settings =

Connect after geometry. Use a standard Solaris primitive pattern to select meshes
or implicit surfaces. The initial Mesh Resolution override is 4.
Disable an override to preserve the upstream opinion. Bypass removes this node's edits.
These native MoonRay primvars control tessellation and normal generation; they do
not change the USD subdivision scheme. Check silhouettes and displacement in final renders.
Edit instance sources for instance proxies. Point-instancer overrides are not provided.
''')
definition.save(str(target))
print('Created', target)
