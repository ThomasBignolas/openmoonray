"""Create an editable Solaris scene using the installed MoonRay HDAs."""
import json
from pathlib import Path
import sys
import hou

out = Path(sys.argv[1]).resolve()
out.mkdir(parents=True, exist_ok=True)
hou.hipFile.clear(suppress_save_prompt=True)
hou.setFrame(1)
stage = hou.node('/stage')
last = None


def lop(kind, name):
    global last
    node = stage.createNode(kind, name)
    if last is not None:
        node.setInput(0, last)
    last = node
    return node


for name, position in [('copper', (-1.15, 1, 0)), ('ceramic', (1.15, 1, 0)), ('floor', (0, -0.1, 0))]:
    node = lop('sopcreate', name)
    node.parm('primpath').set('/' + name)
    subnet = node.node('sopnet/create')
    geo = subnet.createNode('box' if name == 'floor' else 'sphere', name)
    geo.parmTuple('t').set(position)
    if name == 'floor':
        geo.parmTuple('size').set((14, 0.2, 14))
    else:
        types = geo.parm('type').menuItems()
        geo.parm('type').set('polymesh' if 'polymesh' in types else next(t for t in types if 'poly' in t.lower()))
        if geo.parm('freq'):
            geo.parm('freq').set(6)
        if geo.parm('rows'):
            geo.parm('rows').set(48)
        if geo.parm('cols'):
            geo.parm('cols').set(64)
    geo.setDisplayFlag(True)
    geo.setRenderFlag(True)
    if name != 'floor':
        normals = subnet.createNode('normal', 'smooth_normals')
        normals.setInput(0, geo)
        normals.setDisplayFlag(True)
        normals.setRenderFlag(True)
    subnet.layoutChildren()

library = lop('materiallibrary', 'moonray_materials')
library.parm('matpathprefix').set('/Looks/')
material_type = next(t for t in hou.vopNodeTypeCategory().nodeTypes() if 'DwaBaseMaterial' in t)
for name, color, metal, roughness in [
        ('copper', (0.8, 0.32, 0.13), 1, 0.22),
        ('ceramic', (0.025, 0.25, 0.3), 0, 0.28),
        ('floor', (0.18, 0.19, 0.21), 0, 0.65)]:
    mat = library.createNode(material_type, name)
    mat.setMaterialFlag(True)
    mat.parm('metallic').set(metal)
    mat.parm('roughness').set(roughness)
    mat.parmTuple('metallic_color' if metal else 'albedo').set(color)
library.layoutChildren()
for name in ('copper', 'ceramic', 'floor'):
    node = lop('assignmaterial', 'assign_' + name)
    node.parm('primpattern1').set('/' + name)
    node.parm('matspecpath1').set('/Looks/' + name)

camera = lop('camera', 'camera')
camera.parm('primpath').set('/cameras/camera')
camera.parmTuple('t').set((0, 3.2, 10))
camera.parmTuple('r').set((-12, 0, 0))
camera.parm('focalLength').set(45)
for name, pos, rotate, size, intensity, color in [
        ('key', (-3, 5, 4), (-42, -28, 0), (4, 4), 3, (1, 0.9, 0.8)),
        ('fill', (4, 3, 2), (-25, 45, 0), (3, 4), 2, (0.65, 0.8, 1)),
        ('rim', (0, 5, -3), (-120, 0, 0), (4, 2), 4, (1, 1, 1))]:
    light = lop('light', name)
    light.parm('lighttype').set('UsdLuxRectLight')
    light.parmTuple('t').set(pos)
    light.parmTuple('r').set(rotate)
    for parm, value in [('inputs:width', size[0]), ('inputs:height', size[1]), ('inputs:intensity', intensity)]:
        light.parm(hou.text.encodeParm(parm)).set(value)
    light.parmTuple(hou.text.encodeParm('inputs:color')).set(color)

# Author standard USD render products; these can also be edited through
# Solaris Render Product and Render Var nodes in a user's own scene.
product = lop('pythonscript', 'beauty_and_aovs')
product.parm('python').set('''from pxr import UsdRender, Sdf
stage = hou.pwd().editableStage()
variables = []
for name, source, dtype in [('beauty', 'color', 'color4f'), ('normal', 'N', 'normal3f'), ('depth', 'cameraDepth', 'float')]:
    var = UsdRender.Var.Define(stage, '/Render/Vars/' + name)
    var.CreateSourceNameAttr(source)
    var.CreateSourceTypeAttr('raw')
    var.CreateDataTypeAttr(dtype)
    var.GetPrim().CreateAttribute('driver:parameters:aov:husk:name', Sdf.ValueTypeNames.String).Set(name)
    variables.append(var.GetPath())
product = UsdRender.Product.Define(stage, '/Render/Products/beauty')
product.CreateProductTypeAttr('raster')
product.CreateProductNameAttr(hou.expandString('$HIP/moonray_demo.exr'))
product.CreateOrderedVarsRel().SetTargets(variables)
''')
settings = lop('rendersettings', 'moonray_settings')
settings.parm('camera').set('/cameras/camera')
settings.parm('products').set('/Render/Products/beauty')
settings.parm('res_mode').set('manual')
settings.parm('res_mode').pressButton()
settings.parmTuple('resolution').deleteAllKeyframes()
for parm in settings.parmTuple('resolution'):
    parm.lock(False)
settings.parmTuple('resolution').set((960, 540))
for name, value in [('pixel_samples', 8), ('light_samples', 2)]:
    encoded = hou.text.encodeParm('moonray:sceneVariable:' + name)
    settings.parm(encoded + '_control').set('set') if settings.parm(encoded + '_control') else settings.parm(hou.text.encodeParm('moonray:sceneVariable:' + name + '_control')).set('set')
    settings.parm(encoded).set(value)
settings.setDisplayFlag(True)
rop = lop('usdrender_rop', 'RENDER_MOONRAY')
rop.parm('renderer').set('HdMoonrayRendererPlugin')
rop.parm('rendersettings').set('/Render/rendersettings')
rop.parm('outputimage').set('$HIP/moonray_demo.exr')
rop.parm('lopoutput').set('$HIP/moonray_demo.usd')
rop.setComment('Render this node for a MoonRay EXR. Edit materials in moonray_materials; quality in moonray_settings.')
rop.setGenericFlag(hou.nodeFlag.DisplayComment, True)
stage.layoutChildren()
hou.hipFile.save(str(out / 'MoonRay_Solaris_Demo.hip'))
usd = settings.stage()
if not usd:
    raise RuntimeError(settings.errors())
usd.Export(str(out / 'moonray_demo.usda'))
errors = {n.path(): n.errors() for n in stage.children() if n.errors()}
shaders = [(str(p.GetPath()), str(p.GetAttribute('info:id').Get())) for p in usd.Traverse() if p.GetTypeName() == 'Shader']
report = {'hip': hou.hipFile.path(), 'usd': str(out / 'moonray_demo.usda'), 'errors': errors, 'shaders': shaders}
(out / 'scene-report.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2), flush=True)
if errors or not any(shader[1] == 'DwaBaseMaterial' for shader in shaders):
    raise RuntimeError('Solaris scene or MoonRay HDA translation failed')
