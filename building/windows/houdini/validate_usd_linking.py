"""Scene-independent USD light/shadow linking render regressions.

Run with hython to generate/render, then worker Python with --check to inspect
the images. No external assets or scene-specific renderer overrides are used.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess


def render(out):
    import hou
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdRender, UsdShade

    cases = ('unblocked', 'casts', 'shadow_excluded', 'shadow_include_empty',
             'shadow_include_blocker', 'light_excluded', 'unlit_blocker_excluded',
             'unlit_blocker_casts', 'native_casts', 'native_excluded',
             'point_casts', 'point_excluded')
    for case in cases:
        stage = Usd.Stage.CreateNew(str(out / (case + '.usda')))
        instanced = case.startswith(('native_', 'point_'))
        for name, size, height in (('plane', 2, 0), ('blocker', .7, 1.5)):
            path = '/prototype/mesh' if name == 'blocker' and instanced else '/' + name
            if name == 'blocker' and instanced:
                UsdGeom.Xform.Define(stage, '/prototype')
            mesh = UsdGeom.Mesh.Define(stage, path)
            mesh.CreatePointsAttr([(-size, -size, 0), (size, -size, 0),
                                   (size, size, 0), (-size, size, 0)])
            mesh.CreateFaceVertexCountsAttr([4])
            mesh.CreateFaceVertexIndicesAttr([0, 1, 2, 3])
            mesh.CreateSubdivisionSchemeAttr('none')
            mesh.CreateDoubleSidedAttr(True)
            mesh.AddTranslateOp().Set(Gf.Vec3d(0, 0, height))
            if name == 'blocker':
                UsdGeom.PrimvarsAPI(mesh).CreatePrimvar(
                    'moonray:visible_in_camera', Sdf.ValueTypeNames.Bool).Set(False)
                if case == 'unblocked':
                    mesh.GetPrim().SetActive(False)
        if instanced:
            # Keep the prototype out of the image without modifying the
            # referenced mesh or disabling shadow visibility globally.
            UsdGeom.Xform(stage.GetPrimAtPath('/prototype')).AddTranslateOp().Set(Gf.Vec3d(100, 0, 0))
            if case.startswith('native_'):
                blocker = UsdGeom.Xform.Define(stage, '/blocker')
                blocker.GetPrim().GetReferences().AddInternalReference('/prototype')
                blocker.GetPrim().GetAttribute('xformOp:translate').Set(Gf.Vec3d(0))
                blocker.GetPrim().SetInstanceable(True)
                assert blocker.GetPrim().IsInstance()
            else:
                blocker = UsdGeom.PointInstancer.Define(stage, '/blocker')
                blocker.CreatePrototypesRel().SetTargets(['/prototype/mesh'])
                blocker.CreateProtoIndicesAttr([0])
                blocker.CreatePositionsAttr([Gf.Vec3f(0)])
        material = UsdShade.Material.Define(stage, '/material')
        shader = UsdShade.Shader.Define(stage, '/material/surface')
        shader.CreateIdAttr('UsdPreviewSurface')
        shader.CreateInput('diffuseColor', Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(.5))
        shader.CreateOutput('surface', Sdf.ValueTypeNames.Token)
        material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), 'surface')
        UsdShade.MaterialBindingAPI.Apply(stage.GetPrimAtPath('/plane')).Bind(material)
        camera = UsdGeom.Camera.Define(stage, '/camera')
        camera.AddTranslateOp().Set(Gf.Vec3d(0, 0, 5))
        camera.CreateHorizontalApertureAttr(36)
        camera.CreateVerticalApertureAttr(36)
        camera.CreateFocalLengthAttr(35)
        light = UsdLux.RectLight.Define(stage, '/light')
        light.AddTranslateOp().Set(Gf.Vec3d(0, 0, 3))
        light.CreateWidthAttr(2)
        light.CreateHeightAttr(2)
        UsdLux.LightAPI(light).CreateIntensityAttr(10)
        shadow = Usd.CollectionAPI.Apply(light.GetPrim(), 'shadowLink')
        shadow.CreateIncludeRootAttr(True)
        if case in ('shadow_excluded', 'unlit_blocker_excluded', 'native_excluded', 'point_excluded'):
            shadow.CreateExcludesRel().SetTargets(['/blocker'])
        elif case.startswith('shadow_include_'):
            shadow.CreateIncludeRootAttr(False)
            if case == 'shadow_include_blocker':
                shadow.CreateIncludesRel().SetTargets(['/blocker'])
        if case in ('light_excluded', 'unlit_blocker_excluded', 'unlit_blocker_casts'):
            link = Usd.CollectionAPI.Apply(light.GetPrim(), 'lightLink')
            link.CreateIncludeRootAttr(True)
            link.CreateExcludesRel().SetTargets([
                '/plane' if case == 'light_excluded' else '/blocker'])
        settings = UsdRender.Settings.Define(stage, '/Render/settings')
        settings.CreateCameraRel().SetTargets(['/camera'])
        settings.CreateResolutionAttr(Gf.Vec2i(48, 48))
        for name, kind, value in (
                ('localThreads', Sdf.ValueTypeNames.Int, 2),
                ('executionMode', Sdf.ValueTypeNames.String, 'vectorized'),
                ('sceneVariable:pixel_samples', Sdf.ValueTypeNames.Int, 4),
                ('sceneVariable:max_diffuse_depth', Sdf.ValueTypeNames.Int, 0)):
            settings.GetPrim().CreateAttribute('moonray:' + name, kind).Set(value)
        product = UsdRender.Product.Define(stage, '/Render/beauty')
        product.CreateProductNameAttr((out / (case + '.exr')).as_posix())
        var = UsdRender.Var.Define(stage, '/Render/beauty_var')
        var.CreateSourceNameAttr('color')
        var.CreateDataTypeAttr('color4f')
        var.GetPrim().CreateAttribute('driver:parameters:aov:husk:name',
                                     Sdf.ValueTypeNames.String).Set('beauty')
        product.CreateOrderedVarsRel().SetTargets([var.GetPath()])
        settings.CreateProductsRel().SetTargets([product.GetPath()])
        stage.GetRootLayer().Save()
        environment = dict(os.environ,
            HDMOONRAY_RDLA_OUTPUT=(out / (case + '.rdla')).as_posix())
        with (out / (case + '.log')).open('w') as log:
            subprocess.run([str(Path(hou.getenv('HFS')) / 'bin/husk.exe'),
                '--renderer', 'HdMoonrayRendererPlugin', '--settings', '/Render/settings',
                '--complexity', 'low', '--disable-motionblur',
                str(out / (case + '.usda'))], env=environment, stdout=log,
                stderr=subprocess.STDOUT, timeout=90, check=True)
        print(case + ' rendered', flush=True)


def check(out):
    handles = []
    for folder in os.environ['PATH'].split(os.pathsep):
        try:
            handles.append(os.add_dll_directory(folder))
        except OSError:
            pass
    import OpenImageIO as oiio
    stats = {}
    for path in sorted(out.glob('*.exr')):
        image = oiio.ImageBuf(str(path))
        assert image.read(), image.geterror()
        stat = oiio.ImageBufAlgo.computePixelStats(image)
        assert not any(stat.nancount) and not any(stat.infcount), path
        # Central receiving surface, away from silhouette and sampling edges.
        mean = sum(sum(image.getpixel(x, y)[:3]) / 3
                   for y in range(20, 28) for x in range(20, 28)) / 64
        stats[path.stem] = mean
    assertions = {
        'ordinary_shadows': stats['casts'] < stats['unblocked'] * .3,
        'shadow_exclusion': stats['shadow_excluded'] > stats['unblocked'] * .9,
        'empty_shadow_inclusion': stats['shadow_include_empty'] > stats['unblocked'] * .9,
        'explicit_shadow_inclusion': abs(stats['shadow_include_blocker'] - stats['casts']) < .02,
        'light_exclusion': stats['light_excluded'] < stats['unblocked'] * .01,
        'independent_light_and_shadow_links': stats['unlit_blocker_excluded'] > stats['unblocked'] * .9,
        'unlit_objects_still_cast_shadows': abs(stats['unlit_blocker_casts'] - stats['casts']) < .02,
        'native_instance_shadows': abs(stats['native_casts'] - stats['casts']) < .02,
        'native_instance_exclusion': stats['native_excluded'] > stats['unblocked'] * .9,
        'point_instance_shadows': abs(stats['point_casts'] - stats['casts']) < .02,
        'point_instance_exclusion': stats['point_excluded'] > stats['unblocked'] * .9,
    }
    report = {'central_rgb_mean': stats, 'checks': assertions, 'passed': all(assertions.values())}
    (out / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    assert report['passed'], 'USD light/shadow linking regression failed'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    (check if args.check else render)(output)
