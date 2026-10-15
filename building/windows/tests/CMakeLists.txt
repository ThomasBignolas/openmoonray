cmake_minimum_required(VERSION 3.23.1)
project(WindowsPortTests LANGUAGES CXX)
include(CTest)
get_filename_component(OMR_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../.." ABSOLUTE)
list(APPEND CMAKE_MODULE_PATH "${OMR_ROOT}/cmake_modules/cmake")
include(OMR_Platform)
include(OMR_Headers)

add_library(loader_dependency SHARED loader_dependency.cc)
add_library(loader_fixture SHARED loader_fixture.cc)
target_include_directories(loader_fixture PRIVATE "${OMR_ROOT}/moonray/scene_rdl2/lib")
set_target_properties(loader_fixture PROPERTIES WINDOWS_EXPORT_ALL_SYMBOLS OFF)
target_link_libraries(loader_fixture PRIVATE loader_dependency)
# Exercise dependent DLL lookup in a directory absent from PATH.
set_target_properties(loader_dependency loader_fixture PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/plugins with spaces"
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/plugins with spaces")

add_executable(test_dynamic_library test_dynamic_library.cc)
target_compile_features(test_dynamic_library PRIVATE cxx_std_17)
target_include_directories(test_dynamic_library PRIVATE "${OMR_ROOT}/moonray/scene_rdl2/lib")
target_link_libraries(test_dynamic_library PRIVATE ${CMAKE_DL_LIBS})
add_dependencies(test_dynamic_library loader_fixture)
add_test(NAME dynamic_library COMMAND test_dynamic_library "$<TARGET_FILE:loader_fixture>")

# Check header links without requiring source checkout symlink support.
file(MAKE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/headers source")
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/headers source/value.h" "constexpr int header_value = 42;\n")
omr_link_directory("${CMAKE_CURRENT_BINARY_DIR}/headers source"
    "${CMAKE_CURRENT_BINARY_DIR}/headers include/fixture")
omr_link_directory("${CMAKE_CURRENT_BINARY_DIR}/headers source"
    "${CMAKE_CURRENT_BINARY_DIR}/headers include/fixture")
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/test_headers.cc"
    "#include <fixture/value.h>\nint main() { return header_value == 42 ? 0 : 1; }\n")
add_executable(test_headers "${CMAKE_CURRENT_BINARY_DIR}/test_headers.cc")
target_include_directories(test_headers PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/headers include")
add_test(NAME header_directory_link COMMAND test_headers)

if(WIN32)
    add_executable(test_checkpoint_file test_checkpoint_file.cc)
    target_include_directories(test_checkpoint_file PRIVATE "${OMR_ROOT}/moonray/moonray/lib")
    target_compile_features(test_checkpoint_file PRIVATE cxx_std_17)
    target_compile_definitions(test_checkpoint_file PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
    add_test(NAME checkpoint_file COMMAND test_checkpoint_file)
    set_tests_properties(checkpoint_file PROPERTIES TIMEOUT 20)
    add_executable(test_renderer_socket test_renderer_socket.cc
        "${OMR_ROOT}/moonray/moonray/lib/rendering/rndr/statistics/SocketStream.cc")
    target_include_directories(test_renderer_socket PRIVATE "${OMR_ROOT}/moonray/moonray/lib")
    target_compile_definitions(test_renderer_socket PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
    target_link_libraries(test_renderer_socket PRIVATE ws2_32)
    add_test(NAME renderer_socket COMMAND test_renderer_socket)
    set_tests_properties(renderer_socket PROPERTIES TIMEOUT 15)
    add_executable(test_change_watcher test_change_watcher.cc
        "${OMR_ROOT}/moonray/moonray/lib/application/windows/ChangeWatcherImpl.cc")
    target_include_directories(test_change_watcher PRIVATE "${OMR_ROOT}/moonray/moonray/lib")
    target_compile_features(test_change_watcher PRIVATE cxx_std_17)
    target_compile_definitions(test_change_watcher PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
    add_test(NAME file_change_watcher COMMAND test_change_watcher)
    set_tests_properties(file_change_watcher PROPERTIES TIMEOUT 15)
    add_executable(test_shared_memory test_shared_memory.cc
        "${OMR_ROOT}/moonray/scene_rdl2/lib/common/grid_util/WindowsSharedMemory.cc")
    target_include_directories(test_shared_memory PRIVATE "${OMR_ROOT}/moonray/scene_rdl2/lib/common/grid_util")
    target_compile_definitions(test_shared_memory PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
    target_link_libraries(test_shared_memory PRIVATE advapi32 shell32 ole32 bcrypt)
    add_test(NAME windows_shared_memory COMMAND test_shared_memory)
    set_tests_properties(windows_shared_memory PROPERTIES TIMEOUT 30)
    omr_link_directory("${OMR_ROOT}/moonray/scene_rdl2/lib"
        "${CMAKE_CURRENT_BINARY_DIR}/source_include/scene_rdl2")
    add_executable(test_files test_files.cc
        "${OMR_ROOT}/moonray/scene_rdl2/lib/render/util/Files.cc")
    target_include_directories(test_files PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/source_include")
    add_test(NAME windows_files COMMAND test_files "${CMAKE_CURRENT_BINARY_DIR}/file tests")
    add_executable(test_atomic128 test_atomic128.cc)
    target_include_directories(test_atomic128 PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/source_include")
    add_test(NAME atomic128 COMMAND test_atomic128)
    if(EXISTS "${OMR_ROOT}/build/deps/x64-windows/include/log4cplus/logger.h")
    add_executable(test_runtime_utilities test_runtime_utilities.cc
        "${OMR_ROOT}/moonray/scene_rdl2/lib/common/grid_util/Process.cc"
        "${OMR_ROOT}/moonray/scene_rdl2/lib/common/grid_util/UserUtil.cc")
    target_include_directories(test_runtime_utilities PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/source_include"
        "${OMR_ROOT}/build/deps/x64-windows/include" "${OMR_ROOT}/build/tools/tbb/include")
    target_compile_definitions(test_runtime_utilities PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN
        __TBB_NO_IMPLICIT_LINKAGE=1)
    target_compile_options(test_runtime_utilities PRIVATE /arch:AVX2)
    target_link_libraries(test_runtime_utilities PRIVATE advapi32)
    add_test(NAME runtime_utilities COMMAND test_runtime_utilities)
    endif()

    if(EXISTS "${OMR_ROOT}/build/deps/x64-windows/include/log4cplus/logger.h")
        add_executable(test_serialization test_serialization.cc)
        target_include_directories(test_serialization PRIVATE
            "${CMAKE_CURRENT_BINARY_DIR}/source_include"
            "${OMR_ROOT}/build/deps/x64-windows/include"
            "${OMR_ROOT}/build/tools/tbb/include")
        target_compile_definitions(test_serialization PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN
            _USE_MATH_DEFINES __TBB_NO_IMPLICIT_LINKAGE=1)
        target_compile_options(test_serialization PRIVATE /arch:AVX2)
        add_test(NAME serialization_wire_format COMMAND test_serialization)
        add_executable(test_renderer_atomics test_renderer_atomics.cc)
        target_include_directories(test_renderer_atomics PRIVATE
            "${CMAKE_CURRENT_BINARY_DIR}/source_include"
            "${OMR_ROOT}/moonray/moonray/lib"
            "${OMR_ROOT}/build/deps/x64-windows/include"
            "${OMR_ROOT}/build/tools/tbb/include")
        target_compile_definitions(test_renderer_atomics PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN
            _USE_MATH_DEFINES __TBB_NO_IMPLICIT_LINKAGE=1)
        target_compile_options(test_renderer_atomics PRIVATE /arch:AVX2)
        add_test(NAME renderer_atomics COMMAND test_renderer_atomics)
        if(EXISTS "${OMR_ROOT}/build/windows/native/moonray/lib/common/mcrt_util/common_mcrt_util.lib")
            add_executable(test_renderer_platform test_renderer_platform.cc)
            target_include_directories(test_renderer_platform PRIVATE
                "${CMAKE_CURRENT_BINARY_DIR}/source_include" "${OMR_ROOT}/moonray/moonray/lib"
                "${OMR_ROOT}/build/deps/x64-windows/include" "${OMR_ROOT}/build/tools/tbb/include")
            target_compile_definitions(test_renderer_platform PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN
                _USE_MATH_DEFINES __TBB_NO_IMPLICIT_LINKAGE=1)
            target_compile_options(test_renderer_platform PRIVATE /arch:AVX2)
            target_link_libraries(test_renderer_platform PRIVATE
                "${OMR_ROOT}/build/windows/native/moonray/lib/common/mcrt_util/common_mcrt_util.lib")
            add_test(NAME renderer_platform COMMAND test_renderer_platform)
            set_tests_properties(renderer_platform PROPERTIES ENVIRONMENT_MODIFICATION
                "PATH=path_list_prepend:${OMR_ROOT}/build/windows/native/moonray/lib/common/mcrt_util;PATH=path_list_prepend:${OMR_ROOT}/build/windows/native/scene_rdl2/lib/render/util;PATH=path_list_prepend:${OMR_ROOT}/build/windows/native/scene_rdl2/lib/render/logging;PATH=path_list_prepend:${OMR_ROOT}/build/deps/x64-windows/bin;PATH=path_list_prepend:${OMR_ROOT}/build/tools/tbb/bin/intel64/vc14")
        endif()
        set(fixtureBinary "${CMAKE_CURRENT_BINARY_DIR}/sampling fixture.bin")
        set(fixtureObject "${CMAKE_CURRENT_BINARY_DIR}/sampling fixture.obj")
        set(coffGenerator "${OMR_ROOT}/moonray/moonray/cmake/EmbedBinaryCOFF.py")
        add_custom_command(OUTPUT "${fixtureObject}"
            COMMAND "${OMR_ROOT}/build/deps/x64-windows/tools/python3/python.exe"
                "${CMAKE_CURRENT_SOURCE_DIR}/generate_embedding_fixture.py" "${fixtureBinary}"
            COMMAND "${OMR_ROOT}/build/deps/x64-windows/tools/python3/python.exe"
                "${coffGenerator}" "${fixtureBinary}" "${fixtureObject}"
                windows_sampling_fixture_start windows_sampling_fixture_end
            DEPENDS "${coffGenerator}" "${CMAKE_CURRENT_SOURCE_DIR}/generate_embedding_fixture.py"
            VERBATIM)
        set_source_files_properties("${fixtureObject}" PROPERTIES EXTERNAL_OBJECT TRUE GENERATED TRUE)
        add_executable(test_coff_embedding test_coff_embedding.cc "${fixtureObject}")
        add_test(NAME coff_sampling_embedding COMMAND test_coff_embedding)
        add_executable(test_console_socket test_console_socket.cc
            "${OMR_ROOT}/moonray/scene_rdl2/lib/common/grid_util/SockUtil.cc"
            "${OMR_ROOT}/moonray/scene_rdl2/lib/common/grid_util/TlSvrWindows.cc")
        target_include_directories(test_console_socket PRIVATE
            "${CMAKE_CURRENT_BINARY_DIR}/source_include"
            "${OMR_ROOT}/build/deps/x64-windows/include"
            "${OMR_ROOT}/build/tools/tbb/include")
        target_compile_definitions(test_console_socket PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN
            _USE_MATH_DEFINES __TBB_NO_IMPLICIT_LINKAGE=1)
        target_compile_options(test_console_socket PRIVATE /arch:AVX2)
        target_link_libraries(test_console_socket PRIVATE ws2_32)
        add_test(NAME console_socket COMMAND test_console_socket)
        set_tests_properties(console_socket PROPERTIES TIMEOUT 15)
        if(EXISTS "${OMR_ROOT}/build/windows/scene_rdl2-Release/lib/render/util/render_util.lib")
            add_executable(test_topology test_topology.cc
                "${OMR_ROOT}/moonray/scene_rdl2/lib/common/grid_util/SockUtil.cc"
                "${OMR_ROOT}/moonray/scene_rdl2/lib/common/grid_util/NumaUtil.cc"
                "${OMR_ROOT}/moonray/scene_rdl2/lib/common/grid_util/CpuSocketUtil.cc"
                "${OMR_ROOT}/moonray/scene_rdl2/lib/common/grid_util/Arg.cc"
                "${OMR_ROOT}/moonray/scene_rdl2/lib/common/grid_util/TlSvrWindows.cc"
                "${OMR_ROOT}/moonray/scene_rdl2/lib/common/grid_util/Parser.cc")
            target_include_directories(test_topology PRIVATE
                "${CMAKE_CURRENT_BINARY_DIR}/source_include"
                "${OMR_ROOT}/build/deps/x64-windows/include"
                "${OMR_ROOT}/build/tools/tbb/include")
            target_compile_definitions(test_topology PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN
                _USE_MATH_DEFINES __TBB_NO_IMPLICIT_LINKAGE=1)
            target_compile_options(test_topology PRIVATE /arch:AVX2)
            target_link_libraries(test_topology PRIVATE
                ws2_32
                "${OMR_ROOT}/build/windows/scene_rdl2-Release/lib/render/util/render_util.lib")
            add_test(NAME cpu_numa_topology COMMAND test_topology)
            set_tests_properties(cpu_numa_topology PROPERTIES ENVIRONMENT_MODIFICATION
                "PATH=path_list_prepend:${OMR_ROOT}/build/windows/scene_rdl2-Release/lib/render/util;PATH=path_list_prepend:${OMR_ROOT}/build/windows/scene_rdl2-Release/lib/render/logging;PATH=path_list_prepend:${OMR_ROOT}/build/deps/x64-windows/bin;PATH=path_list_prepend:${OMR_ROOT}/build/tools/tbb/bin/intel64/vc14")
        endif()
        add_test(NAME lua_binary_embedding COMMAND
            "${OMR_ROOT}/build/deps/x64-windows/tools/python3/python.exe"
            "${CMAKE_CURRENT_SOURCE_DIR}/test_bin2cc.py"
            "${OMR_ROOT}/build/deps/x64-windows/tools/lua/lua.exe"
            "${OMR_ROOT}/moonray/scene_rdl2/lib/scene/rdl2/rdlalib/bin2cc.lua")
    endif()
endif()
