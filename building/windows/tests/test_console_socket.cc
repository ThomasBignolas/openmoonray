#include <winsock2.h>
#include <scene_rdl2/common/grid_util/TlSvr.h>

#include <chrono>
#include <iostream>
#include <stdexcept>
#include <thread>

static void require(bool value)
{
    if (!value) throw std::runtime_error("Console socket invariant failed");
}

int main()
{
    scene_rdl2::grid_util::TlSvr server;
    std::string line;
    require(server.recv(line) == 0); // Disabled until opened.
    const int port = server.open(0);
    require(port > 0);
    auto connectClient = [&] {
        SOCKET client = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
        require(client != INVALID_SOCKET);
        sockaddr_in address{};
        address.sin_family = AF_INET;
        address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        address.sin_port = htons(static_cast<u_short>(port));
        require(connect(client, reinterpret_cast<sockaddr*>(&address), sizeof(address)) == 0);
        return client;
    };
    auto receiveLine = [&] {
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
        while (std::chrono::steady_clock::now() < deadline) {
            const int count = server.recv(line);
            if (count != 0) return count;
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        throw std::runtime_error("Console receive timed out");
    };
    SOCKET client = connectClient();
    require(::send(client, "hel", 3, 0) == 3);
    require(server.recv(line) == 0);
    line.clear(); // DebugConsoleDriver supplies a fresh string on each poll.
    require(::send(client, "lo\r\nnext\n", 9, 0) == 9);
    require(receiveLine() == 6 && line == "hello\n");
    require(receiveLine() == 5 && line == "next\n");
    require(server.isConnectionEstablised());
    require(server.send("reply\n"));
    char reply[6];
    require(::recv(client, reply, sizeof(reply), MSG_WAITALL) == sizeof(reply));
    require(std::string(reply, sizeof(reply)) == "reply\n");
    closesocket(client);
    require(receiveLine() == -1);
    require(!server.isConnectionEstablised());
    require(server.recv(line) == 0); // Reopen the listener after disconnect.
    client = connectClient();
    require(::send(client, "tail", 4, 0) == 4);
    shutdown(client, SD_SEND);
    require(receiveLine() == 5 && line == "tail\n");
    closesocket(client);
    server.close();
    require(server.recv(line) == 0);
    std::cout << "Loopback fragmentation, replies, EOF and reconnection passed\n";
}
