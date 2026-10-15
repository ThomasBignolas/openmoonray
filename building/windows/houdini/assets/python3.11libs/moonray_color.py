"""OCIO scene preparation for MoonRay, shared by Solaris and exported USD.

Textures are converted before filtering, in a separate content-addressed cache.
No source assets, process-wide OCIO configuration or display preferences change.
"""
from pathlib import Path
import fnmatch
import hashlib
import json
import os
import re
import threading
import uuid

import hou
import numpy as np
import OpenImageIO as oiio
import PyOpenColorIO as ocio
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdRender, UsdShade, Vt

CACHE_VERSION = 1
DATA_NAMES = {'normal', 'normalmap', 'normal_map', 'bump', 'displacement', 'roughness',
              'metallic', 'metalness', 'opacity', 'presence', 'occlusion', 'ior', 'st',
              'input_texture_coordinates', 'texture_coordinates', 'scale', 'bias'}
TEXTURE_IDS = {'UsdUVTexture', 'ImageMap', 'ProjectCameraMap_v2'}
FILTERS = ('box', 'triangle', 'gaussian', 'lanczos3', 'blackman-harris')
AP1 = (.713, .293, .165, .830, .128, .044, .32168, .33767)
REC709 = (.64, .33, .30, .60, .15, .06, .3127, .3290)
_texture_lock = threading.RLock()


def primaries(config, name, custom=None):
    if custom is not None:
        if len(custom) != 8 or not np.isfinite(custom).all():
            raise ValueError('Chromaticities require eight finite x/y values.')
        return tuple(float(x) for x in custom)
    known = {'ACEScg': AP1, 'ACES2065-1': (.7347,.2653,0,1,.0001,-.077,.32168,.33767),
             'Linear Rec.709 (sRGB)': REC709,
             'Linear Rec.2020': (.708,.292,.170,.797,.131,.046,.3127,.3290),
             'Linear P3-D65': (.680,.320,.265,.690,.150,.060,.3127,.3290)}
    for standard, values in known.items():
        if config.getColorSpace(standard) and config.getProcessor(name, standard).isNoOp():
            return values
    raise ValueError('Set custom EXR chromaticities for this working/output color space: ' + name)


def load_config(filename=''):
    filename = hou.expandString(filename) if filename else os.environ.get('OCIO', '')
    if not filename:
        raise ValueError('Set an OCIO configuration in Houdini or on MoonRay Color Management.')
    # Keep this config local. Changing GetCurrentConfig() would affect other renderers.
    config = ocio.Config.CreateFromFile(filename)
    config.validate()
    return filename, config


def space_name(config, value):
    aliases = {'lin_ap1': 'ACEScg', 'lin_ap1_scene': 'ACEScg',
               'lin_rec709': 'Linear Rec.709 (sRGB)', 'lin_rec709_scene': 'Linear Rec.709 (sRGB)',
               'srgb_rec709_scene': 'sRGB - Texture', 'sRGB': 'sRGB - Texture'}
    space = config.getColorSpace(value) or config.getColorSpace(aliases.get(value, value))
    if not space:
        raise ValueError('Color space is not in the OCIO configuration: ' + value)
    return space.getName()


def color_space_menu(kwargs):
    try:
        node = kwargs.get('node')
        _, config = load_config(node.evalParm('config') if node and node.parm('config') else '')
        special = {'output': ['rendering', 'Same as Rendering'],
                   'source': ['auto', 'Automatic', 'raw', 'Raw / Data']}
        parm = kwargs.get('parm')
        prefix = re.sub(r'\d+$', '', parm.name()) if parm else ''
        return special.get(prefix, []) + [item for name in config.getColorSpaceNames() for item in (name, name)]
    except Exception:
        return []


def _samples(attr):
    times = attr.GetTimeSamples()
    if attr.Get(Usd.TimeCode.Default()) is not None:
        yield Usd.TimeCode.Default()
    for time in times:
        yield Usd.TimeCode(time)


def _set(prim, name, dtype, value):
    attr = prim.CreateAttribute(name, dtype)
    attr.Set(value)
    return attr


def _is_data_input(attr):
    name = attr.GetBaseName().lower()
    if name in DATA_NAMES or any(x in name for x in ('roughness', 'normal', 'displacement', 'bump', 'opacity', 'presence')):
        return True
    return attr.GetTypeName().role != Sdf.ValueRoleNames.Color


def _shader_id(prim):
    return str(prim.GetAttribute('info:id').Get() or '')


