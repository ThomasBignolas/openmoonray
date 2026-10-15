#include <scene_rdl2/render/util/TimeUtil.h>
#include <scene_rdl2/render/util/shared_mutex.h>
#include <scene_rdl2/common/grid_util/Process.h>
#include <scene_rdl2/common/grid_util/UserUtil.h>

#include <windows.h>
#include <cstdlib>
#include <iostream>
#include <thread>

static void require(bool condition)
{
    if (!condition) {
        std::cerr << "Runtime utility invariant failed\n";
        std::abort();
    }
}

int main()
{
    using namespace scene_rdl2;
    const auto now = time_util::getCurrentTime();
    require(now.tv_usec >= 0 && now.tv_usec < 1000000);
    require(std::abs(std::difftime(now.tv_sec, std::time(nullptr))) < 2);
    time_util::TimeVal future{4102444800LL, 123000}; // January 2100, beyond 32-bit seconds.
    require(time_util::timeStr(future).find("2100/") == 0 ||
            time_util::timeStr(future).find("2099/") == 0);
    time_util::init(future);
    require(future.tv_sec == 0 && future.tv_usec == 0);

    fauxstd::shared_mutex mutex;
    mutex.lock_shared();
    std::thread reader([&] {
        require(!mutex.try_lock());
        fauxstd::shared_lock<fauxstd::shared_mutex> lock(mutex, std::try_to_lock);
        require(lock.owns_lock());
        auto moved = std::move(lock);
        require(moved.owns_lock() && !lock.owns_lock());
    });
    reader.join();
    mutex.unlock_shared();
    mutex.lock();
    std::thread blockedReader([&] {
        require(!mutex.try_lock_shared());
        require(!mutex.try_lock());
    });
    blockedReader.join();
    mutex.unlock();
    require(mutex.try_lock());
    mutex.unlock();

    require(grid_util::processExists(GetCurrentProcessId()));
    require(!grid_util::processExists(0));
    require(!grid_util::processExists(0xffffffffu));
    require(!grid_util::UserUtil::getUserName().empty());
}
