"""Render known OCIO color values through the real MoonRay Solaris worker."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

import hou
import numpy as np
import OpenImageIO as oiio
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdRender, UsdShade

sys.path.insert(0, str(Path(__file__).parent))
from validate_color_pipeline import fixture, network, read
import moonray_color as color


def scene(out, name, native=False, mode='vectorized', lookup=0, checker=False, output='rendering', deep=False):
    stage = Usd.Stage.CreateNew(str(out / (name + '.usda')))
    source = out / ('checker.exr' if checker else 'color.exr')
    material, texture, surface = network(stage, '/material', source)
    surface.GetInput('opacity').GetAttr().ClearConnections()
    surface.GetInput('opacity').Set(1.)
    # Prevent Husk's automatic camera headlight from adding specular light to
    # the emission-only color measurement.
    dome = UsdLux.DomeLight.Define(stage, '/black_environment')
    UsdLux.LightAPI(dome).CreateColorAttr(Gf.Vec3f(0))
    if checker:
        texture.GetInput('sourceColorSpace').Set('raw')
    if native:
        texture.CreateIdAttr('ImageMap')
        texture.CreateInput('texture', Sdf.ValueTypeNames.String).Set(str(source))
        texture.CreateInput('gamma', Sdf.ValueTypeNames.Int).Set(0)
        texture.CreateInput('moonray_source_colorspace', Sdf.ValueTypeNames.String).Set('sRGB - Texture')
    else:
        st = UsdShade.Shader.Define(stage, '/material/st')
        st.CreateIdAttr('UsdPrimvarReader_float2')
        st.CreateInput('varname', Sdf.ValueTypeNames.Token).Set('st')
        st.CreateOutput('result', Sdf.ValueTypeNames.Float2)
        texture.CreateInput('st', Sdf.ValueTypeNames.Float2).ConnectToSource(st.ConnectableAPI(), 'result')
    mesh = UsdGeom.Mesh.Define(stage, '/mesh')
    mesh.CreatePointsAttr([(-2,-2,0), (2,-2,0), (2,2,0), (-2,2,0)])
    mesh.CreateFaceVertexCountsAttr([4])
    mesh.CreateFaceVertexIndicesAttr([0,1,2,3])
    mesh.CreateSubdivisionSchemeAttr('none')
    UsdGeom.PrimvarsAPI(mesh).CreatePrimvar('st', Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.faceVarying).Set([(0,0),(1,0),(1,1),(0,1)])
    UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(material)
    camera = UsdGeom.Camera.Define(stage, '/camera')
    camera.AddTranslateOp().Set(Gf.Vec3d(0,0,5))
    camera.CreateHorizontalApertureAttr(36)
    camera.CreateVerticalApertureAttr(36)
    camera.CreateFocalLengthAttr(50)
    settings = UsdRender.Settings.Define(stage, '/Render/settings')
    settings.CreateCameraRel().SetTargets(['/camera'])
    settings.CreateResolutionAttr(Gf.Vec2i(32,32))
    for key, dtype, value in [('localThreads',Sdf.ValueTypeNames.Int,2),
                              ('executionMode',Sdf.ValueTypeNames.String,mode),
                              ('sceneVariable:pixel_samples',Sdf.ValueTypeNames.Int,2),
                              ('sceneVariable:max_diffuse_depth',Sdf.ValueTypeNames.Int,0)]:
        settings.GetPrim().CreateAttribute('moonray:' + key,dtype).Set(value)
    product = UsdRender.Product.Define(stage, '/Render/product')
    product.CreateProductNameAttr((out / (name + '.exr')).as_posix())
    paths=[]
    for label, src, dtype in [('beauty','color','color4f'),('normal','N','normal3f')]:
        var=UsdRender.Var.Define(stage,'/Render/Vars/' + label)
        var.CreateSourceNameAttr(src)
        var.CreateDataTypeAttr(dtype)
        var.GetPrim().CreateAttribute('driver:parameters:aov:husk:name',Sdf.ValueTypeNames.String).Set(label)
        paths.append(var.GetPath())
    product.CreateOrderedVarsRel().SetTargets(paths)
    if deep:
        crypto=UsdRender.Var.Define(stage,'/Render/Vars/Cryptomatte')
        crypto.CreateSourceNameAttr('cryptomatte')
        crypto.CreateDataTypeAttr('float')
        crypto.GetPrim().CreateAttribute('driver:parameters:aov:husk:name',Sdf.ValueTypeNames.String).Set('Cryptomatte')
        crypto.GetPrim().CreateAttribute('parameters:moonray:result',Sdf.ValueTypeNames.Token).Set('cryptomatte')
        for key in ('positions','normals','uv'):
            crypto.GetPrim().CreateAttribute('parameters:moonray:cryptomatte_output_'+key,Sdf.ValueTypeNames.Bool).Set(True)
        product.CreateOrderedVarsRel().SetTargets(paths+[crypto.GetPath()])
    settings.CreateProductsRel().SetTargets([product.GetPath()])
    if deep:
        deep_product=UsdRender.Product.Define(stage,'/Render/deep')
        deep_product.CreateProductTypeAttr('deep')
        deep_product.CreateProductNameAttr((out/(name+'.deep.exr')).as_posix())
        deep_product.CreateOrderedVarsRel().SetTargets(paths)
        settings.CreateProductsRel().SetTargets([product.GetPath(),deep_product.GetPath()])
    if name in ('instanced','nested'):
        UsdGeom.Xform.Define(stage,'/asset')
        editor=Usd.NamespaceEditor(stage)
        for src,dst in [('/material','/asset/material'),('/mesh','/asset/mesh')]:
            editor.MovePrimAtPath(src,dst)
            assert editor.ApplyEdits()
        asset=Sdf.Layer.CreateNew(str(out/(name+'_asset.usda')))
        Sdf.CopySpec(stage.GetRootLayer(),'/asset',asset,'/asset')
        asset.Save()
        stage.RemovePrim('/asset')
        if name=='nested':
            nested=Usd.Stage.CreateNew(str(out/'nested_wrapper.usda'))
            UsdGeom.Xform.Define(nested,'/asset')
            child=UsdGeom.Xform.Define(nested,'/asset/inner').GetPrim()
            child.GetReferences().AddReference(asset.realPath,'/asset')
            child.SetInstanceable(True)
            nested.GetRootLayer().Save()
            asset=nested.GetRootLayer()
        instance=UsdGeom.Xform.Define(stage,'/instance').GetPrim()
        instance.GetReferences().AddReference(asset.realPath,'/asset')
        instance.SetInstanceable(True)
    color.prepare_stage(stage, cache=str(out/'cache'),
        sampling=dict(texture_filter=lookup, texture_blur=0., max_anisotropy=8),output=output)
    stage.GetRootLayer().Save()
    return stage.GetRootLayer().realPath


def run(out, all_modes=False, only=''):
    pixels=np.empty((8,8,4),np.float32)
    pixels[:]=[.8,.2,.1,.37]
    fixture(out/'color.exr',pixels)
    yy,xx=np.mgrid[0:512,0:512]
    checker=np.repeat((((xx+yy)%2)*1.0)[...,None],3,axis=2).astype(np.float32)
    fixture(out/'checker.exr',checker)
    _,cfg=color.load_config()
    expected=np.asarray(cfg.getProcessor('sRGB - Texture','ACEScg').getDefaultCPUProcessor().applyRGB([.8,.2,.1]))
    checks,images,metadata={},{},{}
    cases=[('usd_vector',False,'vectorized',0,False,'rendering',True),('native_vector',True,'vectorized',0,False,'rendering',False)]
    if all_modes:
        cases += [('usd_scalar',False,'scalar',0,False,'rendering',False),('usd_xpu',False,'xpu',0,False,'rendering',False),
                  ('nearest',False,'vectorized',1,True,'rendering',False),('bilinear',False,'vectorized',2,True,'rendering',False),
                  ('rec709',False,'vectorized',0,False,color.space_name(cfg,'lin_rec709'),False),
                  ('instanced',False,'vectorized',0,False,'rendering',False),
                  ('nested',False,'vectorized',0,False,'rendering',False),
                  ('trilinear',False,'vectorized',3,True,'rendering',False)]
    if only:
        cases=[c for c in cases if c[0] in only.split(',')]
    for name,native,mode,lookup,is_checker,output,deep in cases:
        path=scene(out,name,native,mode,lookup,is_checker,output,deep)
        with (out/(name+'.log')).open('w') as log:
            env=dict(os.environ,HDMOONRAY_RDLA_OUTPUT=(out/(name+'.rdla')).as_posix())
            subprocess.run([str(Path(hou.getenv('HFS'))/'bin/husk.exe'),'--renderer','HdMoonrayRendererPlugin',
                '--settings','/Render/settings','--complexity','low','--disable-motionblur',path],
                stdout=log,stderr=subprocess.STDOUT,env=env,timeout=90,check=True)
        image,spec=read(out/(name+'.exr'))
        images[name]=image
        metadata[name]={str(p.name):str(p.value) for p in spec.extra_attribs if 'color' in p.name.lower() or 'chrom' in p.name.lower()}
        checks[name+'_finite']=bool(np.isfinite(image).all())
        if not is_checker:
            mean=np.mean(image[10:22,10:22,:3],axis=(0,1))
            reference=expected if output=='rendering' else np.asarray(cfg.getProcessor('ACEScg',output).getDefaultCPUProcessor().applyRGB(expected.tolist()))
            checks[name+'_ocio_match']=bool(np.max(np.abs(mean-reference))<.002)
            metadata[name]['mean']=mean.tolist()
        checks[name+'_no_texture_errors']='sample failure' not in (out/(name+'.log')).read_text(errors='replace')
        chrom = spec.getattribute('chromaticities')
        checks[name+'_primaries'] = isinstance(chrom, (tuple, list)) and len(chrom) == 8 and bool(np.max(np.abs(np.asarray(chrom)-(color.AP1 if output=='rendering' else color.REC709)))<1e-5)
        inp=oiio.ImageInput.open(str(out/(name+'.exr')))
        part=0
        normal=False
        crypto_metadata=False
        crypto_manifest={}
        crypto_ids=[]
        crypto_coverage=None
        while inp.seek_subimage(part,0):
            spec=inp.spec()
            if spec.get_string_attribute('name')=='normal':
                data=inp.read_image(oiio.FLOAT)
                normal=bool(np.max(np.abs(data[10:22,10:22,:3]-[0,0,1]))<1e-5)
            crypto_metadata |= any(a.name.startswith('cryptomatte/') and a.name.endswith('/manifest') for a in spec.extra_attribs)
            for a in spec.extra_attribs:
                if a.name.startswith('cryptomatte/') and a.name.endswith('/manifest'):
                    crypto_manifest.update(json.loads(a.value))
            if spec.get_string_attribute('name')=='Cryptomatte00':
                data=inp.read_image(oiio.FLOAT)
                checks['crypto_float32']=str(spec.format)=='float'
                crypto_coverage=data[...,1]+data[...,3]
                for channel in (0,2):
                    crypto_ids.extend(data[...,channel][data[...,channel+1]>0].view(np.uint32).tolist())
            part+=1
        inp.close()
        checks[name+'_raw_normal']=normal
        if deep:
            checks['crypto_metadata_preserved']=crypto_metadata and part>4
            expected_ids=set()
            for value in crypto_manifest.values():
                bits=int(value,16)
                if (bits>>23)&255 in (0,255):
                    bits^=1<<23
                expected_ids.add(bits)
            checks['crypto_ids_lossless']=bool(crypto_ids) and set(crypto_ids)<=expected_ids
            checks['crypto_coverage_preserved']=crypto_coverage is not None and bool(np.max(np.abs(crypto_coverage-image[...,3]))<1e-5)
        if deep:
            buf=oiio.ImageBuf(str(out/(name+'.deep.exr')))
            assert buf.read(),buf.geterror()
            checks['deep_is_deep']=buf.spec().deep
            checks['deep_primaries']=bool(np.max(np.abs(np.asarray(buf.spec().getattribute('chromaticities'))-color.AP1))<1e-5)
            flat=oiio.ImageBufAlgo.flatten(buf)
            names=list(flat.spec().channelnames)
            arr=flat.get_pixels(oiio.FLOAT)[10:22,10:22]
            checks['deep_color_match']=bool(np.max(np.abs(arr[:,:,[names.index(n) for n in ('R','G','B')]].mean(axis=(0,1))-expected))<.002)
        print(name+' rendered',flush=True)
    if 'nearest' in images and 'bilinear' in images:
        checks['filter_changes_image']=bool(np.mean(np.abs(images['nearest']-images['bilinear']))>.02)
    if 'trilinear' in images:
        checks['mip_minification']=bool(np.max(np.abs(images['trilinear'][10:22,10:22,:3]-.5))<.005)
    return {'passed':all(checks.values()),'checks':checks,'metadata':metadata,'expected':expected.tolist()}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--all-modes',action='store_true')
    parser.add_argument('--only',default='')
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    try:
        result=run(args.out.resolve(),args.all_modes,args.only)
    except Exception:
        result={'passed':False,'error':traceback.format_exc()}
    (args.out/'validation.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2),flush=True)
    raise SystemExit(0 if result['passed'] else 1)
