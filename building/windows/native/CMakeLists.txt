# SPDX-License-Identifier: Apache-2.0
cmake_minimum_required(VERSION 3.23.1)
project(OpenMoonRayWindows LANGUAGES C CXX)
get_filename_component(OMR_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../.." ABSOLUTE)
list(APPEND CMAKE_MODULE_PATH "${OMR_ROOT}/cmake_modules/cmake")
include(OMR_Platform)
include(CTest)

# The native CPU renderer can be built independently of the distributed services
# and DCC integrations. Hydra is added after the renderer and USD are available.
set(BUILD_QT_APPS OFF CACHE BOOL "Build Qt applications")
set(MOONRAY_USE_OPTIX OFF CACHE BOOL "Build OptiX support")
set(MOONRAY_USE_METAL OFF CACHE BOOL "Build Metal support")
find_package(TBB REQUIRED)
add_subdirectory("${OMR_ROOT}/moonray/scene_rdl2" scene_rdl2)
add_subdirectory("${OMR_ROOT}/moonray/mcrt_denoise" mcrt_denoise)
add_subdirectory("${OMR_ROOT}/moonray/moonray" moonray)
add_subdirectory("${OMR_ROOT}/moonray/moonshine" moonshine)
add_subdirectory("${OMR_ROOT}/moonray/moonshine_usd" moonshine_usd)

# Build the existing direct RenderContext backend while Arras is being ported.
# Keep the upstream distributed plugin available as an explicit separate option.
set(HDMOONRAY_BUILD_ARRAS_PLUGIN OFF CACHE BOOL "Build the Arras distributed-rendering plugin")
if(HDMOONRAY_BUILD_ARRAS_PLUGIN)
    find_package(ArrasCore REQUIRED)
    add_subdirectory("${OMR_ROOT}/moonray/moonray_arras/mcrt_messages" mcrt_messages)
    add_subdirectory("${OMR_ROOT}/moonray/moonray_arras/mcrt_dataio" mcrt_dataio)
    add_subdirectory("${OMR_ROOT}/moonray/moonray_arras/mcrt_computation" mcrt_computation)
endif()
add_subdirectory("${OMR_ROOT}/moonray/hydra/hdMoonray" hdMoonray)
add_subdirectory("${OMR_ROOT}/moonray/hydra/moonray_sdr_plugins" moonray_sdr_plugins)

if(BUILD_TESTING)
    add_executable(test_oidn_failure EXCLUDE_FROM_ALL "${CMAKE_CURRENT_SOURCE_DIR}/../tests/test_oidn_failure.cc")
    target_link_libraries(test_oidn_failure PRIVATE McrtDenoise::denoiser SceneRdl2::render_logging)
    add_test(NAME windows_oidn_failure COMMAND test_oidn_failure)
    set_tests_properties(windows_oidn_failure PROPERTIES LABELS "unit;windows;denoise" TIMEOUT 60)

    add_executable(test_texture_file_limit "${CMAKE_CURRENT_SOURCE_DIR}/../tests/test_texture_file_limit.cc")
    target_link_libraries(test_texture_file_limit PRIVATE Moonray::texturing_sampler)
    add_test(NAME windows_texture_file_limit COMMAND test_texture_file_limit "${CMAKE_CURRENT_BINARY_DIR}/texture-file-limit")
    set_tests_properties(windows_texture_file_limit PROPERTIES LABELS "unit;windows;texture" TIMEOUT 60)

    add_executable(test_light_sampling_hash "${CMAKE_CURRENT_SOURCE_DIR}/../tests/test_light_sampling_hash.cc")
    target_include_directories(test_light_sampling_hash PRIVATE "${OMR_ROOT}/moonray/moonray/lib/rendering/pbr")
    add_test(NAME windows_light_sampling_hash COMMAND test_light_sampling_hash)
    set_tests_properties(windows_light_sampling_hash PROPERTIES LABELS "unit;windows" TIMEOUT 10)

    add_executable(test_shm_fb_dump "${CMAKE_CURRENT_SOURCE_DIR}/../tests/test_shm_fb_dump.cc")
    target_link_libraries(test_shm_fb_dump PRIVATE SceneRdl2::common_grid_util)
    target_compile_definitions(test_shm_fb_dump PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
    add_dependencies(test_shm_fb_dump shmFbDump)
    add_test(NAME windows_shm_fb_dump COMMAND test_shm_fb_dump "$<TARGET_FILE:shmFbDump>"
        "${CMAKE_CURRENT_BINARY_DIR}/shm fb dump.ppm")
    set_tests_properties(windows_shm_fb_dump PROPERTIES LABELS "unit;windows" TIMEOUT 70)

    add_executable(test_hydra_values "${CMAKE_CURRENT_SOURCE_DIR}/../tests/test_hydra_values.cc")
    target_link_libraries(test_hydra_values PRIVATE HdMoonray::hydramoonray)
    add_dependencies(test_hydra_values ExtensiveObject)
    add_test(NAME windows_hydra_values
        COMMAND test_hydra_values "$<TARGET_FILE_DIR:ExtensiveObject>")
    set_tests_properties(windows_hydra_values PROPERTIES LABELS "unit;windows" TIMEOUT 30)

    add_executable(test_hydra_lifecycle "${CMAKE_CURRENT_SOURCE_DIR}/../tests/test_hydra_lifecycle.cc")
    target_link_libraries(test_hydra_lifecycle PRIVATE HdMoonray::hydramoonray)
    add_dependencies(test_hydra_lifecycle hd_moonray_debug)
    add_test(NAME windows_hydra_lifecycle COMMAND test_hydra_lifecycle)
    set_tests_properties(windows_hydra_lifecycle PROPERTIES LABELS "unit;windows" TIMEOUT 60)

    if(HDMOONRAY_BUILD_ARRAS_PLUGIN)
        add_dependencies(test_hydra_lifecycle hd_moonray)
        add_test(NAME windows_hydra_arras_lifecycle COMMAND test_hydra_lifecycle HdMoonrayRendererPlugin)
        set_tests_properties(windows_hydra_arras_lifecycle PROPERTIES LABELS "unit;windows;arras" TIMEOUT 60)
        add_executable(test_mcrt_runtime "${CMAKE_CURRENT_SOURCE_DIR}/../tests/test_mcrt_runtime.cc")
        target_link_libraries(test_mcrt_runtime PRIVATE McrtDataio::share_util
            McrtMessages::mcrt_messages ArrasCore::message_impl)
        foreach(mode sockets telemetry messages)
            add_test(NAME windows_mcrt_${mode} COMMAND test_mcrt_runtime ${mode})
            set_tests_properties(windows_mcrt_${mode} PROPERTIES LABELS "unit;windows;arras" TIMEOUT 30)
        endforeach()
    endif()
endif()

option(BUILD_RATS "Configure the upstream render acceptance tests" ON)
if(BUILD_TESTING AND BUILD_RATS)
    add_subdirectory("${OMR_ROOT}/rats" rats)
endif()
