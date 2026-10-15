# SPDX-License-Identifier: Apache-2.0
"""Run under hython with HOUDINI_USER_PREF_DIR set to the prepared prefs21.0."""
import argparse
import json
from pathlib import Path
import hou

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--client', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
client = args.client.resolve()
value = json.loads((client / 'classroom.json').read_text())
assert hou.getenv('HDMOONRAY_STACK') == f'url-http://{value["coordinator"]}:{value["coordinator_port"]}'
assert hou.getenv('HDMOONRAY_HOSTS') == str(value['render_workers'])
assert Path(hou.getenv('ARRAS_SESSION_PATH')).resolve() == (client / 'sessions').resolve()
name = 'soho/parameters/HdMoonrayRendererPlugin_Viewport.ds'
path = Path(hou.findFile(name)).resolve()
assert path == (client / 'overlay' / name).resolve(), path
group = hou.ParmTemplateGroup()
group.setToDialogScript(path.read_text())
for name, expected in [('useRemoteHosts', 1), ('remoteHosts', value['render_workers']),
                       ('maxFps', value['fps']), ('executionMode', value['execution_mode'])]:
    default = group.find(name).defaultValue()
    actual = default[0] if isinstance(default, tuple) else default
    assert actual == expected, (name, default)
import moonray_houdini
assert Path(moonray_houdini.__file__).is_file()
result = {'passed': True, 'houdini': hou.applicationVersionString(), 'remote_enabled': True,
          'render_workers': value['render_workers'], 'fps': value['fps'], 'mode': value['execution_mode'],
          'render_started': False}
args.output.write_text(json.dumps(result, indent=2))
print(json.dumps(result))
