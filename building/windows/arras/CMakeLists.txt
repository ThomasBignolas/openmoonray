# SPDX-License-Identifier: Apache-2.0
cmake_minimum_required(VERSION 3.23.1)
project(OpenMoonRayWindowsArras LANGUAGES C CXX)
get_filename_component(OMR_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../.." ABSOLUTE)
list(APPEND CMAKE_MODULE_PATH "${OMR_ROOT}/cmake_modules/cmake")
include(OMR_Platform)
include(CTest)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
add_subdirectory("${OMR_ROOT}/arras/arras4_core" arras4_core)
option(OMR_BUILD_ARRAS_NODE "Build the distributed Arras node and router" OFF)
if(OMR_BUILD_ARRAS_NODE)
    add_subdirectory("${OMR_ROOT}/arras/distributed/arras4_node" arras4_node)
endif()

if(BUILD_TESTING)
    add_executable(test_arras_process "../tests/test_arras_process.cc")
    target_compile_features(test_arras_process PRIVATE cxx_std_17)
    target_link_libraries(test_arras_process PRIVATE ArrasCore::execute)
    foreach(mode arguments capture tree termination lifecycle manager_shutdown)
        add_test(NAME windows_arras_process_${mode} COMMAND test_arras_process ${mode})
        set_tests_properties(windows_arras_process_${mode} PROPERTIES TIMEOUT 30 LABELS "unit;windows;arras;process"
            ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${VCPKG_INSTALLED_DIR}/${VCPKG_TARGET_TRIPLET}/bin")
    endforeach()
    add_executable(test_arras_runtime "${CMAKE_CURRENT_SOURCE_DIR}/../tests/test_arras_runtime.cc")
    target_link_libraries(test_arras_runtime PRIVATE ArrasCore::network ArrasCore::http
        ArrasCore::httpserver ArrasCore::sdk)
    foreach(mode tcp ipc http sdk tcp_cancel ipc_cancel)
        add_test(NAME windows_arras_${mode} COMMAND test_arras_runtime ${mode})
        set_tests_properties(windows_arras_${mode} PROPERTIES TIMEOUT 30 LABELS "unit;windows;arras"
            ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${VCPKG_INSTALLED_DIR}/${VCPKG_TARGET_TRIPLET}/bin")
    endforeach()
    add_library(arras_worker_computation SHARED "../tests/arras_worker_computation.cc")
    target_compile_features(arras_worker_computation PRIVATE cxx_std_17)
    target_link_libraries(arras_worker_computation PRIVATE ArrasCore::computation_api ArrasCore::core_messages)
    add_executable(test_arras_local_session "../tests/test_arras_local_session.cc")
    target_compile_features(test_arras_local_session PRIVATE cxx_std_17)
    target_link_libraries(test_arras_local_session PRIVATE ArrasCore::sdk)
    foreach(mode normal repeated disconnect missing invalid unicode async concurrent)
        add_test(NAME windows_arras_local_${mode} COMMAND test_arras_local_session
            "$<TARGET_FILE:arras_worker_computation>" ${mode})
        set_tests_properties(windows_arras_local_${mode} PROPERTIES TIMEOUT 30 LABELS "unit;windows;arras;local"
            ENVIRONMENT "TMP=${OMR_ROOT}/build/at;TEMP=${OMR_ROOT}/build/at;HOME=${OMR_ROOT}/build/arras-test-home;DWA_CONFIG_SERVICE="
            ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${VCPKG_INSTALLED_DIR}/${VCPKG_TARGET_TRIPLET}/bin;PATH=path_list_prepend:$<TARGET_FILE_DIR:execComp>")
    endforeach()
    add_executable(test_arras_worker "../tests/test_arras_worker.cc")
    target_compile_features(test_arras_worker PRIVATE cxx_std_17)
    target_link_libraries(test_arras_worker PRIVATE ArrasCore::shared_impl ArrasCore::chunking)
    foreach(mode normal chunking missing no_factory invalid start_exception disconnect disconnect_before_go stop_before_go)
        add_test(NAME windows_arras_worker_${mode} COMMAND test_arras_worker
            "$<TARGET_FILE:execComp>" "$<TARGET_FILE:arras_worker_computation>" ${mode})
        set_tests_properties(windows_arras_worker_${mode} PROPERTIES TIMEOUT 30 LABELS "unit;windows;arras;worker"
            ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${VCPKG_INSTALLED_DIR}/${VCPKG_TARGET_TRIPLET}/bin")
    endforeach()
endif()
