"""Check exported RDL defaults through Sdr and an authored USD round-trip."""
import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--definitions', type=Path, nargs='+', required=True)
parser.add_argument('--report', type=Path, required=True)
parser.add_argument('--translator', type=Path, help='Also check a material through hd_usd2rdl')
args = parser.parse_args()
for directory in args.definitions:
    if not directory.is_dir() or not any(directory.rglob('*.json')):
        parser.error(f'No shader definitions in {directory}')
args.report.parent.mkdir(parents=True, exist_ok=True)
fixture_dir = args.report.parent / 'shader registry fixtures'
fixture_dir.mkdir(exist_ok=True)

# Nonempty arrays and nonidentity matrices expose losses hidden by the many
# empty/identity defaults in production shader definitions.
scalar_defaults = {
    'Bool': True, 'Int': -7, 'Long': 2**53 + 19, 'Float': 0.375,
    'Double': 1.1234567890123, 'String': 'texture path',
    'Rgb': [0.125, 0.25, 0.75], 'Rgba': [0.125, 0.25, 0.75, 0.5],
    'Vec2f': [0.125, -0.5], 'Vec3f': [0.125, -0.5, 2.0],
    'Vec4f': [0.125, -0.5, 2.0, 0.25],
    'Vec2d': [1.1234567890123, -0.5],
    'Vec3d': [1.1234567890123, -0.5, 2.0],
    'Vec4d': [1.1234567890123, -0.5, 2.0, 0.25],
    'SceneObject*': False,
}
for size in (3, 4):
    for precision in ('f', 'd'):
        scalar_defaults[f'Mat{size}{precision}'] = [
            [(row * size + column + 1) * 0.125 for column in range(size)]
            for row in range(size)]

attributes = {}
def add_fixture(name, attr_type, default, **extra):
    attributes[name] = {'attrType': attr_type, 'default': default,
                        'order': len(attributes), **extra}

for attr_type, default in scalar_defaults.items():
    add_fixture(attr_type.replace('*', ''), attr_type, default)
    if attr_type != 'SceneObject*':
        add_fixture(attr_type + 'Vector', attr_type + 'Vector', [default, default])
add_fixture('false_bool', 'Bool', False)
add_fixture('mixed_bools', 'BoolVector', [True, False, True])
add_fixture('signed_longs', 'LongVector', [2**63 - 1, -(2**63), 2**32 + 1])
add_fixture('objects', 'SceneObjectVector', [False, False])
add_fixture('indexed_objects', 'SceneObjectIndexable', [False, False])
add_fixture('asset', 'String', 'texture path.tx', filename=True)
add_fixture('assets', 'StringVector', ['a.tx', 'b.tx'], filename=True)
add_fixture('enum', 'Int', 9, enum={'first': 4, 'second': 9})
fixture = fixture_dir / 'SdrTypeProbe.json'
fixture.write_text(json.dumps({'scene_classes': {'SdrTypeProbe': {
    'type': 'Map', 'attributes': attributes}}}), encoding='utf-8')
os.environ['MOONRAY_CLASS_PATH'] = os.pathsep.join(
    str(path.resolve()) for path in [fixture_dir, *args.definitions])

handles = []
if os.name == 'nt':
    for entry in os.environ['PATH'].split(os.pathsep):
        try:
            handles.append(os.add_dll_directory(entry))
        except OSError:
            pass
from pxr import Sdf, Sdr, Usd, UsdShade

base_types = {
    # Sdr represents RDL boolean controls as integer switches.
    'Bool': 'int', 'Int': 'int', 'Long': 'int64', 'Float': 'float',
    'Double': 'double', 'String': 'string', 'Rgb': 'color3f', 'Rgba': 'color4f',
    'Vec2f': 'float2', 'Vec3f': 'float3', 'Vec4f': 'float4',
    'Vec2d': 'double2', 'Vec3d': 'double3', 'Vec4d': 'double4',
    # USD matrices have double storage, including RDL float matrices.
    'Mat3f': 'matrix3d', 'Mat3d': 'matrix3d',
    'Mat4f': 'matrix4d', 'Mat4d': 'matrix4d', 'SceneObject*': 'token',
}

def expected_type(attr):
    attr_type = attr['attrType']
    if 'enum' in attr:
        return 'string'
    if attr_type in ('SceneObjectVector', 'SceneObjectIndexable'):
        return 'token[]'
    vector = attr_type.endswith('Vector')
    base = attr_type[:-6] if vector else attr_type
    usd_type = 'asset' if attr.get('filename') else base_types[base]
    return usd_type + ('[]' if vector else '')

def plain(value):
    if isinstance(value, Sdf.AssetPath):
        return value.path
    if value is None or isinstance(value, (bool, str, int, float)):
        return value
    if hasattr(value, 'toList'):
        return plain(value.toList())
    return [plain(element) for element in value]

def same(actual, expected):
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(
            same(a, e) for a, e in zip(actual, expected))
    if isinstance(expected, float):
        return isinstance(actual, (float, int)) and math.isclose(
            actual, expected, rel_tol=1e-12, abs_tol=1e-12)
    return actual == expected

