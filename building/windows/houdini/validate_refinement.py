"""Small real-render and image-file checks for geometry controls and denoising."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import traceback

import hou
import numpy as np
import OpenImageIO as oiio
from pxr import Sdf, UsdGeom, UsdRender
import moonray_denoise as denoise
import moonray_houdini as mr


def read(path):
    image = oiio.ImageBuf(str(path))
    assert image.read(), image.geterror()
    return image.spec(), image.get_pixels(oiio.FLOAT)


def parts(path):
    first = oiio.ImageBuf(str(path))
    assert first.read(), first.geterror()
    result = {}
    for part in range(first.nsubimages):
        image = oiio.ImageBuf(str(path), part, 0)
        assert image.read(part, 0, True), image.geterror()
        spec = image.spec()
        result[spec.get_string_attribute('oiio:subimagename')] = (spec, image.get_pixels(oiio.FLOAT))
    return result


def run(out, demo):
    checks, metrics = {}, {}
    host = Path(hou.getenv('MOONRAY_HOUDINI_ROOT'))
    worker, env = denoise.worker_environment(host)
    executable = worker / 'bin/denoise.exe'

    def command(arguments, name, success=True):
        result = subprocess.run([str(executable)] + list(map(str, arguments)), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
        (out / (name + '.log')).write_bytes(result.stdout)
        assert (result.returncode == 0) == success, (name, result.returncode, result.stdout[-2500:])
        return result

    # A 15-channel EXR reproduces the original four-channel allocation hazard.
    rng = np.random.default_rng(45)
    h, w = 64, 96
    y, x = np.mgrid[:h, :w]
    clean = np.zeros((h, w, 3), dtype=np.float32)
    clean[:] = (.2, .45, .7)
    clean[:, w//2:] = (.65, .3, .15)
    noisy = np.maximum(0, clean + rng.normal(0, .08, clean.shape)).astype(np.float32)
    alpha = ((x + y) / (h + w)).astype(np.float32)[..., None]
    normals = np.zeros_like(clean)
    normals[..., 2] = 1
    data = np.concatenate((noisy, alpha, clean, normals,
                           np.ones((h, w, 5), np.float32) * .123), axis=-1)
    spec = oiio.ImageSpec(w, h, data.shape[-1], oiio.FLOAT)
    spec.channelnames = ['beauty.R', 'beauty.G', 'beauty.B', 'beauty.A',
                         'denoise_albedo.R', 'denoise_albedo.G', 'denoise_albedo.B',
                         'denoise_normal.x', 'denoise_normal.y', 'denoise_normal.z',
                         'crypto00.R', 'crypto00.G', 'crypto00.B', 'crypto00.A', 'Z']
    spec.x, spec.y, spec.full_width, spec.full_height = 7, 9, 120, 90
    spec.attribute('compression', 'zip')
    spec.attribute('oiio:ColorSpace', 'ACEScg')
    spec.attribute('chromaticities', oiio.TypeDesc('float[8]'),
                   (.713, .293, .165, .830, .128, .044, .32168, .33767))
    spec.attribute('cryptomatte/abcdefg/name', 'crypto')

    def write(path, image_spec, pixels):
        output = oiio.ImageOutput.create(str(path))
        assert output.open(str(path), image_spec), output.geterror()
        assert output.write_image(pixels), output.geterror()
        assert output.close(), output.geterror()

    source = out / 'multilayer input.exr'
    target = out / 'multilayer denoised.exr'
    write(source, spec, data)
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    arguments = ['-in', source, '-layer', 'beauty', '-albedo', source, '-albedo-layer', 'denoise_albedo',
                 '-normals', source, '-normal-layer', 'denoise_normal', '-mode', 'oidn_cpu', '-out', target]
    command(arguments, 'multilayer')
    actual_spec, actual = read(target)
    checks['multilayer_finite'] = bool(actual.shape == (h, w, 4) and np.isfinite(actual).all())
    checks['alpha_exact'] = bool(np.array_equal(actual[..., 3], alpha[..., 0]))
    checks['source_unchanged'] = hashlib.sha256(source.read_bytes()).hexdigest() == original
    before, after = [float(np.mean((image - clean)**2)**.5) for image in (noisy, actual[..., :3])]
    metrics.update(noisy_rmse=before, denoised_rmse=after)
    checks['noise_reduced'] = after < before * .65
    checks['crop_retained'] = (actual_spec.x, actual_spec.y, actual_spec.full_width, actual_spec.full_height) == (7, 9, 120, 90)
    checks['chromaticities_retained'] = bool(np.allclose(actual_spec.getattribute('chromaticities'),
                                                       spec.getattribute('chromaticities')))
    checks['no_false_crypto_metadata'] = not any(a.name.startswith('cryptomatte/') for a in actual_spec.extra_attribs)
    output_hash = hashlib.sha256(target.read_bytes()).hexdigest()
    command(arguments, 'existing-output', success=False)
    checks['existing_output_protected'] = hashlib.sha256(target.read_bytes()).hexdigest() == output_hash
    command(['-in', source, '-layer', 'missing', '-mode', 'oidn_cpu', '-out', out/'missing.exr'], 'missing-layer', False)
    checks['missing_layer_no_output'] = not (out/'missing.exr').exists()
    command(['-in', source, '-out', source], 'source-output-alias', False)
    checks['alias_protected'] = hashlib.sha256(source.read_bytes()).hexdigest() == original
    bad = data.copy()
    bad[0, 0, 0] = np.nan
    write(out/'nan.exr', spec, bad)
    command(['-in', out/'nan.exr', '-layer', 'beauty', '-mode', 'oidn_cpu', '-out', out/'nan-output.exr'],
            'nonfinite', False)
    checks['nonfinite_rejected'] = not (out/'nan-output.exr').exists()
    mismatch = oiio.ImageSpec(spec)
    mismatch.x += 1
    write(out/'offset.exr', mismatch, data)
    command(['-in', source, '-layer', 'beauty', '-albedo', out/'offset.exr', '-albedo-layer', 'denoise_albedo',
             '-mode', 'oidn_cpu', '-out', out/'offset-output.exr'], 'guide-offset', False)
    checks['guide_window_mismatch_rejected'] = not (out/'offset-output.exr').exists()

    # Test standard Houdini workflows, native primvars and actual CPU/XPU AOVs.
    hou.hipFile.load(str(demo), suppress_save_prompt=True)
    hou.clearAllSelected()
    geometry = mr.run('geometry')
    geometry.parm('set_adaptive').set(True)
    geometry.parm('adaptive').set(1)
    stage = geometry.stage()
    assert stage and not geometry.errors(), geometry.errors()
    shapes = [p for p in stage.Traverse() if p.IsA(UsdGeom.Mesh)]
    assert shapes, 'Demo has no meshes'
    paths = [str(p.GetPath()) for p in shapes]
    checks['geometry_overrides'] = all(UsdGeom.PrimvarsAPI(p).GetPrimvar('moonray:mesh_resolution').Get() == 4 for p in shapes)
    geometry.parm('prims').set(paths[0])
    stage = geometry.stage()
    checks['geometry_selection'] = stage.GetPrimAtPath(paths[0]).GetAttribute('primvars:moonray:mesh_resolution').Get() == 4
    if len(paths) > 1:
        checks['unselected_geometry_preserved'] = not stage.GetPrimAtPath(paths[1]).HasAttribute('primvars:moonray:mesh_resolution')
    geometry.parm('set_resolution').set(False)
    checks['disabled_override_preserved'] = not geometry.stage().GetPrimAtPath(paths[0]).HasAttribute('primvars:moonray:mesh_resolution')
    geometry.parm('set_resolution').set(True)
    geometry.parm('prims').set('/**')
    rop = mr.create_render_setup()
    settings = mr.render_settings_node(rop)
    aovs = settings.input(0)
    aovs.parm('denoise_guides').set(True)
    stage = aovs.stage()
    product = UsdRender.Product(stage.GetPrimAtPath('/Render/MoonRay/beauty'))
    checks['guide_vars'] = all(Sdf.Path('/Render/MoonRay/AOVs/' + name) in product.GetOrderedVarsRel().GetTargets()
                               for name in ('denoise_albedo', 'denoise_normal'))
    aovs.parm('denoise_guides').set(False)
    checks['guides_disable'] = Sdf.Path('/Render/MoonRay/AOVs/denoise_albedo') not in UsdRender.Product(
        aovs.stage().GetPrimAtPath('/Render/MoonRay/beauty')).GetOrderedVarsRel().GetTargets()
    aovs.parm('denoise_guides').set(True)
    aovs.parm('cryptoname').set('denoise_albedo')
    aovs.stage()
    checks['aov_name_collision_rejected'] = bool(aovs.errors())
    aovs.parm('cryptoname').set('Cryptomatte')
    settings.parmTuple('resolution').set((96, 64))
    mr._set(settings, 'moonray:sceneVariable:pixel_samples', 2)
    mr._set(settings, 'moonray:localThreads', 2)
    mr._set(settings, 'moonray:info', True)
    geometry_path, aov_path, rop_path = geometry.path(), aovs.path(), rop.path()
    hip = out / 'MoonRay_Refinement_Demo.hip'
    hou.hipFile.save(str(hip))
    hou.hipFile.load(str(hip), suppress_save_prompt=True)
    geometry, aovs, rop = [hou.node(p) for p in (geometry_path, aov_path, rop_path)]
    settings = mr.render_settings_node(rop)
    checks['hip_reload'] = aovs.evalParm('denoise_guides') and geometry.evalParm('resolution') == 4
    for mode in ('vectorized', 'xpu'):
        mr._set(settings, 'moonray:executionMode', mode)
        checks[mode + '_authored'] = settings.stage().GetPrimAtPath('/Render/MoonRay/settings').GetAttribute(
            'moonray:executionMode').Get() == mode
        rendered = out / (mode + '.exr')
        rop.parm('lopoutput').set((out / (mode + '.usd')).as_posix())
        rop.parm('outputimage').set(rendered.as_posix())
        rop.render()
        assert not rop.errors(), rop.errors()
        raw_spec, raw = read(rendered)
        layers = parts(rendered)
        metrics[mode + '_layers'] = {name: list(s.channelnames) for name, (s, _) in layers.items()}
        for name in ('denoise_albedo', 'denoise_normal'):
            guide = layers[name][1]
            checks[mode + '_' + name] = guide.shape[-1] == 3 and bool(np.isfinite(guide).all() and
                                                                     np.abs(guide).max() > .1)
        # Independently accumulated normal AOVs may differ by float rounding.
        delta = float(np.max(np.abs(layers['normal'][1] - layers['denoise_normal'][1])))
        metrics[mode + '_duplicate_normal_max_error'] = delta
        checks[mode + '_duplicate_source_matches'] = delta < 1.e-6
        source_hash = hashlib.sha256(rendered.read_bytes()).hexdigest()
        mr._set(aovs.input(0), 'productName', rendered.as_posix())
        aovs.parm('denoise_input').set('')
        aovs.parm('denoise_output').set((out / (mode + '.denoised.exr')).as_posix())
        checks[mode + '_product_path_resolved'] = denoise.input_output(aovs)[0] == rendered
        job = denoise.launch(aovs)
        assert job['process'].wait(timeout=90) == 0, (job['directory'] / 'launcher.log').read_text()
        output_spec, filtered = read(job['target'])
        checks[mode + '_denoised'] = bool(np.isfinite(filtered).all() and np.abs(filtered[..., :3]).max() > .1)
        alpha_index = next(i for i, c in enumerate(raw_spec.channelnames) if c.lower() in ('a', 'beauty.a'))
        checks[mode + '_alpha_exact'] = bool(np.array_equal(raw[..., alpha_index], filtered[..., 3]))
        checks[mode + '_crypto_source_unchanged'] = hashlib.sha256(rendered.read_bytes()).hexdigest() == source_hash
    # Leave the saved example ready to use with a real rendered input.
    hou.hipFile.save(str(hip))
    report = dict(passed=all(checks.values()), checks=checks, metrics=metrics, houdini=hou.applicationVersionString())
    (out / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)
    assert report['passed'], [k for k, v in checks.items() if not v]


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--demo', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        run(args.out.resolve(), args.demo.resolve())
    except Exception:
        (args.out / 'failure.txt').write_text(traceback.format_exc())
        raise
