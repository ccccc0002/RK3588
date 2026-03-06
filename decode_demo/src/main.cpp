#include "decode_demo/mpp_decode.hpp"
#include "decode_demo/plan_manifest.hpp"
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
            std::cout << "Usage: rk_decode_demo [--self-check] [--stream <annexb.h264>] [--model <file.rknn>] [--rga-width <n> --rga-height <n>] [--plan-file <plan.manifest.tsv>]\n";
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
    for (std::size_t i = 0; i < run.outputs.size(); ++i) {
        const auto& output = run.outputs[i];
        std::cout << "rknn_output_" << i << "_name=" << output.name << '\n';
        std::cout << "rknn_output_" << i << "_size=" << output.size << '\n';
        std::cout << "rknn_output_" << i << "_n_elems=" << output.n_elems << '\n';
        std::cout << "rknn_output_" << i << "_format=" << output.format << '\n';
        std::cout << "rknn_output_" << i << "_type=" << output.type << '\n';
        std::cout << "rknn_output_" << i << "_qnt_type=" << output.qnt_type << '\n';
        std::ostringstream values;
        for (std::size_t j = 0; j < output.sample_values.size(); ++j) {
            if (j > 0) {
                values << ',';
            }
            values << output.sample_values[j];
        }
        std::cout << "rknn_output_" << i << "_sample_values=" << values.str() << '\n';
    }
}

int run_stream_pipeline(const std::string& stream_path,
                        const std::string& model_path,
                        int requested_rga_width,
                        int requested_rga_height) {
    print_path_summary("stream", stream_path);
    if (!model_path.empty()) {
        print_path_summary("model", model_path);
    }

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
    }

    bool ok = frame.ok && (!pipeline.rga.requested || pipeline.rga.ok);
    if (!model_path.empty()) {
        const decode_demo::RknnRunInfo run = decode_demo::run_rknn_inference(
            model_path,
            pipeline.rga.output_data,
            pipeline.rga.output_width,
            pipeline.rga.output_height,
            pipeline.rga.output_channels);
        print_rknn_run_summary(run);
        ok = ok && run.ok;
    }
    return ok ? 0 : 2;
}

}  // namespace

int main(int argc, char** argv) {
    const Options options = parse_args(argc, argv);

    if (options.self_check) {
        return decode_demo::run_self_check(std::cout);
    }

    std::cout << "rk_decode_demo pipeline prototype\n";
    print_manifest_summary(options.plan_file);

    if (!options.stream.empty()) {
        return run_stream_pipeline(options.stream, options.model, options.rga_width, options.rga_height);
    }

    print_path_summary("model", options.model);
    std::cout << "status=waiting_for_stream\n";
    std::cout << "next=provide --stream <annexb.h264> to execute MPP, RGA, and optional RKNN inference\n";
    return 0;
}
