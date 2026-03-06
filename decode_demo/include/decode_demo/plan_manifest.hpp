#pragma once

#include <string>
#include <vector>

namespace decode_demo {

struct ManifestWorkload {
    std::string tenant_id;
    std::string site_id;
    std::string box_id;
    std::string device_id;
    std::string protocol;
    std::string stream_url;
    double fps_in{0.0};
    double sample_fps{0.0};
    double estimated_cost{0.0};
    int priority{0};
    double complexity{0.0};
    std::string capability;
    std::string algorithm_id;
    std::string algorithm_version;
    std::string base_library_id;
    std::string base_library_version;
    std::string binding_status;
    bool execution_ready{false};
    std::string stream_uri;
    std::string model_uri;
    std::string result_uri;
    int sample_period_ms{0};
    int frames_per_sample{0};
    int max_samples_per_run{1};
};

struct PlanManifest {
    double budget{0.0};
    bool degraded{false};
    double total_cost{0.0};
    int stream_count{0};
    int ready_stream_count{0};
    std::vector<ManifestWorkload> workloads;
};

PlanManifest load_plan_manifest(const std::string& path);
std::vector<ManifestWorkload> collect_ready_workloads(const PlanManifest& manifest);

}  // namespace decode_demo
