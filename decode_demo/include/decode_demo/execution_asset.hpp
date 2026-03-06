#pragma once

#include "decode_demo/plan_manifest.hpp"

#include <string>
#include <vector>

namespace decode_demo {

struct ExecutionAssetBinding {
    std::string tenant_id;
    std::string site_id;
    std::string box_id;
    std::string device_id;
    std::string capability;
    std::string algorithm_id;
    std::string algorithm_version;
    std::string base_library_id;
    std::string base_library_version;
    std::string stream_path;
    std::string model_path;
    std::string output_path;
};

std::vector<ExecutionAssetBinding> load_execution_asset_map(const std::string& path);
const ExecutionAssetBinding* resolve_execution_asset(const std::vector<ExecutionAssetBinding>& bindings,
                                                     const ManifestWorkload& workload);
std::string resolve_stream_path(const ManifestWorkload& workload, const ExecutionAssetBinding* binding);
std::string resolve_model_path(const ManifestWorkload& workload, const ExecutionAssetBinding* binding);
std::string resolve_output_path(const ManifestWorkload& workload, const ExecutionAssetBinding* binding);

}  // namespace decode_demo
