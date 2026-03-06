#include "decode_demo/rknn_runner.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <fstream>
#include <iterator>
#include <set>
#include <string>
#include <utility>
#include <vector>

extern "C" {
#include <rknn_api.h>
}

namespace decode_demo {
namespace {

constexpr int kYolov5ClassCount = 80;
constexpr int kYolov5AnchorCount = 3;
constexpr int kYolov5ProposalBoxSize = 5 + kYolov5ClassCount;
constexpr float kYolov5BoxThreshold = 0.25f;
constexpr float kYolov5NmsThreshold = 0.45f;
constexpr int kYolov5Anchors[3][6] = {
    {10, 13, 16, 30, 33, 23},
    {30, 61, 62, 45, 59, 119},
    {116, 90, 156, 198, 373, 326},
};
constexpr const char* kCoco80Labels[kYolov5ClassCount] = {
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat", "traffic light",
    "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle",
    "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch", "potted plant", "bed",
    "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave", "oven",
    "toaster", "sink", "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush",
};

struct RawDetection {
    float x{0.0f};
    float y{0.0f};
    float w{0.0f};
    float h{0.0f};
    float confidence{0.0f};
    int class_id{-1};
};

bool load_file_bytes(const std::string& path, std::vector<char>* data) {
    std::ifstream ifs(path, std::ios::binary);
    if (!ifs.is_open()) {
        return false;
    }
    data->assign(std::istreambuf_iterator<char>(ifs), std::istreambuf_iterator<char>());
    return !data->empty();
}

RknnTensorSummary summarize_attr(const rknn_tensor_attr& attr) {
    RknnTensorSummary summary;
    summary.index = static_cast<int>(attr.index);
    summary.name = attr.name;
    summary.dims.assign(attr.dims, attr.dims + attr.n_dims);
    summary.n_elems = attr.n_elems;
    summary.size = attr.size;
    summary.format = get_format_string(attr.fmt);
    summary.type = get_type_string(attr.type);
    summary.qnt_type = get_qnt_type_string(attr.qnt_type);
    summary.zp = attr.zp;
    summary.scale = attr.scale;
    return summary;
}

void populate_model_shape(const rknn_tensor_attr& input_attr, RknnModelInfo* info) {
    if (input_attr.fmt == RKNN_TENSOR_NCHW && input_attr.n_dims >= 4) {
        info->model_channel = static_cast<int>(input_attr.dims[1]);
        info->model_height = static_cast<int>(input_attr.dims[2]);
        info->model_width = static_cast<int>(input_attr.dims[3]);
    } else if (input_attr.n_dims >= 4) {
        info->model_height = static_cast<int>(input_attr.dims[1]);
        info->model_width = static_cast<int>(input_attr.dims[2]);
        info->model_channel = static_cast<int>(input_attr.dims[3]);
    }
}

std::vector<std::uint8_t> convert_nhwc_to_nchw(const std::vector<std::uint8_t>& nhwc,
                                               int width,
                                               int height,
                                               int channels) {
    std::vector<std::uint8_t> nchw(nhwc.size(), 0);
    const int plane_size = width * height;
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            const int pixel_index = y * width + x;
            for (int c = 0; c < channels; ++c) {
                nchw[c * plane_size + pixel_index] = nhwc[pixel_index * channels + c];
            }
        }
    }
    return nchw;
}

float dequantize_int8(std::int8_t value, int zp, float scale) {
    return static_cast<float>(static_cast<int>(value) - zp) * scale;
}

float clamp_float(float value, float minimum, float maximum) {
    return std::max(minimum, std::min(maximum, value));
}

float intersection_over_union(const RawDetection& a, const RawDetection& b) {
    const float ax1 = a.x;
    const float ay1 = a.y;
    const float ax2 = a.x + a.w;
    const float ay2 = a.y + a.h;
    const float bx1 = b.x;
    const float by1 = b.y;
    const float bx2 = b.x + b.w;
    const float by2 = b.y + b.h;

    const float inter_w = std::max(0.0f, std::min(ax2, bx2) - std::max(ax1, bx1));
    const float inter_h = std::max(0.0f, std::min(ay2, by2) - std::max(ay1, by1));
    const float intersection = inter_w * inter_h;
    const float union_area = a.w * a.h + b.w * b.h - intersection;
    return union_area <= 0.0f ? 0.0f : (intersection / union_area);
}

std::vector<int> sort_detection_indices(const std::vector<RawDetection>& detections) {
    std::vector<int> indices(detections.size());
    for (std::size_t i = 0; i < detections.size(); ++i) {
        indices[i] = static_cast<int>(i);
    }
    std::sort(indices.begin(), indices.end(), [&detections](int lhs, int rhs) {
        return detections[static_cast<std::size_t>(lhs)].confidence > detections[static_cast<std::size_t>(rhs)].confidence;
    });
    return indices;
}

