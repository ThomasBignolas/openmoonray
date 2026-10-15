// SPDX-License-Identifier: Apache-2.0
#include <hydramoonray/ValueConverter.h>
#include <scene_rdl2/scene/rdl2/SceneContext.h>

#include <iostream>
#include <limits>
#include <stdexcept>

static void require(bool condition, const char* message)
{
    if (!condition) throw std::runtime_error(message);
}

int main(int argc, char** argv)
{
    try {
        require(argc == 2, "Expected the upstream test DSO directory");
        scene_rdl2::rdl2::SceneContext context;
        context.setDsoPath(argv[1]);
        auto* object = context.createSceneObject("ExtensiveObject", "/conversion");
        const auto& sceneClass = object->getSceneClass();
        const auto* scalar = sceneClass.getAttribute("long");
        const auto* array = sceneClass.getAttribute("long_vector");
        object->beginUpdate();

        const int64_t high = std::numeric_limits<int64_t>::max();
        const int64_t low = std::numeric_limits<int64_t>::min();
        for (int64_t value : {high, low, int64_t(0)}) {
            hdMoonray::ValueConverter::setAttribute(object, scalar, pxr::VtValue(value));
            require(object->get<Long>("long") == value, "64-bit scalar was truncated");
        }
        hdMoonray::ValueConverter::setAttribute(object, scalar, pxr::VtValue(long(-123)));
        require(object->get<Long>("long") == -123, "Native long scalar conversion failed");

        pxr::VtArray<int64_t> values = {high, low, int64_t(4294967296), int64_t(-4294967297)};
        hdMoonray::ValueConverter::setAttribute(object, array, pxr::VtValue(values));
        require(object->get<LongVector>("long_vector") == LongVector(values.begin(), values.end()),
                "64-bit array was truncated or misread");
        pxr::VtArray<long> nativeValues = {-2, 0, 2147483647};
        hdMoonray::ValueConverter::setAttribute(object, array, pxr::VtValue(nativeValues));
        require(object->get<LongVector>("long_vector") == LongVector({-2, 0, 2147483647}),
                "Native long array was not widened correctly");
        hdMoonray::ValueConverter::setAttribute(object, array, pxr::VtValue(pxr::VtArray<int64_t>()));
        require(object->get<LongVector>("long_vector").empty(), "Empty 64-bit array was not cleared");
        hdMoonray::ValueConverter::setBinding(object, scalar, nullptr);
        require(object->get<Long>("long") == 1, "Binding unit has the wrong integer type");
        hdMoonray::ValueConverter::setAttribute(object, sceneClass.getAttribute("bool"),
                                               pxr::VtValue(int64_t(1)));
        require(object->get<Bool>("bool"), "64-bit boolean conversion failed");
        hdMoonray::ValueConverter::setAttribute(object, sceneClass.getAttribute("int"),
                                               pxr::VtValue(int64_t(-123456)));
        require(object->get<Int>("int") == -123456, "64-bit integer conversion failed");
        hdMoonray::ValueConverter::setAttribute(object, sceneClass.getAttribute("float"),
                                               pxr::VtValue(int64_t(1) << 40));
        require(object->get<Float>("float") == 1099511627776.0f, "64-bit float conversion failed");

        const auto* booleans = sceneClass.getAttribute("bool_vector");
        hdMoonray::ValueConverter::setAttribute(object, booleans,
            pxr::VtValue(pxr::VtArray<int>{0, 1, -2, 0}));
        require(object->get<BoolVector>("bool_vector") == BoolVector({false, true, true, false}),
                "Sdr integer switches were not converted to booleans");
        hdMoonray::ValueConverter::setAttribute(object, booleans, pxr::VtValue(pxr::VtArray<int>()));
        require(object->get<BoolVector>("bool_vector").empty(), "Empty switch array was not cleared");
        hdMoonray::ValueConverter::setAttribute(object, booleans,
            pxr::VtValue(pxr::VtArray<bool>{true, false}));
        require(object->get<BoolVector>("bool_vector") == BoolVector({true, false}),
                "Native USD boolean array conversion failed");
        hdMoonray::ValueConverter::setAttribute(object, booleans, pxr::VtValue(pxr::VtArray<bool>()));
        require(object->get<BoolVector>("bool_vector").empty(), "Empty boolean array was not cleared");

        const pxr::GfMatrix4d matrix4(1, 2, 3, 4, 5, 6, 7, 8,
                                    9, 10, 11, 12, 13, 14, 15, 16);
        const Mat4f expected4(1, 2, 3, 4, 5, 6, 7, 8,
                             9, 10, 11, 12, 13, 14, 15, 16);
        hdMoonray::ValueConverter::setAttribute(object, sceneClass.getAttribute("mat4f"),
                                                pxr::VtValue(matrix4 * 0.5));
        require(object->get<Mat4f>("mat4f") == expected4 * 0.5f,
                "USD matrix4d was not converted to RDL mat4f");
        const auto* matrices4 = sceneClass.getAttribute("mat4f_vector");
        hdMoonray::ValueConverter::setAttribute(object, matrices4,
            pxr::VtValue(pxr::VtArray<pxr::GfMatrix4d>{matrix4, matrix4 * -0.5}));
        require(object->get<Mat4fVector>("mat4f_vector") == Mat4fVector({expected4, expected4 * -0.5f}),
                "USD matrix4d array lost values or element boundaries");
        hdMoonray::ValueConverter::setAttribute(object, matrices4,
                                                pxr::VtValue(pxr::VtArray<pxr::GfMatrix4d>()));
        require(object->get<Mat4fVector>("mat4f_vector").empty(), "Empty matrix4d array was not cleared");
        object->endUpdate();

        auto* userData = context.createSceneObject("UserData", "/matrices3");
        const auto* matrices3 = userData->getSceneClass().getAttribute("mat3f_values_0");
        const pxr::GfMatrix3d matrix3(1, 2, 3, 4, 5, 6, 7, 8, 9);
        const Mat3f expected3(1, 2, 3, 4, 5, 6, 7, 8, 9);
        userData->beginUpdate();
        hdMoonray::ValueConverter::setAttribute(userData, matrices3,
            pxr::VtValue(pxr::VtArray<pxr::GfMatrix3d>{matrix3, matrix3 * -0.5}));
        require(userData->get<std::vector<Mat3f>>("mat3f_values_0") ==
                std::vector<Mat3f>({expected3, expected3 * -0.5f}),
                "USD matrix3d array lost values or element boundaries");
        hdMoonray::ValueConverter::setAttribute(userData, matrices3,
                                                pxr::VtValue(pxr::VtArray<pxr::GfMatrix3d>()));
        require(userData->get<std::vector<Mat3f>>("mat3f_values_0").empty(),
                "Empty matrix3d array was not cleared");
        userData->endUpdate();
        std::cout << "Hydra integer, boolean and matrix scalar/array conversions passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
