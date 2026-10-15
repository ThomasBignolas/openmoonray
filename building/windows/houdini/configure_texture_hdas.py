"""Add native filtering and OCIO preparation controls to packaged texture HDAs."""
import argparse
from pathlib import Path
import hou

parser = argparse.ArgumentParser()
parser.add_argument('--install', type=Path, required=True)
args = parser.parse_args()
root = args.install.resolve() / 'plugin/houdini/otls'
assert root.is_relative_to(Path(__file__).resolve().parents[3] / 'build')
count = 0
for path in root.glob('*.hda'):
    if not any(name in path.name for name in ('ImageMap', 'UsdUVTexture', 'ProjectCameraMap')):
        continue
    hou.hda.installFile(str(path))
    for definition in hou.hda.definitionsInFile(str(path)):
        if not any('::' + name + '::' in definition.nodeTypeName() for name in ('ImageMap', 'UsdUVTexture', 'ProjectCameraMap_v2')):
            continue
        group = definition.parmTemplateGroup()
        if group.find('moonray_color_controls'):
            group.remove('moonray_color_controls')
        source = hou.StringParmTemplate('moonray_source_colorspace', 'Source Color Space', 1, default_value=('auto',),
            item_generator_script='import moonray_color\nreturn ["auto", "Automatic (Metadata / OCIO Rules)", "raw", "Raw / Data"] + moonray_color.color_space_menu(kwargs)',
            item_generator_script_language=hou.scriptLanguage.Python,
            help='Input interpretation used by the MoonRay Color Management LOP. Cached textures are converted before filtering.')
        usage = hou.StringParmTemplate('moonray_texture_usage', 'Texture Usage', 1, default_value=('auto',),
            menu_items=('auto', 'color', 'data'), menu_labels=('Automatic from Connections', 'Color', 'Raw Data'))
        filtering = hou.IntParmTemplate('texture_filter', 'Lookup Filter', 1, default_value=(0,),
            menu_items=('0', '1', '2', '3', '4'),
            menu_labels=('MoonRay Path Default', 'Nearest / No Mip Filtering', 'Bilinear / No Mip Filtering', 'Trilinear', 'Anisotropic'))
        blur = hou.FloatParmTemplate('texture_blur', 'Additional Blur (UV)', 1, default_value=(0,), min=0, min_is_strict=True)
        anisotropy = hou.IntParmTemplate('max_anisotropy', 'Maximum Anisotropy', 1, default_value=(8,), min=1, max=64, min_is_strict=True, max_is_strict=True)
        mip = hou.StringParmTemplate('moonray_mipmap_filter','Mipmap Generation Filter',1,default_value=('inherit',),
            menu_items=('inherit','box','triangle','gaussian','lanczos3','blackman-harris'),
            menu_labels=('Use Color Management Node','Box','Triangle','Gaussian','Lanczos 3','Blackman-Harris'))
        parms = [source, usage, mip] if 'ProjectCameraMap' in definition.nodeTypeName() else [source, usage, mip, filtering, blur, anisotropy]
        for parm in parms:
            parm.setTags({'moonray::is_parm': '1'})
        group.append(hou.FolderParmTemplate('moonray_color_controls', 'Color and Filtering', parm_templates=parms))
        definition.setParmTemplateGroup(group)
        count += 1
print('Updated', count, 'packaged texture HDAs')
assert count >= 1, 'Native ImageMap HDA is missing'
