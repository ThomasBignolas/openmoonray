"""Render all MoonRay Cryptomatte extensions through Houdini's local delegate."""
import argparse
import json
from pathlib import Path
import subprocess
import hou
from pxr import Gf, Sdf, Usd, UsdGeom, UsdRender, UsdShade, Vt

parser = argparse.ArgumentParser()
parser.add_argument('--demo', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
parser.add_argument('--optics', action='store_true')
parser.add_argument('--geometry', action='store_true')
args = parser.parse_args()
args.out.mkdir(parents=True, exist_ok=True)
stage = Usd.Stage.Open(str(args.demo.resolve()))
stage.SetStartTimeCode(1)
stage.SetEndTimeCode(2)
settings = stage.GetPrimAtPath('/Render/rendersettings')
settings.GetAttribute('resolution').Set(Gf.Vec2i(160, 90))
settings.GetAttribute('moonray:sceneVariable:pixel_samples').Set(3)
settings.CreateAttribute('moonray:sceneVariable:deep_id_attribute_names', Sdf.ValueTypeNames.StringArray).Set(Vt.StringArray(['prim_id']))
transform = stage.GetPrimAtPath('/copper').GetAttribute('xformOp:transform:xform')
transform.Set(Gf.Matrix4d(1), 1)
transform.Set(Gf.Matrix4d(1).SetTranslate(Gf.Vec3d(0, 0.6, 0)), 2)
if args.optics:
    for obj, shader_id, flag in [('/copper', 'DwaMetalMaterial', 'record_reflected_cryptomatte'),
                                  ('/ceramic', 'DwaRefractiveMaterial', 'record_refracted_cryptomatte')]:
        material = UsdShade.Material.Define(stage, '/Looks/crypto_' + obj[1:])
        shader = UsdShade.Shader.Define(stage, material.GetPath().AppendChild('surface'))
        shader.CreateIdAttr(shader_id)
        shader.CreateInput('roughness', Sdf.ValueTypeNames.Float).Set(0.0)
        shader.CreateInput(flag, Sdf.ValueTypeNames.Bool).Set(True)
        shader.CreateOutput('surface', Sdf.ValueTypeNames.Token)
        material.CreateSurfaceOutput('moonray').ConnectToSource(shader.ConnectableAPI(), 'surface')
        for prim in Usd.PrimRange(stage.GetPrimAtPath(obj)):
            if prim.IsA(UsdGeom.Mesh):
                UsdShade.MaterialBindingAPI.Apply(prim).Bind(material)
if args.geometry:
    # Four individual masks for environment-style point instancing.
    instancer = UsdGeom.PointInstancer.Define(stage, '/scatter')
    prototype = UsdGeom.Mesh.Define(stage, '/scatter/prototype')
    prototype.CreateSubdivisionSchemeAttr('none')
    prototype.CreatePointsAttr([(-.225,-.225,-.225),(.225,-.225,-.225),(.225,.225,-.225),(-.225,.225,-.225),
                               (-.225,-.225,.225),(.225,-.225,.225),(.225,.225,.225),(-.225,.225,.225)])
    prototype.CreateFaceVertexCountsAttr([4] * 6)
    prototype.CreateFaceVertexIndicesAttr([0,3,2,1,4,5,6,7,0,1,5,4,3,7,6,2,0,4,7,3,1,2,6,5])
    instancer.CreatePrototypesRel().SetTargets([prototype.GetPath()])
    instancer.CreateProtoIndicesAttr([0, 0, 0, 0])
    instancer.CreatePositionsAttr([(-1.5, 0.4, 1.8), (-0.5, 0.4, 1.8), (0.5, 0.4, 1.8), (1.5, 0.4, 1.8)])
    # Curves exercise the character-groom primitive path and its object mask.
    curves = UsdGeom.BasisCurves.Define(stage, '/groom')
    curves.CreateTypeAttr('linear')
    curves.CreateWrapAttr('nonperiodic')
    curves.CreateCurveVertexCountsAttr([3] * 12)
    points = []
    for i in range(12):
        x = -0.5 + i / 11
        points.extend([(x, 2.3, 0), (x, 2.65, 0), (x + 0.1, 2.9, 0)])
    curves.CreatePointsAttr(points)
    curves.CreateWidthsAttr([0.025])
    curves.SetWidthsInterpolation('constant')
for prim in stage.Traverse():
    if prim.IsA(UsdGeom.Mesh):
        mesh = UsdGeom.Mesh(prim)
        api = UsdGeom.PrimvarsAPI(prim)
        api.CreatePrimvar('ref_P', Sdf.ValueTypeNames.Point3fArray, 'vertex').Set(mesh.GetPointsAttr().Get())
        xform = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(1)
        api.CreatePrimvar('p0', Sdf.ValueTypeNames.Point3fArray, 'vertex').Set(
            Vt.Vec3fArray([Gf.Vec3f(xform.Transform(Gf.Vec3d(p))) for p in mesh.GetPointsAttr().Get()]))
        normals = mesh.GetNormalsAttr().Get()
        if normals:
            api.CreatePrimvar('ref_N', Sdf.ValueTypeNames.Normal3fArray, mesh.GetNormalsInterpolation()).Set(normals)
product = UsdRender.Product(stage.GetPrimAtPath('/Render/Products/beauty'))
product.CreateProductNameAttr((args.out.resolve() / 'all-crypto.$F4.exr').as_posix())
paths = [Sdf.Path('/Render/Vars/beauty')]
for name, dtype in [('P', 'point3f'), ('Wp', 'point3f'), ('N', 'normal3f'), ('St', 'float2'), ('Cryptomatte', 'float')]:
    var = UsdRender.Var.Define(stage, '/Render/Vars/' + name)
    var.CreateSourceNameAttr('cryptomatte' if name == 'Cryptomatte' else name)
    var.CreateSourceTypeAttr('raw')
    var.CreateDataTypeAttr(dtype)
    prim = var.GetPrim()
    prim.CreateAttribute('driver:parameters:aov:husk:name', Sdf.ValueTypeNames.String).Set(name)
    prim.CreateAttribute('driver:parameters:aov:husk:format', Sdf.ValueTypeNames.Token).Set(dtype)
    prim.CreateAttribute('parameters:moonray:channel_format', Sdf.ValueTypeNames.Token).Set('float')
    if name == 'Cryptomatte':
        prim.CreateAttribute('parameters:moonray:result', Sdf.ValueTypeNames.Token).Set('cryptomatte')
        prim.CreateAttribute('parameters:moonray:cryptomatte_depth', Sdf.ValueTypeNames.Int).Set(3)
        for attr in ('positions', 'p0', 'normals', 'beauty', 'refp', 'refn', 'uv'):
            prim.CreateAttribute('parameters:moonray:cryptomatte_output_' + attr, Sdf.ValueTypeNames.Bool).Set(True)
        for attr in ('record_reflected', 'record_refracted', 'support_resume_render'):
            prim.CreateAttribute('parameters:moonray:cryptomatte_' + attr, Sdf.ValueTypeNames.Bool).Set(True)
    paths.append(var.GetPath())
product.GetOrderedVarsRel().SetTargets(paths)
scene = args.out.resolve() / 'all-crypto.usda'
stage.Export(str(scene))
(args.out / 'test-case.json').write_text(json.dumps({'optics': args.optics, 'geometry': args.geometry}))
with (args.out / 'render.log').open('w') as log:
    result = subprocess.run([str(Path(hou.getenv('HFS')) / 'bin/husk.exe'), '--renderer', 'HdMoonrayRendererPlugin',
        '--settings', '/Render/rendersettings', '-f', '1', '-n', '2', str(scene)], stdout=log, stderr=subprocess.STDOUT, timeout=180)
assert result.returncode == 0, (result.returncode, str(args.out / 'render.log'))
print(json.dumps({'package': hou.getenv('MOONRAY_HOUDINI_ROOT'), 'scene': str(scene), 'returncode': result.returncode}), flush=True)
