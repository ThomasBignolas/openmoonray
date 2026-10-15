"""Compare rendered camera framing with USD's own projection matrices."""
import argparse
import json
from pathlib import Path
import traceback

import hou
import numpy as np
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdRender, UsdShade
from validate_default_sphere import render, pixels


def scene(out, name, projection, clipping=None):
    stage = Usd.Stage.CreateInMemory()
    points = [(-.4,-.6,0), (1.,-.6,0), (1.,.2,0), (-.4,.2,0)]
    mesh = UsdGeom.Mesh.Define(stage, '/mesh')
    mesh.CreatePointsAttr(points)
    mesh.CreateFaceVertexCountsAttr([4])
    mesh.CreateFaceVertexIndicesAttr([0,1,2,3])
    mesh.CreateSubdivisionSchemeAttr('none')
    material = UsdShade.Material.Define(stage, '/material')
    shader = UsdShade.Shader.Define(stage, '/material/surface')
    shader.CreateIdAttr('UsdPreviewSurface')
    shader.CreateInput('diffuseColor', Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0))
    shader.CreateInput('emissiveColor', Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(.4,.2,.1))
    shader.CreateOutput('surface', Sdf.ValueTypeNames.Token)
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), 'surface')
    UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(material)
    dome = UsdLux.DomeLight.Define(stage, '/light')
    UsdLux.LightAPI(dome).CreateColorAttr(Gf.Vec3f(0))
    camera = UsdGeom.Camera.Define(stage, '/camera')
    camera.AddTranslateOp().Set(Gf.Vec3d(0,0,5))
    camera.CreateProjectionAttr(projection)
    camera.CreateHorizontalApertureAttr(36)
    camera.CreateVerticalApertureAttr(36)
    camera.CreateHorizontalApertureOffsetAttr(1.5)
    camera.CreateVerticalApertureOffsetAttr(-.5)
    camera.CreateFocalLengthAttr(50)
    if clipping:
        camera.CreateClippingRangeAttr(Gf.Vec2f(*clipping))
    settings = UsdRender.Settings.Define(stage, '/Render/settings')
    settings.CreateCameraRel().SetTargets(['/camera'])
    settings.CreateResolutionAttr(Gf.Vec2i(48,48))
    for key, dtype, value in [('localThreads', Sdf.ValueTypeNames.Int, 2),
                              ('executionMode', Sdf.ValueTypeNames.String, 'vectorized'),
                              ('sceneVariable:pixel_samples', Sdf.ValueTypeNames.Int, 3)]:
        settings.GetPrim().CreateAttribute('moonray:' + key, dtype).Set(value)
    product = UsdRender.Product.Define(stage, '/Render/product')
    product.CreateProductNameAttr((out / (name + '.exr')).as_posix())
    var = UsdRender.Var.Define(stage, '/Render/beauty')
    var.CreateSourceNameAttr('color')
    var.CreateDataTypeAttr('color4f')
    var.GetPrim().CreateAttribute('driver:parameters:aov:husk:name', Sdf.ValueTypeNames.String).Set('beauty')
    product.CreateOrderedVarsRel().SetTargets([var.GetPath()])
    settings.CreateProductsRel().SetTargets([product.GetPath()])
    stage.SetMetadata('renderSettingsPrimPath', str(settings.GetPath()))
    frustum = camera.GetCamera(1).frustum
    matrix = np.asarray(frustum.ComputeViewMatrix()) @ np.asarray(frustum.ComputeProjectionMatrix())
    clip = np.array([list(p) + [1.] for p in points]) @ matrix
    ndc = clip[:, :2] / clip[:, 3, None]
    screen = (ndc * [1., -1.] + 1.) * 24
    expected = [screen[:,0].min(), screen[:,0].max(), screen[:,1].min(), screen[:,1].max()]
    return stage, expected


def run(out):
    checks, observations = {}, {}
    for name, projection, clipping in [('perspective', 'perspective', None),
                                       ('orthographic', 'orthographic', None),
                                       ('ortho_short_clip', 'orthographic', (.1,100.))]:
        stage, expected = scene(out, name, projection, clipping)
        render(stage, out, name)
        image = pixels(out / (name + '.exr'))
        y, x = np.where(image[...,3] > .5)
        actual = [int(x.min()), int(x.max()+1), int(y.min()), int(y.max()+1)] if x.size else None
        checks[name + '_visible'] = bool(x.size)
        checks[name + '_framing'] = bool(actual and np.max(np.abs(np.array(actual)-expected)) < 1.5)
        checks[name + '_finite'] = bool(np.isfinite(image).all())
        observations[name] = dict(expected_bounds=expected, actual_bounds=actual,
                                  alpha_sum=float(image[...,3].sum()))
        print(name, observations[name], flush=True)
    return dict(passed=all(checks.values()), checks=checks, observations=observations,
                installation=hou.getenv('MOONRAY_HOUDINI_ROOT'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        result = run(args.out)
    except Exception:
        result = dict(passed=False, error=traceback.format_exc())
    (args.out / 'validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2), flush=True)
    raise SystemExit(0 if result['passed'] else 1)
