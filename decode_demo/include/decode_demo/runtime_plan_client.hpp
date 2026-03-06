#pragma once

#include "decode_demo/plan_manifest.hpp"

#include <string>

namespace decode_demo {

struct RuntimePlanFetchOptions {
    std::string runtime_url;
    std::string token;
    double budget{10.0};
};

struct RuntimePlanFetchResult {
    std::string request_url;
    long http_status{0};
    std::string response_body;
    PlanManifest manifest;
};

PlanManifest parse_runtime_plan_json(const std::string& payload);
RuntimePlanFetchResult fetch_runtime_plan(const RuntimePlanFetchOptions& options);

}  // namespace decode_demo
