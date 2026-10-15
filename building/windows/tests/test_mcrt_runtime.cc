// SPDX-License-Identifier: Apache-2.0
#include <mcrt_dataio/share/sock/SockClient.h>
#include <mcrt_dataio/share/sock/SockServerInet.h>
#include <mcrt_dataio/share/sock/SockServerUnix.h>
#include <mcrt_dataio/share/sock/SockServerConnection.h>
#include <mcrt_dataio/share/util/SysUsage.h>
#include <mcrt_dataio/share/util/MiscUtil.h>
#include <mcrt_messages/RDLMessage.h>
#include <message_impl/StreamImpl.h>
#include <network/Buffer.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <vector>

void require(bool condition, const char* message)
{
    if (!condition) throw std::runtime_error(message);
}

template<class Listener>
void exchange(Listener& listener, mcrt_dataio::SockClient& client)
{
    auto peer = listener.newClientConnection();
    require(bool(peer), "listener did not accept connection");
    const std::string payload("MoonRay\0frame\xff", 14);
    require(client.send(payload.data(), payload.size()), "client send failed");
    std::string buffer(payload.size(), '\0');
    require(peer->recv(buffer.data(), buffer.size()) == buffer.size() && buffer == payload,
            "server received incorrect bytes");
    require(peer->send(buffer.data(), buffer.size()), "server echo failed");
    require(client.recv(buffer.data(), buffer.size()) == buffer.size() && buffer == payload,
            "client received incorrect bytes");
    peer->close();
    require(client.recv(buffer.data(), buffer.size()) == mcrt_dataio::SockClient::RECV_STATUS_EOF,
            "peer disconnect did not return EOF");
}

void sockets()
{
    {
        mcrt_dataio::SockServerInet listener;
        require(listener.open(0) && listener.getPortNum() > 0, "TCP listener failed");
        require(!listener.newClientConnection(), "idle listener returned a connection");
        mcrt_dataio::SockClient client;
        require(client.open("127.0.0.1", listener.getPortNum(), ""), "TCP client failed");
        exchange(listener, client);
    }
    const auto path = std::filesystem::current_path() / "mcrt-runtime-test.sock";
    {
        mcrt_dataio::SockServerUnix listener;
        require(listener.open(path.string(), 1), "IPC listener setup failed");
        require(!listener.newClientConnection(), "idle IPC listener returned a connection");
        mcrt_dataio::SockClient client;
        require(client.open("localhost", 1, path.string()), "IPC client failed");
        exchange(listener, client);
    }
    require(!std::filesystem::exists(path.string() + ".1"), "IPC endpoint leaked");
}

void telemetry()
{
    using mcrt_dataio::MiscUtil;
    using mcrt_dataio::SysUsage;
    const auto now = MiscUtil::getCurrentMicroSec();
    const auto expected = std::chrono::duration_cast<std::chrono::microseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    require(std::abs(static_cast<int64_t>(now) - expected) < 1000000, "epoch time incorrect");
    require(!MiscUtil::getHostName().empty(), "hostname empty");
    require(!MiscUtil::timeFromEpochStr(now).empty() && !MiscUtil::currentTimeStr().empty(), "time formatting failed");
    require(SysUsage::getMemTotal() > 0, "memory total missing");
    const float memory = SysUsage::getMemUsage();
    require(std::isfinite(memory) && memory >= 0 && memory <= 1, "invalid memory usage");
    SysUsage usage;
    require(usage.getCpuUsage() >= 0, "CPU counters could not initialize");
    std::this_thread::sleep_for(std::chrono::milliseconds(250));
    require(usage.isCpuUsageReady(), "CPU counters never ready");
    const float cpu = usage.getCpuUsage();
    const auto cores = usage.getCoreUsage();
    require(std::isfinite(cpu) && cpu >= 0 && cpu <= 1, "invalid CPU usage");
    require(cores.size() == SysUsage::getCpuTotal() && !cores.empty(), "wrong core count");
    require(std::all_of(cores.begin(), cores.end(), [](float v) { return std::isfinite(v) && v >= 0 && v <= 1; }),
            "invalid per-core usage");
    usage.updateNetIO();
    require(std::isfinite(usage.getNetRecv()) && std::isfinite(usage.getNetSend()), "invalid network counters");
    std::cout << cores.size() << " cores, CPU=" << cpu << ", RAM=" << memory << '\n';
}

void messages()
{
    mcrt::RDLMessage original;
    original.mSyncId = 12345;
    original.mManifest = std::string("manifest\0bytes", 14);
    original.mPayload = std::string("scene\0\xff\x7f", 8);
    original.mForceReload = true;
    arras4::network::Buffer buffer(original.serializedLength());
    arras4::impl::OutStreamImpl output(buffer);
    original.serialize(output);
    require(output.bytesWritten() == original.serializedLength(), "serialized size differs from protocol size");
    arras4::impl::InStreamImpl input(buffer);
    mcrt::RDLMessage decoded;
    decoded.deserialize(input, original.classVersion());
    require(decoded.mSyncId == original.mSyncId && decoded.mManifest == original.mManifest &&
            decoded.mPayload == original.mPayload && decoded.mForceReload, "RDL message roundtrip failed");
    require(buffer.remaining() == 0, "message decoder left trailing bytes");
}

int main(int argc, char** argv)
{
    try {
        const std::string mode = argc == 2 ? argv[1] : "";
        if (mode == "sockets") sockets();
        else if (mode == "telemetry") telemetry();
        else if (mode == "messages") messages();
        else throw std::runtime_error("expected sockets, telemetry or messages");
        std::cout << mode << " passed\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