def _uv_derivatives(stage, prim, frame):
    """Exact UV footprint for the standard USD affine texture-coordinate graph."""
    times = {float(frame)}
    def matrix(attr, time, visited=frozenset()):
        if not attr or not attr.GetConnections():
            return np.zeros((2, 2))  # Authored constant UV.
        path=attr.GetConnections()[0].GetPrimPath()
        if path in visited:
            return None
        source=stage.GetPrimAtPath(path)
        sid=_shader_id(source)
        if sid == 'UsdPrimvarReader_float2':
            return np.eye(2) if source.GetAttribute('inputs:varname').Get(time)=='st' else None
        if sid != 'UsdTransform2d':
            return None
        scale=source.GetAttribute('inputs:scale')
        rotation=source.GetAttribute('inputs:rotation')
        for a in (scale,rotation):
            if a and a.GetConnections():
                return None
            if a:
                times.update(a.GetTimeSamples())
        sx,sy=scale.Get(time) or (1.,1.)
        theta=np.deg2rad(rotation.Get(time) or 0.)
        c,s=np.cos(theta),np.sin(theta)
        upstream=matrix(source.GetAttribute('inputs:in'),time,visited|{path})
        return np.asarray([[c*sx,-s*sy],[s*sx,c*sy]]) @ upstream if upstream is not None else None
    attr=prim.GetAttribute('inputs:st')
    # Discover animation samples before authoring the Jacobian.
    matrix(attr,Usd.TimeCode.Default())
    for time in [Usd.TimeCode.Default()] + [Usd.TimeCode(t) for t in sorted(times)]:
        transform=matrix(attr,time)
        if transform is None:
            transform=np.zeros((2,2))
        for row,name in zip(transform,('st_derivative_u','st_derivative_v')):
            prim.CreateAttribute('inputs:'+name,Sdf.ValueTypeNames.Float2).Set(Gf.Vec2f(*map(float,row)),time)


def _usage(stage):
    """Trace output consumers; data and color use of one image stay distinct."""
    consumers = {}
    for prim in stage.Traverse():
        for attr in prim.GetAttributes():
            for connection in attr.GetConnections():
                consumers.setdefault(connection.GetPrimPath(), []).append((attr, connection))

    def classify(path, visited):
        if path in visited:
            return set()
        visited = visited | {path}
        result = set()
        for attr, connection in consumers.get(path, []):
            # Alpha is independent of RGB color transforms.
            if connection.name == 'outputs:a':
                continue
            owner = attr.GetPrim()
            sid = _shader_id(owner)
            shader = UsdShade.Shader(owner)
            is_terminal = sid in ('UsdPreviewSurface',) or ('Material' in sid) or sid in ('BaseVolume',)
            if is_terminal or not shader or _is_data_input(attr):
                result.add('data' if _is_data_input(attr) else 'color')
            else:
                result |= classify(owner.GetPath(), visited) or {'color'}
        return result
    return consumers, classify


def _copy_shader_tree(stage, source, target):
    """Copy composed shader values, retaining time samples and internal links."""
    src_path = source.GetPath()
    for prim in Usd.PrimRange(source, Usd.TraverseInstanceProxies()):
        new_path = prim.GetPath().ReplacePrefix(src_path, target)
        clone = stage.DefinePrim(new_path, prim.GetTypeName())
        for key, value in prim.GetAllAuthoredMetadata().items():
            if key not in ('specifier', 'typeName', 'references', 'payload', 'instanceable', 'variantSelection', 'variantSetNames'):
                clone.SetMetadata(key, value)
        for attr in prim.GetAttributes():
            new = clone.CreateAttribute(attr.GetName(), attr.GetTypeName(), attr.IsCustom(), attr.GetVariability())
            for key, value in attr.GetAllAuthoredMetadata().items():
                if key not in ('default', 'timeSamples', 'connectionPaths', 'typeName', 'custom', 'variability'):
                    new.SetMetadata(key, value)
            for time in _samples(attr):
                value = attr.Get(time)
                if isinstance(value, Sdf.AssetPath) and value.resolvedPath:
                    value = Sdf.AssetPath(value.resolvedPath)
                new.Set(value, time)
            if attr.GetConnections():
                new.SetConnections([p.ReplacePrefix(src_path, target) if p.HasPrefix(src_path) else p for p in attr.GetConnections()])
        for rel in prim.GetRelationships():
            clone.CreateRelationship(rel.GetName(), rel.IsCustom()).SetTargets([
                p.ReplacePrefix(src_path, target) if p.HasPrefix(src_path) else p for p in rel.GetTargets()])
    return stage.GetPrimAtPath(target)


