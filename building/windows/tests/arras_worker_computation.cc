// SPDX-License-Identifier: Apache-2.0
#include <computation_api/Computation.h>
#include <core_messages/SessionStatusMessage.h>
#include "arras_worker_message.h"

#include <filesystem>
#include <fstream>
#include <stdexcept>

// Loaded only by the real execComp child, exercising the public computation ABI.
class WorkerTestComputation final : public arras4::api::Computation
{
public:
    explicit WorkerTestComputation(arras4::api::ComputationEnvironment* env) : Computation(env) {}
    ~WorkerTestComputation() override { record("destroy"); }

    arras4::api::Result configure(const std::string& op, arras4::api::ObjectConstRef config) override
    {
        using namespace arras4::api;
        if (op == "initialize") {
            mEvents = std::filesystem::u8path(config["events"].asString());
            mThrowOnStart = config["throwOnStart"].asBool();
            record("initialize");
            if (config["invalid"].asBool() || config[ConfigNames::maxMemoryMB].asUInt() != 128 ||
                config[ConfigNames::maxThreads].asUInt() != 2 ||
                environment(EnvNames::computationName).asString() != "worker-test")
                return Result::Invalid;
        } else if (op == "start") {
            record("start");
            if (mThrowOnStart) throw std::runtime_error("worker test start exception");
        } else if (op == "stop") {
            record("stop");
        }
        return Result::Success;
    }

    arras4::api::Result onMessage(const arras4::api::Message& message) override
    {
        const auto content = message.contentAs<arras4::impl::SessionStatusMessage>();
        if (!content) return arras4::api::Result::Invalid;
        send(new WorkerTestMessage(content->getValue()));
        return arras4::api::Result::Success;
    }

private:
    void record(const char* event) const
    {
        if (!mEvents.empty()) std::ofstream(mEvents, std::ios::app) << event << '\n';
    }
    std::filesystem::path mEvents;
    bool mThrowOnStart = false;
};

COMPUTATION_CREATOR(WorkerTestComputation)
