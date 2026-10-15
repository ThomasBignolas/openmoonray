"""Read-only check that normal Houdini startup loads the released color tools."""
import json
from pathlib import Path
import sys

import hou
import moonray_color
import moonray_houdini

expected = Path(sys.argv[1]).resolve()
actual = Path(hou.getenv('MOONRAY_HOUDINI_ROOT')).resolve()
kind = hou.lopNodeTypeCategory().nodeTypes().get('moonray::color::1.0')
image = next(t for n, t in hou.vopNodeTypeCategory().nodeTypes().items()
             if '::ImageMap::' in n and 'MOONRAY' in n)
checks = {
    'normal_package_selected': actual == expected,
    'color_module_selected': Path(moonray_color.__file__).resolve().is_relative_to(expected),
    'workflow_module_selected': Path(moonray_houdini.__file__).resolve().is_relative_to(expected),
    'color_node_available': bool(kind and kind.definition()),
    'texture_controls_available': bool(image.definition().parmTemplateGroup().find('moonray_color_controls')),
}
config_path, config = moonray_color.load_config()
checks['acescg_available'] = moonray_color.space_name(config, 'ACEScg') == 'ACEScg'
report = {'passed': all(checks.values()), 'checks': checks,
          'package': str(actual), 'ocio_config': config_path}
Path(sys.argv[2]).write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2), flush=True)
assert report['passed'], report
