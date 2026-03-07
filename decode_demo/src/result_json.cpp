#include "decode_demo/result_json.hpp"

#include <filesystem>
#include <fstream>
#include <iomanip>
#include <stdexcept>
#include <string>

namespace decode_demo {
namespace {

std::string escape_json(const std::string& input) {
    std::string out;
    out.reserve(input.size() + 8);
    for (char ch : input) {
        switch (ch) {
            case '\\': out += "\\\\"; break;
            case '"': out += "\\\""; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default: out.push_back(ch); break;
        }
    }
    return out;
}

void write_indent(std::ofstream& output, int indent) {
    for (int i = 0; i < indent; ++i) {
        output.put(' ');
    }
}

void write_string_field(std::ofstream& output, int indent, const std::string& key, const std::string& value, bool trailing_comma) {
    write_indent(output, indent);
    output << '"' << key << "\": \"" << escape_json(value) << '\"';
    if (trailing_comma) {
        output << ',';
    }
    output << '\n';
}

void write_bool_field(std::ofstream& output, int indent, const std::string& key, bool value, bool trailing_comma) {
    write_indent(output, indent);
    output << '"' << key << "\": " << (value ? "true" : "false");
    if (trailing_comma) {
        output << ',';
    }
    output << '\n';
}

void write_number_field(std::ofstream& output, int indent, const std::string& key, double value, bool trailing_comma) {
    write_indent(output, indent);
    output << '"' << key << "\": " << std::fixed << std::setprecision(6) << value;
    if (trailing_comma) {
        output << ',';
    }
    output << '\n';
}

void write_int_field(std::ofstream& output, int indent, const std::string& key, int value, bool trailing_comma) {
    write_indent(output, indent);
    output << '"' << key << "\": " << value;
    if (trailing_comma) {
        output << ',';
    }
    output << '\n';
}

void ensure_parent_dir(const std::string& path) {
    if (path.empty()) {
        return;
    }
    const auto parent = std::filesystem::path(path).parent_path();
    if (!parent.empty()) {
        std::filesystem::create_directories(parent);
    }
}

void write_workload_object(std::ofstream& output, int indent, const ManifestWorkload* workload, bool trailing_comma) {
    if (workload == nullptr) {
        write_indent(output, indent);
        output << "\"workload\": null";
        if (trailing_comma) {
            output << ',';
        }
        output << '\n';
        return;
    }
    write_indent(output, indent);
    output << "\"workload\": {\n";
    write_string_field(output, indent + 2, "tenant_id", workload->tenant_id, true);
    write_string_field(output, indent + 2, "site_id", workload->site_id, true);
    write_string_field(output, indent + 2, "box_id", workload->box_id, true);
    write_string_field(output, indent + 2, "device_id", workload->device_id, true);
    write_string_field(output, indent + 2, "capability", workload->capability, true);
    write_string_field(output, indent + 2, "algorithm_id", workload->algorithm_id, true);
    write_string_field(output, indent + 2, "algorithm_version", workload->algorithm_version, true);
    write_string_field(output, indent + 2, "base_library_id", workload->base_library_id, true);
    write_string_field(output, indent + 2, "base_library_version", workload->base_library_version, true);
    write_string_field(output, indent + 2, "stream_url", workload->stream_url, false);
    write_indent(output, indent);
    output << '}';
    if (trailing_comma) {
        output << ',';
    }
    output << '\n';
}

}  // namespace

void write_detection_result_json(const std::string& path,
                                 const ManifestWorkload* workload,
                                 const DecodedFrameInfo& frame,
                                 const RgaResizeInfo& rga,
                                 const RknnRunInfo* run,
                                 const ResultSamplingMetadata* sampling) {
    if (path.empty()) {
        return;
    }
    ensure_parent_dir(path);
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output.is_open()) {
        throw std::runtime_error("failed to open result output: " + path);
    }

    output << "{\n";
    write_string_field(output, 2, "schema_version", "rk_decode_demo_result/v1", true);
    write_workload_object(output, 2, workload, true);

    write_indent(output, 2);
    output << "\"decode\": {\n";
    write_bool_field(output, 4, "ok", frame.ok, true);
    write_string_field(output, 4, "detail", frame.detail, true);
    write_string_field(output, 4, "coding", frame.coding, true);
    write_string_field(output, 4, "pixel_format", frame.pixel_format, true);
    write_int_field(output, 4, "width", frame.width, true);
    write_int_field(output, 4, "height", frame.height, true);
    write_int_field(output, 4, "hor_stride", frame.hor_stride, true);
    write_int_field(output, 4, "ver_stride", frame.ver_stride, true);
    write_int_field(output, 4, "dma_fd", frame.dma_fd, false);
    write_indent(output, 2);
    output << "},\n";

    write_indent(output, 2);
    output << "\"rga\": {\n";
    write_bool_field(output, 4, "requested", rga.requested, true);
    write_bool_field(output, 4, "ok", rga.ok, true);
    write_string_field(output, 4, "detail", rga.detail, true);
    write_int_field(output, 4, "output_width", rga.output_width, true);
    write_int_field(output, 4, "output_height", rga.output_height, true);
    write_int_field(output, 4, "output_channels", rga.output_channels, true);
    write_int_field(output, 4, "scaled_width", rga.scaled_width, true);
    write_int_field(output, 4, "scaled_height", rga.scaled_height, true);
    write_int_field(output, 4, "pad_x", rga.pad_x, true);
    write_int_field(output, 4, "pad_y", rga.pad_y, true);
    write_number_field(output, 4, "scale", rga.scale, false);
    write_indent(output, 2);
    output << "},\n";

