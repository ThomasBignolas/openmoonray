"""Create a short USD sequence to exercise updates in a persistent delegate."""
from pathlib import Path
import sys
from pxr import Gf, Sdf, Usd, UsdGeom, UsdRender, Vt

directory = Path(sys.argv[1]).resolve()
stage = Usd.Stage.Open(str(directory / 'moonray_demo.usda'))
stage.SetStartTimeCode(1)
stage.SetEndTimeCode(2)
prim = stage.GetPrimAtPath('/copper')
transform = prim.GetAttribute('xformOp:transform:xform')
transform.Set(Gf.Matrix4d(1), 1)
transform.Set(Gf.Matrix4d(1).SetTranslate(Gf.Vec3d(0, 0.65, 0)), 2)
settings = stage.GetPrimAtPath('/Render/rendersettings')
settings.GetAttribute('resolution').Set(Gf.Vec2i(256, 144))
settings.GetAttribute('moonray:sceneVariable:pixel_samples').Set(4)
product = UsdRender.Product(stage.GetPrimAtPath('/Render/Products/beauty'))
var = UsdRender.Var.Define(stage, '/Render/Vars/all_light')
var.CreateSourceNameAttr('C.*')
var.CreateSourceTypeAttr('lpe')
var.CreateDataTypeAttr('color3f')
var.GetPrim().CreateAttribute('driver:parameters:aov:husk:name', Sdf.ValueTypeNames.String).Set('all_light')
product.GetOrderedVarsRel().AddTarget(var.GetPath())
stage.Export(str(directory / 'animation-test.usda'))
print('Wrote animation-test.usda', flush=True)