def _instance_materials(stage):
    """Prepare material-only reference overlays, preserving geometry instances.

    Collection bindings that target instance proxies resolve in UsdShade but
    are not propagated by Houdini's Hydra 2 native-instance scene index. A
    reference overlay participates in prototype composition itself.
    """
    clones, jobs = {}, {}
    def job(instance):
        path=instance.GetPath()
        entry=jobs.setdefault(path, {'materials':{},'children':set()})
        if instance.IsInstanceProxy():
            parent=instance.GetParent()
            while parent and not parent.IsInstance():
                parent=parent.GetParent()
            if parent:
                job(parent)['children'].add(path)
        return entry
    for prim in list(Usd.PrimRange.Stage(stage, Usd.TraverseInstanceProxies())):
        if not prim.IsInstanceProxy() or not (prim.IsA(UsdGeom.Gprim) or prim.IsA(UsdGeom.Subset)):
            continue
        material, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial(UsdShade.Tokens.full)
        if not material or not material.GetPrim().IsInstanceProxy():
            continue
        proto = material.GetPrim().GetPrimInPrototype().GetPath()
        if proto not in clones:
            digest = hashlib.sha256(str(proto).encode()).hexdigest()[:16]
            path = Sdf.Path('/__MoonRayColor/Materials/m_' + digest)
            clones[proto] = UsdShade.Material(_copy_shader_tree(stage, material.GetPrim(), path))
        instance = material.GetPrim().GetParent()
        while instance and not instance.IsInstance():
            instance = instance.GetParent()
        if instance:
            relative = material.GetPath().MakeRelativePath(instance.GetPath())
            job(instance)['materials'][relative] = clones[proto].GetPath()
    return jobs, len(clones)


def _commit_instance_materials(stage, jobs, cache, generation):
    files={}
    def build(path):
        if path in files:
            return files[path]
        overlay=Usd.Stage.CreateInMemory()
        root=Sdf.Path('/__root')
        overlay.OverridePrim(root)
        for relative,material in jobs[path]['materials'].items():
            _copy_shader_tree(overlay,stage.GetPrimAtPath(material),root.AppendPath(relative))
        for child in sorted(jobs[path]['children']):
            prim=overlay.OverridePrim(root.AppendPath(child.MakeRelativePath(path)))
            prim.GetReferences().AddReference(build(child),root)
        contents=overlay.GetRootLayer().ExportToString()
        digest=hashlib.sha256(contents.encode('utf-8')).hexdigest()
        target=Path(cache).resolve()/'usd'/(digest+'.usda')
        if not target.is_file():
            if generation=='require':
                raise ValueError('Prepared instance material overlay is missing: '+str(target))
            target.parent.mkdir(parents=True,exist_ok=True)
            temporary=target.with_name(uuid.uuid4().hex+'.tmp.usda')
            try:
                temporary.write_text(contents,encoding='utf-8')
                os.replace(temporary,target)
            finally:
                if temporary.exists():
                    temporary.unlink()
        files[path]=target.as_posix()
        return files[path]
    # Finish reading composed values before any new reference changes prototypes.
    for path in jobs:
        build(path)
    for path,filename in files.items():
        prim=stage.GetPrimAtPath(path)
        if not prim.IsInstanceProxy():
            prim.GetReferences().AddReference(filename,'/__root',position=Usd.ListPositionFrontOfPrependList)


