// SPDX-License-Identifier: Apache-2.0
#include <sdk/SDK.h>
#include <core_messages/SessionStatusMessage.h>
#include "arras_worker_message.h"
#include <filesystem>
#include <condition_variable>
#include <fstream>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <atomic>
#include <set>
#include <thread>
#include <vector>

using namespace arras4;
namespace fs = std::filesystem;
void require(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
std::string utf8(const fs::path& path) { const auto value = path.u8string(); return {value.begin(), value.end()}; }

struct Responses {
    std::mutex mutex;
    std::condition_variable condition;
    bool echo = false, stopped = false;
    std::string error;
    std::set<std::string> echoes;
};

void run(const fs::path& dll, const std::string& mode)
{
    const auto directory = fs::current_path() / ("local-test-" + std::to_string(GetCurrentProcessId()));
    fs::create_directories(directory);
    struct Cleanup { fs::path path; ~Cleanup() { std::error_code ec; fs::remove_all(path, ec); } } cleanup{directory};
    // CTest provides short, workspace-owned paths for AF_UNIX and the SDK log.
    fs::create_directories(fs::temp_directory_path());
    if (mode == "unicode") {
        const auto unicodeTemp = fs::temp_directory_path() / L"\u00e9";
        fs::create_directories(unicodeTemp);
        _wputenv_s(L"TMP", unicodeTemp.c_str());
        _wputenv_s(L"TEMP", unicodeTemp.c_str());
    }
    if (const char* home = std::getenv("HOME")) fs::create_directories(fs::u8path(home));
    const std::string payload = std::string("Local Arras\0Windows\xff", 20) + std::string(262144, 'y');
    const bool concurrent = mode == "concurrent" || mode == "concurrent-sync";
    auto expected = std::make_shared<std::set<std::string>>();
    if (concurrent) {
        for (int i = 0; i < 64; ++i) expected->insert(payload + std::to_string(i));
    }
    const int iterations = mode == "repeated" ? 5 : 1;
    for (int iteration = 0; iteration < iterations; ++iteration) {
        client::SessionDefinition definition;
        auto& comp = definition["worker-test"];
        comp["dso"] = mode == "missing" ? utf8(directory / "missing.dll") : utf8(dll);
        comp["events"] = utf8(directory / ("events-" + std::to_string(iteration)));
        comp["invalid"] = mode == "invalid";
        comp["requirements"]["packaging_system"] = "current-environment";
        comp["requirements"]["resources"]["memoryMB"] = 128;
        comp["requirements"]["resources"]["cores"] = 2;
        comp["environment"] = api::Object(Json::objectValue);
        comp["chunking"] = true;
        comp["chunkSizeBytes"] = 8192;
        comp["minChunkingBytes"] = 4096;
        definition["(client)"]["messages"]["worker-test"] = api::Object(Json::objectValue);
        if (mode == "async") definition["(client)"]["messages"]["worker-test"] = "*";
        auto responses = std::make_shared<Responses>();
        sdk::SDK client;
        if (mode == "async" || mode == "concurrent") client.setAsyncSend();
        else client.setSyncSend();
        client.enableMessageChunking(4096, 8192);
        client.setExceptionCallback([responses](const std::exception& error) {
            std::lock_guard<std::mutex> lock(responses->mutex);
            responses->error = error.what();
            responses->condition.notify_all();
        });
        client.setStatusHandler([responses, payload, expected](const std::string& status) {
            std::lock_guard<std::mutex> lock(responses->mutex);
            if (status == payload) responses->echo = true;
            else if (expected->count(status)) {
                if (!responses->echoes.insert(status).second) responses->error = "duplicate concurrent response";
            }
            else {
                try {
                    api::Object object;
                    api::stringToObject(status, object);
                    if (object["execStatus"].asString() == "stopped") responses->stopped = true;
                } catch (...) { responses->error = "invalid session status"; }
            }
            responses->condition.notify_all();
        });
        const auto start = std::chrono::steady_clock::now();
        if (mode == "missing" || mode == "invalid") {
            bool failed = false;
            try { client.createSession(definition, "arras:local"); }
            catch (const sdk::SDKException&) { failed = true; }
            require(failed, "invalid local computation unexpectedly started");
            require(std::chrono::steady_clock::now() - start < std::chrono::seconds(5),
                    "early worker exit was not detected promptly");
            continue;
        }
        const auto session = client.createSession(definition, "arras:local");
        require(!session.empty() && client.isConnected() && client.isEngineReady(), "local SDK session did not become ready");
        client.sendMessage(std::make_shared<WorkerTestMessage>(payload));
        {
            std::unique_lock<std::mutex> lock(responses->mutex);
            require(responses->condition.wait_for(lock, std::chrono::seconds(10), [&] {
                return responses->echo || !responses->error.empty();
            }), "local computation did not reply");
            if (!responses->error.empty()) throw std::runtime_error(responses->error);
            require(responses->echo, "local computation changed message content");
        }
        if (concurrent) {
            std::atomic<int> ready{0};
            std::atomic<bool> start{false};
            std::vector<std::thread> senders;
            for (int sender = 0; sender < 4; ++sender) {
                senders.emplace_back([&, sender] {
                    ++ready;
                    while (!start) std::this_thread::yield();
                    try {
                        for (int i = sender; i < 64; i += 4)
                            client.sendMessage(std::make_shared<WorkerTestMessage>(payload + std::to_string(i)));
                    } catch (const std::exception& error) {
                        std::lock_guard<std::mutex> lock(responses->mutex);
                        responses->error = error.what();
                        responses->condition.notify_all();
                    }
                });
            }
            while (ready < 4) std::this_thread::yield();
            start = true;
            for (auto& sender : senders) sender.join();
            std::unique_lock<std::mutex> lock(responses->mutex);
            require(responses->condition.wait_for(lock, std::chrono::seconds(10), [&] {
                return responses->echoes.size() == expected->size() || !responses->error.empty();
            }), "concurrent messages were lost");
            if (!responses->error.empty()) throw std::runtime_error(responses->error);
            require(responses->echoes == *expected, "concurrent messages were corrupted");
        }
        if (mode == "disconnect") client.disconnect();
        else {
            client.shutdownSession();
            require(client.waitForDisconnect(5), "local SDK session did not shut down");
            std::unique_lock<std::mutex> lock(responses->mutex);
            require(responses->condition.wait_for(lock, std::chrono::seconds(1), [&] { return responses->stopped; }),
                    "local SDK did not report the worker exit");
        }
    }
}

int main(int argc, char** argv)
{
    if (argc != 3) return 2;
    WSADATA data{};
    if (WSAStartup(MAKEWORD(2, 2), &data)) return 2;
    int result = 0;
    try { run(fs::absolute(fs::u8path(argv[1])), argv[2]); std::cout << argv[2] << " passed\n"; }
    catch (const std::exception& error) { std::cerr << error.what() << '\n'; result = 1; }
    WSACleanup();
    return result;
}