std::vector<RawDetection> run_yolov5_postprocess(const std::vector<RknnTensorSummary>& output_attrs,
                                                 const std::vector<rknn_output>& outputs,
                                                 int model_width,
                                                 int model_height) {
    std::vector<RawDetection> detections;
    if (outputs.size() < 3 || output_attrs.size() < 3) {
        return detections;
    }

    for (std::size_t head = 0; head < 3; ++head) {
        const auto& attr = output_attrs[head];
        if (attr.dims.size() < 4 || outputs[head].buf == nullptr) {
            continue;
        }
        const int grid_h = static_cast<int>(attr.dims[2]);
        const int grid_w = static_cast<int>(attr.dims[3]);
        const int stride = model_height / grid_h;
        const int grid_len = grid_h * grid_w;
        const auto* buffer = static_cast<const std::int8_t*>(outputs[head].buf);

        for (int anchor_index = 0; anchor_index < kYolov5AnchorCount; ++anchor_index) {
            for (int y = 0; y < grid_h; ++y) {
                for (int x = 0; x < grid_w; ++x) {
                    const int offset = (kYolov5ProposalBoxSize * anchor_index) * grid_len + y * grid_w + x;
                    const std::int8_t* in_ptr = buffer + offset;
                    const float box_confidence = dequantize_int8(in_ptr[4 * grid_len], attr.zp, attr.scale);
                    if (box_confidence < kYolov5BoxThreshold) {
                        continue;
                    }

                    float max_class_score = dequantize_int8(in_ptr[5 * grid_len], attr.zp, attr.scale);
                    int max_class_id = 0;
                    for (int class_index = 1; class_index < kYolov5ClassCount; ++class_index) {
                        const float class_score = dequantize_int8(in_ptr[(5 + class_index) * grid_len], attr.zp, attr.scale);
                        if (class_score > max_class_score) {
                            max_class_score = class_score;
                            max_class_id = class_index;
                        }
                    }

                    const float confidence = box_confidence * max_class_score;
                    if (confidence < kYolov5BoxThreshold) {
                        continue;
                    }

                    float box_x = dequantize_int8(in_ptr[0], attr.zp, attr.scale) * 2.0f - 0.5f;
                    float box_y = dequantize_int8(in_ptr[grid_len], attr.zp, attr.scale) * 2.0f - 0.5f;
                    float box_w = dequantize_int8(in_ptr[2 * grid_len], attr.zp, attr.scale) * 2.0f;
                    float box_h = dequantize_int8(in_ptr[3 * grid_len], attr.zp, attr.scale) * 2.0f;
                    box_x = (box_x + static_cast<float>(x)) * static_cast<float>(stride);
                    box_y = (box_y + static_cast<float>(y)) * static_cast<float>(stride);
                    box_w = box_w * box_w * static_cast<float>(kYolov5Anchors[head][anchor_index * 2]);
                    box_h = box_h * box_h * static_cast<float>(kYolov5Anchors[head][anchor_index * 2 + 1]);
                    box_x -= box_w / 2.0f;
                    box_y -= box_h / 2.0f;

                    detections.push_back(RawDetection{box_x, box_y, box_w, box_h, confidence, max_class_id});
                }
            }
        }
    }
    return detections;
}

