"""Generate the MoonRay Color Management Solaris asset with Houdini."""
from pathlib import Path
import sys
import hou

assets = Path(__file__).with_name('assets')
sys.path.insert(0, str(assets / 'python3.11libs'))
import moonray_color

target = assets / 'otls/moonray_color.hda'
target.parent.mkdir(exist_ok=True)
existing = hou.lopNodeTypeCategory().nodeTypes().get('moonray::color::1.0')
if existing and existing.definition():
    hou.hda.uninstallFile(existing.definition().libraryFilePath())
if target.exists():
    target.unlink()
subnet = hou.node('/stage').createNode('subnet', 'moonray_color_build')
layer = subnet.createNode('configurelayer', 'ocio_stage_configuration')
layer.setInput(0, subnet.indirectInputs()[0])
for name in ('setcolorconfig','setcolormanagementsystem'):
    layer.parm(name).setExpression('ch("../enable")')
layer.parm('colorconfig').setExpression('hou.pwd().parent().evalParm("config") or hou.getenv("OCIO") or ""',hou.exprLanguage.Python)
layer.parm('colormanagementsystem').set('OpenColorIO')
script = subnet.createNode('pythonscript', 'prepare_color')
script.setInput(0, layer)
script.parm('python').set('import moonray_color\nmoonray_color.cook(hou.pwd(), hou.pwd().parent())')
script.setDisplayFlag(True)
for child in subnet.children():
    if child.type().name() == 'output':
        child.setInput(0, script)
subnet.setParmTemplateGroup(moonray_color.parameters())
asset = subnet.createDigitalAsset(name='moonray::color::1.0', hda_file_name=str(target),
    description='MoonRay Color Management', min_num_inputs=1, max_num_inputs=1,
    ignore_external_references=True, change_node_type=True)
definition = asset.type().definition()
definition.updateFromNode(asset)
definition.setParmTemplateGroup(moonray_color.parameters())
definition.setIcon('COP2_colorcorrect')
definition.addSection('Help', '''= MoonRay Color Management =

Connect after materials, lights, Render Vars and Render Settings, before rendering.
Uses the selected OCIO configuration; an empty Configuration uses Houdini's OCIO setting.
Rendering Color Space must be scene-linear. Display/view transforms remain in Houdini.

Color textures are converted before mipmap generation; data textures retain their values.
Overrides select source spaces and usage by USD prim/attribute patterns. USD color-space
metadata and OCIO file rules are respected. Untagged scene colors use the selected source.

Textures are written to a separate cache. Source images are never overwritten.
The cache key includes source changes, OCIO processor configuration and generation options.
Require Prepared Cache is useful after preparation and for render workers with read-only caches.
MoonRay needs tiled mipmaps; mipmap-free textures are not supported by its texture sampler.

EXRs remain linear. Alpha, utility AOVs and Cryptomatte are not display-transformed.
''')
definition.save(str(target))
assert definition.parmTemplateGroup().find('working')
print('Created', target, flush=True)
