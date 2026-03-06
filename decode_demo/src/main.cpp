#include "decode_demo/execution_asset.hpp"
#include "decode_demo/mpp_decode.hpp"
#include "decode_demo/plan_manifest.hpp"
#include "decode_demo/result_json.hpp"
#include "decode_demo/rknn_runner.hpp"
#include "decode_demo/runtime_probe.hpp"

#include <cctype>
#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <map>
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

struct ResolvedExecution {
    std::string stream_path;
    std::string model_path;
    std::string output_path;
    const decode_demo::ManifestWorkload* workload{nullptr};
    bool asset_binding_resolved{false};
    std::size_t workload_index{0};
};

struct PipelineRunSummary {
    int exit_code{0};
    bool decode_ok{false};
    bool rga_requested{false};
    bool rga_ok{false};
    bool rknn_requested{false};
    bool rknn_ok{false};
    int detection_count{0};
    std::string status{"ok"};
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
    std::cout << "selected_execution_ready=" << (workload.execution_ready ? "true" : "false") << '\n';
    std::cout << "selected_stream_uri=" << workload.stream_uri << '\n';
    std::cout << "selected_model_uri=" << workload.model_uri << '\n';
    std::cout << "selected_result_uri=" << workload.result_uri << '\n';
    std::cout << "selected_sample_period_ms=" << workload.sample_period_ms << '\n';
    std::cout << "selected_frames_per_sample=" << workload.frames_per_sample << '\n';
    std::cout << "selected_max_samples_per_run=" << workload.max_samples_per_run << '\n';
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

std::string sanitize_component(const std::string& value) {
    std::string sanitized;
    sanitized.reserve(value.size());
    for (char ch : value) {
        const unsigned char uch = static_cast<unsigned char>(ch);
        if (std::isalnum(uch) != 0 || ch == '-' || ch == '_') {
            sanitized.push_back(ch);
        } else {
            sanitized.push_back('_');
        }
    }
    return sanitized.empty() ? std::string("result") : sanitized;
}

std::string resolve_local_uri_or_path(const std::string& value) {
    if (value.empty()) {
        return {};
    }
    if (value.rfind("file://", 0) == 0) {
        return value.substr(7);
    }
    if (value.rfind("/", 0) == 0 || value.rfind("./", 0) == 0 || value.rfind("../", 0) == 0 ||
        value.find(":\") != std::string::npos) {
        return value;
    }
    return {};
}

void ensure_unique_output_paths(std::vector<ResolvedExecution>& executions) {
    std::map<std::string, int> counts;
    for (const auto& execution : executions) {
        if (!execution.output_path.empty()) {
            ++counts[execution.output_path];
        }
    }

    for (std::size_t i = 0; i < executions.size(); ++i) {
        auto& execution = executions[i];
        const bool duplicate = !execution.output_path.empty() && counts[execution.output_path] > 1;
        if (!execution.output_path.empty() && !duplicate) {
            continue;
        }

        std::filesystem::path parent = execution.output_path.empty()
            ? std::filesystem::path("artifacts/results")
            : std::filesystem::path(execution.output_path).parent_path();
        if (parent.empty()) {
            parent = std::filesystem::path("artifacts/results");
        }

        std::string stem = execution.workload == nullptr ? std::string("manual") : sanitize_component(execution.workload->device_id);
        if (execution.workload != nullptr && !execution.workload->capability.empty()) {
            stem += "__" + sanitize_component(execution.workload->capability);
        }
        stem += "__" + std::to_string(i + 1);
        execution.output_path = (parent / (stem + ".json")).string();
    }
}

std::vector<ResolvedExecution> resolve_executions_from_options(const Options& options) {
    std::vector<ResolvedExecution> executions;
    if (options.plan_file.empty()) {
        ResolvedExecution resolved;
        resolved.stream_path = options.stream;
        resolved.model_path = options.model;
        resolved.output_path = options.output;
        executions.push_back(resolved);
        return executions;
    }

    const decode_demo::PlanManifest manifest = decode_demo::load_plan_manifest(options.plan_file);
    print_manifest_summary(manifest);
    static std::vector<decode_demo::ManifestWorkload> selected_workloads;
    selected_workloads = decode_demo::collect_ready_workloads(manifest);
    std::cout << "manifest_ready_workload_count=" << selected_workloads.size() << '\n';
    if (selected_workloads.empty()) {
        throw std::runtime_error("manifest contains no ready workloads");
    }

    const auto bindings = decode_demo::load_execution_asset_map(options.asset_map);
    const bool single_ready_workload = selected_workloads.size() == 1;
    for (std::size_t i = 0; i < selected_workloads.size(); ++i) {
        const auto& workload = selected_workloads[i];
        const decode_demo::ExecutionAssetBinding* binding = decode_demo::resolve_execution_asset(bindings, workload);

        ResolvedExecution execution;
        execution.workload = &selected_workloads[i];
        execution.workload_index = i;
        execution.asset_binding_resolved = binding != nullptr;
        if (!options.stream.empty()) {
            execution.stream_path = options.stream;
        } else {
            execution.stream_path = resolve_local_uri_or_path(workload.stream_uri);
            if (execution.stream_path.empty()) {
                execution.stream_path = decode_demo::resolve_stream_path(workload, binding);
            }
        }
        if (!options.model.empty()) {
            execution.model_path = options.model;
        } else {
            execution.model_path = resolve_local_uri_or_path(workload.model_uri);
            if (execution.model_path.empty()) {
                execution.model_path = decode_demo::resolve_model_path(workload, binding);
            }
        }
        if (single_ready_workload && !options.output.empty()) {
            execution.output_path = options.output;
        } else {
            execution.output_path = resolve_local_uri_or_path(workload.result_uri);
            if (execution.output_path.empty()) {
                execution.output_path = decode_demo::resolve_output_path(workload, binding);
            }
        }
        executions.push_back(execution);
    }

    if (executions.size() > 1) {
        ensure_unique_output_paths(executions);
    }
    return executions;
}

PipelineRunSummary run_stream_pipeline(const std::string& stream_path,
                                       const std::string& model_path,
                                       const std::string& output_path,
                                       const decode_demo::ManifestWorkload* workload,
                                       int requested_rga_width,
                                       int requested_rga_height) {
    PipelineRunSummary summary;
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
            summary.exit_code = 2;
            summary.status = "model_probe_failed";
            return summary;
        }
        if (effective_rga_width == 0 && effective_rga_height == 0) {
            effective_rga_width = model_info.model_width;
            effective_rga_height = model_info.model_height;
        }
    }

