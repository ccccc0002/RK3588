#include "decode_demo/mpp_decode.hpp"
#include "decode_demo/plan_manifest.hpp"
#include "decode_demo/runtime_probe.hpp"

#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <string>
#include <vector>

namespace {

struct Options {
    bool self_check{false};
    std::string stream;
    std::string model;
    std::string plan_file;
    int rga_width{0};
    int rga_height{0};
};

int parse_positive_int(const char* flag, const std::string& value) {
    try {
        const int parsed = std::stoi(value);
        if (parsed > 0) {
            return parsed;
        }
    } catch (...) {
    }
    std::cerr << "Invalid value for " << flag << ": " << value << '\n';
    std::exit(1);
}

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
        } else if (arg == "--rga-width" && i + 1 < argc) {
            options.rga_width = parse_positive_int("--rga-width", argv[++i]);
        } else if (arg == "--rga-height" && i + 1 < argc) {
            options.rga_height = parse_positive_int("--rga-height", argv[++i]);
        } else if (arg == "--help" || arg == "-h") {
            std::cout << "Usage: rk_decode_demo [--self-check] [--stream <annexb.h264>] [--rga-width <n> --rga-height <n>] [--model <file.rknn>] [--plan-file <plan.manifest.tsv>]\n";
            std::exit(0);
        } else {
            std::cerr << "Unknown argument: " << arg << '\n';
            std::exit(1);
        }
    }
    if ((options.rga_width > 0) != (options.rga_height > 0)) {
        std::cerr << "Both --rga-width and --rga-height must be provided together\n";
        std::exit(1);
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

int run_stream_decode(const std::string& stream_path, int rga_width, int rga_height) {
    print_path_summary("stream", stream_path);
    const decode_demo::DecodePipelineInfo pipeline = decode_demo::decode_pipeline_from_annexb(stream_path, rga_width, rga_height);
    const decode_demo::DecodedFrameInfo& frame = pipeline.frame;
    std::cout << "decode_ok=" << (frame.ok ? "true" : "false") << '\n';
    std::cout << "decode_coding=" << frame.coding << '\n';
    std::cout << "decode_pixel_format=" << frame.pixel_format << '\n';
    std::cout << "decode_detail=" << frame.detail << '\n';
    std::cout << "decode_width=" << frame.width << '\n';
    std::cout << "decode_height=" << frame.height << '\n';
    std::cout << "decode_hor_stride=" << frame.hor_stride << '\n';
    std::cout << "decode_ver_stride=" << frame.ver_stride << '\n';
    std::cout << "decode_dma_fd=" << frame.dma_fd << '\n';
    std::cout << "rga_requested=" << (pipeline.rga.requested ? "true" : "false") << '\n';
    if (pipeline.rga.requested) {
        std::cout << "rga_ok=" << (pipeline.rga.ok ? "true" : "false") << '\n';
        std::cout << "rga_detail=" << pipeline.rga.detail << '\n';
        std::cout << "rga_output_width=" << pipeline.rga.output_width << '\n';
        std::cout << "rga_output_height=" << pipeline.rga.output_height << '\n';
        std::cout << "rga_output_channels=" << pipeline.rga.output_channels << '\n';
        std::cout << "rga_output_bytes=" << pipeline.rga.output_bytes << '\n';
    }
    const bool ok = frame.ok && (!pipeline.rga.requested || pipeline.rga.ok);
    return ok ? 0 : 2;
}

}  // namespace

int main(int argc, char** argv) {
    const Options options = parse_args(argc, argv);

    if (options.self_check) {
        return decode_demo::run_self_check(std::cout);
    }

    std::cout << "rk_decode_demo pipeline prototype\n";
    print_path_summary("model", options.model);
    print_manifest_summary(options.plan_file);

    if (!options.stream.empty()) {
        return run_stream_decode(options.stream, options.rga_width, options.rga_height);
    }

    std::cout << "status=waiting_for_stream\n";
    std::cout << "next=provide --stream <annexb.h264> to execute MPP first-frame decode, then extend to RGA and RKNN\n";
    return 0;
}
