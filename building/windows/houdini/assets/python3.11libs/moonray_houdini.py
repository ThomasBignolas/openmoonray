"""MoonRay shelf and menu workflows for Solaris. Uses editable native nodes."""
from pathlib import Path
import hou

RENDERER = 'HdMoonrayRendererPlugin'


MATERIAL_MENU_MASK = '*MOONRAY* ^*::BaseMaterial::* ^BaseMaterial parameter constant rampparm collect null subnet subnetconnector suboutput subinput'


def _setup_material_builder(builder, shader='DwaBaseMaterial'):
    import voptoolutils
    builder.setShaderLanguageName('USD')
    voptoolutils._addMtlSubnetParms(builder, MATERIAL_MENU_MASK, 'moonray', 'MoonRay Material Builder')
    name = next((n for n in hou.vopNodeTypeCategory().nodeTypes()
                 if '::DW_MOONRAY::' in n and ('::' + shader + '::') in n), None)
    if name is None:
        raise hou.OperationFailed('MoonRay shader is unavailable: ' + shader)
    surface = builder.createNode(name, 'volume' if shader == 'BaseVolume' else 'surface')
    surface.setMaterialFlag(False)
    surface.setInputGroupExpanded(None, False)
    albedo = surface.parmTuple('albedo')
    if albedo:
        for folder, index in zip(albedo[0].containingFolderSetParmTuples(),
                                 albedo[0].containingFolderIndices()):
            folder[0].set(index)
    output = builder.node('suboutput1')
    output.setName('material_output')
    output.setInput(0, surface)
    output.parm('name1').set('volume' if shader == 'BaseVolume' else 'surface')
    builder.setMaterialFlag(True)
    builder.setColor(hou.Color((0.32, 0.47, 0.62)))
    builder.setComment('MoonRay material. Dive inside to edit the shader and add textures.')
    builder.layoutChildren()
    return builder


def material_builder_tool(kwargs):
    """Native Tab-menu placement, like Houdini's other material builders."""
    import voptoolutils
    with hou.undos.group('MoonRay Material Builder'):
        builder = voptoolutils.genericTool(kwargs, 'subnet', 'moonray_material')
        return _setup_material_builder(builder)


def _context(kwargs=None):
    kwargs = kwargs or {}
    pane = kwargs.get('pane')
    if pane and hasattr(pane, 'pwd') and pane.pwd().childTypeCategory() == hou.lopNodeTypeCategory():
        network = pane.pwd()
    else:
        selected = [n for n in hou.selectedNodes() if n.type().category() == hou.lopNodeTypeCategory()]
        network = selected[-1].parent() if selected else hou.node('/stage')
    selected = [n for n in hou.selectedNodes() if n.parent() == network]
    source = selected[-1] if selected else network.displayNode()
    if source and source.type().name() == 'usdrender_rop':
        source = source.input(0)
    return network, source


def _append(network, source, kind, name):
    display_tail = None
    if kind in ('materiallibrary','light','domelight','assignmaterial','camera','moonray::aovs::1.0','moonray::deep::1.0'):
        current = source
        while current:
            if current.type().name() == 'moonray::color::1.0':
                display_tail, source = source, current.input(0)
                break
            current = current.input(0)
        # A selected light/material may already be upstream of the displayed
        # color node (for example, immediately after using a shelf action).
        # Keep that managed display tail while inserting the next scene edit.
        displayed = network.displayNode()
        if not display_tail and source and displayed and source in displayed.inputAncestors():
            managed = [displayed] + list(displayed.inputAncestors())
            if any(n.type().name() == 'moonray::color::1.0' and source in n.inputAncestors() for n in managed):
                display_tail = displayed
    connections = list(source.outputConnections()) if source and kind != 'usdrender_rop' else []
    node = network.createNode(kind, name)
    if display_tail:
        node.setUserData('moonray_display_tail',display_tail.path())
    if source:
        node.setInput(0, source)
    # New lights and materials must reach existing render nodes as well as
    # the viewport. Insert into the selected node's outgoing connections.
    for connection in connections:
        connection.outputNode().setInput(connection.inputIndex(), node)
    node.moveToGoodPosition()
    return node


def _show(node):
    node.setSelected(True, clear_all_selected=True)
    if isinstance(node, hou.LopNode):
        _display_created(node)
    if hou.isUIAvailable():
        pane = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
        if pane:
            pane.setPwd(node.parent())
            pane.homeToSelection()
    return node


