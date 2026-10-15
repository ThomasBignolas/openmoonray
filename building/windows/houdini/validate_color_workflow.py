"""Verify packaged color UI, shader translation and saved HIP recooking."""
import json
from pathlib import Path
import sys
import hou
import numpy as np
import OpenImageIO as oiio
from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade
import moonray_color
import moonray_houdini as mr

out=Path(sys.argv[1]).resolve()
out.mkdir(parents=True,exist_ok=True)
hou.hipFile.setName(str(out/'Color_Management.hip'))
network=hou.node('/stage')
geometry=Usd.Stage.CreateNew(str(out/'geometry.usda'))
mesh=UsdGeom.Mesh.Define(geometry,'/mesh')
mesh.CreatePointsAttr([(-2,-2,0),(2,-2,0),(2,2,0),(-2,2,0)])
mesh.CreateFaceVertexCountsAttr([4])
mesh.CreateFaceVertexIndicesAttr([0,1,2,3])
mesh.CreateSubdivisionSchemeAttr('none')
UsdGeom.PrimvarsAPI(mesh).CreatePrimvar('st',Sdf.ValueTypeNames.TexCoord2fArray,UsdGeom.Tokens.faceVarying).Set([(0,0),(1,0),(1,1),(0,1)])
UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim())
mesh.GetPrim().CreateRelationship('material:binding').SetTargets(['/Looks/test_material'])
camera=UsdGeom.Camera.Define(geometry,'/camera')
camera.AddTranslateOp().Set(Gf.Vec3d(0,0,5))
geometry.GetRootLayer().Save()
sublayer=network.createNode('sublayer','geometry')
sublayer.parm('filepath1').set(str(out/'geometry.usda'))
library=network.createNode('materiallibrary','materials')
library.setInput(0,sublayer)
library.parm('matpathprefix').set('/Looks/')
builder=mr._setup_material_builder(library.createNode('subnet','test_material'))
kind=next(n for n in hou.vopNodeTypeCategory().nodeTypes() if '::ImageMap::' in n and 'MOONRAY' in n)
image=builder.createNode(kind,'image')
image.parm('texture').set((out.parent/'core5/color.exr').as_posix())
image.parm('moonray_source_colorspace').set('sRGB - Texture')
image.parm('moonray_mipmap_filter').set('triangle')
image.parm('texture_filter').set(4)
image.parm('texture_blur').set(.01)
image.parm('max_anisotropy').set(12)
surface=builder.node('surface')
surface.setNamedInput('albedo',image,0)
library.setSelected(True,clear_all_selected=True)
library.setDisplayFlag(True)
try:
    rop=mr.create_render_setup()
except Exception:
    for n in network.allSubChildren():
        if isinstance(n,hou.LopNode) and n.errors():
            print(n.path(),n.errors(),flush=True)
    raise
node=next(n for n in network.children() if n.type().name()=='moonray::color::1.0')
node.parm('cache').set((out/'cache').as_posix())
stage=node.stage()
assert stage, node.errors()
shader=next(p for p in stage.Traverse() if p.GetAttribute('info:id').Get()=='ImageMap')
checks={
 'native_sampling_exported': shader.GetAttribute('inputs:texture_filter').Get()==4 and abs(shader.GetAttribute('inputs:texture_blur').Get()-.01)<1e-6,
 'native_anisotropy_exported': shader.GetAttribute('inputs:max_anisotropy').Get()==12,
 'texture_prepared': shader.GetAttribute('inputs:texture').Get().path.endswith('.tx'),
 'legacy_gamma_disabled': shader.GetAttribute('inputs:gamma').Get()==0,
 'rendering_space': stage.GetPrimAtPath('/Render/MoonRay/settings').GetAttribute('renderingColorSpace').Get()=='ACEScg',
 'rop_connected': node in rop.inputAncestors(),
 'config_preserved': stage.GetColorConfiguration().path==hou.getenv('OCIO'),
}
node.parm('overridesampling').set(True)
node.parm('lookup').set(1)
node.parm('blur').set(.02)
checks['sampling_override']=next(p for p in node.stage().Traverse() if p.GetAttribute('info:id').Get()=='ImageMap').GetAttribute('inputs:texture_filter').Get()==1
node.parm('generation').set(1)
checks['require_cooks']=bool(node.stage()) and not node.errors()
node.parm('enable').set(False)
checks['disabled_preserves_source']=next(p for p in node.stage().Traverse() if p.GetAttribute('info:id').Get()=='ImageMap').GetAttribute('inputs:texture').Get().path.endswith('.exr')
node.parm('enable').set(True)
rop.setSelected(True,clear_all_selected=True)
light=mr.create_light()
checks['new_light_before_color']=light in node.inputAncestors() and node in rop.inputAncestors()
checks['new_light_display_managed']=node in network.displayNode().inputAncestors() or network.displayNode()==node
# Keep the newly created light selected, as users do for consecutive shelf actions.
new_material=mr.create_material()
checks['new_material_before_color']=new_material.parent() in node.inputAncestors()
checks['new_material_display_managed']=node in network.displayNode().inputAncestors() or network.displayNode()==node
settings=network.node('moonray_settings')
settings.parmTuple('resolution').set((32,32))
mr._set(settings,'moonray:sceneVariable:pixel_samples',2)
mr._set(settings,'moonray:localThreads',2)
product=network.node('moonray_output')
mr._set(product,'productName',(out/'workflow.exr').as_posix())
rop.parm('lopoutput').set((out/'workflow.usd').as_posix())
hou.hipFile.save()
saved=node.path()
rop_path=rop.path()
hou.hipFile.load(str(out/'Color_Management.hip'),suppress_save_prompt=True)
node=hou.node(saved)
checks['saved_hip_recooks']=bool(node.stage()) and not node.errors()
checks['menus_populated']='ACEScg' in node.parm('working').menuItems()
hou.node(rop_path).render(frame_range=(1,1))
render=oiio.ImageBuf(str(out/'workflow.exr'))
checks['saved_hip_renders']=render.read() and bool(np.isfinite(render.get_pixels(oiio.FLOAT)).all()) and float(np.max(render.get_pixels(oiio.FLOAT)[...,:3]))>0
checks['rop_exr_primaries']=bool(np.max(np.abs(np.asarray(render.spec().getattribute('chromaticities'))-moonray_color.AP1))<1e-5)
report={'passed':all(checks.values()),'checks':checks,'node':node.path(),'package':hou.getenv('MOONRAY_HOUDINI_ROOT')}
(out/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2),flush=True)
assert report['passed'],report