class TextureCache:
    def __init__(self, root, config, config_path, working, options):
        self.root = Path(root).resolve()
        self.config, self.config_path, self.working = config, config_path, working
        self.options = options
        self.generated = 0
        self.reused = 0

    def prepare(self, filename, source, data=False):
        pattern = Path(filename)
        if '<UDIM>' in filename:
            expression = re.compile('^' + re.escape(pattern.name).replace('<UDIM>', r'(1\d{3})') + '$')
            files = [(p, expression.match(p.name).group(1)) for p in sorted(pattern.parent.glob(pattern.name.replace('<UDIM>', '*')))
                     if expression.match(p.name)]
        else:
            files = [(pattern, '')] if pattern.is_file() else []
        if not files:
            raise ValueError('Texture does not exist: ' + filename)
        spaces = [(p, tile, self.source_space(str(p), source, data)) for p, tile in files]
        identity = {'version': CACHE_VERSION, 'input': str(pattern),
                    'files': [(str(p), p.stat().st_size, p.stat().st_mtime_ns, space) for p, _, space in spaces],
                    'config': self.config.getCacheID(), 'working': self.working, 'data': data,
                    'options': {k: v for k, v in self.options.items() if k not in ('generation', 'threads')}, 'oiio': oiio.VERSION_STRING}
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        directory = self.root / digest[:2] / digest
        output = directory / ('texture.<UDIM>.tx' if '<UDIM>' in filename else 'texture.tx')
        if self.options.get('generation', 'auto') == 'require':
            # This mode is useful for farm jobs that must never generate textures.
            if not all(Path(str(output).replace('<UDIM>', tile)).is_file() for _, tile, _ in spaces):
                raise ValueError('Prepared texture is missing. Generate the cache first: ' + str(output))
        if self.options.get('generation', 'auto') != 'require':
            directory.mkdir(parents=True, exist_ok=True)
        for path, tile, source_space in spaces:
            target = Path(str(output).replace('<UDIM>', tile))
            if target.is_file():
                self.reused += 1
                continue
            temporary = target.with_name(target.stem + '.' + uuid.uuid4().hex + '.tmp.tx')
            try:
                settings = oiio.ImageSpec()
                settings.format = oiio.FLOAT if data or self.options.get('precision', 'float') == 'float' else oiio.HALF
                settings.tile_width = settings.tile_height = int(self.options.get('tile', 64))
                settings.attribute('compression', 'zip')
                settings.attribute('maketx:filtername', self.options.get('filter', 'lanczos3'))
                settings.attribute('maketx:opaque_detect', 0)
                settings.attribute('maketx:monochrome_detect', 0)
                settings.attribute('maketx:constant_color_detect', 0)
                settings.attribute('maketx:checknan', 1)
                settings.attribute('maketx:unpremult', int(self.options.get('unpremult', False)))
                settings.attribute('maketx:colorconfig', self.config_path)
                if not data and source_space != self.working:
                    settings.attribute('maketx:incolorspace', source_space)
                    settings.attribute('maketx:outcolorspace', self.working)
                settings.attribute('oiio:ColorSpace', 'raw' if data else self.working)
                settings.attribute('moonray:cacheKey', digest)
                settings.attribute('moonray:source', str(path))
                settings.attribute('maketx:highlightcomp', int(self.options.get('highlightcomp', False) and not data))
                with _texture_lock:
                    previous_threads = oiio.get_int_attribute('threads')
                    threads = max(1, min(int(self.options.get('threads', 4)), max(1, (os.cpu_count() or 2) - 1)))
                    try:
                        oiio.attribute('threads', threads)
                        if not oiio.ImageBufAlgo.make_texture(oiio.MakeTextureMode.MakeTxTexture, str(path), str(temporary), settings):
                            raise ValueError('Texture conversion failed: ' + str(path) + ': ' + oiio.geterror())
                    finally:
                        oiio.attribute('threads', previous_threads)
                os.replace(temporary, target)
                self.generated += 1
            finally:
                if temporary.exists():
                    temporary.unlink()
        manifest = directory / 'source.json'
        if not manifest.exists() and self.options.get('generation', 'auto') != 'require':
            temporary = manifest.with_name(uuid.uuid4().hex + '.json')
            temporary.write_text(json.dumps(identity, indent=2) + '\n', encoding='utf-8')
            os.replace(temporary, manifest)
        return output.as_posix()

    def source_space(self, filename, source, data):
        if data or source.lower() in ('raw', 'data'):
            return 'raw'
        if source and source != 'auto':
            return space_name(self.config, source)
        image = oiio.ImageInput.open(filename)
        if not image:
            raise ValueError('Cannot read texture metadata: ' + filename + ': ' + oiio.geterror())
        try:
            tagged = image.spec().get_string_attribute('oiio:ColorSpace')
        finally:
            image.close()
        # Honor explicit, identifiable metadata. Generic "linear" has no primaries.
        if tagged and tagged not in ('linear', 'Linear', 'unknown'):
            if tagged.lower() in ('raw', 'data'):
                return self.working
            return space_name(self.config, tagged)
        return space_name(self.config, self.config.getColorSpaceFromFilepath(filename)[0])


