"""Artist-facing AOV presets, authored as standard USD Render Vars."""
import hou
from pxr import Sdf, UsdRender

CRYPTO_FIELDS = (
    ('positions', 'CryptoP — Render-space Position'),
    ('p0', 'CryptoP0 — Provided Initial Position'),
    ('normals', 'CryptoN — Normal'),
    ('beauty', 'CryptoB — Beauty'),
    ('refp', 'CryptoRefP — Reference Position'),
    ('refn', 'CryptoRefN — Reference Normal'),
    ('uv', 'CryptoUV — Texture Coordinates'),
)
UTILITY_FIELDS = (
    ('P', 'P — Render-space Position', 'point3f'),
    ('Wp', 'Wp — World-space Position', 'point3f'),
    ('N', 'N — Shading Normal', 'normal3f'),
    ('Ng', 'Ng — Geometric Normal', 'normal3f'),
    ('St', 'UV — Texture Coordinates', 'float2'),
    ('cameraDepth', 'Z — Camera Depth', 'float'),
    ('motionvec', 'Motion Vectors', 'float2'),
)


def parameters():
    product = hou.StringParmTemplate('products', 'Render Products', 1, default_value=('',),
        help='Space-separated flat Render Product prim paths. Leave empty to add passes to every existing flat Render Product.')
    root = hou.StringParmTemplate('varroot', 'Render Var Scope', 1,
        default_value=('/Render/MoonRay/AOVs',))
    crypto = [hou.ToggleParmTemplate('crypto', 'Enable Cryptomatte', default_value=True),
              hou.StringParmTemplate('cryptoname', 'Layer Name', 1, default_value=('Cryptomatte',)),
              hou.IntParmTemplate('depth', 'ID Depth', 1, default_value=(6,), min=1, max=100,
                  min_is_strict=True, max_is_strict=True,
                  help='Maximum IDs per pixel. Two IDs are stored per RGBA layer. Extra data is stored per ID.')]
    for key, label in CRYPTO_FIELDS:
        parm = hou.ToggleParmTemplate('crypto_' + key, label, default_value=key in ('positions', 'normals', 'uv'))
        if key in ('refp', 'refn'):
            parm.setHelp('Uses the reference attributes ref_P / ref_N on the geometry. Supply reference data for a meaningful rest-space pass.')
        if key == 'p0':
            parm.setHelp('Reads the p0 geometry primvar in world space and writes it in render space. Supply the desired initial-position data on the geometry.')
        crypto.append(parm)
    crypto += [hou.ToggleParmTemplate('reflected', 'Reflected Cryptomatte', default_value=False,
                   help='Record IDs and enabled extra data through mirror reflection. Requires scalar rendering in this MoonRay version.'),
               hou.ToggleParmTemplate('refracted', 'Refracted Cryptomatte', default_value=False,
                   help='Record IDs and enabled extra data through refraction. Requires scalar rendering in this MoonRay version.'),
               hou.ToggleParmTemplate('resume_data', 'CryptoS — Fragment Sample Data', default_value=False,
                   help='Writes presence-depth and sample-count layers. This does not enable checkpoint/resume rendering in Houdini.')]
    for parm in crypto[1:]:
        parm.setConditional(hou.parmCondType.DisableWhen, '{ crypto == 0 }')
    utility = [hou.ToggleParmTemplate('utility_' + key, label, default_value=False)
               for key, label, dtype in UTILITY_FIELDS]
    lighting = [hou.ToggleParmTemplate('all_light', 'All Light Contributions', default_value=False,
                    help='Light path expression C.*. Additional custom LPEs can be created with standard Render Var LOPs.')]
    import moonray_denoise
    return hou.ParmTemplateGroup([product, root,
        hou.FolderParmTemplate('crypto_tab', 'Cryptomatte', crypto),
        hou.FolderParmTemplate('utility_tab', 'Utility Passes', utility),
        hou.FolderParmTemplate('lighting_tab', 'Lighting', lighting),
        hou.FolderParmTemplate('denoise_tab', 'Denoising', moonray_denoise.parameters())])


