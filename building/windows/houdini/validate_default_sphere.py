"""Check Solaris primitive and polygon spheres with and without a material."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import traceback

import hou
import numpy as np
import OpenImageIO as oiio
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdRender, UsdShade


def render(stage, out, name, frames=1):
    path = out / (name + '.usda')
    stage.GetRootLayer().Export(str(path))
    env = dict(os.environ, HDM_LOG_FILE=str(out / (name + '-hydra.log')), HDMOONRAY_INFO='1',
               HDMOONRAY_RDLA_OUTPUT=(out / (name + '.rdla')).as_posix())
    with (out / (name + '.log')).open('w') as log:
        subprocess.run([str(Path(hou.getenv('HFS')) / 'bin/husk.exe'), '--renderer',
            'HdMoonrayRendererPlugin', '--disable-motionblur', '-f', '1', '-n', str(frames), str(path)],
            env=env, stdout=log, stderr=subprocess.STDOUT, timeout=90, check=True)


def pixels(path):
    image = oiio.ImageBuf(str(path))
    assert image.read(), image.geterror()
    return image.get_pixels(oiio.FLOAT)


def extended(out, checks, observations):
    stage = Usd.Stage.Open(str(out / 'primitive_default.usda'))
    sphere = next(UsdGeom.Sphere(p) for p in stage.Traverse() if p.IsA(UsdGeom.Sphere))
    sphere.GetRadiusAttr().Set(1., 1)
    sphere.GetRadiusAttr().Set(.5, 2)
    stage.SetStartTimeCode(1)
    stage.SetEndTimeCode(2)
    product = UsdRender.Product(stage.GetPrimAtPath('/Render/product'))
    product.CreateProductNameAttr((out / 'animated.$F4.exr').as_posix())
    render(stage, out, 'animated', frames=2)
    areas = [float(pixels(out / f'animated.{frame:04}.exr')[..., 3].sum()) for frame in (1, 2)]
    checks['animated_radius_updates'] = .15 < areas[1] / max(areas[0], 1) < .4
    observations['animated_coverage'] = areas

    # One tiny grid exercises all implicit types handled by the standard USD
    # conversion filter. Keep the USD prims implicit in the exported file.
    for prim in list(stage.GetPseudoRoot().GetChildren()):
        if prim.GetName() not in ('Render', 'camera', 'light'):
            stage.RemovePrim(prim.GetPath())
    kinds = (UsdGeom.Sphere, UsdGeom.Cube, UsdGeom.Cone, UsdGeom.Cylinder, UsdGeom.Capsule, UsdGeom.Plane)
    for i, kind in enumerate(kinds):
        shape = kind.Define(stage, '/shapes/' + kind.__name__)
        shape.AddTranslateOp().Set(Gf.Vec3d((i % 3 - 1) * 2.5, 1.25 if i < 3 else -1.25, 0))
        for key, value in [('radius', .6), ('height', 1.2), ('size', 1.2), ('width', 1.2), ('length', 1.2)]:
            attr = shape.GetPrim().GetAttribute(key)
            if attr:
                attr.Set(value)
    camera = UsdGeom.Camera(stage.GetPrimAtPath('/camera'))
    camera.CreateProjectionAttr('perspective')
    camera.CreateHorizontalApertureAttr(75.)
    camera.CreateVerticalApertureAttr(50.)
    settings = UsdRender.Settings(stage.GetPrimAtPath('/Render/settings'))
    settings.CreateResolutionAttr(Gf.Vec2i(96, 64))
    # Test conversion of all six types with a bounded triangle count. The
    # individual sphere and animation above retain ordinary subdivision.
    settings.GetPrim().CreateAttribute('moonray:forcePolygon', Sdf.ValueTypeNames.Bool).Set(True)
    for mode in ('vectorized', 'xpu'):
        name = 'grid_' + mode
        settings.GetPrim().GetAttribute('moonray:executionMode').Set(mode)
        product.CreateProductNameAttr((out / (name + '.exr')).as_posix())
        render(stage, out, name)
        image = pixels(out / (name + '.exr'))
        checks[name + '_finite'] = bool(np.isfinite(image).all())
        for i, kind in enumerate(kinds):
            x, y = (i % 3) * 32 + 16, (i // 3) * 32 + 16
            center = image[y-2:y+2, x-2:x+2]
            checks[name + '_' + kind.__name__] = bool(center[..., 3].mean() > .99 and center[..., :3].mean() > .02)
        if mode == 'xpu':
            log = (out / (name + '.log')).read_text(errors='replace')
            gpu = re.search(r'GPU bundled intersection ray utilization\s*=\s*([\d.]+)%', log)
            checks['grid_xpu_accelerated'] = bool(gpu and float(gpu[1]) > 0) and 'falling back' not in log.lower()


def run(out, extra=False):
    checks, observations = {}, {}
    for name in ('primitive_default', 'polygon_default', 'primitive_assigned'):
        sopcreate = hou.node('/stage').createNode('sopcreate', name)
        sopcreate.parm('primpath').set('/sphere')
        sphere = sopcreate.node('sopnet/create').createNode('sphere')
        if name.startswith('polygon'):
            sphere.parm('type').set('polymesh')
        sphere.setDisplayFlag(True)
        sphere.setRenderFlag(True)
        usd = out / (name + '.usda')
        sopcreate.stage().Flatten().Export(str(usd))
        stage = Usd.Stage.Open(str(usd))
        geometry = [p for p in stage.Traverse() if p.GetTypeName() in ('Mesh', 'Sphere', 'Points')]
        if name.endswith('assigned'):
            material = UsdShade.Material.Define(stage, '/material')
            shader = UsdShade.Shader.Define(stage, '/material/surface')
            shader.CreateIdAttr('UsdPreviewSurface')
            shader.CreateInput('diffuseColor', Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(.5))
            shader.CreateOutput('surface', Sdf.ValueTypeNames.Token)
            material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), 'surface')
            for prim in geometry:
                UsdShade.MaterialBindingAPI.Apply(prim).Bind(material)
        dome = UsdLux.DomeLight.Define(stage, '/light')
        UsdLux.LightAPI(dome).CreateIntensityAttr(1.)
        camera = UsdGeom.Camera.Define(stage, '/camera')
        camera.AddTranslateOp().Set(Gf.Vec3d(0, 0, 5))
        camera.CreateHorizontalApertureAttr(36)
        camera.CreateVerticalApertureAttr(36)
        camera.CreateFocalLengthAttr(50)
        settings = UsdRender.Settings.Define(stage, '/Render/settings')
        settings.CreateCameraRel().SetTargets(['/camera'])
        settings.CreateResolutionAttr(Gf.Vec2i(48, 48))
        for key, dtype, value in [('localThreads', Sdf.ValueTypeNames.Int, 2),
                                  ('executionMode', Sdf.ValueTypeNames.String, 'vectorized'),
                                  ('sceneVariable:pixel_samples', Sdf.ValueTypeNames.Int, 2)]:
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
        stage.GetRootLayer().Save()
        env = dict(os.environ, HDMOONRAY_RDLA_OUTPUT=(out / (name + '.rdla')).as_posix(),
                   HDM_LOG_FILE=str(out / (name + '-hydra.log')))
        with (out / (name + '.log')).open('w') as log:
            subprocess.run([str(Path(hou.getenv('HFS')) / 'bin/husk.exe'), '--renderer',
                'HdMoonrayRendererPlugin', '--disable-motionblur', str(usd)], env=env,
                stdout=log, stderr=subprocess.STDOUT, timeout=60, check=True)
        image = oiio.ImageBuf(str(out / (name + '.exr')))
        assert image.read(), image.geterror()
        pixels = image.get_pixels(oiio.FLOAT)
        center = pixels[20:28, 20:28]
        rdl = (out / (name + '.rdla')).read_text()
        checks[name + '_geometry_exported'] = bool(geometry)
        checks[name + '_opaque_center'] = bool(center[..., 3].mean() > .99)
        checks[name + '_lit_center'] = bool(center[..., :3].mean() > .05)
        checks[name + '_finite'] = bool(np.isfinite(pixels).all())
        if name.endswith('default'):
            checks[name + '_fallback_material'] = 'UsdPreviewSurface("defaultMaterial")' in rdl
        observations[name] = dict(sop_type=sphere.evalParm('type'),
            usd_geometry=[dict(path=str(p.GetPath()), type=str(p.GetTypeName())) for p in geometry],
            center_mean=center.mean(axis=(0, 1)).tolist(),
            rdl_mesh='RdlMeshGeometry(' in rdl)
        print(name, observations[name], flush=True)
    if extra:
        extended(out, checks, observations)
    return dict(passed=all(checks.values()), checks=checks, observations=observations,
                installation=hou.getenv('MOONRAY_HOUDINI_ROOT'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--extended', action='store_true')
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        result = run(args.out, args.extended)
    except Exception:
        result = dict(passed=False, error=traceback.format_exc())
    (args.out / 'validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2), flush=True)
    raise SystemExit(0 if result['passed'] else 1)
