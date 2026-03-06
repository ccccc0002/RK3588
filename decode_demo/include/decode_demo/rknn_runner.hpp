#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace decode_demo {

struct RknnTensorSummary {
    int index{0};
    std::string name;
    std::vector<std::uint32_t> dims;
    std::uint32_t n_elems{0};
    std::uint32_t size{0};
    std::string format;
    std::string type;
    std::string qnt_type;
    int zp{0};
    float scale{0.0f};
    std::vector<float> sample_values;
};

struct RknnDetection {
    int class_id{-1};
    std::string class_name;
    float confidence{0.0f};
    int left{0};
    int top{0};
    int right{0};
    int bottom{0};
};

struct RknnModelInfo {
    bool ok{false};
    std::string detail;
    std::string api_version;
    std::string driver_version;
    int input_count{0};
    int output_count{0};
    int model_width{0};
    int model_height{0};
    int model_channel{0};
    std::string input_format;
    std::string input_type;
    std::vector<RknnTensorSummary> inputs;
    std::vector<RknnTensorSummary> outputs;
};

struct RknnRunInfo {
    bool requested{false};
    bool ok{false};
    std::string detail;
    RknnModelInfo model;
    std::vector<RknnTensorSummary> outputs;
    std::vector<RknnDetection> detections;
};

RknnModelInfo inspect_rknn_model(const std::string& model_path);
RknnRunInfo run_rknn_inference(const std::string& model_path,
                               const std::vector<std::uint8_t>& input_data,
                               int input_width,
                               int input_height,
                               int input_channels,
                               float letterbox_scale,
                               int letterbox_pad_x,
                               int letterbox_pad_y,
                               int source_width,
                               int source_height);

}  // namespace decode_demo