std::vector<RknnDetection> convert_detections_to_image_space(const std::vector<RawDetection>& raw_detections,
                                                             float letterbox_scale,
                                                             int letterbox_pad_x,
                                                             int letterbox_pad_y,
                                                             int source_width,
                                                             int source_height,
                                                             int model_width,
                                                             int model_height) {
    std::vector<RknnDetection> final_detections;
    if (letterbox_scale <= 0.0f) {
        return final_detections;
    }

    const auto sorted_indices = sort_detection_indices(raw_detections);
    std::vector<bool> suppressed(raw_detections.size(), false);
    for (std::size_t order_idx = 0; order_idx < sorted_indices.size(); ++order_idx) {
        const int raw_index = sorted_indices[order_idx];
        if (suppressed[static_cast<std::size_t>(raw_index)]) {
            continue;
        }
        const auto& candidate = raw_detections[static_cast<std::size_t>(raw_index)];
        for (std::size_t next_idx = order_idx + 1; next_idx < sorted_indices.size(); ++next_idx) {
            const int compare_index = sorted_indices[next_idx];
            if (suppressed[static_cast<std::size_t>(compare_index)]) {
                continue;
            }
            const auto& other = raw_detections[static_cast<std::size_t>(compare_index)];
            if (candidate.class_id != other.class_id) {
                continue;
            }
            if (intersection_over_union(candidate, other) > kYolov5NmsThreshold) {
                suppressed[static_cast<std::size_t>(compare_index)] = true;
            }
        }

        const float x1 = (candidate.x - static_cast<float>(letterbox_pad_x)) / letterbox_scale;
        const float y1 = (candidate.y - static_cast<float>(letterbox_pad_y)) / letterbox_scale;
        const float x2 = (candidate.x + candidate.w - static_cast<float>(letterbox_pad_x)) / letterbox_scale;
        const float y2 = (candidate.y + candidate.h - static_cast<float>(letterbox_pad_y)) / letterbox_scale;

        RknnDetection detection;
        detection.class_id = candidate.class_id;
        if (candidate.class_id >= 0 && candidate.class_id < kYolov5ClassCount) {
            detection.class_name = kCoco80Labels[candidate.class_id];
        }
        detection.confidence = candidate.confidence;
        detection.left = static_cast<int>(clamp_float(x1, 0.0f, static_cast<float>(source_width)));
        detection.top = static_cast<int>(clamp_float(y1, 0.0f, static_cast<float>(source_height)));
        detection.right = static_cast<int>(clamp_float(x2, 0.0f, static_cast<float>(source_width)));
        detection.bottom = static_cast<int>(clamp_float(y2, 0.0f, static_cast<float>(source_height)));
        if (detection.right > detection.left && detection.bottom > detection.top) {
            final_detections.push_back(std::move(detection));
        }
    }

    std::sort(final_detections.begin(), final_detections.end(), [](const RknnDetection& lhs, const RknnDetection& rhs) {
        return lhs.confidence > rhs.confidence;
    });
    if (final_detections.size() > 32) {
        final_detections.resize(32);
    }
    (void)model_width;
    (void)model_height;
    return final_detections;
}

RknnModelInfo inspect_rknn_model_with_bytes(const std::vector<char>& model_bytes) {
    RknnModelInfo info;
    if (model_bytes.empty()) {
        info.detail = "model bytes are empty";
        return info;
    }

    rknn_context ctx = 0;
    int ret = rknn_init(&ctx, const_cast<char*>(model_bytes.data()), static_cast<int>(model_bytes.size()), 0, nullptr);
    if (ret < 0 || ctx == 0) {
        info.detail = "rknn_init failed: " + std::to_string(ret);
        return info;
    }

    rknn_sdk_version sdk_version {};
    ret = rknn_query(ctx, RKNN_QUERY_SDK_VERSION, &sdk_version, sizeof(sdk_version));
    if (ret == 0) {
        info.api_version = sdk_version.api_version;
        info.driver_version = sdk_version.drv_version;
    }

    rknn_input_output_num io_num {};
    ret = rknn_query(ctx, RKNN_QUERY_IN_OUT_NUM, &io_num, sizeof(io_num));
    if (ret < 0) {
        info.detail = "RKNN_QUERY_IN_OUT_NUM failed: " + std::to_string(ret);
        rknn_destroy(ctx);
        return info;
    }
    info.input_count = static_cast<int>(io_num.n_input);
    info.output_count = static_cast<int>(io_num.n_output);

    for (std::uint32_t i = 0; i < io_num.n_input; ++i) {
        rknn_tensor_attr attr {};
        attr.index = i;
        ret = rknn_query(ctx, RKNN_QUERY_INPUT_ATTR, &attr, sizeof(attr));
        if (ret < 0) {
            info.detail = "RKNN_QUERY_INPUT_ATTR failed: " + std::to_string(ret);
            rknn_destroy(ctx);
            return info;
        }
        info.inputs.push_back(summarize_attr(attr));
        if (i == 0) {
            info.input_format = get_format_string(attr.fmt);
            info.input_type = get_type_string(attr.type);
            populate_model_shape(attr, &info);
        }
    }

    for (std::uint32_t i = 0; i < io_num.n_output; ++i) {
        rknn_tensor_attr attr {};
        attr.index = i;
        ret = rknn_query(ctx, RKNN_QUERY_OUTPUT_ATTR, &attr, sizeof(attr));
        if (ret < 0) {
            info.detail = "RKNN_QUERY_OUTPUT_ATTR failed: " + std::to_string(ret);
            rknn_destroy(ctx);
            return info;
        }
        info.outputs.push_back(summarize_attr(attr));
    }

    info.ok = true;
    info.detail = "model_ready";
    rknn_destroy(ctx);
    return info;
}

}  // namespace

RknnModelInfo inspect_rknn_model(const std::string& model_path) {
    std::vector<char> model_bytes;
    if (!load_file_bytes(model_path, &model_bytes)) {
        RknnModelInfo info;
        info.detail = "failed to load model file";
        return info;
    }
    return inspect_rknn_model_with_bytes(model_bytes);
}

