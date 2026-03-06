#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace decode_demo {

struct DecodedFrameInfo {
    bool ok{false};
    std::string detail;
    std::string coding;
    std::string pixel_format;
    int width{0};
    int height{0};
    int hor_stride{0};
    int ver_stride{0};
    int dma_fd{-1};
};

struct RgaResizeInfo {
    bool requested{false};
    bool ok{false};
    std::string detail;
    int output_width{0};
    int output_height{0};
    int output_channels{0};
    std::size_t output_bytes{0};
    int scaled_width{0};
    int scaled_height{0};
    int pad_x{0};
    int pad_y{0};
    float scale{1.0f};
    std::vector<std::uint8_t> output_data;
};

struct DecodePipelineInfo {
    DecodedFrameInfo frame;
    RgaResizeInfo rga;
};

DecodedFrameInfo decode_one_frame_from_annexb(const std::string& path);
DecodePipelineInfo decode_pipeline_from_annexb(const std::string& path, int rga_width, int rga_height);

}  // namespace decode_demo