def prepare_stage(stage, *, config_path='', working='ACEScg', authored='scene_linear',
                  cache='', rules=(), texture_options=None, frame=1, settings_pattern='*',
                  instance_materials=True, sampling=None, output='rendering', chromaticities=None):
    config_path, config = load_config(config_path)
    if stage.GetEditTarget().GetLayer() in (stage.GetRootLayer(), stage.GetSessionLayer()):
        stage.SetColorConfiguration(Sdf.AssetPath(config_path))
        stage.SetColorManagementSystem('OpenColorIO')
    working = space_name(config, working)
    authored = space_name(config, authored)
    if not config.isColorSpaceLinear(working, ocio.REFERENCE_SPACE_SCENE):
        raise ValueError('The rendering color space must be scene-linear: ' + working)
    output = working if output == 'rendering' else space_name(config, output)
    if not config.isColorSpaceLinear(output, ocio.REFERENCE_SPACE_SCENE):
        raise ValueError('EXR output must be scene-linear. Use Houdini display/view controls for viewing.')
    output_primaries = primaries(config, output, chromaticities)
    products = [UsdRender.Product(p) for p in stage.Traverse() if p.IsA(UsdRender.Product)]
    if output != working and any(str(p.GetProductTypeAttr().Get()) == 'deep' for p in products):
        raise ValueError('Native deep output uses the rendering color space. Set Output Color Space to Rendering.')
    options = dict(texture_options or {})
    if options.get('filter', 'lanczos3') not in FILTERS:
        raise ValueError('Unsupported mipmap filter')
    if not cache:
        raise ValueError('Choose a texture-cache directory.')
    textures = TextureCache(cache, config, config_path, working, options)
    instance_jobs, instance_count = _instance_materials(stage) if instance_materials else ({},0)
    report = {'working': working, 'config': config_path, 'textures': [], 'colors': 0,
              'instance_materials': instance_count}
    consumers, classify = _usage(stage)

    def rule_for(attr):
        selected = {}
        for rule in rules:
            if fnmatch.fnmatchcase(str(attr.GetPrimPath()), rule.get('prim', '*')) and fnmatch.fnmatchcase(attr.GetName(), rule.get('attribute', '*')):
                selected = rule
        return selected

    # Separate complete data branches, including intermediate map nodes. A
    # shared texture must never be color-converted on its way to roughness/N.
    mixed = {p.GetPath() for p in stage.Traverse() if _shader_id(p) in TEXTURE_IDS
             and classify(p.GetPath(), set()) == {'color', 'data'}}
    clones = {}
    def has_mixed(path, visited=frozenset()):
        if path in mixed:
            return True
        if path in visited:
            return False
        return any(has_mixed(c.GetPrimPath(), visited | {path})
                   for a in stage.GetPrimAtPath(path).GetAttributes() for c in a.GetConnections())
    def data_clone(path):
        if path in clones:
            return clones[path]
        original = stage.GetPrimAtPath(path)
        target = Sdf.Path('/__MoonRayColor/Data/d_' + hashlib.sha256(str(path).encode()).hexdigest()[:20])
        clones[path] = target
        clone = _copy_shader_tree(stage, original, target)
        _set(clone, 'moonray:rawGraph', Sdf.ValueTypeNames.Bool, True)
        if _shader_id(clone) in TEXTURE_IDS:
            _set(clone, 'inputs:moonray_texture_usage', Sdf.ValueTypeNames.String, 'data')
        for attr in clone.GetAttributes():
            links = attr.GetConnections()
            if links:
                attr.SetConnections([p.ReplacePrefix(p.GetPrimPath(), data_clone(p.GetPrimPath()))
                                     if not p.HasPrefix(target) else p for p in links])
        return target
    for prim in list(stage.Traverse()):
        for attr in prim.GetAttributes():
            if not attr.GetName().startswith('inputs:') or not _is_data_input(attr):
                continue
            links = attr.GetConnections()
            if any(has_mixed(p.GetPrimPath()) for p in links):
                attr.SetConnections([p.ReplacePrefix(p.GetPrimPath(), data_clone(p.GetPrimPath()))
                                     if has_mixed(p.GetPrimPath()) else p for p in links])
    consumers, classify = _usage(stage)

    for prim in list(stage.Traverse()):
        sid = _shader_id(prim)
        is_texture = sid in TEXTURE_IDS
        data = False
        texture_attr = prim.GetAttribute('inputs:file' if sid == 'UsdUVTexture' else 'inputs:texture') if is_texture else None
        if not is_texture:
            texture_attr = prim.GetAttribute('inputs:texture:file')
        if texture_attr and texture_attr.Get():
            rule = rule_for(texture_attr)
            usage = rule.get('usage', 'auto')
            explicit_usage = prim.GetAttribute('inputs:moonray_texture_usage').Get()
            if usage == 'auto' and explicit_usage:
                usage = explicit_usage
            if usage == 'auto':
                usage = 'data' if is_texture and classify(prim.GetPath(), set()) == {'data'} else 'color'
            source = rule.get('source') or texture_attr.GetColorSpace() or prim.GetAttribute('inputs:moonray_source_colorspace').Get() or 'auto'
            legacy = prim.GetAttribute('inputs:sourceColorSpace').Get() if sid == 'UsdUVTexture' else None
            if source == 'auto' and legacy in ('raw', 0):
                source = 'raw'
            elif source == 'auto' and legacy in ('sRGB', 1):
                source = 'sRGB - Texture'
            data = usage == 'data' or str(source).lower() in ('raw', 'data')
            local_options = dict(options)
            mip_filter = rule.get('filter', 'inherit')
            if mip_filter == 'inherit':
                mip_filter = prim.GetAttribute('inputs:moonray_mipmap_filter').Get() or 'inherit'
            if mip_filter != 'inherit':
                if mip_filter not in FILTERS:
                    raise ValueError('Unsupported mipmap filter on ' + str(prim.GetPath()))
                local_options['filter'] = mip_filter
            image_cache = TextureCache(cache, config, config_path, working, local_options)
            for time in list(_samples(texture_attr)):
                asset = texture_attr.Get(time)
                filename = (asset.resolvedPath or asset.path) if isinstance(asset, Sdf.AssetPath) else str(asset)
                if not Path(filename).is_absolute():
                    stack = texture_attr.GetPropertyStack(time)
                    if stack:
                        filename = Sdf.ComputeAssetPathRelativeToLayer(stack[0].layer, filename)
                filename = hou.expandStringAtFrame(filename, frame)
                prepared = image_cache.prepare(filename, str(source), data)
                texture_attr.Set(Sdf.AssetPath(prepared) if texture_attr.GetTypeName() == Sdf.ValueTypeNames.Asset else prepared, time)
                report['textures'].append({'attribute': str(texture_attr.GetPath()), 'source': filename, 'prepared': prepared, 'usage': 'data' if data else 'color'})
            textures.generated += image_cache.generated
            textures.reused += image_cache.reused
            texture_attr.SetColorSpace('raw' if data else working)
            if sid == 'UsdUVTexture':
                _uv_derivatives(stage,prim,frame)
                attr = prim.GetAttribute('inputs:sourceColorSpace')
                _set(prim, 'inputs:sourceColorSpace', attr.GetTypeName() if attr else Sdf.ValueTypeNames.Token,
                     0 if attr and attr.GetTypeName() == Sdf.ValueTypeNames.Int else 'raw')
            elif sid in ('ImageMap', 'ProjectCameraMap_v2'):
                _set(prim, 'inputs:gamma', Sdf.ValueTypeNames.Int, 0)
            if sid in ('ImageMap', 'UsdUVTexture') and sampling:
                for name, dtype in (('texture_filter', Sdf.ValueTypeNames.Int),
                                    ('texture_blur', Sdf.ValueTypeNames.Float),
                                    ('max_anisotropy', Sdf.ValueTypeNames.Int)):
                    _set(prim, 'inputs:' + name, dtype, sampling[name])

        # Transform actual color values, never coordinate/vector data or the
        # RGB-typed scale/bias used by USD UV Texture normal decoding.
        for attr in prim.GetAttributes():
            if prim.GetAttribute('moonray:rawGraph').Get():
                continue
            if attr.GetTypeName().role != Sdf.ValueRoleNames.Color or attr.GetConnections():
                continue
            if is_texture and (data or attr.GetBaseName() in ('scale', 'bias')):
                continue
            rule = rule_for(attr)
            if rule.get('usage') == 'data' or attr.GetBaseName().lower() in DATA_NAMES:
                continue
            source = rule.get('source')
            if not source or source == 'auto':
                source = attr.GetColorSpace() or authored
            if str(source).lower() in ('raw', 'data'):
                continue
            source = space_name(config, source)
            processor = config.getProcessor(source, working).getDefaultCPUProcessor()
            if not processor.isNoOp():
                for time in list(_samples(attr)):
                    value = attr.Get(time)
                    if attr.GetTypeName().isArray:
                        pixels = np.asarray(value, dtype=np.float32).copy()
                        if not pixels.size:
                            continue
                        processor.applyRGB(pixels)
                        result = type(value)([type(value[0])(*map(float, v)) for v in pixels])
                    else:
                        result = type(value)(*processor.applyRGB(list(value)))
                    attr.Set(result, time)
                report['colors'] += 1
            attr.SetColorSpace(working)

        # UsdLux's blackbody RGB is defined in linear Rec.709. Bake its factor
        # in the selected working primaries before the delegate consumes it.
        light = UsdLux.LightAPI(prim)
        if light:
            color = light.GetColorAttr()
            temperature = light.GetColorTemperatureAttr()
            enabled = light.GetEnableColorTemperatureAttr()
            times = [Usd.TimeCode.Default()] + [Usd.TimeCode(t) for t in sorted(
                set(color.GetTimeSamples()) | set(temperature.GetTimeSamples()) |
                set(enabled.GetTimeSamples()) | {float(frame)})]
            # Read all original values before authoring; otherwise an earlier
            # edit can change interpolation at a later sample.
            original = [(t, color.Get(t), temperature.Get(t), enabled.Get(t)) for t in times]
            if any(on for _, _, _, on in original):
                proc = config.getProcessor(space_name(config, 'lin_rec709'), working).getDefaultCPUProcessor()
                for time, value, kelvin, on in original:
                    tint = proc.applyRGB(list(UsdLux.BlackbodyTemperatureAsRgb(kelvin))) if on else [1., 1., 1.]
                    color.Set(Gf.Vec3f(*(np.asarray(value) * tint)), time)
                    enabled.Set(False, time)
                color.SetColorSpace(working)

    # Author both USD's standard working-space token and Husk's explicit
    # per-plane spaces. Data AOVs, including crypto extensions, remain raw.
    for prim in stage.Traverse():
        if prim.IsA(UsdRender.Settings) and fnmatch.fnmatchcase(str(prim.GetPath()), settings_pattern):
            UsdRender.Settings(prim).CreateRenderingColorSpaceAttr(working)
            _set(prim, 'moonray:colorSpace', Sdf.ValueTypeNames.String, working)
            _set(prim, 'moonray:ocioConfig', Sdf.ValueTypeNames.Asset, Sdf.AssetPath(config_path))
            _set(prim, 'moonray:chromaticities', Sdf.ValueTypeNames.FloatArray,
                 Vt.FloatArray(primaries(config, working, chromaticities if output == working else None)))
        elif prim.IsA(UsdRender.Var):
            var = UsdRender.Var(prim)
            dtype = str(var.GetDataTypeAttr().Get())
            source = str(var.GetSourceNameAttr().Get())
            data_source = source in ('N', 'Ng', 'P', 'St', 'st', 'uv', 'cameraDepth') or source.lower().startswith('crypto')
            color = dtype in ('color3f', 'color4f') and not data_source
            for suffix, space in (('source_colorspace', working), ('output_colorspace', output)):
                _set(prim, 'driver:parameters:aov:husk:' + suffix, Sdf.ValueTypeNames.String, space if color else 'raw')
    for product in products:
        if product.GetProductTypeAttr().Get() == 'raster' and str(product.GetProductNameAttr().Get()).lower().endswith('.exr'):
            _set(product.GetPrim(), 'driver:parameters:husk:image_format', Sdf.ValueTypeNames.String, 'MoonRayEXR')
            _set(product.GetPrim(), 'driver:parameters:husk:OpenEXR:moonray_chromaticities',
                 Sdf.ValueTypeNames.String, ' '.join(str(x) for x in output_primaries))
    _commit_instance_materials(stage,instance_jobs,cache,options.get('generation','auto'))
    report.update(generated=textures.generated, reused=textures.reused)
    return report


