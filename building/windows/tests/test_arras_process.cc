// SPDX-License-Identifier: Apache-2.0
#include <execute/ProcessManager.h>
#include <execute/ProcessController.h>
#include <execute/SpawnArgs.h>
#include <execute/IoCapture.h>
#include <message_api/Object.h>
#include <windows.h>
#include <atomic>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <thread>

using namespace arras4;
namespace fs = std::filesystem;

void require(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
std::string utf8(const std::wstring& value) {
    if (value.empty()) return {};
    int size = WideCharToMultiByte(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), nullptr, 0, nullptr, nullptr);
    std::string result(size, 0);
    WideCharToMultiByte(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), result.data(), size, nullptr, nullptr);
    return result;
}
std::string environment(const wchar_t* name) {
    DWORD size = GetEnvironmentVariableW(name, nullptr, 0);
    if (!size) return {};
    std::wstring value(size, 0);
    value.resize(GetEnvironmentVariableW(name, value.data(), size));
    return utf8(value);
}

int child(int argc, wchar_t** argv)
{
    const std::wstring mode = argv[2];
    if (mode == L"inspect") {
        api::Object report;
        for (int i = 3; i < argc; ++i) report["args"].append(utf8(argv[i]));
        report["value"] = environment(L"ARRAS_PROCESS_VALUE");
        report["removed"] = environment(L"ARRAS_PROCESS_REMOVED");
        report["cwd"] = utf8(fs::current_path().wstring());
        const auto inherited = environment(L"ARRAS_TEST_INHERITED_HANDLE");
        if (!inherited.empty()) SetEvent(reinterpret_cast<HANDLE>(std::stoull(inherited)));
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
        require(QueryInformationJobObject(nullptr, JobObjectExtendedLimitInformation, &limits, sizeof(limits), nullptr) != 0,
                "child was not placed in a job");
        report["memoryLimit"] = Json::UInt64(limits.JobMemoryLimit);
        JOBOBJECT_CPU_RATE_CONTROL_INFORMATION cpu{};
        require(QueryInformationJobObject(nullptr, JobObjectCpuRateControlInformation, &cpu, sizeof(cpu), nullptr) != 0,
                "child could not query CPU limits");
        report["cpuRate"] = Json::UInt(cpu.CpuRate);
        std::cout << api::objectToString(report) << std::flush;
        return 37;
    }
    if (mode == L"burst") {
        const std::string error = std::string("e\0", 2) + std::string(65534, 'e');
        const std::string output = std::string("o\0", 2) + std::string(65534, 'o');
        for (DWORD stream : {STD_ERROR_HANDLE, STD_OUTPUT_HANDLE}) {
            const auto& data = stream == STD_ERROR_HANDLE ? error : output;
            for (int i = 0; i < 32; ++i) {
                DWORD written = 0;
                require(WriteFile(GetStdHandle(stream), data.data(), static_cast<DWORD>(data.size()), &written, nullptr) &&
                        written == data.size(), "child write failed");
            }
        }
        return 0;
    }
    if (mode == L"sleep") {
        std::cout << "ready" << std::flush;
        Sleep(60000);
        return 0;
    }
    if (mode == L"wait_event") {
        HANDLE event = OpenEventW(SYNCHRONIZE, FALSE, argv[3]);
        require(event != nullptr, "child failed to open stop event");
        DWORD status = WaitForSingleObject(event, 10000);
        CloseHandle(event);
        return status == WAIT_OBJECT_0 ? 0 : 1;
    }
    if (mode == L"tree") {
        std::wstring command = L"\"" + std::wstring(argv[0]) + L"\" --child sleep";
        STARTUPINFOW startup{};
        startup.cb = sizeof(startup);
        PROCESS_INFORMATION process{};
        require(CreateProcessW(argv[0], command.data(), nullptr, nullptr, FALSE, CREATE_NO_WINDOW,
                               nullptr, nullptr, &startup, &process) != 0, "grandchild launch failed");
        std::cout << process.dwProcessId << std::flush;
        CloseHandle(process.hThread);
        CloseHandle(process.hProcess);
        return 0;
    }
    if (mode == L"exit") return 143;
    return 2;
}