    write_indent(output, 2);
    output << "\"inference\": {\n";
    if (run != nullptr) {
        write_bool_field(output, 4, "requested", run->requested, true);
        write_bool_field(output, 4, "ok", run->ok, true);
        write_string_field(output, 4, "detail", run->detail, true);
        write_int_field(output, 4, "detection_count", static_cast<int>(run->detections.size()), true);
        write_indent(output, 4);
        output << "\"detections\": [\n";
        for (std::size_t i = 0; i < run->detections.size(); ++i) {
            const auto& detection = run->detections[i];
            write_indent(output, 6);
            output << "{\n";
            write_int_field(output, 8, "class_id", detection.class_id, true);
            write_string_field(output, 8, "class_name", detection.class_name, true);
            write_number_field(output, 8, "confidence", detection.confidence, true);
            write_int_field(output, 8, "left", detection.left, true);
            write_int_field(output, 8, "top", detection.top, true);
            write_int_field(output, 8, "right", detection.right, true);
            write_int_field(output, 8, "bottom", detection.bottom, false);
            write_indent(output, 6);
            output << '}';
            if (i + 1 < run->detections.size()) {
                output << ',';
            }
            output << '\n';
        }
        write_indent(output, 4);
        output << "]\n";
    } else {
        write_bool_field(output, 4, "requested", false, true);
        write_bool_field(output, 4, "ok", false, true);
        write_string_field(output, 4, "detail", "not_requested", true);
        write_int_field(output, 4, "detection_count", 0, true);
        write_indent(output, 4);
        output << "\"detections\": []\n";
    }
    write_indent(output, 2);
    output << "}\n";
    output << "}\n";
}

void write_batch_result_json(const std::string& path, const std::vector<BatchExecutionItem>& items, const BatchRunMetadata* metadata) {
    if (path.empty()) {
        return;
    }
    ensure_parent_dir(path);
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output.is_open()) {
        throw std::runtime_error("failed to open batch result output: " + path);
    }

    int success_count = 0;
    for (const auto& item : items) {
        if (item.exit_code == 0) {
            ++success_count;
        }
    }

    output << "{\n";
    write_string_field(output, 2, "schema_version", "rk_decode_demo_batch_result/v1", true);
    write_int_field(output, 2, "item_count", static_cast<int>(items.size()), true);
    write_int_field(output, 2, "success_count", success_count, true);
    write_int_field(output, 2, "failure_count", static_cast<int>(items.size()) - success_count, true);
    if (metadata != nullptr) {
        write_string_field(output, 2, "plan_source", metadata->plan_source, true);
        write_string_field(output, 2, "runtime_plan_url", metadata->runtime_plan_url, true);
        write_int_field(output, 2, "runtime_plan_http_status", static_cast<int>(metadata->runtime_plan_http_status), true);
        write_int_field(output, 2, "runtime_plan_attempt_count", metadata->runtime_plan_attempt_count, true);
        write_bool_field(output, 2, "runtime_plan_used_cache", metadata->runtime_plan_used_cache, true);
        write_string_field(output, 2, "runtime_plan_cache_path", metadata->runtime_plan_cache_path, true);
    }
    write_indent(output, 2);
    output << "\"items\": [\n";
    for (std::size_t i = 0; i < items.size(); ++i) {
        const auto& item = items[i];
        write_indent(output, 4);
        output << "{\n";
        write_int_field(output, 6, "index", static_cast<int>(i), true);
        write_workload_object(output, 6, item.workload, true);
        write_string_field(output, 6, "stream_path", item.stream_path, true);
        write_string_field(output, 6, "model_path", item.model_path, true);
        write_string_field(output, 6, "output_path", item.output_path, true);
        write_bool_field(output, 6, "asset_binding_resolved", item.asset_binding_resolved, true);
        write_int_field(output, 6, "exit_code", item.exit_code, true);
        write_string_field(output, 6, "status", item.status, true);
        write_bool_field(output, 6, "decode_ok", item.decode_ok, true);
        write_bool_field(output, 6, "rga_requested", item.rga_requested, true);
        write_bool_field(output, 6, "rga_ok", item.rga_ok, true);
        write_bool_field(output, 6, "rknn_requested", item.rknn_requested, true);
        write_bool_field(output, 6, "rknn_ok", item.rknn_ok, true);
        write_int_field(output, 6, "detection_count", item.detection_count, true);
        write_int_field(output, 6, "frames_per_sample", item.frames_per_sample, true);
        write_int_field(output, 6, "requested_sample_count", item.requested_sample_count, true);
        write_int_field(output, 6, "sampled_frame_count", item.sampled_frame_count, false);
        write_indent(output, 4);
        output << '}';
        if (i + 1 < items.size()) {
            output << ',';
        }
        output << '\n';
    }
    write_indent(output, 2);
    output << "]\n";
    output << "}\n";
}

}  // namespace decode_demo
