#include "decode_demo/rknn_runner.hpp"

#include <algorithm>
#include <cstring>
#include <fstream>
#include <iterator>
#include <vector>

extern "C" {
#include <rknn_api.h>
}

namespace decode_demo {
namespace {

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

RknnModelInfo inspect_rknn_model_with_bytes(const std::string& model_path, const std::vector<char>& model_bytes) {
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
    (void)model_path;
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
    return inspect_rknn_model_with_bytes(model_path, model_bytes);
}

RknnRunInfo run_rknn_inference(const std::string& model_path,
                               const std::vector<std::uint8_t>& input_data,
                               int input_width,
                               int input_height,
                               int input_channels) {
    RknnRunInfo result;
    result.requested = true;

    std::vector<char> model_bytes;
    if (!load_file_bytes(model_path, &model_bytes)) {
        result.detail = "failed to load model file";
        return result;
    }

    result.model = inspect_rknn_model_with_bytes(model_path, model_bytes);
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
        outputs[static_cast<std::size_t>(i)].want_float = 1;
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
            const float* values = static_cast<const float*>(outputs[i].buf);
            result.outputs[i].sample_values.assign(values, values + sample_count);
        }
    }

    rknn_outputs_release(ctx, static_cast<std::uint32_t>(outputs.size()), outputs.data());
    rknn_destroy(ctx);
    result.ok = true;
    result.detail = "inference_ok";
    return result;
}

}  // namespace decode_demo
