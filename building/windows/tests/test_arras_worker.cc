// SPDX-License-Identifier: Apache-2.0
#include <network/IPCSocketPeer.h>
#include <message_impl/PeerMessageEndpoint.h>
#include <message_impl/Envelope.h>
#include <chunking/ChunkingMessageEndpoint.h>
#include <chunking/MessageChunk.h>
#include "arras_worker_message.h"
#include <core_messages/ControlMessage.h>
#include <core_messages/SessionStatusMessage.h>
#include <core_messages/ExecutorHeartbeat.h>
#include <shared_impl/RegistrationData.h>
#include <shared_impl/ProcessExitCodes.h>
#include <message_impl/messaging_version.h>

#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

namespace fs = std::filesystem;
using namespace arras4;

void require(bool condition, const char* message)
{
    if (!condition) throw std::runtime_error(message);
}

std::string utf8(const fs::path& path)
{
    const auto value = path.u8string();
    return {value.begin(), value.end()};
}

class CountChunks final : public impl::MessageEndpoint
{
public:
    explicit CountChunks(impl::MessageEndpoint& endpoint) : mEndpoint(endpoint) {}
    impl::Envelope getEnvelope() override {
        auto envelope = mEndpoint.getEnvelope();
        if (envelope.contentAs<impl::MessageChunk>()) ++received;
        return envelope;
    }
    void putEnvelope(const impl::Envelope& envelope) override {
        if (envelope.contentAs<impl::MessageChunk>()) ++sent;
        mEndpoint.putEnvelope(envelope);
    }
    void shutdown() override { mEndpoint.shutdown(); }
    size_t sent = 0, received = 0;
private:
    impl::MessageEndpoint& mEndpoint;
};

