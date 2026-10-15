// SPDX-License-Identifier: Apache-2.0
#include <network/InetSocketPeer.h>
#include <network/IPCSocketPeer.h>
#include <http/HttpRequest.h>
#include <httpserver/HttpServer.h>
#include <httpserver/HttpServerRequest.h>
#include <httpserver/HttpServerResponse.h>
#include <sdk/SDK.h>

#include <array>
#include <chrono>
#include <filesystem>
#include <future>
#include <iostream>
#include <stdexcept>
#include <string>

using namespace arras4::network;
static_assert(sizeof(ARRAS_SOCKET) == sizeof(SOCKET));
static_assert(ARRAS_INVALID_SOCKET == INVALID_SOCKET);

void require(bool condition, const char* message)
{
    if (!condition) throw std::runtime_error(message);
}

void exchange(SocketPeer& listener, SocketPeer& client)
{
    Peer* peers[1] = {};
    Peer** peersPtr = peers;
    int count = 1;
    listener.accept(peersPtr, count, 1000);
    require(count == 1, "accept did not return the connected client");
    std::unique_ptr<Peer> server(peers[0]);
    bool readable = false, writable = false;
    require(!client.poll(true, readable, false, writable, 20) && !readable,
            "idle connection reported readable or disconnected");
    const std::string payload("Arras\0Windows\xff", 14);
    require(client.send(payload.data(), payload.size()), "client send failed");
    std::array<char, 14> received{};
    require(server->peek(received.data(), received.size()) > 0 && received[0] == payload[0],
            "peek failed to inspect the pending payload");
    require(server->receive_all(received.data(), received.size(), 1000), "server receive failed");
    require(std::string(received.data(), received.size()) == payload, "binary payload changed");
    require(server->send(received.data(), received.size()), "server send failed");
    require(client.receive_all(received.data(), received.size(), 1000), "client receive failed");
    require(std::string(received.data(), received.size()) == payload, "echo payload changed");
    require(client.bytesWritten() == payload.size() && client.bytesRead() == payload.size(),
            "socket byte counters do not match the transferred payload");
    server->shutdown_send();
    require(client.poll(true, readable, false, writable, 1000) && readable,
            "peer shutdown was not reported");
    require(client.receive(received.data(), received.size()) == 0, "EOF not returned after shutdown");
}

void tcp()
{
    InetSocketPeer listener(static_cast<unsigned short>(0));
    InetSocketPeer client("127.0.0.1", listener.localPort());
    exchange(listener, client);
    const auto closedPort = listener.localPort();
    listener.shutdown();
    try {
        InetSocketPeer refused("127.0.0.1", closedPort);
        throw std::runtime_error("connection to closed listener succeeded");
    } catch (const PeerException& error) {
        require(error.code() == PeerException::CONNECTION_REFUSED, "wrong refusal error code");
    }
}

void ipc()
{
    const auto path = std::filesystem::current_path() /
        ("arras-test-" + std::to_string(GetCurrentProcessId()) + ".sock");
    {
        IPCSocketPeer listener, client;
        listener.listen(path.string());
        client.connect(path.string());
        exchange(listener, client);
    }
    require(!std::filesystem::exists(path), "IPC endpoint was not removed on destruction");
}

void cancelIo(SocketPeer& listener, SocketPeer& client, bool sending)
{
    Peer* peers[1]{};
    Peer** peerPointer = peers;
    int count = 1;
    listener.accept(peerPointer, count, 1000);
    require(count == 1, "cancellation test did not connect");
    std::unique_ptr<Peer> server(peers[0]);
    const int bufferSize = 4096;
    require(setsockopt(client.fd(), SOL_SOCKET, SO_SNDBUF,
                      reinterpret_cast<const char*>(&bufferSize), sizeof(bufferSize)) == 0,
            "could not limit test send buffer");
    auto blocked = std::async(std::launch::async, [&] {
        try {
            if (sending) {
                const std::string bytes(1024 * 1024, 'x');
                // The peer never reads; eventually this must block on backpressure.
                while (client.send(bytes.data(), bytes.size())) {}
            } else {
                char byte;
                require(client.receive(&byte, 1) == 0, "unexpected data in cancellation test");
            }
        } catch (const PeerDisconnectException&) {
            return;
        }
    });
    require(blocked.wait_for(std::chrono::milliseconds(100)) == std::future_status::timeout,
            "socket operation was not blocked before shutdown");
    client.threadSafeShutdown();
    require(blocked.wait_for(std::chrono::seconds(2)) == std::future_status::ready,
            "socket shutdown did not cancel pending I/O");
    blocked.get();
    // A submission racing with or following shutdown must not start another wait.
    try {
        char byte;
        client.receive(&byte, 1);
        throw std::runtime_error("receive after shutdown did not report a disconnect");
    } catch (const PeerDisconnectException&) {}
}

