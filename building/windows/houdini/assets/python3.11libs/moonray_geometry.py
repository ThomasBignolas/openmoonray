"""Explicit MoonRay mesh quality overrides using the existing native primvars."""
import math
import hou
from pxr import Sdf, UsdGeom

TYPES = ('Mesh', 'Sphere', 'Cube', 'Cone', 'Cylinder', 'Capsule', 'Plane')


def parameters():
    prims = hou.StringParmTemplate('prims', 'Primitive Pattern', 1, default_value=('/**',),
        help='Standard Solaris primitive pattern. Only meshes and supported implicit surfaces are edited. Select descendants when choosing a model.')
    resolution = hou.FloatParmTemplate('resolution', 'Mesh Resolution', 1, default_value=(4,),
        min=1, max=64, min_is_strict=True,
        help='Maximum edge subdivisions for MoonRay tessellation. Higher values cost memory and preparation time. Check silhouettes and displacement at final resolution.')
    adaptive = hou.FloatParmTemplate('adaptive', 'Adaptive Error (pixels)', 1, default_value=(1,),
        min=0, max=8, min_is_strict=True,
        help='Screen-space tessellation error. Zero disables adaptive tessellation. Mesh Resolution still sets the maximum.')
    smooth = hou.ToggleParmTemplate('smooth', 'Smooth Normals', default_value=True)
    items = [prims]
    for key, label, parm, enabled in (
            ('resolution', 'Override Mesh Resolution', resolution, True),
            ('adaptive', 'Override Adaptive Error', adaptive, False),
            ('smooth', 'Override Smooth Normals', smooth, False)):
        items.append(hou.ToggleParmTemplate('set_' + key, label, default_value=enabled))
        parm.setConditional(hou.parmCondType.DisableWhen, '{ set_' + key + ' == 0 }')
        items.append(parm)
    return hou.ParmTemplateGroup(items)


def cook(lop, controls):
    values = {p.name(): p.eval() for p in controls.parms()}
    if not lop.input(0):
        raise hou.NodeError('Connect geometry before MoonRay Geometry Settings.')
    rule = hou.LopSelectionRule()
    rule.setPathPattern(values['prims'])
    paths = rule.expandedPaths(lop.input(0))
    for key, minimum in (('resolution', 1), ('adaptive', 0)):
        if values['set_' + key] and (not math.isfinite(values[key]) or values[key] < minimum):
            raise hou.NodeError(key + ' must be finite and at least ' + str(minimum))
    stage = lop.editableStage()
    matched = 0
    for path in paths:
        prim = stage.GetPrimAtPath(path)
        if prim.GetTypeName() not in TYPES:
            continue
        if prim.IsInstanceProxy():
            raise hou.NodeError('Edit the source of this USD instance: ' + str(path))
        api = UsdGeom.PrimvarsAPI(prim)
        for key, name, dtype in (('resolution', 'mesh_resolution', Sdf.ValueTypeNames.Float),
                                 ('adaptive', 'adaptive_error', Sdf.ValueTypeNames.Float),
                                 ('smooth', 'smooth_normal', Sdf.ValueTypeNames.Bool)):
            if values['set_' + key]:
                value = bool(values[key]) if key == 'smooth' else values[key]
                api.CreatePrimvar('moonray:' + name, dtype, UsdGeom.Tokens.constant).Set(value)
        matched += 1
    if not matched:
        raise hou.NodeWarning('Pattern matched no editable meshes or supported implicit surfaces.')


def create(kwargs=None):
    import moonray_houdini as mr
    network, source = mr._context(kwargs)
    with hou.undos.group('MoonRay Geometry Settings'):
        return mr._show(mr._append(network, source, 'moonray::geometry::1.0', 'moonray_geometry'))
