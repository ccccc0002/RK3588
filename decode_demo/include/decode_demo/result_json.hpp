#pragma once

#include "decode_demo/mpp_decode.hpp"
#include "decode_demo/plan_manifest.hpp"
#include "decode_demo/rknn_runner.hpp"

#include <string>

namespace decode_demo {

void write_detection_result_json(const std::string& path,
                                 const ManifestWorkload* workload,
                                 const DecodedFrameInfo& frame,
                                 const RgaResizeInfo& rga,
                                 const RknnRunInfo* run);

}  // namespace decode_demo
