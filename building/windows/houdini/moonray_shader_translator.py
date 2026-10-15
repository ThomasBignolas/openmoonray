"""Translate native MoonRay ramps to per-knot integer interpolation arrays.

Loaded by Houdini's shader translator registry, scoped to MoonRay VOPs.
The upstream HDAs use Hermite for MoonRay's smooth interpolation mode.
"""
import hou
from pxr import Sdf
from husd import shaderutils
from husd.shadertranslator import RampParmTranslator, ShaderTranslator, ShaderTranslatorHelper


class MoonrayRampTranslator(RampParmTranslator):
    def createBasisAttrib(self, usd_shader):
        return shaderutils.createUsdInputAttrib(
            usd_shader, self.basisAttribName(), Sdf.ValueTypeNames.IntArray)

    def rampBasisValue(self, ramp_val):
        mapping = {hou.rampBasis.Constant: 0, hou.rampBasis.Linear: 1,
                   hou.rampBasis.Hermite: 4, hou.rampBasis.CatmullRom: 5,
                   hou.rampBasis.MonotoneCubic: 6}
        result = []
        for basis in ramp_val.basis():
            if basis not in mapping:
                raise hou.OperationFailed('MoonRay ramps support Constant, Linear, Hermite (Smooth), Catmull-Rom and Monotone Cubic.')
            result.append(mapping[basis])
        return result


class MoonrayShaderHelper(ShaderTranslatorHelper):
    def rampParameterTranslator(self, parm_tuple):
        return MoonrayRampTranslator(parm_tuple)


class MoonrayShaderTranslator(ShaderTranslator):
    def matchesRenderMask(self, render_mask):
        return 'moonray' in render_mask.lower().split()

    def shaderTranslatorHelper(self, translator_id, usd_stage, usd_material_path, usd_time_code):
        return MoonrayShaderHelper(translator_id, usd_stage, usd_material_path, usd_time_code)


_translator = MoonrayShaderTranslator()


def usdShaderTranslator():
    return _translator
