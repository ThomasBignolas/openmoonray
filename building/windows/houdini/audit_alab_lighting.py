"""Record ALab's authored lights and prepare a small Karma comparison."""
import argparse
import json
from pathlib import Path
import hou
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdRender

parser = argparse.ArgumentParser()
parser.add_argument('--scene', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
args.out.mkdir(parents=True, exist_ok=True)
stage = Usd.Stage.Open(str(args.scene.resolve()))
camera_path = '/root/camera01/GEO/renderCam_hrc/renderCam_buffer/renderCam_srt/renderCam'
camera = UsdGeom.Camera(stage.GetPrimAtPath(camera_path))
report = {'camera': {a.GetName(): str(a.Get(1004)) for a in camera.GetPrim().GetAttributes()}, 'lights': []}
for prim in Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies()):
    if not prim.GetTypeName().endswith('Light'):
        continue
    record = {'path': str(prim.GetPath()), 'type': prim.GetTypeName(),
              'visible': str(UsdGeom.Imageable(prim).ComputeVisibility(1004)),
              'attributes': {a.GetName(): str(a.Get(1004)) for a in prim.GetAttributes()
                             if a.HasAuthoredValueOpinion() and not a.GetName().startswith('xformOp')},
              'relationships': {r.GetName(): [str(p) for p in r.GetTargets()] for r in prim.GetRelationships()},
              'world_transform': str(UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(1004))}
    report['lights'].append(record)
(args.out / 'lighting-audit.json').write_text(json.dumps(report, indent=2) + '\n')

layer = Sdf.Layer.CreateNew(str((args.out / 'karma-comparison.usda').resolve()))
layer.subLayerPaths = [args.scene.resolve().as_posix()]
comparison = Usd.Stage.Open(layer)
settings = UsdRender.Settings(comparison.GetPrimAtPath('/Render/MoonRay/settings'))
settings.CreateResolutionAttr(Gf.Vec2i(192, 128))
settings.GetPrim().CreateAttribute('karma:global:samplesperpixel', Sdf.ValueTypeNames.Int).Set(8)
settings.GetPrim().CreateAttribute('karma:global:enableadaptive', Sdf.ValueTypeNames.Bool).Set(False)
settings.GetPrim().CreateAttribute('disableMotionBlur', Sdf.ValueTypeNames.Bool).Set(True)
settings.GetPrim().CreateAttribute('disableDepthOfField', Sdf.ValueTypeNames.Bool).Set(True)
product = UsdRender.Product(comparison.GetPrimAtPath('/Render/MoonRay/beauty'))
product.CreateProductNameAttr((args.out.resolve() / 'karma.exr').as_posix())
product.GetOrderedVarsRel().SetTargets([Sdf.Path('/Render/MoonRay/Vars/beauty')])
karma_var = UsdRender.Var(comparison.GetPrimAtPath('/Render/MoonRay/Vars/beauty'))
karma_var.CreateSourceTypeAttr('lpe')
karma_var.CreateSourceNameAttr('C.*[LO]')
layer.Save()
sun = stage.GetPrimAtPath('/root/lightrig01/lights/set/exterior/lgt_sun_distant')
excludes = sun.GetRelationship('collection:shadowLink:excludes').GetTargets()
report['sun_shadow_excludes'] = [{'path': str(p), 'is_instance': stage.GetPrimAtPath(p).IsInstance(),
                                 'instanceable': stage.GetPrimAtPath(p).IsInstanceable()}
                                for p in excludes]
(args.out / 'lighting-audit.json').write_text(json.dumps(report, indent=2) + '\n')
test_layer = Sdf.Layer.CreateNew(str((args.out / 'moonray-window-test.usda').resolve()))
test_layer.subLayerPaths = [layer.realPath]
test = Usd.Stage.Open(test_layer)
UsdRender.Var(test.GetPrimAtPath('/Render/MoonRay/Vars/beauty')).CreateSourceNameAttr('color')
UsdRender.Var(test.GetPrimAtPath('/Render/MoonRay/Vars/beauty')).CreateSourceTypeAttr('raw')
for path in excludes:
    test.OverridePrim(path).SetInstanceable(False)
UsdRender.Product(test.GetPrimAtPath('/Render/MoonRay/beauty')).CreateProductNameAttr((args.out.resolve() / 'moonray-window-test.exr').as_posix())
test_layer.Save()
occluder_layer = Sdf.Layer.CreateNew(str((args.out / 'moonray-occluder-test.usda').resolve()))
occluder_layer.subLayerPaths = [test_layer.realPath]
occluder_test = Usd.Stage.Open(occluder_layer)
for path in excludes:
    occluder_test.OverridePrim(path).SetActive(False)
UsdRender.Product(occluder_test.GetPrimAtPath('/Render/MoonRay/beauty')).CreateProductNameAttr((args.out.resolve() / 'moonray-occluder-test.exr').as_posix())
occluder_layer.Save()

export_layer = Sdf.Layer.CreateNew(str((args.out / 'light-export.usda').resolve()))
export_layer.subLayerPaths = [test_layer.realPath]
export_stage = Usd.Stage.Open(export_layer)
for prim in export_stage.GetPrimAtPath('/root').GetChildren():
    if prim.GetName() not in ('camera01', 'lightrig01'):
        export_stage.OverridePrim(prim.GetPath()).SetActive(False)
UsdRender.Product(export_stage.GetPrimAtPath('/Render/MoonRay/beauty')).CreateProductNameAttr((args.out.resolve() / 'light-export.exr').as_posix())
UsdRender.Settings(export_stage.GetPrimAtPath('/Render/MoonRay/settings')).CreateResolutionAttr(Gf.Vec2i(32,32))
export_layer.Save()
print(json.dumps(report['sun_shadow_excludes']), flush=True)
print(json.dumps({'lights': len(report['lights']), 'horizontal_aperture': camera.GetHorizontalApertureAttr().Get(1004),
                  'vertical_aperture': camera.GetVerticalApertureAttr().Get(1004)}), flush=True)