def _display_created(node):
    tail=node.userData('moonray_display_tail')
    target=hou.node(tail) if tail else node
    (target or node).setDisplayFlag(True)
    if tail:
        node.destroyUserData('moonray_display_tail')


def _set(node, name, value):
    parm = node.parm(name) or node.parm(hou.text.encodeParm(name))
    if parm is None:
        raise hou.OperationFailed('Missing parameter: ' + name)
    control = node.parm(parm.name() + '_control') or node.parm(hou.text.encodeParm(name + '_control'))
    if control:
        control.set('set')
    parm.set(value)


def create_render_setup(kwargs=None):
    """Append beauty, normal and depth AOVs, settings and a configured render ROP."""
    network, source = _context(kwargs)
    with hou.undos.group('MoonRay Render Setup'):
        cameras = []
        if source and source.stage():
            cameras = [str(p.GetPath()) for p in source.stage().Traverse() if p.GetTypeName() == 'Camera']
        if not cameras:
            source = _append(network, source, 'camera', 'moonray_camera')
            source.parm('primpath').set('/cameras/moonray_camera')
            source.parmTuple('t').set((0, 3.2, 10))
            source.parmTuple('r').set((-12, 0, 0))
            source.parm('focalLength').set(45)
            cameras = ['/cameras/moonray_camera']
        paths = []
        for label, raw, dtype in (('beauty', 'color', 'color4f'), ('normal', 'N', 'normal3f'), ('depth', 'cameraDepth', 'float')):
            source = _append(network, source, 'rendervar', 'moonray_' + label)
            path = '/Render/MoonRay/Vars/' + label
            source.parm('primpath').set(path)
            _set(source, 'sourceName', raw)
            _set(source, 'sourceType', 'raw')
            _set(source, 'dataType', dtype)
            _set(source, 'driver:parameters:aov:husk:name', label)
            _set(source, 'driver:parameters:aov:husk:format', dtype)
            paths.append(path)
        product = _append(network, source, 'renderproduct', 'moonray_output')
        product.parm('primpath').set('/Render/MoonRay/beauty')
        _set(product, 'orderedVars', ' '.join(paths))
        _set(product, 'productName', '$HIP/render/moonray.$F4.exr')
        aovs = _append(network, product, 'moonray::aovs::1.0', 'moonray_aovs')
        settings = _append(network, aovs, 'rendersettings', 'moonray_settings')
        settings.parm('primpath').set('/Render/MoonRay/settings')
        _set(settings, 'camera', cameras[0])
        _set(settings, 'products', '/Render/MoonRay/beauty')
        settings.parm('res_mode').set('manual')
        settings.parm('res_mode').pressButton()
        for parm in settings.parmTuple('resolution'):
            parm.deleteAllKeyframes()
            parm.lock(False)
        settings.parmTuple('resolution').set((960, 540))
        _set(settings, 'moonray:sceneVariable:pixel_samples', 4)
        _set(settings, 'moonray:sceneVariable:light_samples', 2)
        _set(settings, 'moonray:localThreads', 4)
        color = _append(network, settings, 'moonray::color::1.0', 'moonray_color')
        rop = _append(network, color, 'usdrender_rop', 'RENDER_MOONRAY')
        rop.parm('renderer').set(RENDERER)
        rop.parm('rendersettings').set('/Render/MoonRay/settings')
        rop.parm('lopoutput').set('$HIP/render/moonray_scene.usd')
        rop.setUserData('moonray_render', '1')
        rop.setComment('MoonRay render. Quality: moonray_settings. Color and texture preparation: moonray_color. Files: moonray_output. Passes: moonray_aovs.')
        rop.setGenericFlag(hou.nodeFlag.DisplayComment, True)
        context = use_render_settings(rop)
        _show(rop)
        context.setDisplayFlag(True)
        return rop


def create_material(shader='DwaBaseMaterial', kwargs=None):
    network, source = _context(kwargs)
    with hou.undos.group('MoonRay Material'):
        library = _append(network, source, 'materiallibrary', 'moonray_materials')
        library.parm('matpathprefix').set('/Looks/')
        material = _setup_material_builder(library.createNode('subnet', shader), shader)
        material.moveToGoodPosition()
        _display_created(library)
        _show(material)
        return material


