// SPDX-License-Identifier: Apache-2.0
#include "WindowsSharedMemory.h"
#include <windows.h>
#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace shm = scene_rdl2::grid_util::windows_shm;
void require(bool value, const char* message)
{
    if (!value) throw std::runtime_error(std::string(message) + " errno=" + std::to_string(errno));
}
struct Child {
    PROCESS_INFORMATION process{};
    explicit Child(const std::wstring& args)
    {
        wchar_t exe[32768];
        require(GetModuleFileNameW(nullptr, exe, 32768) != 0, "executable path");
        std::wstring command = L"\"" + std::wstring(exe) + L"\" " + args;
        STARTUPINFOW startup{};
        startup.cb = sizeof(startup);
        require(CreateProcessW(nullptr, command.data(), nullptr, nullptr, FALSE, CREATE_NO_WINDOW,
                               nullptr, nullptr, &startup, &process), "start child");
    }
    ~Child()
    {
        if (WaitForSingleObject(process.hProcess, 0) == WAIT_TIMEOUT) {
            TerminateProcess(process.hProcess, 99);
            WaitForSingleObject(process.hProcess, 5000);
        }
        CloseHandle(process.hThread);
        CloseHandle(process.hProcess);
    }
    void wait()
    {
        require(WaitForSingleObject(process.hProcess, 10000) == WAIT_OBJECT_0, "child completion");
        DWORD result = 0;
        require(GetExitCodeProcess(process.hProcess, &result) && result == 0, "child status");
    }
};
int main(int argc, char** argv)
{
    std::vector<int> cleanup;
    try {
        if (argc > 1) {
            const int id = std::stoi(argv[2]);
            if (std::string(argv[1]) == "read") {
                auto* data = static_cast<const char*>(shm::shmat(id, nullptr, shm::SHM_RDONLY));
                require(data != reinterpret_cast<void*>(-1), "child read attach");
                require(std::string(data) == "persistent renderer state", "cross-process data");
                MEMORY_BASIC_INFORMATION mbi{};
                require(VirtualQuery(data, &mbi, sizeof(mbi)) && mbi.Protect == PAGE_READONLY, "read-only protection");
                require(shm::shmdt(data) == 0, "child detach");
            } else if (std::string(argv[1]) == "hold-semaphore") {
                shm::sembuf operation{0, -1, shm::SEM_UNDO};
                require(shm::semop(id, &operation, 1) == 0, "child semaphore acquire");
                HANDLE event = OpenEventA(EVENT_MODIFY_STATE, FALSE, argv[3]);
                require(event && SetEvent(event), "signal semaphore acquired");
                CloseHandle(event);
                Sleep(INFINITE);
            } else if (std::string(argv[1]) == "increment") {
                const int memoryId = std::stoi(argv[3]);
                auto* counter = static_cast<int*>(shm::shmat(memoryId, nullptr, 0));
                require(counter != reinterpret_cast<void*>(-1), "counter attach");
                shm::sembuf acquire{0, -1, shm::SEM_UNDO}, release{0, 1, shm::SEM_UNDO};
                for (int i = 0; i < 300; ++i) {
                    require(shm::semop(id, &acquire, 1) == 0, "counter lock");
                    const int value = *counter;
                    SwitchToThread();
                    *counter = value + 1;
                    require(shm::semop(id, &release, 1) == 0, "counter unlock");
                }
                require(shm::shmdt(counter) == 0, "counter detach");
            } else if (std::string(argv[1]) == "crash") {
                auto* data = static_cast<char*>(shm::shmat(id, nullptr, 0));
                require(data != reinterpret_cast<void*>(-1), "crash child attach");
                strcpy_s(data, 1024, "survives forced termination");
                HANDLE event = OpenEventA(EVENT_MODIFY_STATE, FALSE, argv[3]);
                require(event && SetEvent(event), "signal attachment");
                CloseHandle(event);
                Sleep(INFINITE);
            }
            return 0;
        }
        const int key = -static_cast<int>(GetCurrentProcessId()); // negative legacy keys remain distinct
        int id = shm::shmget(key, 1024, shm::IPC_CREAT | shm::IPC_EXCL | 0644);
        require(id > 0, "keyed create");
        cleanup.push_back(id);
        require(shm::shmget(key, 0, 0) == id, "key lookup");
        require(shm::shmget(key, 1024, shm::IPC_CREAT | shm::IPC_EXCL) == -1 && errno == EEXIST, "exclusive create");
        require(shm::shmget(key, 2048, 0) == -1 && errno == EINVAL, "size validation");
        auto* data = static_cast<char*>(shm::shmat(id, nullptr, 0));
        require(data != reinterpret_cast<void*>(-1), "attach");
        require(reinterpret_cast<uintptr_t>(data) % 65536 == 0, "payload alignment");
        for (int i = 0; i < 1024; ++i) require(data[i] == 0, "initial zero fill");
        strcpy_s(data, 1024, "persistent renderer state");
        auto* second = shm::shmat(id, nullptr, shm::SHM_RDONLY);
        require(second != reinterpret_cast<void*>(-1), "second local attach");
        shm::shmid_ds info;
        require(shm::shmctl(id, shm::IPC_STAT, &info) == 0 && info.shm_nattch == 2 &&
                info.shm_segsz == 1024 && info.owner.starts_with("S-1-"), "metadata and local leases");
        require(!shm::removeUnused(id) && errno == EBUSY, "active segment protected");
        Child reader(L"read " + std::to_wstring(id));
        reader.wait();
        require(shm::shmdt(second) == 0 && shm::shmdt(data) == 0, "detach both");
        require(shm::shmctl(id, shm::IPC_STAT, &info) == 0 && info.shm_nattch == 0, "persist without attachments");
        Child persistedReader(L"read " + std::to_wstring(id));
        persistedReader.wait();
        const auto eventName = "Local\\MoonRayShmTest-" + std::to_string(GetCurrentProcessId());
        HANDLE event = CreateEventA(nullptr, TRUE, FALSE, eventName.c_str());
        require(event != nullptr, "create event");
        {
            Child crashing(L"crash " + std::to_wstring(id) + L" " + std::wstring(eventName.begin(), eventName.end()));
            require(WaitForSingleObject(event, 10000) == WAIT_OBJECT_0, "child attached");
            require(shm::shmctl(id, shm::IPC_STAT, &info) == 0 && info.shm_nattch == 1, "remote lease");
            require(!shm::removeUnused(id) && errno == EBUSY, "remote active segment protected");
        } // forcible termination, bypassing all destructors
        CloseHandle(event);
        require(shm::shmctl(id, shm::IPC_STAT, &info) == 0 && info.shm_nattch == 0, "crash releases lease");
        data = static_cast<char*>(shm::shmat(id, nullptr, shm::SHM_RDONLY));
        require(data != reinterpret_cast<void*>(-1) && std::string(data) == "survives forced termination", "crash persistence");
        require(shm::shmdt(data) == 0, "crash data detach");
        auto ids = shm::list();
        require(std::find(ids.begin(), ids.end(), id) != ids.end(), "enumeration");
        require(shm::removeUnused(id), "unused cleanup");
        require(shm::shmget(key, 0, 0) == -1 && errno == ENOENT, "key removed");
        id = shm::shmget(shm::IPC_PRIVATE, 4096, 0600);
        require(id > 0, "private create");
        cleanup.push_back(id);
        data = static_cast<char*>(shm::shmat(id, nullptr, 0));
        require(data != reinterpret_cast<void*>(-1), "private attach");
        require(shm::shmctl(id, shm::IPC_RMID, nullptr) == 0, "deferred removal");
        data[0] = 42;
        require(shm::shmat(id, nullptr, 0) == reinterpret_cast<void*>(-1), "no new attach after removal");
        require(data[0] == 42 && shm::shmdt(data) == 0, "existing view survives removal");
        require(shm::shmctl(id, shm::IPC_STAT, &info) == -1 && errno == ENOENT, "final detach deletes storage");

        // Semaphores and shared memory have independent key namespaces.
        id = shm::shmget(key, sizeof(int), shm::IPC_CREAT | shm::IPC_EXCL | 0600);
        require(id > 0, "counter create");
        cleanup.push_back(id);
        const int semaphore = shm::semget(key, 1, shm::IPC_CREAT | shm::IPC_EXCL | 0600);
        require(semaphore > 0 && semaphore != id, "separate semaphore key namespace");
        cleanup.push_back(semaphore);
        require(shm::semget(key, 0, 0) == semaphore, "semaphore lookup");
        require(shm::semget(key, 1, shm::IPC_CREAT | shm::IPC_EXCL) == -1 && errno == EEXIST, "exclusive semaphore");
        require(shm::semctl(semaphore, 0, shm::SETVAL, 1) == 0, "initialize semaphore");
        auto semaphoreIds = shm::listSemaphores();
        require(std::find(semaphoreIds.begin(), semaphoreIds.end(), semaphore) != semaphoreIds.end(), "semaphore enumeration");
        const auto childArgs = L"increment " + std::to_wstring(semaphore) + L" " + std::to_wstring(id);
        Child first(childArgs), secondChild(childArgs), third(childArgs);
        first.wait(); secondChild.wait(); third.wait();
        auto* counter = static_cast<int*>(shm::shmat(id, nullptr, shm::SHM_RDONLY));
        require(counter != reinterpret_cast<void*>(-1) && *counter == 900, "mutual exclusion across processes");
        require(shm::shmdt(counter) == 0 && shm::removeUnused(id), "counter cleanup");
        event = CreateEventA(nullptr, TRUE, FALSE, eventName.c_str());
        require(event != nullptr, "create semaphore event");
        shm::sembuf acquire{0, -1, shm::SEM_UNDO}, release{0, 1, shm::SEM_UNDO};
        timespec timeout{0, 50000000};
        {
            Child holder(L"hold-semaphore " + std::to_wstring(semaphore) + L" " + std::wstring(eventName.begin(), eventName.end()));
            require(WaitForSingleObject(event, 10000) == WAIT_OBJECT_0, "remote semaphore acquired");
            const auto start = std::chrono::steady_clock::now();
            require(shm::semtimedop(semaphore, &acquire, 1, &timeout) == -1 && errno == EAGAIN, "semaphore timeout");
            require(std::chrono::steady_clock::now() - start >= std::chrono::milliseconds(45), "timeout duration");
        }
        CloseHandle(event);
        require(shm::semtimedop(semaphore, &acquire, 1, &timeout) == 0, "termination releases semaphore");
        require(shm::semop(semaphore, &release, 1) == 0, "semaphore release");
        require(shm::semctl(semaphore, 0, shm::IPC_RMID) == 0, "semaphore cleanup");
        require(shm::semget(key, 0, 0) == -1 && errno == ENOENT, "semaphore removed");
        std::cout << "Windows shared memory: cross-process, read-only, crash persistence, leases and cleanup passed\n";
        std::cout << "Windows semaphores: contention, mutual exclusion, timeout and crash recovery passed\n";
        return 0;
    } catch (const std::exception& e) {
        std::cerr << e.what() << '\n';
        for (int id : cleanup) {
            shm::shmctl(id, shm::IPC_RMID, nullptr);
            shm::semctl(id, 0, shm::IPC_RMID);
        }
        return 1;
    }
}
