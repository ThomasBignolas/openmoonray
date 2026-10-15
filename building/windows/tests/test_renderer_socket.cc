// SPDX-License-Identifier: Apache-2.0
#include "rendering/rndr/statistics/SocketStream.h"
#include <future>
#include <iostream>
#include <stdexcept>
#include <string>
using namespace moonray::stats;
void require(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
int main()
{
    try {
        ListeningSocket listener;
        const int port = listener.getPortNumber();
        require(port > 0, "automatic port");
        ListeningSocket moved(std::move(listener));
        require(!listener && moved, "listener move ownership");
        const std::string payload(100000, 'x');
        auto server = std::async(std::launch::async, [&] {
            SocketStream stream(Socket::as_server(moved));
            std::string received;
            std::getline(stream, received);
            require(received == payload, "large buffered write");
            for (char ch : std::string("abc")) {
                stream << ch << std::flush;
                require(stream.get() == ch, "short-read acknowledgement");
            }
            stream << "complete\n" << std::flush;
        });
        {
            Socket client = Socket::as_client("localhost", port);
            Socket movedClient(std::move(client));
            require(!client && movedClient, "socket move ownership");
            SocketStream stream(std::move(movedClient));
            stream << payload << '\n' << std::flush;
            for (char ch : std::string("abc")) {
                require(stream.get() == ch, "short read");
                stream.unget();
                require(stream.get() == ch, "putback after short read");
                stream << ch << std::flush;
            }
            std::string response;
            std::getline(stream, response);
            require(response == "complete", "reply");
            require(stream.get() == std::char_traits<char>::eof(), "peer close reaches EOF");
        }
        server.get();
        bool failed = false;
        try { Socket::as_client("127.0.0.1", 0); } catch (const SocketException&) { failed = true; }
        require(failed, "connection failure is reported");
        std::cout << "Renderer sockets: loopback, large writes, short reads, putback, moves, EOF passed\n";
        return 0;
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
