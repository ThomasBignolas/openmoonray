"""Check preview settings through Solaris authoring and real Hydra renders."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import traceback

import hou
import numpy as np
import OpenImageIO as oiio
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdRender, UsdShade
import moonray_houdini as mr


def run(out):
    checks, timings, images = {}, {}, {}
    rop = mr.create_render_setup()
    node = mr.render_settings_node(rop)
    for name in ('forcePolygon', 'info'):
        key = 'moonray:' + name
        mr._set(node, key, True)
        checks[name + '_authored'] = node.stage().GetPrimAtPath(
            node.evalParm('primpath')).GetAttribute(key).Get() is True
    node_path = node.path()
    hou.hipFile.save(str(out / 'Preview_Controls.hip'))
    hou.hipFile.load(str(out / 'Preview_Controls.hip'), suppress_save_prompt=True)
    node = hou.node(node_path)
    checks['hip_persistence'] = all(node.evalParm(hou.text.encodeParm('moonray:' + name))
                                    for name in ('forcePolygon', 'info'))
    for name, authored, legacy in [('polygon', True, False), ('subdiv', False, True),
                                    ('legacy', None, True)]:
        stage = Usd.Stage.CreateNew(str(out / (name + '.usda')))
        mesh = UsdGeom.Mesh.Define(stage, '/mesh')
        mesh.CreatePointsAttr([(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),
                              (-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)])
        mesh.CreateFaceVertexCountsAttr([4]*6)
        mesh.CreateFaceVertexIndicesAttr([0,3,2,1,4,5,6,7,0,1,5,4,3,7,6,2,0,4,7,3,1,2,6,5])
        mesh.CreateSubdivisionSchemeAttr('catmullClark')
        material = UsdShade.Material.Define(stage, '/material')
        shader = UsdShade.Shader.Define(stage, '/material/surface')
        shader.CreateIdAttr('UsdPreviewSurface')
        shader.CreateInput('diffuseColor', Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0))
        shader.CreateInput('emissiveColor', Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(.4,.2,.1))
        shader.CreateOutput('surface', Sdf.ValueTypeNames.Token)
        material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), 'surface')
        UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(material)
        dome = UsdLux.DomeLight.Define(stage, '/dome')
        UsdLux.LightAPI(dome).CreateColorAttr(Gf.Vec3f(0))
        camera = UsdGeom.Camera.Define(stage, '/camera')
        camera.AddTranslateOp().Set(Gf.Vec3d(0,0,6))
        camera.CreateHorizontalApertureAttr(36)
        camera.CreateVerticalApertureAttr(36)
        camera.CreateFocalLengthAttr(50)
        settings = UsdRender.Settings.Define(stage, '/Render/settings')
        settings.CreateCameraRel().SetTargets(['/camera'])
        settings.CreateResolutionAttr(Gf.Vec2i(48,48))
        for key, dtype, value in [('localThreads', Sdf.ValueTypeNames.Int, 2),
                                  ('executionMode', Sdf.ValueTypeNames.String, 'vectorized'),
                                  ('info', Sdf.ValueTypeNames.Bool, True),
                                  ('sceneVariable:pixel_samples', Sdf.ValueTypeNames.Int, 2)]:
            settings.GetPrim().CreateAttribute('moonray:' + key, dtype).Set(value)
        if authored is not None:
            settings.GetPrim().CreateAttribute('moonray:forcePolygon', Sdf.ValueTypeNames.Bool).Set(authored)
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
        env = dict(os.environ, HDMOONRAY_FORCE_POLYGON=str(int(legacy)),
                   HDM_LOG_FILE=str(out / (name + '-hydra.log')),
                   HDMOONRAY_RDLA_OUTPUT=(out / (name + '.rdla')).as_posix())
        started = time.monotonic()
        with (out / (name + '.log')).open('w') as log:
            subprocess.run([str(Path(hou.getenv('HFS'))/'bin/husk.exe'), '--renderer',
                            'HdMoonrayRendererPlugin', '--complexity', 'high', '--disable-motionblur',
                            str(out / (name + '.usda'))], env=env, stdout=log,
                           stderr=subprocess.STDOUT, timeout=60, check=True)
        timings[name] = round(time.monotonic() - started, 3)
        rdl = (out / (name + '.rdla')).read_text()
        checks[name + '_geometry'] = ('["is_subd"] = false' in rdl) == (name != 'subdiv')
        checks[name + '_info_enabled'] = '["log_info"] = true' in rdl
        checks[name + '_first_image_logged'] = 'First MoonRay image received' in (out / (name + '-hydra.log')).read_text()
        image = oiio.ImageBuf(str(out / (name + '.exr')))
        assert image.read(), image.geterror()
        images[name] = image.get_pixels(oiio.FLOAT)
        checks[name + '_pixels'] = bool(np.isfinite(images[name]).all() and images[name].max() > .1)
    checks['preview_changes_silhouette'] = bool(np.mean(np.abs(images['polygon']-images['subdiv'])) > .02)
    checks['legacy_preserved'] = bool(np.max(np.abs(images['polygon']-images['legacy'])) < .001)
    return dict(passed=all(checks.values()), checks=checks, total_render_seconds=timings,
                package=hou.getenv('MOONRAY_HOUDINI_ROOT'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
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
