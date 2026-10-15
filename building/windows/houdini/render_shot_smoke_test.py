"""Small Solaris shot probe: native skin/hair, instances, motion and cached VDB."""
import argparse
import json
from pathlib import Path
import subprocess
import hou
from pxr import Gf, Sdf, Usd, UsdGeom, UsdRender, UsdShade, UsdVol

parser = argparse.ArgumentParser()
parser.add_argument('--scene', required=True, type=Path)
parser.add_argument('--out', required=True, type=Path)
args = parser.parse_args()
out = args.out.resolve()
out.mkdir(parents=True, exist_ok=True)
stage = Usd.Stage.Open(str(args.scene.resolve()))

def material(path, identifier, terminal='surface'):
    mat = UsdShade.Material.Define(stage, path)
    shader = UsdShade.Shader.Define(stage, mat.GetPath().AppendChild('shader'))
    shader.CreateIdAttr(identifier)
    shader.CreateOutput(terminal, Sdf.ValueTypeNames.Token)
    output = mat.CreateVolumeOutput('moonray') if terminal == 'volume' else mat.CreateSurfaceOutput('moonray')
    output.ConnectToSource(shader.ConnectableAPI(), terminal)
    return mat, shader

skin, skin_shader = material('/Looks/shot_skin', 'DwaSkinMaterial')
UsdShade.MaterialBindingAPI.Apply(stage.GetPrimAtPath('/ceramic/mesh_0')).Bind(skin)
hair, hair_shader = material('/Looks/shot_hair', 'HairMaterial_v3')
UsdShade.MaterialBindingAPI.Apply(stage.GetPrimAtPath('/groom')).Bind(hair)

geo = hou.node('/obj').createNode('geo', 'volume_cache_test', run_init_scripts=False)
sphere = geo.createNode('sphere')
sphere.parm('type').set('polymesh')
sphere.parmTuple('rad').set((0.6, 0.6, 0.6))
vdb = geo.createNode('vdbfrompolygons')
vdb.setInput(0, sphere)
vdb.parm('builddistance').set(False)
vdb.parm('buildfog').set(True)
vdb.parm('voxelsize').set(0.05)
cache = out / 'density.vdb'
vdb.geometry().saveToFile(str(cache))
assert cache.stat().st_size > 1000
volume = UsdVol.Volume.Define(stage, '/fog')
UsdGeom.Xformable(volume).AddTranslateOp().Set(Gf.Vec3d(0, 1.5, 1.0))
field = UsdVol.OpenVDBAsset.Define(stage, '/fog/density')
field.CreateFilePathAttr(Sdf.AssetPath(cache.as_posix()))
field.CreateFieldNameAttr('density')
volume.CreateFieldRelationship('density', field.GetPath())
volume_mat, volume_shader = material('/Looks/shot_volume', 'BaseVolume', 'volume')
volume_shader.CreateInput('diffuse_color', Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.5, 0.6, 0.7))
UsdShade.MaterialBindingAPI.Apply(volume.GetPrim()).Bind(volume_mat)

camera = UsdGeom.Camera(stage.GetPrimAtPath('/cameras/camera'))
camera.CreateShutterOpenAttr(-0.25)
camera.CreateShutterCloseAttr(0.25)
settings = stage.GetPrimAtPath('/Render/rendersettings')
settings.CreateAttribute('instantaneousShutter', Sdf.ValueTypeNames.Bool).Set(False)
settings.CreateAttribute('moonray:sceneVariable:enable_motion_blur', Sdf.ValueTypeNames.Bool).Set(True)
settings.GetAttribute('moonray:sceneVariable:pixel_samples').Set(4)
product = UsdRender.Product(stage.GetPrimAtPath('/Render/Products/beauty'))
# The shot probe uses beauty and ordinary utilities; Cryptomatte validation is separate.
product.GetOrderedVarsRel().SetTargets([Sdf.Path('/Render/Vars/beauty'), Sdf.Path('/Render/Vars/P'), Sdf.Path('/Render/Vars/N')])
renders = []
for name, visible, blur in [('shot', True, True), ('no_volume', False, True), ('no_motion_blur', False, False)]:
    UsdGeom.Imageable(volume).CreateVisibilityAttr().Set('inherited' if visible else 'invisible')
    settings.GetAttribute('instantaneousShutter').Set(not blur)
    settings.GetAttribute('moonray:sceneVariable:enable_motion_blur').Set(blur)
    product.CreateProductNameAttr((out / (name + '.exr')).as_posix())
    usd = out / (name + '.usda')
    stage.Export(str(usd))
    with (out / (name + '.log')).open('w') as log:
        result = subprocess.run([str(Path(hou.getenv('HFS')) / 'bin/husk.exe'), '--renderer', 'HdMoonrayRendererPlugin',
            '--settings', '/Render/rendersettings', '-f', '1.5', str(usd)], stdout=log, stderr=subprocess.STDOUT, timeout=180)
    assert result.returncode == 0, (name, result.returncode)
    renders.append(name)
(out / 'render-report.json').write_text(json.dumps({'package': hou.getenv('MOONRAY_HOUDINI_ROOT'),
    'materials': ['DwaSkinMaterial', 'HairMaterial_v3', 'BaseVolume'], 'renders': renders,
    'vdb_cache': str(cache)}, indent=2) + '\n')
print('Rendered shot, volume-off and motion-blur-off probes.', flush=True)