def create_light(shape='rect', kwargs=None):
    network, source = _context(kwargs)
    kinds = {'rect': 'UsdLuxRectLight', 'disk': 'UsdLuxDiskLight',
             'dome': 'UsdLuxDomeLight', 'distant': 'UsdLuxDistantLight'}
    with hou.undos.group('MoonRay Light'):
        light = _append(network, source, 'domelight' if shape == 'dome' else 'light', 'moonray_' + shape + '_light')
        if shape != 'dome':
            light.parm('lighttype').set(kinds[shape])
        else:
            # Houdini 21's dome node no longer supplies the primtype value
            # expected by the upstream MoonRay class default expression.
            _set(light, 'moonray:class', 'EnvLight')
        if shape in ('rect', 'disk'):
            light.parmTuple('t').set((0, 5, 4))
            light.parmTuple('r').set((-40, 0, 0))
            _set(light, 'inputs:intensity', 3)
            if shape == 'rect':
                _set(light, 'inputs:width', 4)
                _set(light, 'inputs:height', 4)
        return _show(light)


def assign_material(kwargs=None):
    network, source = _context(kwargs)
    with hou.undos.group('MoonRay Material Assignment'):
        node = _append(network, source, 'assignmaterial', 'assign_moonray_material')
        node.parm('primpattern1').set('')
        return _show(node)


def _render_node():
    selected = [n for n in hou.selectedNodes() if n.parm('renderer') and n.evalParm('renderer') == RENDERER]
    if selected:
        return selected[-1]
    nodes = [n for n in hou.node('/stage').allSubChildren()
             if n.type().name() == 'usdrender_rop' and n.evalParm('renderer') == RENDERER]
    if len(nodes) == 1:
        return nodes[0]
    if nodes and hou.isUIAvailable():
        choice = hou.ui.selectFromList([n.path() for n in nodes], exclusive=True, title='MoonRay Render Node')
        return nodes[choice[0]] if choice else None
    raise hou.OperationFailed('Create a MoonRay Render Setup, or select its render node first.')


def render(preview=False):
    node = _render_node()
    if node:
        node.parm('renderpreview' if preview else 'execute').pressButton()


def start_ipr():
    viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
    if viewer is None:
        raise hou.OperationFailed('Open a Scene View pane to use MoonRay IPR.')
    rop = _render_node()
    if rop is None:
        return
    source = use_render_settings(rop)
    viewer.setPwd(source.parent())
    viewer.setIsCurrentTab()
    if viewer.currentHydraRenderer() != 'Moonray':
        viewer.setHydraRenderer('Moonray')
        _resume_on_idle(viewer)
    viewer.setRendererPaused(False)


def _resume_on_idle(viewer):
    # Houdini creates/recreates the delegate after the current UI action.
    # Applying resume only before that happens can leave the new view idle.
    def resume():
        try:
            if viewer.currentHydraRenderer() == 'Moonray':
                hou.ui.triggerUpdate()
                viewer.setRendererPaused(False)
        except hou.ObjectWasDeleted:
            pass
    hou.ui.postEventCallback(resume)


def pause_ipr():
    viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
    if viewer and viewer.currentHydraRenderer() == 'Moonray':
        viewer.setRendererPaused(True)


def render_settings_node(rop):
    """Find the settings authored for this ROP, including intervening AOV nodes."""
    target = rop.evalParm('rendersettings')
    settings = next((node for node in rop.inputAncestors()
                     if node.type().name() == 'rendersettings' and
                     node.evalParm('primpath') == target), None)
    if settings is None:
        raise hou.OperationFailed('No upstream Render Settings node authors ' + target)
    return settings


