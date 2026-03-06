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

}  // namespace

void write_detection_result_json(const std::string& path,
                                 const ManifestWorkload* workload,
                                 const DecodedFrameInfo& frame,
                                 const RgaResizeInfo& rga,
                                 const RknnRunInfo* run) {
    if (path.empty()) {
        return;
    }
    const auto parent = std::filesystem::path(path).parent_path();
    if (!parent.empty()) {
        std::filesystem::create_directories(parent);
    }
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output.is_open()) {
        throw std::runtime_error("failed to open result output: " + path);
    }

    output << "{\n";
    write_string_field(output, 2, "schema_version", "rk_decode_demo_result/v1", true);
    if (workload != nullptr) {
        write_indent(output, 2);
        output << "\"workload\": {\n";
        write_string_field(output, 4, "tenant_id", workload->tenant_id, true);
        write_string_field(output, 4, "site_id", workload->site_id, true);
        write_string_field(output, 4, "box_id", workload->box_id, true);
        write_string_field(output, 4, "device_id", workload->device_id, true);
        write_string_field(output, 4, "capability", workload->capability, true);
        write_string_field(output, 4, "algorithm_id", workload->algorithm_id, true);
        write_string_field(output, 4, "algorithm_version", workload->algorithm_version, true);
        write_string_field(output, 4, "base_library_id", workload->base_library_id, true);
        write_string_field(output, 4, "base_library_version", workload->base_library_version, true);
        write_string_field(output, 4, "stream_url", workload->stream_url, false);
        write_indent(output, 2);
        output << "},\n";
    }

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

}  // namespace decode_demo
