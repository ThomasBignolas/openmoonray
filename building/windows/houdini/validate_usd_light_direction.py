"""Render a known USD light-facing test to isolate light-axis translation."""
from pathlib import Path
import subprocess
import sys
import os

import hou
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdRender, UsdShade

out = Path(sys.argv[1]).resolve()
out.mkdir(parents=True, exist_ok=True)
shadow_test = '--shadow' in sys.argv[2:]
for flipped in (False, True):
    label = ('shadow_excluded' if flipped else 'shadow_cast') if shadow_test else ('rect_flipped' if flipped else 'rect_usd')
    stage = Usd.Stage.CreateNew(str(out / (label + '.usda')))
    plane = UsdGeom.Mesh.Define(stage, '/plane')
    plane.CreatePointsAttr([(-2,-2,0), (2,-2,0), (2,2,0), (-2,2,0)])
    plane.CreateFaceVertexCountsAttr([4])
    plane.CreateFaceVertexIndicesAttr([0,1,2,3])
    plane.CreateSubdivisionSchemeAttr('none')
    material = UsdShade.Material.Define(stage, '/material')
    shader = UsdShade.Shader.Define(stage, '/material/surface')
    shader.CreateIdAttr('UsdPreviewSurface')
    shader.CreateInput('diffuseColor', Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(.5))
    shader.CreateOutput('surface', Sdf.ValueTypeNames.Token)
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), 'surface')
    UsdShade.MaterialBindingAPI.Apply(plane.GetPrim()).Bind(material)
    camera = UsdGeom.Camera.Define(stage, '/camera')
    camera.AddTranslateOp().Set(Gf.Vec3d(0,0,5))
    camera.CreateHorizontalApertureAttr(36)
    camera.CreateVerticalApertureAttr(36)
    camera.CreateFocalLengthAttr(35)
    light = UsdLux.RectLight.Define(stage, '/light')
    light.AddTranslateOp().Set(Gf.Vec3d(0,0,3))
    if flipped and not shadow_test:
        light.AddRotateYOp().Set(180)
    light.CreateWidthAttr(2)
    light.CreateHeightAttr(2)
    UsdLux.LightAPI(light).CreateIntensityAttr(10)
    if shadow_test:
        blocker = UsdGeom.Mesh.Define(stage, '/blocker')
        blocker.CreatePointsAttr([(-.7,-.7,0), (.7,-.7,0), (.7,.7,0), (-.7,.7,0)])
        blocker.CreateFaceVertexCountsAttr([4])
        blocker.CreateFaceVertexIndicesAttr([0,1,2,3])
        blocker.CreateSubdivisionSchemeAttr('none')
        blocker.CreateDoubleSidedAttr(True)
        blocker.AddTranslateOp().Set(Gf.Vec3d(0, 0, 1.5))
        blocker.AddScaleOp().Set(Gf.Vec3f(1, 1, .1))
        UsdGeom.PrimvarsAPI(blocker).CreatePrimvar('moonray:visible_in_camera', Sdf.ValueTypeNames.Bool).Set(False)
        collection = Usd.CollectionAPI.Apply(light.GetPrim(), 'shadowLink')
        collection.CreateIncludeRootAttr(True)
        if flipped:
            collection.CreateExcludesRel().SetTargets(['/blocker'])
    settings = UsdRender.Settings.Define(stage, '/Render/settings')
    settings.CreateCameraRel().SetTargets(['/camera'])
    settings.CreateResolutionAttr(Gf.Vec2i(48,48))
    settings.GetPrim().CreateAttribute('moonray:localThreads', Sdf.ValueTypeNames.Int).Set(2)
    settings.GetPrim().CreateAttribute('moonray:executionMode', Sdf.ValueTypeNames.String).Set('vectorized')
    settings.GetPrim().CreateAttribute('moonray:sceneVariable:pixel_samples', Sdf.ValueTypeNames.Int).Set(2)
    product = UsdRender.Product.Define(stage, '/Render/beauty')
    product.CreateProductNameAttr((out / (label + '.exr')).as_posix())
    var = UsdRender.Var.Define(stage, '/Render/beauty_var')
    var.CreateSourceNameAttr('color')
    var.CreateDataTypeAttr('color4f')
    var.GetPrim().CreateAttribute('driver:parameters:aov:husk:name', Sdf.ValueTypeNames.String).Set('beauty')
    product.CreateOrderedVarsRel().SetTargets([var.GetPath()])
    settings.CreateProductsRel().SetTargets([product.GetPath()])
    stage.GetRootLayer().Save()
    with (out / (label + '.log')).open('w') as log:
        environment = dict(os.environ, HDMOONRAY_RDLA_OUTPUT=(out / (label + '.rdla')).as_posix())
        result = subprocess.run([str(Path(hou.getenv('HFS')) / 'bin/husk.exe'), '--renderer',
            'HdMoonrayRendererPlugin', '--settings', '/Render/settings', '--complexity', 'low',
            '--disable-motionblur', str(out / (label + '.usda'))], stdout=log, stderr=subprocess.STDOUT, timeout=60, env=environment)
    assert result.returncode == 0, (label, result.returncode)
    print(label + ' rendered', flush=True)