def cook(lop, controls):
    # Evaluate controls before acquiring the editable stage.
    values = {p.name(): p.eval() for p in controls.parms()}
    stage = lop.editableStage()
    paths = values['products'].split()
    products = [UsdRender.Product(stage.GetPrimAtPath(path)) for path in paths] if paths else [
        UsdRender.Product(p) for p in stage.Traverse() if p.IsA(UsdRender.Product)
        and UsdRender.Product(p).GetProductTypeAttr().Get() == 'raster']
    if not products or any(not product for product in products):
        raise hou.NodeError('Connect MoonRay AOVs after a Render Product, or enter valid Render Product prim paths.')
    if any(product.GetProductTypeAttr().Get() != 'raster' for product in products):
        raise hou.NodeError('MoonRay AOVs adds flat compositing passes. Choose raster Render Products; use MoonRay Deep Output for deep passes.')
    root = Sdf.Path(values['varroot'])
    if not root.IsAbsolutePath() or not root.IsPrimPath():
        raise hou.NodeError('Render Var Scope must be an absolute USD prim path.')
    selected = []

    def make(name, source, dtype, source_type='raw'):
        if not Sdf.Path.IsValidIdentifier(name):
            raise hou.NodeError('AOV layer name must be a valid identifier: ' + name)
        if root.AppendChild(name) in selected:
            raise hou.NodeError('Two enabled passes use the layer name ' + name + '. Choose a different Cryptomatte layer name.')
        var = UsdRender.Var.Define(stage, root.AppendChild(name))
        var.CreateSourceNameAttr(source)
        var.CreateSourceTypeAttr(source_type)
        var.CreateDataTypeAttr(dtype)
        prim = var.GetPrim()
        prim.CreateAttribute('driver:parameters:aov:husk:name', Sdf.ValueTypeNames.String).Set(name)
        prim.CreateAttribute('driver:parameters:aov:husk:format', Sdf.ValueTypeNames.Token).Set(dtype)
        prim.CreateAttribute('parameters:moonray:channel_format', Sdf.ValueTypeNames.Token).Set('float')
        selected.append(var.GetPath())
        return prim

    if values['crypto']:
        prim = make(values['cryptoname'], 'cryptomatte', 'float')
        prim.CreateAttribute('parameters:moonray:result', Sdf.ValueTypeNames.Token).Set('cryptomatte')
        prim.CreateAttribute('parameters:moonray:cryptomatte_depth', Sdf.ValueTypeNames.Int).Set(values['depth'])
        for key, label in CRYPTO_FIELDS:
            prim.CreateAttribute('parameters:moonray:cryptomatte_output_' + key, Sdf.ValueTypeNames.Bool).Set(bool(values['crypto_' + key]))
        for key, parm in [('record_reflected', 'reflected'), ('record_refracted', 'refracted'), ('support_resume_render', 'resume_data')]:
            prim.CreateAttribute('parameters:moonray:cryptomatte_' + key, Sdf.ValueTypeNames.Bool).Set(bool(values[parm]))
    for source, label, dtype in UTILITY_FIELDS:
        if values['utility_' + source]:
            make('Z' if source == 'cameraDepth' else source, source, dtype)
    if values['all_light']:
        make('all_light', 'C.*', 'color3f', 'lpe')
    if values.get('denoise_guides', False):
        make('denoise_albedo', 'shader:albedo', 'color3f')
        make('denoise_normal', 'N', 'normal3f')
    for product in products:
        existing = product.GetOrderedVarsRel().GetTargets()
        product.GetOrderedVarsRel().SetTargets(existing + [path for path in selected if path not in existing])


def create(kwargs=None):
    import moonray_houdini
    network, source = moonray_houdini._context(kwargs)
    with hou.undos.group('MoonRay AOVs'):
        node = moonray_houdini._append(network, source, 'moonray::aovs::1.0', 'moonray_aovs')
        return moonray_houdini._show(node)
