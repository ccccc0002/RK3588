#include "decode_demo/plan_manifest.hpp"
#include "decode_demo/runtime_probe.hpp"

#include <algorithm>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

namespace {

struct Options {
    bool self_check{false};
    std::string stream;
    std::string model;
    std::string plan_file;
};

Options parse_args(int argc, char** argv) {
    Options options;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--self-check") {
            options.self_check = true;
        } else if (arg == "--stream" && i + 1 < argc) {
            options.stream = argv[++i];
        } else if (arg == "--model" && i + 1 < argc) {
            options.model = argv[++i];
        } else if (arg == "--plan-file" && i + 1 < argc) {
            options.plan_file = argv[++i];
        } else if (arg == "--help" || arg == "-h") {
            std::cout << "Usage: rk_decode_demo [--self-check] [--stream <url_or_path>] [--model <file.rknn>] [--plan-file <plan.manifest.tsv>]\n";
            std::exit(0);
        } else {
            std::cerr << "Unknown argument: " << arg << '\n';
            std::exit(1);
        }
    }
    return options;
}

void print_path_summary(const std::string& label, const std::string& value) {
    if (value.empty()) {
        return;
    }
    std::cout << label << '=' << value;
    if (std::filesystem::exists(value) && std::filesystem::is_regular_file(value)) {
        std::cout << " exists=true size=" << std::filesystem::file_size(value);
    } else {
        std::cout << " exists=" << (std::filesystem::exists(value) ? "true" : "false");
    }
    std::cout << '\n';
}

void print_manifest_summary(const std::string& plan_file) {
    if (plan_file.empty()) {
        return;
    }
    const decode_demo::PlanManifest manifest = decode_demo::load_plan_manifest(plan_file);
    const std::vector<decode_demo::ManifestWorkload> ready = decode_demo::collect_ready_workloads(manifest);
    std::cout << "plan_file=" << plan_file << '\n';
    std::cout << "manifest_budget=" << manifest.budget << '\n';
    std::cout << "manifest_degraded=" << (manifest.degraded ? "true" : "false") << '\n';
    std::cout << "manifest_stream_count=" << manifest.stream_count << '\n';
    std::cout << "manifest_ready_stream_count=" << manifest.ready_stream_count << '\n';
    std::cout << "manifest_workload_count=" << manifest.workloads.size() << '\n';
    std::cout << "manifest_ready_workload_count=" << ready.size() << '\n';
    if (!ready.empty()) {
        const auto& first = ready.front();
        std::cout << "selected_device_id=" << first.device_id << '\n';
        std::cout << "selected_capability=" << first.capability << '\n';
        std::cout << "selected_algorithm_id=" << first.algorithm_id << '\n';
        std::cout << "selected_algorithm_version=" << first.algorithm_version << '\n';
        std::cout << "selected_base_library_id=" << first.base_library_id << '\n';
        std::cout << "selected_stream_url=" << first.stream_url << '\n';
        std::cout << "selected_sample_fps=" << first.sample_fps << '\n';
    }
}

}  // namespace

int main(int argc, char** argv) {
    const Options options = parse_args(argc, argv);

    if (options.self_check) {
        return decode_demo::run_self_check(std::cout);
    }

    std::cout << "rk_decode_demo pipeline skeleton\n";
    print_path_summary("model", options.model);
    if (!options.stream.empty()) {
        std::cout << "stream=" << options.stream << '\n';
    }
    print_manifest_summary(options.plan_file);
    std::cout << "status=not_yet_executing_real_pipeline\n";
    std::cout << "next=implement MPP demux/decode, RGA resize, and RKNN init/run using the selected ready workload\n";
    return 0;
}
