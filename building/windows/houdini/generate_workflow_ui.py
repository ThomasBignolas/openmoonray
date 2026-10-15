"""Generate matching MoonRay menu and shelf actions from one definition."""
from pathlib import Path
from xml.sax.saxutils import escape

assets = Path(__file__).with_name('assets')
actions = [
    ('setup', 'Render Setup', 'Create Render Setup', "'setup'", 'ROP_usdrender'),
    ('ipr', 'Start IPR', 'Start / Resume Live Render', "'ipr'", 'BUTTONS_play'),
    ('pause', 'Pause IPR', 'Pause Live Render', "'pause'", 'BUTTONS_pause'),
    ('restart', 'Restart IPR', 'Restart Live Render', "'restart'", 'BUTTONS_reload'),
    ('stop', 'Stop IPR', 'Stop Live Render', "'stop'", 'BUTTONS_stop'),
    ('preview', 'Render to MPlay', 'Render to MPlay', "'render', True", 'ROP_ifd'),
    ('render', 'Render to Disk', 'Render to Disk', "'render'", 'ROP_usdrender'),
    ('settings', 'Settings', 'Render Settings', "'settings'", 'LOP_rendersettings'),
    ('color', 'Color Management', 'Create Color Management', "'color'", 'COP2_colorcorrect'),
    ('aovs', 'AOVs', 'Create AOVs', "'aovs'", 'LOP_rendervar'),
    ('deep', 'Deep Output', 'Create Deep Output', "'deep'", 'LOP_renderproduct'),
    ('surface', 'Surface', 'Surface Material', "'material', 'DwaBaseMaterial'", 'VOP_material'),
    ('glass', 'Glass', 'Glass Material', "'material', 'DwaRefractiveMaterial'", 'VOP_material'),
    ('skin', 'Skin', 'Skin Material', "'material', 'DwaSkinMaterial'", 'VOP_material'),
    ('volume', 'Volume', 'Volume Material', "'material', 'BaseVolume'", 'VOP_material'),
    ('assign', 'Assign Material', 'Assign Material', "'assign'", 'LOP_assignmaterial'),
    ('rect', 'Area Light', 'Area Light', "'light', 'rect'", 'LOP_light'),
    ('disk', 'Disk Light', 'Disk Light', "'light', 'disk'", 'LOP_light'),
    ('dome', 'Dome Light', 'Dome Light', "'light', 'dome'", 'LOP_light'),
    ('distant', 'Distant Light', 'Distant Light', "'light', 'distant'", 'LOP_light'),
    ('help', 'Help', 'Quick Start', "'help'", 'BUTTONS_help'),
]
tools = ['<?xml version="1.0" encoding="UTF-8"?>', '<shelfDocument>',
         '  <toolshelf name="moonray" label="MoonRay">']
menu = ['<?xml version="1.0" encoding="UTF-8"?>', '<mainMenu><menuBar>',
        '<subMenu id="moonray_menu"><label>MoonRay</label><insertBefore>help_menu</insertBefore>']
for name, label, menu_label, args, icon in actions:
    tools.append(f'    <memberTool name="moonray_{name}"/>')
tools.append('  </toolshelf>')
for name, label, menu_label, args, icon in actions:
    script = f'import moonray_houdini\nmoonray_houdini.run({args})'
    tools.append(f'  <tool name="moonray_{name}" label="{escape(label)}" icon="{icon}">'
                 f'<script scriptType="python"><![CDATA[{script}]]></script></tool>')
    if name in ('surface', 'rect', 'help'):
        menu.append('<separatorItem/>')
    menu.append(f'<scriptItem id="moonray_{name}"><label>{escape(menu_label)}</label>'
                f'<scriptCode><![CDATA[{script}]]></scriptCode></scriptItem>')
tools.append('''  <tool name="vop_moonray_materialbuilder" label="MoonRay Material Builder" icon="VOP_material">
    <toolMenuContext name="network"><contextOpType>Vop/materialbuilder</contextOpType></toolMenuContext>
    <toolSubmenu>MoonRay</toolSubmenu>
    <script scriptType="python"><![CDATA[import moonray_houdini
moonray_houdini.material_builder_tool(kwargs)]]></script>
  </tool>''')
tools.append('</shelfDocument>')
menu.append('</subMenu></menuBar></mainMenu>')
(assets / 'toolbar').mkdir(parents=True, exist_ok=True)
(assets / 'toolbar/MoonRay.shelf').write_text('\n'.join(tools) + '\n')
(assets / 'MainMenuCommon.xml').write_text('\n'.join(menu) + '\n')
print('Generated MoonRay menu and shelf with', len(actions), 'actions.')
