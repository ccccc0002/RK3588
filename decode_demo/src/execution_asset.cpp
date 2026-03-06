#include "decode_demo/execution_asset.hpp"

#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace decode_demo {
namespace {

std::vector<std::string> split_tab(const std::string& line) {
    std::vector<std::string> parts;
    std::string current;
    for (char ch : line) {
        if (ch == '\t') {
            parts.push_back(current);
            current.clear();
        } else {
            current.push_back(ch);
        }
    }
    parts.push_back(current);
    return parts;
}

bool field_matches(const std::string& expected, const std::string& actual) {
    return expected.empty() || expected == actual;
}

int match_score(const ExecutionAssetBinding& binding, const ManifestWorkload& workload) {
    if (!field_matches(binding.tenant_id, workload.tenant_id) ||
        !field_matches(binding.site_id, workload.site_id) ||
        !field_matches(binding.box_id, workload.box_id) ||
        !field_matches(binding.device_id, workload.device_id) ||
        !field_matches(binding.capability, workload.capability) ||
        !field_matches(binding.algorithm_id, workload.algorithm_id) ||
        !field_matches(binding.algorithm_version, workload.algorithm_version) ||
        !field_matches(binding.base_library_id, workload.base_library_id) ||
        !field_matches(binding.base_library_version, workload.base_library_version)) {
        return -1;
    }

    int score = 0;
    score += binding.tenant_id.empty() ? 0 : 1;
    score += binding.site_id.empty() ? 0 : 1;
    score += binding.box_id.empty() ? 0 : 1;
    score += binding.device_id.empty() ? 0 : 2;
    score += binding.capability.empty() ? 0 : 3;
    score += binding.algorithm_id.empty() ? 0 : 3;
    score += binding.algorithm_version.empty() ? 0 : 1;
    score += binding.base_library_id.empty() ? 0 : 2;
    score += binding.base_library_version.empty() ? 0 : 1;
    return score;
}

bool looks_like_local_path(const std::string& value) {
    return !value.empty() &&
           (value.rfind("/", 0) == 0 || value.rfind("./", 0) == 0 || value.rfind("../", 0) == 0 ||
            value.find(":\\") != std::string::npos || value.find(".h264") != std::string::npos ||
            value.find(".hevc") != std::string::npos || value.find(".265") != std::string::npos);
}

bool starts_with(const std::string& value, const std::string& prefix) {
    return value.size() >= prefix.size() && value.compare(0, prefix.size(), prefix) == 0;
}

}  // namespace

std::vector<ExecutionAssetBinding> load_execution_asset_map(const std::string& path) {
    if (path.empty()) {
        return {};
    }

    std::ifstream input(path);
    if (!input.is_open()) {
        throw std::runtime_error("failed to open asset map: " + path);
    }

    std::vector<ExecutionAssetBinding> bindings;
    std::string line;
    while (std::getline(input, line)) {
        if (line.empty() || line[0] == '#') {
            continue;
        }
        const auto fields = split_tab(line);
        if (fields.empty() || fields[0] != "binding") {
            continue;
        }
        if (fields.size() < 13) {
            throw std::runtime_error("invalid binding line in asset map: " + line);
        }
        ExecutionAssetBinding binding;
        binding.tenant_id = fields[1];
        binding.site_id = fields[2];
        binding.box_id = fields[3];
        binding.device_id = fields[4];
        binding.capability = fields[5];
        binding.algorithm_id = fields[6];
        binding.algorithm_version = fields[7];
        binding.base_library_id = fields[8];
        binding.base_library_version = fields[9];
        binding.stream_path = fields[10];
        binding.model_path = fields[11];
        binding.output_path = fields[12];
        bindings.push_back(binding);
    }
    return bindings;
}

const ExecutionAssetBinding* resolve_execution_asset(const std::vector<ExecutionAssetBinding>& bindings,
                                                     const ManifestWorkload& workload) {
    const ExecutionAssetBinding* best = nullptr;
    int best_score = -1;
    for (const auto& binding : bindings) {
        const int score = match_score(binding, workload);
        if (score > best_score) {
            best = &binding;
            best_score = score;
        }
    }
    return best_score >= 0 ? best : nullptr;
}

std::string resolve_stream_path(const ManifestWorkload& workload, const ExecutionAssetBinding* binding) {
    if (binding != nullptr && !binding->stream_path.empty()) {
        return binding->stream_path;
    }
    if (starts_with(workload.stream_url, "file://")) {
        return workload.stream_url.substr(7);
    }
    if (looks_like_local_path(workload.stream_url)) {
        return workload.stream_url;
    }
    return {};
}

std::string resolve_model_path(const ManifestWorkload& workload, const ExecutionAssetBinding* binding) {
    (void)workload;
    return binding == nullptr ? std::string() : binding->model_path;
}

std::string resolve_output_path(const ManifestWorkload& workload, const ExecutionAssetBinding* binding) {
    if (binding != nullptr && !binding->output_path.empty()) {
        return binding->output_path;
    }
    if (workload.device_id.empty()) {
        return {};
    }
    return "artifacts/results/" + workload.device_id + ".json";
}

}  // namespace decode_demo