def parameters():
    space_menu = 'import moonray_color\nreturn moonray_color.color_space_menu(kwargs)'
    def space(name, label, default):
        return hou.StringParmTemplate(name, label, 1, default_value=(default,),
            item_generator_script=space_menu, item_generator_script_language=hou.scriptLanguage.Python)
    group = hou.ParmTemplateGroup([
        hou.ToggleParmTemplate('enable', 'Enable Color Management', default_value=True),
        hou.FolderParmTemplate('color', 'Color', parm_templates=[
            hou.StringParmTemplate('config', 'OCIO Configuration', 1, default_value=('',),
                string_type=hou.stringParmType.FileReference, help='Empty uses Houdini\'s OCIO environment configuration. Invalid configs fail explicitly.'),
            space('working', 'Rendering Color Space', 'ACEScg'),
            space('authored', 'Untagged Scene Colors', 'scene_linear'),
            space('output', 'Output Color Space', 'rendering'),
            hou.StringParmTemplate('settings', 'Render Settings Pattern', 1, default_value=('*',)),
            hou.LabelParmTemplate('viewnote', 'Viewing', column_labels=('Use Houdini\'s OCIO display/view controls. EXRs remain scene-linear.',)),
            hou.ToggleParmTemplate('customprimaries', 'Custom Output Chromaticities', default_value=False),
            hou.FloatParmTemplate('redxy', 'Red x/y', 2, default_value=AP1[:2]),
            hou.FloatParmTemplate('greenxy', 'Green x/y', 2, default_value=AP1[2:4]),
            hou.FloatParmTemplate('bluexy', 'Blue x/y', 2, default_value=AP1[4:6]),
            hou.FloatParmTemplate('whitexy', 'White x/y', 2, default_value=AP1[6:]),
        ]),
        hou.FolderParmTemplate('textures', 'Textures and Mipmaps', parm_templates=[
            hou.StringParmTemplate('cache', 'Texture Cache', 1, default_value=('$HIP/.moonray/textures',), string_type=hou.stringParmType.FileReference),
            hou.MenuParmTemplate('generation', 'Generation', ('auto', 'require'), ('Generate Missing / Reuse Cache', 'Require Prepared Cache'), default_value=0),
            hou.MenuParmTemplate('filter', 'Mipmap Filter', FILTERS, ('Box', 'Triangle', 'Gaussian', 'Lanczos 3', 'Blackman-Harris'), default_value=3),
            hou.MenuParmTemplate('precision', 'Cache Precision', ('float', 'half'), ('32-bit Float', '16-bit Half'), default_value=0),
            hou.MenuParmTemplate('tile', 'Tile Size', ('32', '64', '128'), ('32', '64', '128'), default_value=1),
            hou.IntParmTemplate('threads', 'Preparation Threads', 1, default_value=(4,), min=1, max=max(1,(os.cpu_count() or 2)-1), min_is_strict=True, max_is_strict=True,
                help='Texture generation leaves at least one logical CPU free. Renderer threads are controlled in Render Settings.'),
            hou.ToggleParmTemplate('unpremult', 'Unpremultiply Color Before Conversion', default_value=False,
                help='Enable for premultiplied color textures. Alpha is preserved. Leave off for straight texture RGB.'),
            hou.ToggleParmTemplate('highlightcomp', 'Reduce HDR Mipmap Ringing', default_value=False),
            hou.LabelParmTemplate('mipnote', 'Mipmaps', column_labels=('MoonRay requires tiled, mipmapped textures. Data maps are cached without color conversion.',)),
        ]),
        hou.FolderParmTemplate('sampling', 'Texture Sampling', parm_templates=[
            hou.ToggleParmTemplate('overridesampling', 'Override Texture Nodes', default_value=False),
            hou.MenuParmTemplate('lookup', 'Lookup Filter', ('0', '1', '2', '3', '4'),
                ('MoonRay Path Default', 'Nearest / No Mip Filtering', 'Bilinear / No Mip Filtering', 'Trilinear', 'Anisotropic'), default_value=0),
            hou.FloatParmTemplate('blur', 'Additional Blur (UV)', 1, default_value=(0,), min=0, min_is_strict=True),
            hou.IntParmTemplate('anisotropy', 'Maximum Anisotropy', 1, default_value=(8,), min=1, max=64, min_is_strict=True, max_is_strict=True),
            hou.LabelParmTemplate('samplingnote', 'Scope', column_labels=('Applies to ImageMap and USD UV Texture nodes. Per-node filtering is preserved when override is off.',)),
        ]),
        hou.FolderParmTemplate('rules', 'Overrides', parm_templates=[
            hou.FolderParmTemplate('overrides', 'Input Overrides', folder_type=hou.folderType.MultiparmBlock, parm_templates=[
                hou.StringParmTemplate('prim#', 'Prim Pattern', 1, default_value=('*',)),
                hou.StringParmTemplate('attribute#', 'Attribute Pattern', 1, default_value=('inputs:file',)),
                space('source#', 'Source Color Space', 'auto'),
                hou.MenuParmTemplate('usage#', 'Usage', ('auto', 'color', 'data'), ('Automatic', 'Color', 'Raw Data'), default_value=0),
                hou.MenuParmTemplate('mipfilter#', 'Mipmap Filter', ('inherit',) + FILTERS,
                    ('Use Texture / Global Setting', 'Box', 'Triangle', 'Gaussian', 'Lanczos 3', 'Blackman-Harris'), default_value=0),
            ]),
            hou.LabelParmTemplate('rulenote', 'Priority', column_labels=('Last matching override wins; then USD color-space metadata, texture settings and OCIO file rules.',)),
        ]),
    ])
    for name in ('redxy','greenxy','bluexy','whitexy'):
        parm=group.find(name)
        parm.setConditional(hou.parmCondType.DisableWhen,'{ customprimaries == 0 }')
        group.replace(name,parm)
    for name in ('lookup','blur','anisotropy'):
        parm=group.find(name)
        parm.setConditional(hou.parmCondType.DisableWhen,'{ overridesampling == 0 }')
        group.replace(name,parm)
    return group


