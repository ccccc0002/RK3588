#include "decode_demo/plan_manifest.hpp"

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

bool parse_bool(const std::string& value) {
    return value == "true" || value == "True" || value == "1" || value == "yes";
}

double parse_double(const std::string& value) {
    return value.empty() ? 0.0 : std::stod(value);
}

int parse_int(const std::string& value) {
    return value.empty() ? 0 : std::stoi(value);
}

}  // namespace

PlanManifest load_plan_manifest(const std::string& path) {
    std::ifstream input(path);
    if (!input.is_open()) {
        throw std::runtime_error("failed to open manifest: " + path);
    }

    PlanManifest manifest;
    std::string line;
    while (std::getline(input, line)) {
        if (line.empty() || line[0] == '#') {
            continue;
        }
        const auto fields = split_tab(line);
        if (fields.empty()) {
            continue;
        }
        if (fields[0] == "meta") {
            if (fields.size() < 3) {
                continue;
            }
            const std::string& key = fields[1];
            const std::string& value = fields[2];
            if (key == "budget") {
                manifest.budget = parse_double(value);
            } else if (key == "degraded") {
                manifest.degraded = parse_bool(value);
            } else if (key == "total_cost") {
                manifest.total_cost = parse_double(value);
            } else if (key == "stream_count") {
                manifest.stream_count = parse_int(value);
            } else if (key == "ready_stream_count") {
                manifest.ready_stream_count = parse_int(value);
            }
            continue;
        }
        if (fields[0] == "workload") {
            if (fields.size() < 18) {
                throw std::runtime_error("invalid workload line in manifest: " + line);
            }
            ManifestWorkload item;
            item.tenant_id = fields[1];
            item.site_id = fields[2];
            item.box_id = fields[3];
            item.device_id = fields[4];
            item.protocol = fields[5];
            item.stream_url = fields[6];
            item.fps_in = parse_double(fields[7]);
            item.sample_fps = parse_double(fields[8]);
            item.estimated_cost = parse_double(fields[9]);
            item.priority = parse_int(fields[10]);
            item.complexity = parse_double(fields[11]);
            item.capability = fields[12];
            item.algorithm_id = fields[13];
            item.algorithm_version = fields[14];
            item.base_library_id = fields[15];
            item.base_library_version = fields[16];
            item.binding_status = fields[17];
            if (fields.size() > 18) {
                item.execution_ready = parse_bool(fields[18]);
            }
            if (fields.size() > 19) {
                item.stream_uri = fields[19];
            }
            if (fields.size() > 20) {
                item.model_uri = fields[20];
            }
            if (fields.size() > 21) {
                item.result_uri = fields[21];
            }
            if (fields.size() > 22) {
                item.sample_period_ms = parse_int(fields[22]);
            }
            if (fields.size() > 23) {
                item.frames_per_sample = parse_int(fields[23]);
            }
            if (fields.size() > 24) {
                item.max_samples_per_run = parse_int(fields[24]);
            }
            manifest.workloads.push_back(item);
        }
    }
    return manifest;
}

std::vector<ManifestWorkload> collect_ready_workloads(const PlanManifest& manifest) {
    std::vector<ManifestWorkload> ready;
    for (const auto& item : manifest.workloads) {
        if (item.binding_status == "ready") {
            ready.push_back(item);
        }
    }
    return ready;
}

}  // namespace decode_demo