RknnRunInfo run_rknn_inference(const std::string& model_path,
                               const std::vector<std::uint8_t>& input_data,
                               int input_width,
                               int input_height,
                               int input_channels,
                               float letterbox_scale,
                               int letterbox_pad_x,
                               int letterbox_pad_y,
                               int source_width,
                               int source_height) {
    RknnRunInfo result;
    result.requested = true;

    std::vector<char> model_bytes;
    if (!load_file_bytes(model_path, &model_bytes)) {
        result.detail = "failed to load model file";
        return result;
    }

    result.model = inspect_rknn_model_with_bytes(model_bytes);
    if (!result.model.ok) {
        result.detail = result.model.detail;
        return result;
    }

    if (input_width != result.model.model_width ||
        input_height != result.model.model_height ||
        input_channels != result.model.model_channel) {
        result.detail = "input shape does not match model input shape";
        return result;
    }

    const std::size_t expected_size =
        static_cast<std::size_t>(input_width) * static_cast<std::size_t>(input_height) * static_cast<std::size_t>(input_channels);
    if (input_data.size() != expected_size) {
        result.detail = "input byte size does not match model input tensor size";
        return result;
    }

    rknn_context ctx = 0;
    int ret = rknn_init(&ctx, const_cast<char*>(model_bytes.data()), static_cast<int>(model_bytes.size()), 0, nullptr);
    if (ret < 0 || ctx == 0) {
        result.detail = "rknn_init failed: " + std::to_string(ret);
        return result;
    }

    std::vector<std::uint8_t> nchw_data;
    const void* input_buffer = input_data.data();
    rknn_tensor_format input_format = RKNN_TENSOR_NHWC;
    if (!result.model.inputs.empty() && result.model.inputs[0].format == "NCHW") {
        nchw_data = convert_nhwc_to_nchw(input_data, input_width, input_height, input_channels);
        input_buffer = nchw_data.data();
        input_format = RKNN_TENSOR_NCHW;
    }

    rknn_input input {};
    input.index = 0;
    input.buf = const_cast<void*>(input_buffer);
    input.size = static_cast<std::uint32_t>(expected_size);
    input.pass_through = 0;
    input.type = RKNN_TENSOR_UINT8;
    input.fmt = input_format;

    ret = rknn_inputs_set(ctx, 1, &input);
    if (ret < 0) {
        result.detail = "rknn_inputs_set failed: " + std::to_string(ret);
        rknn_destroy(ctx);
        return result;
    }

    ret = rknn_run(ctx, nullptr);
    if (ret < 0) {
        result.detail = "rknn_run failed: " + std::to_string(ret);
        rknn_destroy(ctx);
        return result;
    }

    std::vector<rknn_output> outputs(static_cast<std::size_t>(result.model.output_count));
    for (int i = 0; i < result.model.output_count; ++i) {
        outputs[static_cast<std::size_t>(i)].index = static_cast<std::uint32_t>(i);
        outputs[static_cast<std::size_t>(i)].want_float = 0;
    }

    ret = rknn_outputs_get(ctx, static_cast<std::uint32_t>(outputs.size()), outputs.data(), nullptr);
    if (ret < 0) {
        result.detail = "rknn_outputs_get failed: " + std::to_string(ret);
        rknn_destroy(ctx);
        return result;
    }

    result.outputs = result.model.outputs;
    for (std::size_t i = 0; i < result.outputs.size() && i < outputs.size(); ++i) {
        const std::size_t sample_count = std::min<std::size_t>(8, result.outputs[i].n_elems);
        if (outputs[i].buf != nullptr && sample_count > 0) {
            const auto* values = static_cast<const std::int8_t*>(outputs[i].buf);
            result.outputs[i].sample_values.reserve(sample_count);
            for (std::size_t j = 0; j < sample_count; ++j) {
                result.outputs[i].sample_values.push_back(dequantize_int8(values[j], result.outputs[i].zp, result.outputs[i].scale));
            }
        }
    }

    const auto raw_detections = run_yolov5_postprocess(result.model.outputs, outputs, result.model.model_width, result.model.model_height);
    result.detections = convert_detections_to_image_space(
        raw_detections,
        letterbox_scale,
        letterbox_pad_x,
        letterbox_pad_y,
        source_width,
        source_height,
        result.model.model_width,
        result.model.model_height);

    rknn_outputs_release(ctx, static_cast<std::uint32_t>(outputs.size()), outputs.data());
    rknn_destroy(ctx);
    result.ok = true;
    result.detail = "inference_ok";
    return result;
}

}  // namespace decode_demo
