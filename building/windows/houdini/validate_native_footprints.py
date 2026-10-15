"""Render standard USD textures without a MoonRay Color Management LOP."""
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


def scene(out, name, frame, write=True):
    stage = Usd.Stage.CreateInMemory()
    material = UsdShade.Material.Define(stage, '/material')
    reader = UsdShade.Shader.Define(stage, '/material/reader')
    reader.CreateIdAttr('UsdPrimvarReader_float2')
    reader.CreateInput('varname', Sdf.ValueTypeNames.Token).Set('other' if name == 'other' else 'st')
    reader.CreateOutput('result', Sdf.ValueTypeNames.Float2)
    source = reader
    expected = np.eye(2)
    if name in ('affine', 'animated1', 'animated2'):
        for index, (scale, rotation) in enumerate([((3, 2), 90), ((2, 4), -90)]):
            transform = UsdShade.Shader.Define(stage, '/material/transform' + str(index))
            transform.CreateIdAttr('UsdTransform2d')
            transform.CreateInput('in', Sdf.ValueTypeNames.Float2).ConnectToSource(source.ConnectableAPI(), 'result')
            scale_input = transform.CreateInput('scale', Sdf.ValueTypeNames.Float2)
            scale_input.Set(Gf.Vec2f(*scale))
            if name.startswith('animated') and index == 0:
                scale_input.Set(Gf.Vec2f(*scale), 1)
                scale_input.Set(Gf.Vec2f(6, 5), 2)
                scale = scale if frame == 1 else (6, 5)
            transform.CreateInput('rotation', Sdf.ValueTypeNames.Float).Set(rotation)
            transform.CreateInput('translation', Sdf.ValueTypeNames.Float2).Set(Gf.Vec2f(.2, .3))
            transform.CreateOutput('result', Sdf.ValueTypeNames.Float2)
            angle = np.deg2rad(rotation)
            c, s = np.cos(angle), np.sin(angle)
            expected = np.array([[c * scale[0], -s * scale[1]], [s * scale[0], c * scale[1]]]) @ expected
            source = transform
    texture = UsdShade.Shader.Define(stage, '/material/texture')
    texture.CreateIdAttr('UsdUVTexture')
    texture.CreateInput('file', Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath((out / 'checker.tx').as_posix()))
    texture.CreateInput('sourceColorSpace', Sdf.ValueTypeNames.Token).Set('raw')
    for axis in ('S', 'T'):
        texture.CreateInput('wrap' + axis, Sdf.ValueTypeNames.Token).Set('repeat')
    st = texture.CreateInput('st', Sdf.ValueTypeNames.Float2)
    if name == 'constant':
        st.Set(Gf.Vec2f(.25, .25))
        expected = np.zeros((2, 2))
    else:
        st.ConnectToSource(source.ConnectableAPI(), 'result')
    if name == 'other':
        expected = np.zeros((2, 2))
    if name == 'explicit':
        expected = np.array([[2., .25], [.5, 3.]])
        for row, key in zip(expected, ('st_derivative_u', 'st_derivative_v')):
            texture.CreateInput(key, Sdf.ValueTypeNames.Float2).Set(Gf.Vec2f(*row))
    texture.CreateOutput('rgb', Sdf.ValueTypeNames.Float3)
    surface = UsdShade.Shader.Define(stage, '/material/surface')
    surface.CreateIdAttr('UsdPreviewSurface')
    surface.CreateInput('diffuseColor', Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0))
    surface.CreateInput('emissiveColor', Sdf.ValueTypeNames.Color3f).ConnectToSource(texture.ConnectableAPI(), 'rgb')
    surface.CreateOutput('surface', Sdf.ValueTypeNames.Token)
    material.CreateSurfaceOutput().ConnectToSource(surface.ConnectableAPI(), 'surface')
    mesh = UsdGeom.Mesh.Define(stage, '/mesh')
    mesh.CreatePointsAttr([(-2,-2,0), (2,-2,0), (2,2,0), (-2,2,0)])
    mesh.CreateFaceVertexCountsAttr([4])
    mesh.CreateFaceVertexIndicesAttr([0,1,2,3])
    mesh.CreateSubdivisionSchemeAttr('none')
    for key in ('st', 'other'):
        UsdGeom.PrimvarsAPI(mesh).CreatePrimvar(key, Sdf.ValueTypeNames.TexCoord2fArray,
            UsdGeom.Tokens.faceVarying).Set([(0,0), (1,0), (1,1), (0,1)])
    UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(material)
    dome = UsdLux.DomeLight.Define(stage, '/dome')
    UsdLux.LightAPI(dome).CreateColorAttr(Gf.Vec3f(0))
    camera = UsdGeom.Camera.Define(stage, '/camera')
    camera.AddTranslateOp().Set(Gf.Vec3d(0,0,5))
    camera.CreateHorizontalApertureAttr(36)
    camera.CreateVerticalApertureAttr(36)
    camera.CreateFocalLengthAttr(50)
    settings = UsdRender.Settings.Define(stage, '/Render/settings')
    settings.CreateCameraRel().SetTargets(['/camera'])
    settings.CreateResolutionAttr(Gf.Vec2i(32,32))
    for key, dtype, value in [('localThreads', Sdf.ValueTypeNames.Int, 2),
                              ('executionMode', Sdf.ValueTypeNames.String, name if name in ('scalar', 'xpu') else 'vectorized'),
                              ('info', Sdf.ValueTypeNames.Bool, True),
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
    if write:
        stage.GetRootLayer().Export(str(out / (name + '.usda')))
    return expected


def run(out, cases, check_existing=False):
    if not check_existing:
        yy, xx = np.mgrid[0:512, 0:512]
        pixels = np.repeat(((xx + yy) % 2)[..., None], 3, axis=2).astype(np.float32)
        buf = oiio.ImageBuf(oiio.ImageSpec(512, 512, 3, oiio.FLOAT))
        assert buf.set_pixels(buf.roi, pixels)
        spec = oiio.ImageSpec()
        spec.attribute('maketx:filtername', 'box')
        assert oiio.ImageBufAlgo.make_texture(oiio.MakeTxTexture, buf, str(out / 'checker.tx'), spec)
    checks, measurements = {}, {}
    for name in cases:
        frame = 2 if name == 'animated2' else 1
        expected = scene(out, name, frame, write=not check_existing)
        env = dict(os.environ, HDMOONRAY_RDLA_OUTPUT=(out / (name + '.rdla')).as_posix(),
                   HDM_LOG_FILE=str(out / (name + '-hydra.log')))
        if not check_existing:
            with (out / (name + '.log')).open('w') as log:
                subprocess.run([str(Path(hou.getenv('HFS')) / 'bin/husk.exe'), '--renderer',
                    'HdMoonrayRendererPlugin', '--frame', str(frame), '--disable-motionblur',
                    str(out / (name + '.usda'))], env=env, stdout=log, stderr=subprocess.STDOUT,
                    timeout=60, check=True)
        rdl = (out / (name + '.rdla')).read_text()
        actual = []
        for key in ('st_derivative_u', 'st_derivative_v'):
            match = re.search(r'\["' + key + r'"\] = Vec2\(([^)]+)\)', rdl)
            actual.append([float(v) for v in match[1].split(',')] if match else [0., 0.])
        checks[name + '_footprint'] = bool(np.allclose(actual, expected, atol=1e-5))
        image = oiio.ImageBuf(str(out / (name + '.exr')))
        assert image.read(), image.geterror()
        data = image.get_pixels(oiio.FLOAT)
        center = data[6:26, 6:26, :3]
        checks[name + '_finite'] = bool(np.isfinite(data).all())
        if name not in ('constant', 'other'):
            checks[name + '_minified_gray'] = bool(np.max(np.abs(center - .5)) < .01)
        log = (out / (name + '.log')).read_text(errors='replace')
        checks[name + '_no_errors'] = not re.search(r'\b(?:Error|Fatal):|sample failure', log)
        if name == 'xpu':
            gpu = re.search(r'GPU bundled intersection ray utilization\s*=\s*([\d.]+)%', log)
            checks['xpu_no_fallback'] = 'falling back' not in log.lower() and bool(gpu and float(gpu[1]) > 0)
        measurements[name] = dict(footprint=actual, mean=float(center.mean()), stddev=float(center.std()),
                                  max_gray_error=float(np.max(np.abs(center - .5))))
        print(name, measurements[name], flush=True)
    return dict(passed=all(checks.values()), checks=checks, measurements=measurements,
                package=hou.getenv('MOONRAY_HOUDINI_ROOT'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--check', action='store_true', help='Check existing images and logs without rendering')
    parser.add_argument('--cases', default='identity,affine,animated1,animated2,constant,other,explicit,scalar,xpu')
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        result = run(args.out, args.cases.split(','), args.check)
    except Exception:
        result = dict(passed=False, error=traceback.format_exc())
    (args.out / 'validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2), flush=True)
    raise SystemExit(0 if result['passed'] else 1)
