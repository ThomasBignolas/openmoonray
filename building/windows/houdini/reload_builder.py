"""Reload Python/shelf tools in an open Houdini session; never save the HIP."""
import importlib
import json
from pathlib import Path
import traceback
import hou
from PySide6 import QtCore, QtGui
import moonray_houdini

mr = importlib.reload(moonray_houdini)
root = Path(hou.getenv('MOONRAY_HOUDINI_ROOT')).parent
hou.shelves.loadFile(str(root / 'install/plugin/houdini/toolbar/MoonRay.shelf'))
report = {'tool_loaded': 'vop_moonray_materialbuilder' in hou.shelves.tools(), 'steps': []}
command_path = root / 'builder-command.json'


def record(step, **values):
    report['steps'].append({'step': step, **values})
    (root / 'builder-live.json').write_text(json.dumps(report, indent=2) + '\n')


def poll():
    if not command_path.is_file():
        return
    try:
        command = json.loads(command_path.read_text(encoding='utf-8-sig'))
        command_path.unlink()
        action = command['action']
        pane = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
        if action == 'create':
            library = pane.pwd()
            while library and library.type().name() != 'materiallibrary':
                library = library.parent()
            if not library:
                selected = hou.selectedNodes()
                library = selected[-1] if selected else None
                while library and library.type().name() != 'materiallibrary':
                    library = library.parent()
            if not library:
                raise hou.OperationFailed('Select or dive inside your Material Library first.')
            with hou.undos.group('MoonRay Material Builder'):
                builder = mr._setup_material_builder(library.createNode('subnet', 'moonray_material'))
                builder.moveToGoodPosition()
                mr._show(builder)
            record('builder_created', node=builder.path())
        elif action == 'menu':
            if command.get('path'):
                pane.setPwd(hou.node(command['path']))
            pane.openTabMenu(auto_place=False)
            record('menu_opened', path=pane.pwd().path())
        elif action == 'capture':
            destination = root / ('builder-' + command.get('name', 'ui') + '.png')
            QtGui.QGuiApplication.primaryScreen().grabWindow(int(hou.qt.mainWindow().winId())).save(str(destination))
            record('capture', file=str(destination))
        elif action == 'inspect_shader':
            builder = hou.node(command['path'])
            mr._show(builder.node('surface'))
            record('shader_selected', node=builder.node('surface').path())
        elif action == 'finish':
            hou.ui.removeEventLoopCallback(poll)
            record('finished')
    except Exception:
        record('error', traceback=traceback.format_exc())


record('loaded', selected=[n.path() for n in hou.selectedNodes()],
       networks=[p.pwd().path() for p in hou.ui.paneTabs() if p.type() == hou.paneTabType.NetworkEditor])
hou.ui.addEventLoopCallback(poll)
print('MoonRay Material Builder loaded. Find it in the Material Library Tab menu.')
