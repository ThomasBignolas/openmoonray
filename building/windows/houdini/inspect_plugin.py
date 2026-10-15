"""Run with hython after loading the staged MoonRay package."""
import json
import os
from pathlib import Path
import sys
import hou
from pxr import Plug, Sdr, Usd

result = {'houdini': hou.applicationVersionString(), 'usd': Usd.GetVersion(),
          'package_root': hou.getenv('MOONRAY_HOUDINI_ROOT'), 'plugins': {}, 'errors': []}
for name in ('moonrayShaderDiscovery', 'moonrayShaderParser', 'hdMoonrayAdapters', 'hd_moonray'):
    plugin = Plug.Registry().GetPluginWithName(name)
    try:
        result['plugins'][name] = {'path': plugin.path if plugin else None,
                                   'loaded': bool(plugin and plugin.Load())}
    except Exception as exc:
        result['errors'].append(f'{name}: {exc}')
result['renderers'] = list(zip(hou.lop.availableRendererNames(), hou.lop.availableRendererLabels()))
result['shaders'] = {}
for name in ('DwaBaseMaterial', 'UsdPreviewSurface', 'ImageMap', 'BaseVolume'):
    node = Sdr.Registry().GetShaderNodeByIdentifier(name)
    result['shaders'][name] = {'found': bool(node), 'inputs': len(node.GetInputNames()) if node else 0}
types = [name for name in hou.vopNodeTypeCategory().nodeTypes() if 'MOONRAY' in name.upper()]
result['vop_types'] = types
stage = hou.node('/stage')
library = stage.createNode('materiallibrary', 'moonray_materials')
for name in types:
    try:
        node = library.createNode(name)
        node.destroy()
    except Exception as exc:
        result['errors'].append(f'{name}: {exc}')
settings = stage.createNode('rendersettings', 'moonray_settings')
result['render_settings_parms'] = [p.name() for p in settings.parms() if 'moonray' in p.name().lower()]
result['settings_errors'] = settings.errors()
output = Path(sys.argv[1])
output.write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2), flush=True)
if result['errors'] or not all(p['loaded'] for p in result['plugins'].values()):
    raise RuntimeError('MoonRay plugin inspection failed')