def cook(lop, controls):
    if not controls.evalParm('enable'):
        return
    rules = [dict(prim=controls.evalParm('prim' + str(i)), attribute=controls.evalParm('attribute' + str(i)),
                  source=controls.evalParm('source' + str(i)), usage=controls.parm('usage' + str(i)).evalAsString(),
                  filter=controls.parm('mipfilter' + str(i)).evalAsString())
             for i in range(1, controls.evalParm('overrides') + 1)]
    options = {key: controls.parm(key).evalAsString() for key in ('generation', 'filter', 'precision', 'tile')}
    options.update({key: controls.evalParm(key) for key in ('unpremult', 'highlightcomp', 'threads')})
    sampling = dict(texture_filter=int(controls.parm('lookup').evalAsString()),
                    texture_blur=controls.evalParm('blur'), max_anisotropy=controls.evalParm('anisotropy')) if controls.evalParm('overridesampling') else None
    try:
        report = prepare_stage(lop.editableStage(), config_path=controls.evalParm('config'),
            working=controls.evalParm('working'), authored=controls.evalParm('authored'),
            cache=controls.evalParm('cache'), rules=rules, texture_options=options, frame=hou.frame(),
            settings_pattern=controls.evalParm('settings'), sampling=sampling,
            output=controls.evalParm('output'), chromaticities=tuple(x for key in ('redxy','greenxy','bluexy','whitexy')
                for x in controls.parmTuple(key).eval()) if controls.evalParm('customprimaries') else None)
        controls.setCachedUserData('moonray_color_report', report)
    except Exception as error:
        raise hou.NodeError('MoonRay color management: ' + str(error)) from error


def create(kwargs=None):
    import moonray_houdini
    network, source = moonray_houdini._context(kwargs)
    with hou.undos.group('MoonRay Color Management'):
        node = moonray_houdini._append(network, source, 'moonray::color::1.0', 'moonray_color')
        return moonray_houdini._show(node)