    const decode_demo::DecodePipelineInfo pipeline =
        decode_demo::decode_pipeline_from_annexb(stream_path, effective_rga_width, effective_rga_height);
    const decode_demo::DecodedFrameInfo& frame = pipeline.frame;
    summary.decode_ok = frame.ok;
    summary.rga_requested = pipeline.rga.requested;
    summary.rga_ok = pipeline.rga.ok;
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
        summary.rknn_requested = run.requested;
        summary.rknn_ok = run.ok;
        summary.detection_count = static_cast<int>(run.detections.size());
        print_rknn_run_summary(run);
        ok = ok && run.ok;
        decode_demo::write_detection_result_json(output_path, workload, frame, pipeline.rga, &run);
    } else {
        summary.rknn_requested = false;
        summary.rknn_ok = false;
        summary.detection_count = 0;
        decode_demo::write_detection_result_json(output_path, workload, frame, pipeline.rga, nullptr);
    }

    summary.exit_code = ok ? 0 : 2;
    if (!summary.decode_ok) {
        summary.status = "decode_failed";
    } else if (summary.rga_requested && !summary.rga_ok) {
        summary.status = "rga_failed";
    } else if (summary.rknn_requested && !summary.rknn_ok) {
        summary.status = "inference_failed";
    } else {
        summary.status = "ok";
    }
    return summary;
}

std::string default_batch_output_path(const Options& options, const std::vector<ResolvedExecution>& executions) {
    if (executions.size() <= 1) {
        return options.output;
    }
    if (!options.output.empty()) {
        return options.output;
    }
    return "artifacts/results/manifest-run-summary.json";
}

