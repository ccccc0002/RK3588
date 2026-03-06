#include "decode_demo/execution_asset.hpp"
#include "decode_demo/mpp_decode.hpp"
#include "decode_demo/plan_manifest.hpp"
#include "decode_demo/result_json.hpp"
#include "decode_demo/rknn_runner.hpp"
#include "decode_demo/runtime_probe.hpp"

#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace {

struct Options {
    bool self_check{false};
    std::string stream;
    std::string model;
    std::string plan_file;
    std::string asset_map;
    std::string output;
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
        } else if (arg == "--asset-map" && i + 1 < argc) {
            options.asset_map = argv[++i];
        } else if (arg == "--output" && i + 1 < argc) {
            options.output = argv[++i];
        } else if (arg == "--rga-width" && i + 1 < argc) {
            options.rga_width = parse_positive_int("--rga-width", argv[++i]);
        } else if (arg == "--rga-height" && i + 1 < argc) {
            options.rga_height = parse_positive_int("--rga-height", argv[++i]);
        } else if (arg == "--help" || arg == "-h") {
            std::cout
                << "Usage: rk_decode_demo [--self-check] [--stream <annexb.h264>] [--model <file.rknn>] "
                << "[--plan-file <plan.manifest.tsv>] [--asset-map <assets.tsv>] [--output <result.json>] "
                << "[--rga-width <n> --rga-height <n>]\n";
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

void print_manifest_summary(const decode_demo::PlanManifest& manifest) {
    std::cout << "manifest_budget=" << manifest.budget << '\n';
    std::cout << "manifest_degraded=" << (manifest.degraded ? "true" : "false") << '\n';
    std::cout << "manifest_stream_count=" << manifest.stream_count << '\n';
    std::cout << "manifest_ready_stream_count=" << manifest.ready_stream_count << '\n';
    std::cout << "manifest_workload_count=" << manifest.workloads.size() << '\n';
}

void print_selected_workload(const decode_demo::ManifestWorkload& workload) {
    std::cout << "selected_device_id=" << workload.device_id << '\n';
    std::cout << "selected_capability=" << workload.capability << '\n';
    std::cout << "selected_algorithm_id=" << workload.algorithm_id << '\n';
    std::cout << "selected_algorithm_version=" << workload.algorithm_version << '\n';
    std::cout << "selected_base_library_id=" << workload.base_library_id << '\n';
    std::cout << "selected_base_library_version=" << workload.base_library_version << '\n';
    std::cout << "selected_stream_url=" << workload.stream_url << '\n';
    std::cout << "selected_sample_fps=" << workload.sample_fps << '\n';
}

void print_rknn_model_summary(const decode_demo::RknnModelInfo& model) {
    std::cout << "rknn_model_ok=" << (model.ok ? "true" : "false") << '\n';
    std::cout << "rknn_model_detail=" << model.detail << '\n';
    std::cout << "rknn_api_version=" << model.api_version << '\n';
    std::cout << "rknn_driver_version=" << model.driver_version << '\n';
    std::cout << "rknn_input_count=" << model.input_count << '\n';
    std::cout << "rknn_output_count=" << model.output_count << '\n';
    std::cout << "rknn_model_width=" << model.model_width << '\n';
    std::cout << "rknn_model_height=" << model.model_height << '\n';
    std::cout << "rknn_model_channel=" << model.model_channel << '\n';
    std::cout << "rknn_model_input_format=" << model.input_format << '\n';
    std::cout << "rknn_model_input_type=" << model.input_type << '\n';
}

void print_rknn_run_summary(const decode_demo::RknnRunInfo& run) {
    std::cout << "rknn_requested=" << (run.requested ? "true" : "false") << '\n';
    std::cout << "rknn_ok=" << (run.ok ? "true" : "false") << '\n';
    std::cout << "rknn_detail=" << run.detail << '\n';
    std::cout << "rknn_detection_count=" << run.detections.size() << '\n';
    for (std::size_t i = 0; i < run.detections.size(); ++i) {
        const auto& detection = run.detections[i];
        std::cout << "detection_" << i << "_class_id=" << detection.class_id << '\n';
        std::cout << "detection_" << i << "_class_name=" << detection.class_name << '\n';
        std::cout << "detection_" << i << "_confidence=" << detection.confidence << '\n';
        std::cout << "detection_" << i << "_left=" << detection.left << '\n';
        std::cout << "detection_" << i << "_top=" << detection.top << '\n';
        std::cout << "detection_" << i << "_right=" << detection.right << '\n';
        std::cout << "detection_" << i << "_bottom=" << detection.bottom << '\n';
    }
}

struct ResolvedExecution {
    std::string stream_path;
    std::string model_path;
    std::string output_path;
    const decode_demo::ManifestWorkload* workload{nullptr};
};

ResolvedExecution resolve_execution_from_options(const Options& options) {
    ResolvedExecution resolved;
    resolved.stream_path = options.stream;
    resolved.model_path = options.model;
    resolved.output_path = options.output;

    if (options.plan_file.empty()) {
        return resolved;
    }

    const decode_demo::PlanManifest manifest = decode_demo::load_plan_manifest(options.plan_file);
    print_manifest_summary(manifest);
    const auto ready = decode_demo::collect_ready_workloads(manifest);
    std::cout << "manifest_ready_workload_count=" << ready.size() << '\n';
    if (ready.empty()) {
        throw std::runtime_error("manifest contains no ready workloads");
    }

    static decode_demo::ManifestWorkload selected;
    selected = ready.front();
    resolved.workload = &selected;
    print_selected_workload(selected);

    const auto bindings = decode_demo::load_execution_asset_map(options.asset_map);
    const decode_demo::ExecutionAssetBinding* binding = decode_demo::resolve_execution_asset(bindings, selected);
    if (binding != nullptr) {
        std::cout << "asset_binding_resolved=true\n";
    } else if (!options.asset_map.empty()) {
        std::cout << "asset_binding_resolved=false\n";
    }

    if (resolved.stream_path.empty()) {
        resolved.stream_path = decode_demo::resolve_stream_path(selected, binding);
    }
    if (resolved.model_path.empty()) {
        resolved.model_path = decode_demo::resolve_model_path(selected, binding);
    }
    if (resolved.output_path.empty()) {
        resolved.output_path = decode_demo::resolve_output_path(selected, binding);
    }
    return resolved;
}

int run_stream_pipeline(const std::string& stream_path,
                        const std::string& model_path,
                        const std::string& output_path,
                        const decode_demo::ManifestWorkload* workload,
                        int requested_rga_width,
                        int requested_rga_height) {
    print_path_summary("stream", stream_path);
    if (!model_path.empty()) {
        print_path_summary("model", model_path);
    }
    print_path_summary("output", output_path);

    int effective_rga_width = requested_rga_width;
    int effective_rga_height = requested_rga_height;
    decode_demo::RknnModelInfo model_info;

    if (!model_path.empty()) {
        model_info = decode_demo::inspect_rknn_model(model_path);
        print_rknn_model_summary(model_info);
        if (!model_info.ok) {
            return 2;
        }
        if (effective_rga_width == 0 && effective_rga_height == 0) {
            effective_rga_width = model_info.model_width;
            effective_rga_height = model_info.model_height;
        }
    }

    const decode_demo::DecodePipelineInfo pipeline =
        decode_demo::decode_pipeline_from_annexb(stream_path, effective_rga_width, effective_rga_height);
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
        std::cout << "rga_scaled_width=" << pipeline.rga.scaled_width << '\n';
        std::cout << "rga_scaled_height=" << pipeline.rga.scaled_height << '\n';
        std::cout << "rga_pad_x=" << pipeline.rga.pad_x << '\n';
        std::cout << "rga_pad_y=" << pipeline.rga.pad_y << '\n';
        std::cout << "rga_scale=" << pipeline.rga.scale << '\n';
    }

    bool ok = frame.ok && (!pipeline.rga.requested || pipeline.rga.ok);
    decode_demo::RknnRunInfo run;
    if (!model_path.empty()) {
        run = decode_demo::run_rknn_inference(
            model_path,
            pipeline.rga.output_data,
            pipeline.rga.output_width,
            pipeline.rga.output_height,
            pipeline.rga.output_channels,
            pipeline.rga.scale,
            pipeline.rga.pad_x,
            pipeline.rga.pad_y,
            frame.width,
            frame.height);
        print_rknn_run_summary(run);
        ok = ok && run.ok;
        decode_demo::write_detection_result_json(output_path, workload, frame, pipeline.rga, &run);
    } else {
        decode_demo::write_detection_result_json(output_path, workload, frame, pipeline.rga, nullptr);
    }
    return ok ? 0 : 2;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const Options options = parse_args(argc, argv);

        if (options.self_check) {
            return decode_demo::run_self_check(std::cout);
        }

        std::cout << "rk_decode_demo pipeline prototype\n";
        const ResolvedExecution resolved = resolve_execution_from_options(options);

        if (!resolved.stream_path.empty()) {
            return run_stream_pipeline(
                resolved.stream_path,
                resolved.model_path,
                resolved.output_path,
                resolved.workload,
                options.rga_width,
                options.rga_height);
        }

        print_path_summary("model", resolved.model_path);
        print_path_summary("asset_map", options.asset_map);
        print_path_summary("output", resolved.output_path);
        std::cout << "status=waiting_for_stream\n";
        std::cout << "next=provide --stream directly or use --plan-file with --asset-map to resolve stream/model/output automatically\n";
        return 0;
    } catch (const std::exception& ex) {
        std::cerr << "fatal=" << ex.what() << '\n';
        return 2;
    }
}
