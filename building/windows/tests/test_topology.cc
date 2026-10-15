#include <scene_rdl2/common/grid_util/CpuSocketUtil.h>
#include <scene_rdl2/common/grid_util/NumaUtil.h>
#include <scene_rdl2/common/grid_util/WindowsCpuTopology.h>

#include <cstring>
#include <iostream>
#include <set>
#include <stdexcept>

static void require(bool condition)
{
    if (!condition) throw std::runtime_error("CPU/NUMA topology invariant failed");
}

int main()
{
    using namespace scene_rdl2::grid_util;
    CpuSocketUtil sockets;
    NumaUtil numa;
    const auto count = GetActiveProcessorCount(ALL_PROCESSOR_GROUPS);
    require(sockets.getTotalCores() == count && sockets.getTotalSockets() > 0);
    std::set<unsigned> discovered;
    for (auto id : windows_cpu::nodeIds()) {
        const NumaNode* node = numa.getNumaNode(id);
        require(node != nullptr);
        for (auto cpu : node->getCpuIdList()) {
            require(discovered.insert(cpu).second);
            require(sockets.findSocketByCpuId(cpu) != nullptr);
            require(numa.findNumaNodeByCpuId(cpu)->getNodeId() == id);
        }
        const size_t bytes = windows_cpu::pageSize() * 2;
        void* memory = node->alloc(bytes);
        require(reinterpret_cast<uintptr_t>(memory) % windows_cpu::pageSize() == 0);
        std::memset(memory, 0x5a, bytes); // Populate the pages before querying placement.
        const unsigned actualNode = NumaUtil::findNumaNodeByMemAddr(memory);
        require(numa.getNumaNode(actualNode) != nullptr);
        require(numa.getNumaNode(actualNode)->isBelongMem(memory, bytes));
        node->free(memory, bytes);
    }
    require(discovered.size() == count);
    std::cout << "Discovered " << count << " CPUs, " << sockets.getTotalSockets()
              << " sockets and " << numa.getTotalNumaNode() << " NUMA nodes\n";
}
