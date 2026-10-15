"""Numerical OCIO and USD regressions, run with Houdini's hython."""
import argparse
import json
import os
from pathlib import Path
import sys
import traceback

import hou
import numpy as np
import OpenImageIO as oiio
import PyOpenColorIO as ocio
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdRender, UsdShade

sys.path.insert(0, str(Path(__file__).with_name('assets') / 'python3.11libs'))
import moonray_color as color


def fixture(path, pixels, colorspace=''):
    pixels = np.asarray(pixels, dtype=np.float32)
    spec = oiio.ImageSpec(pixels.shape[1], pixels.shape[0], pixels.shape[2], oiio.FLOAT)
    spec.channelnames = ('R', 'G', 'B', 'A')[:pixels.shape[2]]
    if pixels.shape[2] == 4:
        spec.alpha_channel = 3
    if colorspace:
        spec.attribute('oiio:ColorSpace', colorspace)
    buf = oiio.ImageBuf(spec)
    assert buf.set_pixels(buf.roi, pixels)
    assert buf.write(str(path)), buf.geterror()


def read(path, mip=0):
    image = oiio.ImageBuf(str(path), 0, mip)
    assert image.read(0, mip), image.geterror()
    return image.get_pixels(oiio.FLOAT), image.spec()


def network(stage, root, filename, mixed=False):
    material = UsdShade.Material.Define(stage, root)
    image = UsdShade.Shader.Define(stage, root + '/texture')
    image.CreateIdAttr('UsdUVTexture')
    image.CreateInput('file', Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(str(filename)))
    image.CreateInput('sourceColorSpace', Sdf.ValueTypeNames.Token).Set('sRGB')
    image.CreateOutput('rgb', Sdf.ValueTypeNames.Float3)
    image.CreateOutput('r', Sdf.ValueTypeNames.Float)
    image.CreateOutput('a', Sdf.ValueTypeNames.Float)
    shader = UsdShade.Shader.Define(stage, root + '/surface')
    shader.CreateIdAttr('UsdPreviewSurface')
    shader.CreateInput('emissiveColor', Sdf.ValueTypeNames.Color3f).ConnectToSource(image.ConnectableAPI(), 'rgb')
    shader.CreateInput('diffuseColor', Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0))
    if mixed:
        shader.CreateInput('roughness', Sdf.ValueTypeNames.Float).ConnectToSource(image.ConnectableAPI(), 'r')
    shader.CreateInput('opacity', Sdf.ValueTypeNames.Float).ConnectToSource(image.ConnectableAPI(), 'a')
    shader.CreateOutput('surface', Sdf.ValueTypeNames.Token)
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), 'surface')
    return material, image, shader


