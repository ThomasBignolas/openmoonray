# SPDX-License-Identifier: Apache-2.0
cmake_minimum_required(VERSION 3.23.1)
project(HdMoonray LANGUAGES C CXX)

# Houdini embeds its own USD ABI. Keep this build separate from standalone USD.
get_filename_component(OMR_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../.." ABSOLUTE)
set(HOUDINI_ROOT "C:/Houdini21" CACHE PATH "Houdini installation")
set(MOONRAY_INSTALL "${OMR_ROOT}/build/windows/install-fp-contract" CACHE PATH "Native MoonRay SDK")
set(MOONRAY_DEPS "${OMR_ROOT}/build/deps/x64-windows" CACHE PATH "MoonRay dependencies")
set(ARRAS_INSTALL "${OMR_ROOT}/build/deps-arras" CACHE PATH "Arras SDK")
set(HD_SOURCE "${OMR_ROOT}/moonray/hydra/hdMoonray")
set(PACKAGE_NAME hdMoonray)
list(APPEND CMAKE_MODULE_PATH "${OMR_ROOT}/cmake_modules/cmake" "${HD_SOURCE}/cmake")
include(OMR_Platform)
include(OMR_UsdPlugin)
include(OMR_Headers)
include(SConscriptStub)
include(HdMoonrayCompileDefinitions)
include(HdMoonrayCompileFeatures)
include(HdMoonrayCompileOptions)
include(HdMoonrayLinkOptions)

set(CMAKE_BUILD_TYPE Release CACHE STRING "Build configuration")
add_compile_options(/EHsc /bigobj /Zc:__cplusplus /Zc:externC-)
add_compile_definitions(NOMINMAX WIN32_LEAN_AND_MEAN _USE_MATH_DEFINES
    BOOST_ALL_NO_LIB BOOST_NO_CXX98_FUNCTION_BASE _CRT_SECURE_NO_WARNINGS)
include_directories("${HOUDINI_ROOT}/toolkit/include"
    "${HOUDINI_ROOT}/toolkit/include/python3.11"
    "${MOONRAY_INSTALL}/include" "${ARRAS_INSTALL}/include"
    "${MOONRAY_DEPS}/include" "${HD_SOURCE}/lib")
set(PROJECT_SOURCE_INCLUDE_DIR "${HD_SOURCE}/lib")

function(import_moonray namespace component prefix)
    if(EXISTS "${prefix}/lib/${component}.lib")
        add_library(${namespace}::${component} SHARED IMPORTED GLOBAL)
        set_target_properties(${namespace}::${component} PROPERTIES
            IMPORTED_IMPLIB "${prefix}/lib/${component}.lib"
            IMPORTED_LOCATION "${prefix}/bin/${component}.dll")
    else()
        message(FATAL_ERROR "Missing native MoonRay library: ${prefix}/lib/${component}.lib")
    endif()
endfunction()
foreach(component common_fb_util common_math common_platform render_logging render_util)
    import_moonray(SceneRdl2 ${component} "${MOONRAY_INSTALL}")
endforeach()
add_library(SceneRdl2::common_except INTERFACE IMPORTED)
foreach(component arras4_log client_api sdk core_messages message_api)
    import_moonray(ArrasCore ${component} "${ARRAS_INSTALL}")
endforeach()
import_moonray(McrtDataio client_receiver "${MOONRAY_INSTALL}")
import_moonray(McrtMessages mcrt_messages "${MOONRAY_INSTALL}")

# USD import libraries do not encode their transitive link dependencies.
file(GLOB houdini_usd_libs "${HOUDINI_ROOT}/custom/houdini/dsolib/libpxr_*.lib")
if(NOT houdini_usd_libs)
    message(FATAL_ERROR "Houdini USD SDK import libraries were not found")
endif()
add_library(houdini_usd INTERFACE)
target_link_libraries(houdini_usd INTERFACE ${houdini_usd_libs}
    "${HOUDINI_ROOT}/custom/houdini/dsolib/tbb12.lib"
    "${HOUDINI_ROOT}/python311/libs/python311.lib")
foreach(component hd hdsi usdImaging ar ndr sdr)
    add_library(${component} INTERFACE IMPORTED)
    target_link_libraries(${component} INTERFACE houdini_usd)
endforeach()
add_library(TBB::tbb INTERFACE IMPORTED)
target_link_libraries(TBB::tbb INTERFACE "${HOUDINI_ROOT}/custom/houdini/dsolib/tbb12.lib")
add_library(Python::Module INTERFACE IMPORTED)
target_link_libraries(Python::Module INTERFACE "${HOUDINI_ROOT}/python311/libs/python311.lib")
add_library(Boost::headers INTERFACE IMPORTED)

# SceneContext embeds TBB containers. Rebuild it for Houdini's oneTBB ABI;
# exchanging oneTBB objects with the standalone TBB 2020 DLL corrupts memory.
# Rendering itself runs in the existing standalone Arras worker process.
set(RDL_SOURCE "${OMR_ROOT}/moonray/scene_rdl2/lib")
omr_link_directory("${RDL_SOURCE}" "${CMAKE_CURRENT_BINARY_DIR}/source_include/scene_rdl2")
include_directories(BEFORE "${CMAKE_CURRENT_BINARY_DIR}/source_include")
set(RDL_BUILD_SOURCE "${CMAKE_CURRENT_BINARY_DIR}/source_include/scene_rdl2/scene/rdl2")
file(GLOB rdl_sources CONFIGURE_DEPENDS "${RDL_BUILD_SOURCE}/*.cc")
add_custom_command(OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/rdlalib.cc"
    COMMAND "${MOONRAY_DEPS}/tools/lua/luac.exe" -o "${CMAKE_CURRENT_BINARY_DIR}/rdlalib.luac"
        "${RDL_BUILD_SOURCE}/rdlalib/constructors.lua" "${RDL_BUILD_SOURCE}/rdlalib/transforms.lua"
    COMMAND "${MOONRAY_DEPS}/tools/lua/lua.exe" "${RDL_BUILD_SOURCE}/rdlalib/bin2cc.lua"
        "${CMAKE_CURRENT_BINARY_DIR}/rdlalib.luac" "${CMAKE_CURRENT_BINARY_DIR}/rdlalib.cc"
    DEPENDS "${RDL_BUILD_SOURCE}/rdlalib/constructors.lua" "${RDL_BUILD_SOURCE}/rdlalib/transforms.lua"
    VERBATIM)
add_library(scene_rdl2_tmp SHARED ${rdl_sources} "${CMAKE_CURRENT_BINARY_DIR}/rdlalib.cc")
set_target_properties(scene_rdl2_tmp PROPERTIES OUTPUT_NAME scene_rdl2)
add_library(SceneRdl2::scene_rdl2 ALIAS scene_rdl2_tmp)
target_include_directories(scene_rdl2_tmp PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
target_compile_definitions(scene_rdl2_tmp PRIVATE ${GLOBAL_COMPILE_DEFINITIONS} ${GLOBAL_CPP_FLAGS})
target_compile_options(scene_rdl2_tmp PRIVATE /arch:AVX2 /fp:contract)
target_link_libraries(scene_rdl2_tmp PRIVATE SceneRdl2::common_fb_util SceneRdl2::common_math
    SceneRdl2::common_platform SceneRdl2::render_logging SceneRdl2::render_util TBB::tbb
    "${MOONRAY_DEPS}/lib/boost_filesystem-vc140-mt.lib"
    "${MOONRAY_DEPS}/lib/boost_regex-vc140-mt.lib"
    "${MOONRAY_DEPS}/lib/boost_thread-vc140-mt.lib"
    "${MOONRAY_DEPS}/lib/lua.lib")
install(TARGETS scene_rdl2_tmp RUNTIME DESTINATION bin ARCHIVE DESTINATION lib)

add_subdirectory("${HD_SOURCE}/lib/hydramoonray" hydramoonray)
target_compile_definitions(hydramoonray PRIVATE HDMOONRAY_HOUDINI=1)
target_sources(hydramoonray PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/ColorOutput.cc")
set_source_files_properties("${CMAKE_CURRENT_SOURCE_DIR}/ColorOutput.cc" TARGET_DIRECTORY hydramoonray
    PROPERTIES COMPILE_DEFINITIONS "WIN32;SIZEOF_VOID_P=8;AMD64")
target_link_libraries(hydramoonray PRIVATE "${HOUDINI_ROOT}/custom/houdini/dsolib/libIMG.lib"
    "${HOUDINI_ROOT}/custom/houdini/dsolib/libUT.lib")
add_subdirectory("${HD_SOURCE}/plugin/hd_moonray" hd_moonray)
target_link_libraries(hd_moonray PRIVATE "${MOONRAY_DEPS}/lib/jsoncpp.lib")
add_subdirectory("${HD_SOURCE}/plugin/adapters" adapters)
foreach(component moonrayShaderDiscovery moonrayShaderParser)
    add_subdirectory("${OMR_ROOT}/moonray/hydra/moonray_sdr_plugins/${component}" ${component})
endforeach()
install(FILES "${HD_SOURCE}/plugin/plugInfo.json" DESTINATION plugin/pxr)
add_subdirectory("${HD_SOURCE}/plugin/houdini" houdini)

# Explicit integration-test target; run with a staged host/worker environment
# and a tiny exported RDLA scene under run_bounded.py.
add_executable(test_arras_renderer_lifecycle EXCLUDE_FROM_ALL test_arras_renderer_lifecycle.cc)
target_compile_features(test_arras_renderer_lifecycle PRIVATE cxx_std_17)
target_include_directories(test_arras_renderer_lifecycle PRIVATE "${HD_SOURCE}/plugin/hd_moonray")
target_link_libraries(test_arras_renderer_lifecycle PRIVATE hd_moonray Ws2_32 "${MOONRAY_DEPS}/lib/jsoncpp.lib")