registry = Sdr.Registry()
stage = Usd.Stage.CreateInMemory()
failures = []
checked = []
types = Counter()
seen = set()
roundtrip = []
for directory in [fixture_dir, *args.definitions]:
    for path in sorted(directory.rglob('*.json')):
        data = json.loads(path.read_text(encoding='utf-8'))
        for name, definition in data.get('scene_classes', {}).items():
            if name in seen:
                continue
            seen.add(name)
            try:
                node = registry.GetShaderNodeByIdentifier(name)
            except Exception as error:
                failures.append(f'{name}: shader definition raised {error}')
                continue
            if not node or not node.IsValid():
                failures.append(f'{name}: shader definition did not parse')
                continue
            shader = UsdShade.Shader.Define(stage, f'/node{len(seen)}')
            shader.CreateIdAttr(name)
            count = 0
            for attr_name, attr in (definition.get('attributes') or {}).items():
                label = f'{name}.{attr_name}'
                prop = node.GetShaderInput(attr_name)
                if not prop:
                    failures.append(f'{label}: missing input')
                    continue
                expected = attr['default']
                if attr['attrType'].startswith('SceneObject'):
                    expected = [''] * len(expected) if isinstance(expected, list) else ''
                if 'enum' in attr:
                    allowed = [key for key, value in attr['enum'].items() if value == expected]
                else:
                    allowed = [expected]
                usd_type = expected_type(attr)
                dynamic = attr['attrType'].endswith('Vector') or attr['attrType'] == 'SceneObjectIndexable'
                if prop.IsDynamicArray() != dynamic:
                    failures.append(f'{label}: incorrect dynamic-array metadata')
                actual_type = prop.GetTypeAsSdfType()[0]
                value = prop.GetDefaultValueAsSdfType()
                actual = plain(value)
                if str(actual_type) != usd_type:
                    failures.append(f'{label}: USD type {actual_type}, expected {usd_type}')
                if not any(same(actual, item) for item in allowed):
                    failures.append(f'{label}: default {actual!r}, expected {allowed!r}')
                try:
                    authored = shader.CreateInput(attr_name, actual_type)
                    authored.Set(value)
                    roundtrip.append((authored.GetAttr().GetPath(), allowed, label))
                except Exception as error:
                    failures.append(f'{label}: cannot author USD input: {error}')
                count += 1
                types[attr['attrType']] += 1
            checked.append({'class': name, 'attributes': count})

usd_file = args.report.with_suffix('.usda')
stage.GetRootLayer().Export(str(usd_file))
restored = Usd.Stage.Open(str(usd_file))
for path, allowed, label in roundtrip:
    actual = plain(restored.GetAttributeAtPath(path).Get())
    if not any(same(actual, item) for item in allowed):
        failures.append(f'{label}: USD round-trip default {actual!r}, expected {allowed!r}')
report = {'classes_checked': len(checked), 'attributes_checked': sum(types.values()),
          'attribute_types': dict(sorted(types.items())), 'failures': failures, 'classes': checked}
if args.translator and not failures:
    from pxr import UsdGeom
    import scene_rdl2 as rdl
    material_stage = Usd.Stage.CreateInMemory()
    mesh = UsdGeom.Mesh.Define(material_stage, '/triangle')
    mesh.CreatePointsAttr([(-1, -1, 0), (1, -1, 0), (0, 1, 0)])
    mesh.CreateFaceVertexCountsAttr([3])
    mesh.CreateFaceVertexIndicesAttr([0, 1, 2])
    mesh.CreateSubdivisionSchemeAttr('none')
    material = UsdShade.Material.Define(material_stage, '/material')
    shader = UsdShade.Shader.Define(material_stage, '/material/shader')
    shader.CreateIdAttr('DwaBaseMaterial')
    shader.CreateOutput('out', Sdf.ValueTypeNames.Token)
    material.CreateSurfaceOutput('moonray').ConnectToSource(shader.ConnectableAPI(), 'out')
    UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(material)
    node = registry.GetShaderNodeByIdentifier('DwaBaseMaterial')
    # Both boolean states plus scalar, color and array parameters travel through
    # the real material adapter. Compare to native scene-class defaults.
    names = ['show_specular', 'casts_caustics', 'albedo', 'roughness', 'iridescence_colors']
    for name in names:
        prop = node.GetShaderInput(name)
        shader.CreateInput(name, prop.GetTypeAsSdfType()[0]).Set(prop.GetDefaultValueAsSdfType())
    material_file = args.report.parent / 'registry-material.usda'
    rdl_file = args.report.parent / 'registry-material.rdla'
    material_stage.GetRootLayer().Export(str(material_file))
    with (args.report.parent / 'registry-material.log').open('w') as log:
        subprocess.run([str(args.translator.resolve()), '-in', str(material_file.resolve()),
                        '-out', str(rdl_file.resolve())],
                       stdout=log, stderr=subprocess.STDOUT, timeout=60, check=True)
    context = rdl.SceneContext()
    context.setProxyModeEnabled(True)
    rdl.AsciiReader(context).fromFile(str(rdl_file))
    actual_material = context.getSceneObject('/material/shader')
    default_material = context.createSceneObject('DwaBaseMaterial', '/expected_defaults')
    for name in names:
        actual, expected = actual_material.get(name), default_material.get(name)
        if not same(plain(actual), plain(expected)):
            failures.append(f'DwaBaseMaterial.{name}: translated {actual!r}, native default {expected!r}')
    report['translated_material_parameters'] = names
args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(f"Checked {len(checked)} classes, {sum(types.values())} attributes, "
      f"{len(types)} RDL types: {len(failures)} failures", flush=True)
for failure in failures[:20]:
    print(failure, file=sys.stderr)
sys.exit(bool(failures))