def run(out):
    config_path, cfg = color.load_config()
    source_space = color.space_name(cfg, 'sRGB')
    expected = np.asarray(cfg.getProcessor(source_space, 'ACEScg').getDefaultCPUProcessor().applyRGB([.8, .2, .1]))
    pixels = np.empty((8, 8, 4), dtype=np.float32)
    pixels[:] = [.8, .2, .1, .37]
    source = out / 'color.exr'
    fixture(source, pixels)
    cache = color.TextureCache(out / 'cache', cfg, config_path, 'ACEScg', {'filter': 'box'})
    converted = cache.prepare(str(source), source_space)
    result, spec = read(converted)
    checks = {}
    checks['color_matches_ocio'] = bool(np.max(np.abs(result[..., :3] - expected)) < 2e-5)
    checks['alpha_unchanged'] = bool(np.max(np.abs(result[..., 3] - .37)) < 1e-6)
    checks['tiled'] = bool(spec.tile_width == 64 and spec.tile_height == 64)
    mip, _ = read(converted, 3)
    checks['mip_chain'] = bool(mip.shape[:2] == (1, 1))
    checks['mip_color'] = bool(np.max(np.abs(mip[..., :3] - expected)) < 2e-5)
    raw = cache.prepare(str(source), 'raw', True)
    raw_result, _ = read(raw)
    checks['data_unchanged'] = bool(np.max(np.abs(raw_result - pixels)) < 1e-6)
    reused = cache.prepare(str(source), source_space)
    checks['reuse'] = reused == converted and cache.reused == 1
    changed_filter = color.TextureCache(out / 'cache', cfg, config_path, 'ACEScg', {'filter': 'triangle'})
    checks['filter_invalidates'] = changed_filter.prepare(str(source), source_space) != converted
    require = color.TextureCache(out / 'cache', cfg, config_path, 'ACEScg', {'filter':'box', 'generation':'require'})
    checks['require_reuses_generated_cache'] = require.prepare(str(source), source_space) == converted
    try:
        color.TextureCache(out / 'missing', cfg, config_path, 'ACEScg', {'generation':'require'}).prepare(str(source),source_space)
        checks['require_missing_fails'] = False
    except ValueError:
        checks['require_missing_fails'] = not (out/'missing').exists()
    for tile in (1001,1002):
        fixture(out/f'tile.{tile}.exr',pixels)
    udim = cache.prepare(str(out/'tile.<UDIM>.exr'),source_space)
    checks['udim_tiles'] = all(Path(udim.replace('<UDIM>',str(i))).is_file() for i in (1001,1002))
    checks['udim_values'] = all(np.max(np.abs(read(udim.replace('<UDIM>',str(i)))[0][...,:3]-expected))<2e-5 for i in (1001,1002))
    extreme = pixels.copy()
    extreme[0,0]=[-.125,1.25,32.,.37]
    fixture(out/'data.exr',extreme)
    data = color.TextureCache(out/'cache',cfg,config_path,'ACEScg',{'precision':'half'}).prepare(str(out/'data.exr'),'raw',True)
    checks['data_hdr_and_negative_unchanged'] = bool(np.array_equal(read(data)[0],extreme))
    checks['data_always_float32'] = str(read(data)[1].format) == 'float'
    premult = pixels.copy()
    premult[...,:3] *= premult[...,3:]
    fixture(out/'premult.exr',premult)
    premult_tx = color.TextureCache(out/'cache',cfg,config_path,'ACEScg',{'unpremult':True}).prepare(str(out/'premult.exr'),source_space)
    checks['premultiplied_color_matches'] = bool(np.max(np.abs(read(premult_tx)[0][...,:3]-expected*.37))<2e-5)
    # A nonlinear input must be converted before downsampling: averaging first
    # and then converting yields a different result for this checkerboard.
    checker = np.zeros((2, 2, 3), np.float32)
    checker[0, 0] = checker[1, 1] = 1
    checker_source = out / 'checker.exr'
    fixture(checker_source, checker)
    checker_tx = cache.prepare(str(checker_source), source_space)
    checker_mip, _ = read(checker_tx, 1)
    checks['linear_mipmap_filtering'] = bool(np.max(np.abs(checker_mip - .5)) < .002)

    stage = Usd.Stage.CreateNew(str(out / 'prepared.usda'))
    material, texture, surface = network(stage, '/material', source, mixed=True)
    swatch = surface.CreateInput('specularColor', Sdf.ValueTypeNames.Color3f)
    swatch.Set(Gf.Vec3f(.8, .2, .1))
    swatch.GetAttr().SetColorSpace(source_space)
    for name, dtype, raw_name in [('beauty', 'color4f', 'color'), ('normal', 'normal3f', 'N'),
                                   ('position', 'point3f', 'P'), ('crypto', 'color4f', 'cryptomatte'),
                                   ('named_color', 'color3f', 'Paint')]:
        var = UsdRender.Var.Define(stage, '/Render/' + name)
        var.CreateDataTypeAttr(dtype)
        var.CreateSourceNameAttr(raw_name)
    settings = UsdRender.Settings.Define(stage, '/Render/settings')
    light = UsdLux.DistantLight.Define(stage, '/light')
    api = UsdLux.LightAPI(light)
    api.CreateEnableColorTemperatureAttr(True)
    api.CreateColorTemperatureAttr(3200)
    api.GetColorAttr().Set(Gf.Vec3f(.5,.75,1.),1)
    api.GetColorAttr().Set(Gf.Vec3f(1.,.75,.5),3)
    temperature_expected = np.asarray(cfg.getProcessor(color.space_name(cfg,'lin_rec709'),'ACEScg').getDefaultCPUProcessor().applyRGB(list(UsdLux.BlackbodyTemperatureAsRgb(3200))))
    cp = UsdGeom.Points.Define(stage,'/color_points')
    cp.CreateDisplayColorAttr([Gf.Vec3f(.8,.2,.1),Gf.Vec3f(.8,.2,.1)]).SetColorSpace(source_space)
    report = color.prepare_stage(stage, cache=str(out / 'cache'), texture_options={'filter': 'box'})
    stage.GetRootLayer().Save()
    checks['scene_color_matches_ocio'] = bool(np.max(np.abs(np.asarray(swatch.Get()) - expected)) < 2e-5)
    checks['working_space_authored'] = settings.GetRenderingColorSpaceAttr().Get() == 'ACEScg'
    paths = [surface.GetInput(n).GetAttr().GetConnections()[0].GetPrimPath() for n in ('emissiveColor', 'roughness')]
    checks['mixed_use_split'] = paths[0] != paths[1]
    for path, reference, label in zip(paths, (expected, pixels[0, 0, :3]), ('color_branch', 'data_branch')):
        texture_path = stage.GetPrimAtPath(path).GetAttribute('inputs:file').Get().path
        values, _ = read(texture_path)
        checks[label] = bool(np.max(np.abs(values[..., :3] - reference)) < 2e-5)
    checks['raw_aovs'] = all(stage.GetPrimAtPath('/Render/' + name).GetAttribute('driver:parameters:aov:husk:output_colorspace').Get() == 'raw' for name in ('normal', 'position', 'crypto'))
    checks['color_aov'] = stage.GetPrimAtPath('/Render/beauty').GetAttribute('driver:parameters:aov:husk:source_colorspace').Get() == 'ACEScg'
    checks['named_color_aov'] = stage.GetPrimAtPath('/Render/named_color').GetAttribute('driver:parameters:aov:husk:source_colorspace').Get() == 'ACEScg'
    checks['temperature_baked'] = not api.GetEnableColorTemperatureAttr().Get()
    checks['temperature_samples_match'] = bool(np.max(np.abs(np.asarray(api.GetColorAttr().Get(3))-temperature_expected*[1.,.75,.5]))<2e-5)
    checks['color_arrays_match'] = bool(np.max(np.abs(np.asarray(cp.GetDisplayColorAttr().Get())-expected))<2e-5)
    checks['stage_ocio_config'] = stage.GetColorConfiguration().path == config_path and stage.GetColorManagementSystem() == 'OpenColorIO'
    # Source file remains byte-identical after conversion and stage preparation.
    original, _ = read(source)
    checks['source_preserved'] = bool(np.array_equal(original, pixels))
    # Instanced assets keep geometry instanced and get a converted material
    # through material-only USD reference overlays.
    instanced = Usd.Stage.CreateNew(str(out / 'instances.usda'))
    UsdGeom.Xform.Define(instanced, '/asset')
    inst_material, _, _ = network(instanced, '/asset/material', source)
    mesh = UsdGeom.Mesh.Define(instanced, '/asset/mesh')
    UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(inst_material)
    for name in ('one', 'two'):
        instance = UsdGeom.Xform.Define(instanced, '/' + name)
        instance.GetPrim().GetReferences().AddInternalReference('/asset')
        instance.GetPrim().SetInstanceable(True)
    color.prepare_stage(instanced, cache=str(out / 'cache'), texture_options={'filter': 'box'})
    instanced.GetRootLayer().Save()
    checks['instances_preserved'] = all(instanced.GetPrimAtPath('/' + name).IsInstance() for name in ('one', 'two'))
    checks['instance_materials_prepared'] = all(UsdShade.MaterialBindingAPI(instanced.GetPrimAtPath('/' + name + '/mesh')).ComputeBoundMaterial(UsdShade.Tokens.full)[0].GetPrim().IsInstanceProxy() for name in ('one', 'two'))
    prepared_material, _ = UsdShade.MaterialBindingAPI(instanced.GetPrimAtPath('/one/mesh')).ComputeBoundMaterial(UsdShade.Tokens.full)
    checks['instance_shader_copied'] = instanced.GetPrimAtPath(prepared_material.GetPath().AppendChild('texture')).GetAttribute('inputs:file').Get().path.endswith('.tx')
    branch = Usd.Stage.CreateInMemory()
    _, tex, terminal = network(branch,'/material',source)
    mid = UsdShade.Shader.Define(branch,'/material/correct')
    mid.CreateIdAttr('ColorCorrectMap')
    mid.CreateInput('input',Sdf.ValueTypeNames.Color3f).ConnectToSource(tex.ConnectableAPI(),'rgb')
    mid.CreateOutput('result',Sdf.ValueTypeNames.Color3f)
    for name, dtype in [('emissiveColor',Sdf.ValueTypeNames.Color3f),('roughness',Sdf.ValueTypeNames.Float)]:
        terminal.CreateInput(name,dtype).ConnectToSource(mid.ConnectableAPI(),'result')
    color.prepare_stage(branch,cache=str(out/'cache'))
    links=[terminal.GetInput(n).GetAttr().GetConnections()[0].GetPrimPath() for n in ('emissiveColor','roughness')]
    checks['mixed_intermediate_split'] = links[0] != links[1]
    raw_tex=branch.GetPrimAtPath(links[1]).GetAttribute('inputs:input').GetConnections()[0].GetPrimPath()
    checks['mixed_intermediate_data_unchanged'] = bool(np.max(np.abs(read(branch.GetPrimAtPath(raw_tex).GetAttribute('inputs:file').Get().path)[0]-pixels))<1e-6)
    uv = UsdShade.Shader.Define(branch, '/uv')
    uv.CreateIdAttr('UsdPrimvarReader_float2')
    uv.CreateInput('varname', Sdf.ValueTypeNames.Token).Set('st')
    uv.CreateOutput('result', Sdf.ValueTypeNames.Float2)
    transform = UsdShade.Shader.Define(branch, '/transform')
    transform.CreateIdAttr('UsdTransform2d')
    transform.CreateInput('in', Sdf.ValueTypeNames.Float2).ConnectToSource(uv.ConnectableAPI(), 'result')
    transform.CreateInput('scale', Sdf.ValueTypeNames.Float2).Set(Gf.Vec2f(2,3))
    transform.CreateInput('rotation', Sdf.ValueTypeNames.Float).Set(90)
    transform.GetInput('rotation').Set(0, 2)
    transform.CreateOutput('result', Sdf.ValueTypeNames.Float2)
    tex.CreateInput('st', Sdf.ValueTypeNames.Float2).ConnectToSource(transform.ConnectableAPI(), 'result')
    color._uv_derivatives(branch, tex.GetPrim(), 1)
    matrix = lambda t: np.asarray([tex.GetInput('st_derivative_'+axis).Get(t) for axis in ('u','v')])
    checks['transformed_uv_footprint'] = bool(np.max(np.abs(matrix(Usd.TimeCode.Default())-[[0,-3],[2,0]]))<1e-6)
    checks['animated_uv_footprint'] = bool(np.max(np.abs(matrix(2)-[[2,0],[0,3]]))<1e-6)
    return {'passed': all(checks.values()), 'checks': checks, 'prepare': report,
            'expected': expected.tolist(), 'actual': result[0, 0].tolist()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        result = run(args.out.resolve())
    except Exception:
        result = {'passed': False, 'error': traceback.format_exc()}
    (args.out / 'validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2), flush=True)
    raise SystemExit(0 if result['passed'] else 1)
