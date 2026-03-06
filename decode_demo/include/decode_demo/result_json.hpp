#pragma once

#include "decode_demo/mpp_decode.hpp"
#include "decode_demo/plan_manifest.hpp"
#include "decode_demo/rknn_runner.hpp"

#include <string>
#include <vector>

namespace decode_demo {

struct BatchExecutionItem {
    const ManifestWorkload* workload{nullptr};
    std::string stream_path;
    std::string model_path;
    std::string output_path;
    bool asset_binding_resolved{false};
    int exit_code{0};
    std::string status;
    bool decode_ok{false};
    bool rga_requested{false};
    bool rga_ok{false};
    bool rknn_requested{false};
    bool rknn_ok{false};
    int detection_count{0};
};

void write_detection_result_json(const std::string& path,
                                 const ManifestWorkload* workload,
                                 const DecodedFrameInfo& frame,
                                 const RgaResizeInfo& rga,
                                 const RknnRunInfo* run);

void write_batch_result_json(const std::string& path, const std::vector<BatchExecutionItem>& items);

}  // namespace decode_demo