class Child
{
public:
    Child(const fs::path& executable, const fs::path& config)
    {
        mJob = CreateJobObjectW(nullptr, nullptr);
        require(mJob != nullptr, "CreateJobObject failed");
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        if (!SetInformationJobObject(mJob, JobObjectExtendedLimitInformation, &limits, sizeof(limits))) {
            CloseHandle(mJob);
            throw std::runtime_error("SetInformationJobObject failed");
        }
        std::wstring command = L"\"" + executable.wstring() +
            L"\" --use_affinity 0 --use_color 0 --memoryMB 128 --cores 2 \"" + config.wstring() + L"\"";
        mLog = config.parent_path() / "worker.log";
        SECURITY_ATTRIBUTES security{sizeof(security), nullptr, TRUE};
        HANDLE log = CreateFileW(mLog.c_str(), GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
                                 &security, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        HANDLE input = CreateFileW(L"NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
                                   &security, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
        STARTUPINFOW startup{};
        startup.cb = sizeof(startup);
        startup.dwFlags = STARTF_USESTDHANDLES;
        startup.hStdOutput = startup.hStdError = log;
        startup.hStdInput = input;
        PROCESS_INFORMATION process{};
        const bool created = CreateProcessW(executable.c_str(), command.data(), nullptr, nullptr, TRUE,
                            CREATE_SUSPENDED | CREATE_NO_WINDOW, nullptr, nullptr, &startup, &process) != 0;
        const DWORD error = GetLastError();
        CloseHandle(input);
        CloseHandle(log);
        if (!created) {
            CloseHandle(mJob);
            throw std::runtime_error("CreateProcess failed: " + std::to_string(error));
        }
        mProcess = process.hProcess;
        if (!AssignProcessToJobObject(mJob, mProcess) || ResumeThread(process.hThread) == DWORD(-1)) {
            TerminateProcess(mProcess, 99);
            CloseHandle(process.hThread);
            CloseHandle(mProcess);
            CloseHandle(mJob);
            throw std::runtime_error("could not start worker in test job");
        }
        CloseHandle(process.hThread);
    }
    ~Child()
    {
        CloseHandle(mJob); // Also cleans up a worker if an assertion throws.
        WaitForSingleObject(mProcess, 5000);
        CloseHandle(mProcess);
    }
    void expectExit(DWORD expected)
    {
        if (WaitForSingleObject(mProcess, 10000) != WAIT_OBJECT_0) {
            std::ifstream log(mLog);
            std::cerr << log.rdbuf();
            throw std::runtime_error("worker failed to exit within 10 seconds");
        }
        DWORD code = 0;
        require(GetExitCodeProcess(mProcess, &code) != 0, "cannot read worker exit status");
        if (code != expected) throw std::runtime_error("worker exit " + std::to_string(code) +
                                                     ", expected " + std::to_string(expected));
    }
private:
    HANDLE mJob = nullptr;
    HANDLE mProcess = nullptr;
    fs::path mLog;
};

void run(const fs::path& worker, const fs::path& computation, const std::string& mode)
{
    const auto directory = fs::current_path() / ("worker test " + std::to_string(GetCurrentProcessId()));
    fs::create_directories(directory);
    struct Cleanup { fs::path path; ~Cleanup() { std::error_code ec; fs::remove_all(path, ec); } } cleanup{directory};
    const auto dllDirectory = directory / fs::u8path(u8"computation \u00e9");
    fs::create_directory(dllDirectory);
    const auto dll = dllDirectory / computation.filename();
    fs::copy_file(computation, dll, fs::copy_options::overwrite_existing);
    const auto ipc = directory / "worker.sock";
    const auto configPath = directory / "worker.json";
    const auto events = directory / "events.txt";
    const api::UUID session("10000000-0000-0000-0000-000000000001");
    const api::UUID node("20000000-0000-0000-0000-000000000002");
    const api::UUID comp("30000000-0000-0000-0000-000000000003");
    api::Object config;
    config["sessionId"] = session.toString();
    config["nodeId"] = node.toString();
    config["compId"] = comp.toString();
    config["ipc"] = utf8(ipc);
    config["logLevel"] = 5;
    auto& computationConfig = config["config"]["worker-test"];
    computationConfig["dso"] = utf8(dll);
    computationConfig["events"] = utf8(events);
    computationConfig["invalid"] = mode == "invalid";
    computationConfig["throwOnStart"] = mode == "start_exception";
    computationConfig["chunking"] = mode == "chunking";
    computationConfig["minChunkingBytes"] = 4096;
    computationConfig["chunkSizeBytes"] = 8192;
    auto& entry = config["routing"][session.toString()]["computations"]["worker-test"];
    entry["nodeId"] = node.toString();
    entry["compId"] = comp.toString();
    config["routing"]["messageFilter"]["worker-test"]["(client)"] = api::Object(Json::objectValue);
    if (mode == "missing") computationConfig["dso"] = utf8(directory / "missing.dll");
    if (mode == "no_factory") computationConfig["dso"] = utf8(worker.parent_path() / "core_messages.dll");
    { std::ofstream output(configPath); output << api::objectToStyledString(config); }

    network::IPCSocketPeer listener;
    listener.listen(ipc.string());
    Child child(worker, configPath);
    if (mode == "missing" || mode == "no_factory") {
        child.expectExit(impl::ProcessExitCodes::COMPUTATION_LOAD_ERROR);
        return;
    }
    if (mode == "invalid") {
        child.expectExit(impl::ProcessExitCodes::INITIALIZATION_FAILED);
    } else {
        network::Peer* peers[1]{};
        network::Peer** peerPointer = peers;
        int count = 1;
        listener.accept(peerPointer, count, 10000);
        require(count == 1, "worker did not connect");
        std::unique_ptr<network::Peer> peer(peers[0]);
        impl::RegistrationData registration(0, 0, 0);
        require(peer->receive_all(&registration, sizeof(registration), 5000), "registration was not received");
        require(registration.mMagic == impl::RegistrationData::MAGIC &&
                registration.mMessagingAPIVersionMajor == ARRAS_MESSAGING_API_VERSION_MAJOR &&
                registration.mType == impl::REGISTRATION_EXECUTOR && registration.mSessionId == session &&
                registration.mNodeId == node && registration.mComputationId == comp, "incorrect worker registration");
        impl::PeerMessageEndpoint wire(*peer, true, "Windows worker integration test");
        CountChunks counts(wire);
        impl::ChunkingConfig chunking;
        chunking.enabled = mode == "chunking";
        chunking.minChunkingSize = 4096;
        chunking.chunkSize = 8192;
        impl::ChunkingMessageEndpoint endpoint(counts, chunking);
        auto control = [&](const char* command) { endpoint.putEnvelope(impl::Envelope(new impl::ControlMessage(command))); };
        if (mode == "disconnect_before_go") {
            endpoint.shutdown();
            child.expectExit(impl::ProcessExitCodes::DISCONNECTED);
        } else if (mode == "stop_before_go") {
            control("stop");
            child.expectExit(impl::ProcessExitCodes::NORMAL);
        } else {
            control("go");
            if (mode == "start_exception") {
                child.expectExit(impl::ProcessExitCodes::EXCEPTION_CAUGHT);
            } else {
                const std::string payload = std::string("Windows\0worker\xff", 15) + std::string(262144, 'x');
                endpoint.putEnvelope(impl::Envelope(new WorkerTestMessage(payload)));
                bool ready = false, heartbeat = false, echoed = false;
                while (!ready || !heartbeat || !echoed) {
                    auto envelope = endpoint.getEnvelope(); // CTest bounds a failed/blocking wire transfer.
                    require(envelope.metadata()->from().computation == comp, "wrong message source");
                    if (const auto response = envelope.contentAs<impl::SessionStatusMessage>()) {
                        require(response->getValue() == payload, "worker changed binary message payload");
                        require(envelope.to().size() == 1 && envelope.to().front().session == session &&
                                envelope.to().front().computation == api::UUID::null, "incorrect client routing");
                        echoed = true;
                    } else if (const auto response = envelope.contentAs<impl::ControlMessage>()) {
                        require(response->command() == "ready", "unexpected control message");
                        ready = true;
                    } else if (const auto stats = envelope.contentAs<impl::ExecutorHeartbeat>()) {
                        const auto now = std::chrono::duration_cast<std::chrono::seconds>(
                            std::chrono::system_clock::now().time_since_epoch()).count();
                        require(stats->mTransmitSecs <= now + 1 && stats->mTransmitSecs + 30 >= now &&
                                stats->mTransmitMicroSecs < 1000000 && stats->mMemoryUsageBytesCurrent > 0 &&
                                stats->mThreads > 0 && std::isfinite(stats->mCpuUsageTotalSecs) &&
                                stats->mCpuUsageTotalSecs >= 0, "invalid worker performance heartbeat");
                        heartbeat = true;
                    } else throw std::runtime_error("unexpected worker message");
                }
                require(mode == "chunking" ? (counts.sent > 1 && counts.received > 1) :
                        (counts.sent == 0 && counts.received == 0), "incorrect message chunking on the wire");
                if (mode == "disconnect") {
                    endpoint.shutdown();
                    child.expectExit(impl::ProcessExitCodes::DISCONNECTED);
                } else {
                    control("stop");
                    child.expectExit(impl::ProcessExitCodes::NORMAL);
                }
            }
        }
    }
    std::ifstream input(events);
    const std::string actual((std::istreambuf_iterator<char>(input)), {});
    const std::string expected = mode == "invalid" || mode == "disconnect_before_go" || mode == "stop_before_go" ? "initialize\ndestroy\n" :
        mode == "start_exception" ? "initialize\nstart\ndestroy\n" : "initialize\nstart\nstop\ndestroy\n";
    require(actual == expected, "incorrect computation lifecycle callbacks");
}

int main(int argc, char** argv)
{
    if (argc != 4) return 2;
    WSADATA data{};
    if (WSAStartup(MAKEWORD(2, 2), &data) != 0) return 2;
    int result = 0;
    try {
        run(fs::absolute(fs::u8path(argv[1])), fs::absolute(fs::u8path(argv[2])), argv[3]);
        std::cout << argv[3] << " passed\n";
    } catch (const std::exception& error) {
        std::cerr << argv[3] << ": " << error.what() << '\n';
        result = 1;
    }
    WSACleanup();
    return result;
}