def use_render_settings(rop=None):
    """Select the ROP's render settings in USD so preview and disk agree."""
    rop = rop or _render_node()
    if not rop:
        return
    target = rop.evalParm('rendersettings')
    source = rop.input(0)
    if source is None:
        raise hou.OperationFailed('Connect a scene to ' + rop.path())
    stage = source.stage()
    if not stage or not stage.GetPrimAtPath(target):
        raise hou.OperationFailed('The render settings prim is missing: ' + target)
    if stage.GetMetadata('renderSettingsPrimPath') != target:
        with hou.undos.group('Use MoonRay Render Settings in Viewport'):
            if source.type().name() == 'configurelayer' and source.userData('moonray_view_settings'):
                config = source
            else:
                config = source.parent().createNode('configurelayer', 'moonray_view_settings')
                config.setInput(0, source)
                config.setUserData('moonray_view_settings', '1')
                config.moveToGoodPosition()
                rop.setInput(0, config)
            config.parm('setrendersettings').set(True)
            config.parm('rendersettings').set(target)
            config.setComment('Render settings used by the viewport and this render ROP: ' + target)
            source = config
    if not source.isDisplayFlagSet():
        source.setDisplayFlag(True)
    return source


def refresh_settings():
    """Refresh only the MoonRay folder using Houdini's native parameter updater."""
    import loputils
    nodes = [node for node in hou.selectedNodes() if node.type().name() == 'rendersettings']
    if not nodes:
        rop = _render_node()
        if rop is None:
            return []
        nodes = [render_settings_node(rop)]
    template = str(Path(hou.getenv('MOONRAY_HOUDINI_ROOT')) /
                   'plugin/houdini/soho/parameters/HdMoonrayRendererPlugin_Global.ds')
    with hou.undos.group('Refresh MoonRay Render Settings Controls'):
        for node in nodes:
            # Replacing a nested dialog-script folder can reset its children.
            # Preserve expressions, animation and unexpanded paths explicitly.
            saved = {}
            if node.parmTemplateGroup().findFolder('Moonray'):
                for parm in node.parmsInFolder(('Moonray',)):
                    kind = parm.parmTemplate().type()
                    if kind in (hou.parmTemplateType.Int, hou.parmTemplateType.Float,
                                hou.parmTemplateType.String, hou.parmTemplateType.Toggle,
                                hou.parmTemplateType.Menu):
                        keys = parm.keyframes()
                        value = None if keys else (parm.unexpandedString()
                            if kind == hou.parmTemplateType.String else parm.eval())
                        saved[parm.name()] = (keys, value, parm.isLocked())
            loputils.addDialogScriptFolder(template, node, 'Moonray')
            for name, (keys, value, locked) in saved.items():
                parm = node.parm(name)
                if parm is not None:
                    parm.lock(False)
                    parm.deleteAllKeyframes()
                    if keys:
                        parm.setKeyframes(keys)
                    else:
                        parm.set(value, follow_parm_reference=False)
                    parm.lock(locked)
    return nodes


def restart_ipr():
    viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
    if viewer is None or viewer.currentHydraRenderer() != 'Moonray':
        return start_ipr()
    viewer.restartRenderer()
    viewer.setRendererPaused(False)
    _resume_on_idle(viewer)


def stop_ipr():
    viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
    if viewer and viewer.currentHydraRenderer() == 'Moonray':
        viewer.setRendererPaused(True)
        viewer.setHydraRenderer('Houdini VK')


def show_settings():
    rop = _render_node()
    if not rop:
        return
    settings = render_settings_node(rop)
    displayed = settings.parent().displayNode()
    _show(settings)
    if displayed:
        displayed.setDisplayFlag(True)
    return settings


def documentation():
    installation = Path(hou.getenv('MOONRAY_HOUDINI_ROOT'))
    bundled = installation.parent / 'docs/HOUDINI.md'
    guide = bundled if bundled.is_file() else installation.parents[3] / 'building/windows/houdini/README.md'
    hou.ui.showInFileBrowser(str(guide))


def run(action, *args, **kwargs):
    """Present Houdini operation errors as normal tool messages."""
    from moonray_aovs import create as create_aovs
    from moonray_deep import create as create_deep
    from moonray_color import create as create_color
    actions = {'setup': create_render_setup, 'aovs': create_aovs, 'deep': create_deep, 'color': create_color, 'material': create_material,
               'light': create_light, 'assign': assign_material, 'render': render,
               'ipr': start_ipr, 'pause': pause_ipr, 'restart': restart_ipr, 'stop': stop_ipr,
               'settings': show_settings, 'use_settings': use_render_settings, 'refresh_settings': refresh_settings,
               'help': documentation}
    try:
        return actions[action](*args, **kwargs)
    except hou.Error as error:
        if not hou.isUIAvailable():
            raise
        hou.ui.displayMessage(str(error), title='MoonRay', severity=hou.severityType.Error)
