// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <core_messages/SessionStatusMessage.h>

// Preserve the upstream message format while exposing its size for chunking.
class WorkerTestMessage final : public arras4::impl::SessionStatusMessage
{
public:
    explicit WorkerTestMessage(const std::string& value) : SessionStatusMessage(value) {}
    size_t serializedLength() const override { return sizeof(uint32_t) + getValue().size(); }
};
