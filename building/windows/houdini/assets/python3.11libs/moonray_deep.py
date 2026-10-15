"""Native MoonRay deep Render Products for Solaris."""
import re
import hou
from pxr import Sdf, UsdRender


def parameters():
    return hou.ParmTemplateGroup([
        hou.ToggleParmTemplate('enable', 'Write Deep EXR', default_value=True),
        hou.StringParmTemplate('settings', 'Render Settings', 1, default_value=('',),
            help='Space-separated Render Settings prim paths. Empty selects all existing settings. Place this node after Render Settings.'),
        hou.StringParmTemplate('productpath', 'Deep Product Path', 1, default_value=('/Render/MoonRay/deep',)),
        hou.StringParmTemplate('filename', 'Deep EXR File', 1, default_value=('$HIP/render/moonray_deep.$F4.exr',),
            string_type=hou.stringParmType.FileReference,
            help='A separate deep file alongside flat products. $F and $F4 are preserved for Husk animation renders.'),
        hou.MenuParmTemplate('format', 'Deep Format', ['0', '1'], ['OpenEXR Deep', 'OpenDCX (Subpixel Masks)'], default_value=0),
        hou.ToggleParmTemplate('normals', 'Include N', default_value=False),
        hou.ToggleParmTemplate('positions', 'Include P', default_value=False),
        hou.ToggleParmTemplate('uv', 'Include UV', default_value=False),
        hou.FloatParmTemplate('ztolerance', 'Depth Merge Tolerance', 1, default_value=(2.0,), min=0,
            min_is_strict=True, help='Maximum surface Z range within a pixel before MoonRay splits a deep sample.'),
        hou.FloatParmTemplate('curvature', 'Curvature Merge Tolerance', 1, default_value=(45.0,), min=0, max=180,
            min_is_strict=True, max_is_strict=True),
        hou.IntParmTemplate('volumecompression', 'Volume Compression Resolution', 1, default_value=(10,), min=1,
            min_is_strict=True, help='Lower values increase compression of volume opacity samples.'),
    ])


def cook(lop, controls):
    values = {p.name(): p.eval() for p in controls.parms()}
    if not values['enable']:
        return
    # Expand Houdini variables while retaining frame placeholders for exported USD.
    raw = controls.parm('filename').unexpandedString()
    frames = []
    def protect(match):
        frames.append(match.group())
        return '__MOONRAY_FRAME_' + str(len(frames) - 1) + '__'
    filename = hou.expandString(re.sub(r'\$(?:F\d*|\{F\d*\})', protect, raw))
    for index, token in enumerate(frames):
        filename = filename.replace('__MOONRAY_FRAME_' + str(index) + '__', token)
    if not filename.lower().endswith('.exr'):
        raise hou.NodeError('Deep output requires an .exr filename.')
    stage = lop.editableStage()
    settings = [UsdRender.Settings(stage.GetPrimAtPath(path)) for path in values['settings'].split()] if values['settings'] else [
        UsdRender.Settings(prim) for prim in stage.Traverse() if prim.IsA(UsdRender.Settings)]
    if not settings or any(not item for item in settings):
        raise hou.NodeError('Connect MoonRay Deep Output after valid Render Settings, before the USD Render ROP.')
    path = Sdf.Path(values['productpath'])
    if not path.IsAbsolutePath() or not path.IsPrimPath():
        raise hou.NodeError('Deep Product Path must be an absolute USD prim path.')
    for prim in stage.Traverse():
        if prim.IsA(UsdRender.Product) and prim.GetPath() != path and str(UsdRender.Product(prim).GetProductNameAttr().Get()) == filename:
            raise hou.NodeError('Deep and flat products must use separate output files.')
    product = UsdRender.Product.Define(stage, path)
    product.CreateProductTypeAttr('deep')
    product.CreateProductNameAttr(filename)
    selected = [('beauty', 'beauty', 'color3f')]
    for parm, name, dtype in [('normals', 'N', 'normal3f'), ('positions', 'P', 'point3f'), ('uv', 'St', 'float2')]:
        if values[parm]:
            selected.append((name, name, dtype))
    variables = []
    for name, source, dtype in selected:
        var = UsdRender.Var.Define(stage, path.AppendChild('Vars').AppendChild(name))
        var.CreateSourceNameAttr(source)
        var.CreateSourceTypeAttr('raw')
        var.CreateDataTypeAttr(dtype)
        var.GetPrim().CreateAttribute('driver:parameters:aov:husk:name', Sdf.ValueTypeNames.String).Set(name)
        variables.append(var.GetPath())
    product.CreateOrderedVarsRel().SetTargets(variables)
    for item in settings:
        paths = item.GetProductsRel().GetTargets()
        item.GetProductsRel().SetTargets(paths + ([path] if path not in paths else []))
        for attr, dtype, value in [('deep_format', Sdf.ValueTypeNames.Int, int(values['format'])),
                                   ('deep_z_tolerance', Sdf.ValueTypeNames.Float, values['ztolerance']),
                                   ('deep_curvature_tolerance', Sdf.ValueTypeNames.Float, values['curvature']),
                                   ('deep_vol_compression_res', Sdf.ValueTypeNames.Int, values['volumecompression'])]:
            item.GetPrim().CreateAttribute('moonray:sceneVariable:' + attr, dtype).Set(value)


def create(kwargs=None):
    import moonray_houdini
    network, source = moonray_houdini._context(kwargs)
    with hou.undos.group('MoonRay Deep Output'):
        # Insert before a selected render ROP so Render to Disk picks it up.
        rop = source if source and source.type().name() == 'usdrender_rop' else None
        node = moonray_houdini._append(network, rop.input(0) if rop else source,
                                      'moonray::deep::1.0', 'moonray_deep')
        if rop:
            rop.setInput(0, node)
        return moonray_houdini._show(node)
