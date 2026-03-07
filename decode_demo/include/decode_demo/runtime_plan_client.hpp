#pragma once

#include "decode_demo/plan_manifest.hpp"

#include <string>

namespace decode_demo {

struct RuntimePlanFetchOptions {
    std::string runtime_url;
    std::string token;
    std::string cache_path{"artifacts/runtime-plan-cache.json"};
    double budget{10.0};
    int max_attempts{3};
    int retry_backoff_ms{500};
};

struct RuntimePlanFetchResult {
    std::string request_url;
    std::string cache_path;
    long http_status{0};
    int attempt_count{0};
    bool used_cache{false};
    std::string response_body;
    PlanManifest manifest;
};

PlanManifest parse_runtime_plan_json(const std::string& payload);
RuntimePlanFetchResult fetch_runtime_plan(const RuntimePlanFetchOptions& options);

}  // namespace decode_demo