void print_waiting_message(const ResolvedExecution& execution, const Options& options) {
    print_path_summary("model", execution.model_path);
    print_path_summary("asset_map", options.asset_map);
    print_path_summary("output", execution.output_path);
    std::cout << "status=waiting_for_stream\n";
    std::cout << "next=provide --stream directly or use --plan-file with --asset-map to resolve stream/model/output automatically\n";
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const Options options = parse_args(argc, argv);

        if (options.self_check) {
            return decode_demo::run_self_check(std::cout);
        }

        std::cout << "rk_decode_demo pipeline prototype\n";
        std::vector<ResolvedExecution> executions = resolve_executions_from_options(options);
        if (executions.empty()) {
            throw std::runtime_error("no executable workload resolved");
        }

        if (executions.size() == 1) {
            const ResolvedExecution& execution = executions.front();
            if (execution.workload != nullptr) {
                print_selected_workload(*execution.workload);
                std::cout << "asset_binding_resolved=" << (execution.asset_binding_resolved ? "true" : "false") << '\n';
            }
            if (execution.stream_path.empty()) {
                print_waiting_message(execution, options);
                return 0;
            }
            if (execution.workload != nullptr && execution.model_path.empty()) {
                print_path_summary("stream", execution.stream_path);
                print_path_summary("asset_map", options.asset_map);
                std::cout << "status=waiting_for_model\n";
                std::cout << "next=provide --model directly or use --asset-map to resolve model/output automatically\n";
                return 2;
            }
            const PipelineRunSummary summary = run_stream_pipeline(
                execution.stream_path,
                execution.model_path,
                execution.output_path,
                execution.workload,
                options.rga_width,
                options.rga_height);
            return summary.exit_code;
        }

        std::vector<decode_demo::BatchExecutionItem> batch_items;
        batch_items.reserve(executions.size());
        int overall_exit = 0;
        int success_count = 0;
        for (const auto& execution : executions) {
            std::cout << "batch_workload_index=" << execution.workload_index << '\n';
            if (execution.workload != nullptr) {
                print_selected_workload(*execution.workload);
            }
            std::cout << "asset_binding_resolved=" << (execution.asset_binding_resolved ? "true" : "false") << '\n';

            decode_demo::BatchExecutionItem item;
            item.workload = execution.workload;
            item.stream_path = execution.stream_path;
            item.model_path = execution.model_path;
            item.output_path = execution.output_path;
            item.asset_binding_resolved = execution.asset_binding_resolved;

            if (execution.stream_path.empty()) {
                std::cout << "status=waiting_for_stream\n";
                item.exit_code = 2;
                item.status = "waiting_for_stream";
                overall_exit = 2;
                batch_items.push_back(item);
                continue;
            }
            if (execution.workload != nullptr && execution.model_path.empty()) {
                print_path_summary("stream", execution.stream_path);
                print_path_summary("output", execution.output_path);
                std::cout << "status=waiting_for_model\n";
                item.exit_code = 2;
                item.status = "waiting_for_model";
                overall_exit = 2;
                batch_items.push_back(item);
                continue;
            }

            const PipelineRunSummary summary = run_stream_pipeline(
                execution.stream_path,
                execution.model_path,
                execution.output_path,
                execution.workload,
                options.rga_width,
                options.rga_height);
            item.exit_code = summary.exit_code;
            item.status = summary.status;
            item.decode_ok = summary.decode_ok;
            item.rga_requested = summary.rga_requested;
            item.rga_ok = summary.rga_ok;
            item.rknn_requested = summary.rknn_requested;
            item.rknn_ok = summary.rknn_ok;
            item.detection_count = summary.detection_count;
            if (summary.exit_code == 0) {
                ++success_count;
            } else {
                overall_exit = 2;
            }
            batch_items.push_back(item);
        }

        const std::string batch_output_path = default_batch_output_path(options, executions);
        decode_demo::write_batch_result_json(batch_output_path, batch_items);
        print_path_summary("batch_output", batch_output_path);
        std::cout << "batch_run_count=" << batch_items.size() << '\n';
        std::cout << "batch_success_count=" << success_count << '\n';
        std::cout << "batch_failure_count=" << (batch_items.size() - static_cast<std::size_t>(success_count)) << '\n';
        return overall_exit;
    } catch (const std::exception& ex) {
        std::cerr << "fatal=" << ex.what() << '\n';
        return 2;
    }
}
