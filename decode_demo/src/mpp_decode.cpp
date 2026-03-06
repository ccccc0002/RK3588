#include "decode_demo/mpp_decode.hpp"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <thread>
#include <utility>
#include <vector>

extern "C" {
#include <rk_mpi.h>
}
#include <im2d.h>

namespace decode_demo {
namespace {

constexpr std::uint8_t kLetterboxFill = 114;

int align_up(int value, int alignment) {
    return ((value + alignment - 1) / alignment) * alignment;
}

bool load_file_to_buffer(const std::string& path, std::vector<std::uint8_t>* out) {
    std::ifstream ifs(path, std::ios::binary);
    if (!ifs.is_open()) {
        return false;
    }
    ifs.seekg(0, std::ios::end);
    const auto end = ifs.tellg();
    if (end <= 0) {
        return false;
    }
    const auto size = static_cast<std::size_t>(end);
    ifs.seekg(0, std::ios::beg);
    out->resize(size);
    ifs.read(reinterpret_cast<char*>(out->data()), static_cast<std::streamsize>(size));
    return ifs.good() || ifs.eof();
}

std::vector<std::size_t> build_nal_offsets(const std::vector<std::uint8_t>& bitstream) {
    std::vector<std::size_t> offsets;
    const std::size_t n = bitstream.size();
    if (n < 4) {
        return offsets;
    }
    for (std::size_t i = 0; i + 3 < n; ++i) {
        if (bitstream[i] == 0x00 && bitstream[i + 1] == 0x00 &&
            (bitstream[i + 2] == 0x01 || (i + 3 < n && bitstream[i + 2] == 0x00 && bitstream[i + 3] == 0x01))) {
            offsets.push_back(i);
        }
    }
    if (offsets.empty()) {
        offsets.push_back(0);
    }
    return offsets;
}

MppCodingType guess_coding(const std::string& path) {
    if (path.size() >= 5) {
        const std::string tail = path.substr(path.size() - 5);
        if (tail == ".hevc" || tail == ".h265") {
            return MPP_VIDEO_CodingHEVC;
        }
    }
    if (path.size() >= 4) {
        const std::string tail = path.substr(path.size() - 4);
        if (tail == ".265") {
            return MPP_VIDEO_CodingHEVC;
        }
    }
    return MPP_VIDEO_CodingAVC;
}

const char* coding_name(MppCodingType coding) {
    return coding == MPP_VIDEO_CodingHEVC ? "hevc" : "avc";
}

std::string pixel_format_name(MppFrameFormat fmt) {
    switch (fmt & MPP_FRAME_FMT_MASK) {
        case MPP_FMT_YUV420SP:
            return "NV12";
        case MPP_FMT_YUV420SP_VU:
            return "NV21";
        case MPP_FMT_YUV420P:
            return "I420";
        default:
            return "mpp_fmt_" + std::to_string(static_cast<int>(fmt & MPP_FRAME_FMT_MASK));
    }
}

bool resolve_rga_source_format(MppFrameFormat fmt, int* rga_format) {
    switch (fmt & MPP_FRAME_FMT_MASK) {
        case MPP_FMT_YUV420SP:
            *rga_format = RK_FORMAT_YCbCr_420_SP;
            return true;
        case MPP_FMT_YUV420SP_VU:
            *rga_format = RK_FORMAT_YCrCb_420_SP;
            return true;
        default:
            return false;
    }
}

bool is_im_success(IM_STATUS status) {
    return status == IM_STATUS_SUCCESS || status == IM_STATUS_NOERROR;
}

bool ensure_external_group(MppCtx ctx, MppApi* mpi, MppBufferGroup* frm_grp, MppFrame frame) {
    if (*frm_grp == nullptr) {
        MPP_RET ret = mpp_buffer_group_get_internal(frm_grp, MPP_BUFFER_TYPE_DRM);
        if (ret != MPP_OK) {
            ret = mpp_buffer_group_get_internal(frm_grp, MPP_BUFFER_TYPE_DMA_HEAP);
        }
        if (ret != MPP_OK) {
            ret = mpp_buffer_group_get_internal(frm_grp, MPP_BUFFER_TYPE_ION);
        }
        if (ret != MPP_OK || *frm_grp == nullptr) {
            return false;
        }
    }

    const auto buf_size = mpp_frame_get_buf_size(frame);
    mpp_buffer_group_limit_config(*frm_grp, buf_size, 24);
    if (mpi->control(ctx, MPP_DEC_SET_EXT_BUF_GROUP, *frm_grp) != MPP_OK) {
        return false;
    }
    if (mpi->control(ctx, MPP_DEC_SET_INFO_CHANGE_READY, nullptr) != MPP_OK) {
        return false;
    }
    return true;
}

bool feed_one_packet(MppCtx ctx,
                     MppApi* mpi,
                     const std::vector<std::uint8_t>& bitstream,
                     const std::vector<std::size_t>& nal_offsets,
                     std::size_t* offset,
                     std::size_t* nal_index,
                     bool* eos_sent) {
    if (*eos_sent || *offset >= bitstream.size()) {
        return false;
    }

    auto* chunk_ptr = const_cast<std::uint8_t*>(bitstream.data() + *offset);
    std::size_t chunk_size = 0;
    if (!nal_offsets.empty() && *nal_index < nal_offsets.size()) {
        const std::size_t start = nal_offsets[*nal_index];
        std::size_t end = bitstream.size();
        if (*nal_index + 1 < nal_offsets.size()) {
            end = nal_offsets[*nal_index + 1];
        }
        if (end > start) {
            *offset = start;
            chunk_ptr = const_cast<std::uint8_t*>(bitstream.data() + start);
            chunk_size = end - start;
        }
        (*nal_index)++;
    }

    if (chunk_size == 0) {
        const std::size_t remain = bitstream.size() - *offset;
        chunk_size = remain > 65536 ? 65536 : remain;
        chunk_ptr = const_cast<std::uint8_t*>(bitstream.data() + *offset);
    }

    MppPacket packet = nullptr;
    MPP_RET ret = mpp_packet_init(&packet, chunk_ptr, chunk_size);
    if (ret != MPP_OK || packet == nullptr) {
        return false;
    }
    mpp_packet_set_pos(packet, chunk_ptr);
    mpp_packet_set_length(packet, chunk_size);
    mpp_packet_set_size(packet, chunk_size);

    if (*offset + chunk_size >= bitstream.size() || *nal_index >= nal_offsets.size()) {
        mpp_packet_set_eos(packet);
        *eos_sent = true;
    }

    ret = mpi->decode_put_packet(ctx, packet);
    mpp_packet_deinit(&packet);
    if (ret == MPP_OK) {
        *offset += chunk_size;
        return true;
    }
    return false;
}

RgaResizeInfo probe_rga_resize(MppFrame frame, int output_width, int output_height) {
    RgaResizeInfo info;
    info.requested = output_width > 0 && output_height > 0;
    info.output_width = output_width;
    info.output_height = output_height;
    info.output_channels = 3;
    if (!info.requested) {
        info.detail = "not_requested";
        return info;
    }

    const int src_width = static_cast<int>(mpp_frame_get_width(frame));
    const int src_height = static_cast<int>(mpp_frame_get_height(frame));
    const int src_hor_stride = static_cast<int>(mpp_frame_get_hor_stride(frame));
    const int src_ver_stride = static_cast<int>(mpp_frame_get_ver_stride(frame));
    const MppFrameFormat frame_format = mpp_frame_get_fmt(frame);
    MppBuffer buffer = mpp_frame_get_buffer(frame);
    if (buffer == nullptr) {
        info.detail = "mpp frame buffer missing";
        return info;
    }

    const int dma_fd = mpp_buffer_get_fd(buffer);
    if (dma_fd < 0) {
        info.detail = "mpp frame does not expose a dma fd";
        return info;
    }

    int rga_format = 0;
    if (!resolve_rga_source_format(frame_format, &rga_format)) {
        info.detail = "unsupported source format for RGA: " + pixel_format_name(frame_format);
        return info;
    }

    const float scale_w = static_cast<float>(output_width) / static_cast<float>(src_width);
    const float scale_h = static_cast<float>(output_height) / static_cast<float>(src_height);
    info.scale = std::min(scale_w, scale_h);
    info.scaled_width = std::max(1, std::min(output_width, static_cast<int>(static_cast<float>(src_width) * info.scale + 0.5f)));
    info.scaled_height = std::max(1, std::min(output_height, static_cast<int>(static_cast<float>(src_height) * info.scale + 0.5f)));
    info.pad_x = (output_width - info.scaled_width) / 2;
    info.pad_y = (output_height - info.scaled_height) / 2;

    const int rgb_src_stride = align_up(src_width, 16);
    const int rgb_scaled_stride = align_up(info.scaled_width, 16);

    rga_buffer_handle_t src_handle = importbuffer_fd(dma_fd, src_hor_stride, src_ver_stride, rga_format);
    if (src_handle == 0) {
        info.detail = "importbuffer_fd failed";
        return info;
    }

    std::vector<std::uint8_t> rgb_src(
        static_cast<std::size_t>(rgb_src_stride) * static_cast<std::size_t>(src_height) * static_cast<std::size_t>(info.output_channels), 0);
    std::vector<std::uint8_t> rgb_scaled(
        static_cast<std::size_t>(rgb_scaled_stride) * static_cast<std::size_t>(info.scaled_height) * static_cast<std::size_t>(info.output_channels), 0);

    rga_buffer_handle_t rgb_src_handle = importbuffer_virtualaddr(rgb_src.data(), static_cast<int>(rgb_src.size()));
    rga_buffer_handle_t rgb_scaled_handle = importbuffer_virtualaddr(rgb_scaled.data(), static_cast<int>(rgb_scaled.size()));
    if (rgb_src_handle == 0 || rgb_scaled_handle == 0) {
        if (rgb_src_handle != 0) {
            releasebuffer_handle(rgb_src_handle);
        }
        if (rgb_scaled_handle != 0) {
            releasebuffer_handle(rgb_scaled_handle);
        }
        releasebuffer_handle(src_handle);
        info.detail = "importbuffer_virtualaddr failed";
        return info;
    }

    rga_buffer_t src_buffer = wrapbuffer_handle_t(src_handle, src_width, src_height, src_hor_stride, src_ver_stride, rga_format);
    rga_buffer_t rgb_src_buffer = wrapbuffer_handle_t(
        rgb_src_handle, src_width, src_height, rgb_src_stride, src_height, RK_FORMAT_RGB_888);
    rga_buffer_t rgb_scaled_buffer = wrapbuffer_handle_t(
        rgb_scaled_handle, info.scaled_width, info.scaled_height, rgb_scaled_stride, info.scaled_height, RK_FORMAT_RGB_888);

    IM_STATUS status = imcvtcolor(src_buffer, rgb_src_buffer, rga_format, RK_FORMAT_RGB_888);
    if (!is_im_success(status)) {
        releasebuffer_handle(rgb_src_handle);
        releasebuffer_handle(rgb_scaled_handle);
        releasebuffer_handle(src_handle);
        info.detail = "imcvtcolor failed: " + std::string(imStrError(status));
        return info;
    }

    status = imresize(rgb_src_buffer, rgb_scaled_buffer, 0, 0, INTER_LINEAR, 1);
    releasebuffer_handle(rgb_src_handle);
    releasebuffer_handle(rgb_scaled_handle);
    releasebuffer_handle(src_handle);
    if (!is_im_success(status)) {
        info.detail = "imresize failed: " + std::string(imStrError(status));
        return info;
    }

    std::vector<std::uint8_t> rgb_output(
        static_cast<std::size_t>(output_width) * static_cast<std::size_t>(output_height) * static_cast<std::size_t>(info.output_channels),
        kLetterboxFill);
    for (int y = 0; y < info.scaled_height; ++y) {
        const std::size_t dst_row =
            (static_cast<std::size_t>(y + info.pad_y) * static_cast<std::size_t>(output_width) + static_cast<std::size_t>(info.pad_x)) *
            static_cast<std::size_t>(info.output_channels);
        const std::size_t src_row =
            static_cast<std::size_t>(y) * static_cast<std::size_t>(rgb_scaled_stride) * static_cast<std::size_t>(info.output_channels);
        const std::size_t copy_bytes = static_cast<std::size_t>(info.scaled_width) * static_cast<std::size_t>(info.output_channels);
        std::memcpy(rgb_output.data() + dst_row, rgb_scaled.data() + src_row, copy_bytes);
    }

    info.ok = true;
    info.output_bytes = rgb_output.size();
    info.output_data = std::move(rgb_output);
    info.detail = "imcvtcolor+imresize_letterbox_ok";
    return info;
}

}  // namespace

DecodeSamplingInfo decode_sampled_pipelines_from_annexb(const std::string& path,
                                                        int rga_width,
                                                        int rga_height,
                                                        int max_samples,
                                                        int frames_per_sample) {
    DecodeSamplingInfo sampling;
    const int capped_max_samples = std::max(1, max_samples);
    const int frame_stride = std::max(1, frames_per_sample);

    std::vector<std::uint8_t> bitstream;
    if (!load_file_to_buffer(path, &bitstream)) {
        return sampling;
    }

    const auto nal_offsets = build_nal_offsets(bitstream);
    const MppCodingType coding = guess_coding(path);

    MppCtx ctx = nullptr;
    MppApi* mpi = nullptr;
    MppBufferGroup frm_grp = nullptr;
    std::size_t offset = 0;
    std::size_t nal_index = 0;
    bool eos_sent = false;

    MPP_RET ret = mpp_create(&ctx, &mpi);
    if (ret != MPP_OK || ctx == nullptr || mpi == nullptr) {
        return sampling;
    }

    RK_U32 split_mode = 1;
    mpi->control(ctx, MPP_DEC_SET_PARSER_SPLIT_MODE, &split_mode);
    ret = mpp_init(ctx, MPP_CTX_DEC, coding);
    if (ret != MPP_OK) {
        mpp_destroy(ctx);
        return sampling;
    }

    int idle_loops_after_eos = 0;
    for (int attempts = 0; attempts < 4096; ++attempts) {
        const bool fed_packet = feed_one_packet(ctx, mpi, bitstream, nal_offsets, &offset, &nal_index, &eos_sent);

        MppFrame frame = nullptr;
        ret = mpi->decode_get_frame(ctx, &frame);
        if (ret != MPP_OK || frame == nullptr) {
            if (eos_sent && !fed_packet) {
                ++idle_loops_after_eos;
                if (idle_loops_after_eos > 64) {
                    break;
                }
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(2));
            continue;
        }
        idle_loops_after_eos = 0;

        if (mpp_frame_get_info_change(frame)) {
            if (!ensure_external_group(ctx, mpi, &frm_grp, frame)) {
                mpp_frame_deinit(&frame);
                break;
            }
            mpp_frame_deinit(&frame);
            continue;
        }

        ++sampling.decoded_frame_count;
        const bool should_sample = ((sampling.decoded_frame_count - 1) % frame_stride) == 0;
        if (should_sample) {
            SampledDecodePipelineInfo sample;
            sample.frame_index = sampling.decoded_frame_count;
            sample.pipeline.frame.ok = true;
            sample.pipeline.frame.width = static_cast<int>(mpp_frame_get_width(frame));
            sample.pipeline.frame.height = static_cast<int>(mpp_frame_get_height(frame));
            sample.pipeline.frame.hor_stride = static_cast<int>(mpp_frame_get_hor_stride(frame));
            sample.pipeline.frame.ver_stride = static_cast<int>(mpp_frame_get_ver_stride(frame));
            sample.pipeline.frame.pixel_format = pixel_format_name(mpp_frame_get_fmt(frame));
            sample.pipeline.frame.coding = coding_name(coding);
            MppBuffer buffer = mpp_frame_get_buffer(frame);
            sample.pipeline.frame.dma_fd = buffer ? mpp_buffer_get_fd(buffer) : -1;
            sample.pipeline.frame.detail = "decoded_sample_frame";
            sample.pipeline.rga.requested = rga_width > 0 && rga_height > 0;
            sample.pipeline.rga.output_width = rga_width;
            sample.pipeline.rga.output_height = rga_height;
            sample.pipeline.rga.output_channels = 3;
            if (sample.pipeline.rga.requested) {
                sample.pipeline.rga = probe_rga_resize(frame, rga_width, rga_height);
            }
            sampling.samples.push_back(std::move(sample));
            if (static_cast<int>(sampling.samples.size()) >= capped_max_samples) {
                mpp_frame_deinit(&frame);
                break;
            }
        }
        mpp_frame_deinit(&frame);
    }

    sampling.hit_eos = eos_sent;
    if (frm_grp != nullptr) {
        mpp_buffer_group_put(frm_grp);
    }
    if (ctx != nullptr) {
        mpp_destroy(ctx);
    }
    return sampling;
}

DecodePipelineInfo decode_pipeline_from_annexb(const std::string& path, int rga_width, int rga_height) {
    DecodePipelineInfo result;
    result.rga.requested = rga_width > 0 && rga_height > 0;
    result.rga.output_width = rga_width;
    result.rga.output_height = rga_height;
    result.rga.output_channels = 3;

    const DecodeSamplingInfo sampling = decode_sampled_pipelines_from_annexb(path, rga_width, rga_height, 1, 1);
    if (!sampling.samples.empty()) {
        return sampling.samples.front().pipeline;
    }

    std::vector<std::uint8_t> bitstream;
    if (!load_file_to_buffer(path, &bitstream)) {
        result.frame.detail = "failed to load bitstream file";
        if (result.rga.requested) {
            result.rga.detail = "decode input unavailable";
        }
        return result;
    }

    result.frame.coding = coding_name(guess_coding(path));
    result.frame.detail = "no frame decoded within attempt budget";
    if (result.rga.requested) {
        result.rga.detail = "decode did not produce a frame";
    }
    return result;
}

DecodedFrameInfo decode_one_frame_from_annexb(const std::string& path) {
    return decode_pipeline_from_annexb(path, 0, 0).frame;
}

}  // namespace decode_demo