class Observer final : public impl::ProcessObserver {
public:
    void onSpawn(const api::UUID&, const api::UUID&, impl::ProcessId pid) override {
        require(pid != 0, "spawn observer received invalid pid"); ++spawned;
    }
    void onTerminate(const api::UUID&, const api::UUID&, impl::ExitStatus) override { ++terminated; }
    std::atomic<int> spawned{0}, terminated{0};
};
class Controller final : public impl::ProcessController {
public:
    explicit Controller(HANDLE event) : mEvent(event) {}
    bool sendStop(const api::UUID&, const api::UUID&) override { ++calls; return SetEvent(mEvent) != 0; }
    std::atomic<int> calls{0};
private:
    HANDLE mEvent;
};

impl::ExitStatus wait(const impl::Process::Ptr& process)
{
    impl::ExitStatus status;
    require(process->waitForExit(&status, std::chrono::seconds(10)), "process did not exit within ten seconds");
    require(process->pid() == 0 && process->state() == impl::ProcessState::Terminated, "invalid terminal process state");
    return status;
}

void parent(const fs::path& executable, const std::string& mode)
{
    const auto directory = fs::current_path() / (L"process test \u00e9 " + std::to_wstring(GetCurrentProcessId()));
    fs::create_directories(directory);
    struct Cleanup { fs::path path; ~Cleanup() { std::error_code error; fs::remove_all(path, error); } } cleanup{directory};
    const auto program = directory / L"worker child.exe";
    fs::copy_file(executable, program, fs::copy_options::overwrite_existing);
    impl::SpawnArgs args;
    args.program = utf8(program.wstring());
    args.workingDirectory = utf8(directory.wstring());
    args.cleanupProcessGroup = true;
    args.environment.setFromCurrent();
    args.environment.set("Path", utf8(executable.parent_path().wstring()) + ";" + args.environment.get("PATH"));
    args.environment.set("PATH", "incorrect", false);
    require(args.environment.get("path") != "incorrect", "environment variable names are not case insensitive");
    auto capture = std::make_shared<impl::SimpleIoCapture>();
    auto observer = std::make_shared<Observer>();
    args.ioCapture = capture;
    args.observer = observer;
    impl::ProcessManager manager;
    auto process = manager.addProcess();
    if (mode == "arguments") {
        SECURITY_ATTRIBUTES security{sizeof(security), nullptr, TRUE};
        HANDLE event = CreateEventW(&security, TRUE, FALSE, nullptr);
        require(event != nullptr, "could not create inheritance probe");
        struct Close { HANDLE value; ~Close() { CloseHandle(value); } } close{event};
        args.environment.set("ARRAS_TEST_INHERITED_HANDLE", std::to_string(reinterpret_cast<uintptr_t>(event)));
        args.environment.set("ARRAS_PROCESS_VALUE", utf8(L"value \u00e9 \u65e5\u672c"));
        SetEnvironmentVariableW(L"ARRAS_PROCESS_REMOVED", L"must not leak");
        args.environment.remove("arras_process_removed");
        args.enforceMemory = args.enforceCores = true;
        args.assignedMb = 256;
        args.assignedCores = 1;
        args.args = {"--child", "inspect", "", "two words", "a\"b", "slash\\", "two\\\\\"quotes", "tab\tvalue", utf8(L"\u00e9 \u65e5\u672c")};
        require(process->spawn(args) == impl::StateChange::Success, "process spawn failed");
        auto status = wait(process);
        SetEnvironmentVariableW(L"ARRAS_PROCESS_REMOVED", nullptr);
        require(status.exitType == impl::ExitType::Exit && status.status == 37, "wrong child exit code");
        api::Object report;
        api::stringToObject(capture->out(), report);
        require(report["args"].size() == args.args.size() - 2, "argument count changed");
        for (Json::ArrayIndex i = 0; i < report["args"].size(); ++i)
            require(report["args"][i].asString() == args.args[i + 2], "argument quoting changed the child argv");
        require(report["value"].asString() == args.environment.get("ARRAS_PROCESS_VALUE") &&
                report["removed"].asString().empty(), "child environment was not preserved");
        require(report["cwd"].asString() == utf8(directory.wstring()), "working directory changed");
        require(report["memoryLimit"].asUInt64() == 256ull * 1024 * 1024 && report["cpuRate"].asUInt() > 0,
                "Windows job resource limits were not applied");
        require(WaitForSingleObject(event, 0) == WAIT_TIMEOUT, "unrelated inheritable handle leaked into child");
        impl::SpawnArgs search = args;
        search.environment.set("PATH", "Z:\\missing;\"" + utf8(directory.wstring()) + "\"");
        require(search.findProgramInPath("worker child") && search.program == args.program,
                "PATH search failed with drive letters, quotes, spaces and an implicit .exe");
    } else if (mode == "capture") {
        args.args = {"--child", "burst"};
        require(process->spawn(args) == impl::StateChange::Success, "capture child spawn failed");
        require(wait(process).status == 0, "capture child failed");
        const auto output = capture->out(), error = capture->err();
        require(output.size() == 32 * 65536 && error.size() == 32 * 65536, "output capture lost bytes");
        for (size_t i = 0; i < output.size(); ++i) {
            require(output[i] == (i % 65536 == 1 ? '\0' : 'o') && error[i] == (i % 65536 == 1 ? '\0' : 'e'),
                    "output capture changed binary content");
        }
    } else if (mode == "tree") {
        args.args = {"--child", "tree"};
        require(process->spawn(args) == impl::StateChange::Success, "tree child spawn failed");
        require(wait(process).status == 0, "tree child failed");
        DWORD pid = static_cast<DWORD>(std::stoul(capture->out()));
        HANDLE descendant = OpenProcess(SYNCHRONIZE, FALSE, pid);
        if (descendant) {
            DWORD result = WaitForSingleObject(descendant, 2000);
            CloseHandle(descendant);
            require(result == WAIT_OBJECT_0, "process-tree cleanup left a descendant running");
        } else require(GetLastError() == ERROR_INVALID_PARAMETER, "could not verify descendant exit");
    } else if (mode == "termination") {
        const auto name = L"Local\\ArrasStopTest-" + std::to_wstring(GetCurrentProcessId());
        HANDLE event = CreateEventW(nullptr, TRUE, FALSE, name.c_str());
        require(event != nullptr, "could not create stop event");
        struct Close { HANDLE value; ~Close() { CloseHandle(value); } } close{event};
        auto controller = std::make_shared<Controller>(event);
        manager.setProcessController(controller);
        args.args = {"--child", "wait_event", utf8(name)};
        require(process->spawn(args) == impl::StateChange::Success, "controlled child spawn failed");
        process->terminate(false);
        auto status = wait(process);
        require(status.exitType == impl::ExitType::Exit && status.status == 0 && controller->calls == 1,
                "controlled stop did not allow a normal child exit");
        require(process->reset() == impl::StateChange::Success, "process reset failed");
        args.args = {"--child", "sleep"};
        require(process->spawn(args) == impl::StateChange::Success, "forced child spawn failed");
        require(!process->waitForExit(nullptr, std::chrono::milliseconds(50)), "running process reported an exit");
        process->terminate(true);
        status = wait(process);
        require(status.exitType == impl::ExitType::Signal && status.status == 9, "forced termination status is wrong");
    } else if (mode == "lifecycle") {
        args.args = {"--child", "exit"};
        for (int i = 0; i < 3; ++i) {
            require(process->spawn(args) == impl::StateChange::Success, "reset child spawn failed");
            auto status = wait(process);
            require(status.status == 143 && !status.convertHighExitToSignal(), "Windows exit code was misinterpreted as a Unix signal");
            require(process->reset() == impl::StateChange::Success, "reset after exit failed");
        }
        args.program = utf8((directory / "missing.exe").wstring());
        require(process->spawn(args) == impl::StateChange::Terminated, "missing executable did not fail to spawn");
        require(wait(process).exitType == impl::ExitType::Internal, "missing executable returned a normal exit");
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(1);
        while (observer->terminated != 4 && std::chrono::steady_clock::now() < deadline) std::this_thread::yield();
        require(observer->spawned == 3 && observer->terminated == 4, "process observer missed or duplicated callbacks");
        require(manager.removeProcess(process->id()) && !manager.getProcess(process->id()), "process removal failed");
    } else if (mode == "manager_shutdown") {
        auto owner = std::make_unique<impl::ProcessManager>();
        auto owned = owner->addProcess();
        args.args = {"--child", "sleep"};
        require(owned->spawn(args) == impl::StateChange::Success, "owned child spawn failed");
        owner.reset();
        require(owned->state() == impl::ProcessState::Terminated, "manager destruction left its child running");
    } else throw std::runtime_error("unknown test mode");
}

int wmain(int argc, wchar_t** argv)
{
    try {
        if (argc >= 3 && std::wstring(argv[1]) == L"--child") return child(argc, argv);
        if (argc != 2) return 2;
        parent(fs::absolute(argv[0]), utf8(argv[1]));
        std::cout << utf8(argv[1]) << " passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