void cancellation(bool useIpc)
{
    for (bool sending : {false, true}) {
        if (useIpc) {
            const auto path = std::filesystem::current_path() /
                ("arras-cancel-" + std::to_string(GetCurrentProcessId()) + ".sock");
            IPCSocketPeer listener, client;
            listener.listen(path.string());
            client.connect(path.string());
            cancelIo(listener, client, sending);
        } else {
            InetSocketPeer listener(static_cast<unsigned short>(0));
            InetSocketPeer client("127.0.0.1", listener.localPort());
            cancelIo(listener, client, sending);
        }
    }
}

void http()
{
    HttpServer server(0, 1);
    server.GET += [](const HttpServerRequest& request, HttpServerResponse& response) {
        std::string value;
        if (request.url() == "/health" && request.queryParam("value", value)) response.write(value);
        else response.setResponseCode(404);
    };
    server.POST += [](const HttpServerRequest& request, HttpServerResponse& response) {
        // Arras keeps a trailing NUL in its receive buffer; echo the wire bytes.
        std::string length;
        if (request.header("Content-Length", length)) {
            response.write(request.data(), std::stoi(length));
        }
    };
    const std::string base = "http://127.0.0.1:" + std::to_string(server.getListenPort());
    HttpRequest get(base + "/health");
    get.addParam("value", "Windows Arras + & test");
    const auto& response = get.submit(3);
    std::string body;
    // HttpServer deliberately leaves URI decoding to the application.
    require(response.responseCode() == 200 && response.getResponseString(body) &&
            body == "Windows%20Arras%20%2B%20%26%20test", "HTTP GET query roundtrip failed");
    HttpRequest post(base + "/echo", POST);
    const std::string message = "{\"platform\":\"Windows\"}";
    const auto& echoed = post.submit(message.data(), static_cast<int>(message.size()), 3);
    require(echoed.responseCode() == 200 && echoed.getResponseString(body) && body == message,
            "HTTP POST body roundtrip failed");
}

void sdk()
{
    for (int i = 0; i < 3; ++i) {
        arras4::sdk::SDK client;
        client.setSyncSend();
        client.disconnect();
    }
    arras4::client::SessionDefinition definition;
    definition["renderer"]["resources"]["cores"] = 4;
    const auto directory = std::filesystem::current_path() / "arras test sessions";
    std::filesystem::create_directories(directory);
    const auto path = directory / "runtime.sessiondef";
    definition.saveToFile(path.string());
    arras4::client::SessionDefinition loaded(path.string());
    const auto searched = arras4::client::SessionDefinition::load("runtime",
        (directory / "missing").string() + ";" + directory.string());
    std::filesystem::remove(path);
    std::filesystem::remove(directory);
    require(loaded.has("renderer") && loaded["renderer"]["resources"]["cores"].asInt() == 4,
            "session definition roundtrip failed");
    require(searched.has("renderer"), "session search failed with drive letters and spaces");
}

int main(int argc, char** argv)
{
    WSADATA data{};
    if (WSAStartup(MAKEWORD(2, 2), &data) != 0) return 2;
    int result = 0;
    try {
        const std::string mode = argc == 2 ? argv[1] : "";
        if (mode == "tcp") tcp();
        else if (mode == "ipc") ipc();
        else if (mode == "http") http();
        else if (mode == "sdk") sdk();
        else if (mode == "tcp_cancel") cancellation(false);
        else if (mode == "ipc_cancel") cancellation(true);
        else throw std::runtime_error("expected tcp, ipc, http, sdk, tcp_cancel or ipc_cancel");
        std::cout << mode << " passed\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        result = 1;
    }
    WSACleanup();
    return result;
}
