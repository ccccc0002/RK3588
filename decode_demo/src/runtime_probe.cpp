#include "decode_demo/runtime_probe.hpp"

#include <dlfcn.h>

#include <iostream>
#include <utility>

extern "C" {
#include <rk_mpi.h>
#include <rknn_api.h>
}
#include <im2d.h>

namespace decode_demo {
namespace {

LibraryProbe probe_one_library(std::string logical_name, std::string soname) {
    LibraryProbe probe;
    probe.logical_name = std::move(logical_name);
    probe.soname = std::move(soname);

    dlerror();
    void* handle = dlopen(probe.soname.c_str(), RTLD_NOW | RTLD_LOCAL);
    if (handle == nullptr) {
        const char* err = dlerror();
        probe.loadable = false;
        probe.detail = err == nullptr ? "dlopen failed without detail" : err;
        return probe;
    }

    probe.loadable = true;
    probe.resolved_path = probe.soname;
    probe.detail = "loaded";
    dlclose(handle);
    return probe;
}

std::pair<bool, std::string> probe_mpp_decoder_init_avc() {
    MppCtx ctx = nullptr;
    MppApi* mpi = nullptr;
    MPP_RET ret = mpp_create(&ctx, &mpi);
    if (ret != MPP_OK) {
        return {false, "mpp_create failed: " + std::to_string(ret)};
    }

    ret = mpp_init(ctx, MPP_CTX_DEC, MPP_VIDEO_CodingAVC);
    if (ret != MPP_OK) {
        mpp_destroy(ctx);
        return {false, "mpp_init(MPP_CTX_DEC, MPP_VIDEO_CodingAVC) failed: " + std::to_string(ret)};
    }

    ret = mpp_destroy(ctx);
    if (ret != MPP_OK) {
        return {false, "mpp_destroy failed: " + std::to_string(ret)};
    }
    return {true, "initialized"};
}

}  // namespace

ProbeReport probe_runtime_environment() {
    ProbeReport report;
    report.include_dirs = {
        RK_DECODE_DEMO_RK_MPP_INCLUDE_DIR,
        RK_DECODE_DEMO_RGA_INCLUDE_DIR,
        RK_DECODE_DEMO_RKNN_INCLUDE_DIR,
    };
    report.libraries.push_back(probe_one_library("mpp", "librockchip_mpp.so"));
    report.libraries.push_back(probe_one_library("rga", "librga.so"));
    report.libraries.push_back(probe_one_library("rknn", "librknnrt.so"));

    report.all_libraries_loadable = true;
    for (const auto& item : report.libraries) {
        if (!item.loadable) {
            report.all_libraries_loadable = false;
            break;
        }
    }

    const auto mpp_probe = probe_mpp_decoder_init_avc();
    report.mpp_decoder_init_avc = mpp_probe.first;
    report.mpp_decoder_init_detail = mpp_probe.second;
    return report;
}

int run_self_check(std::ostream& os) {
    const ProbeReport report = probe_runtime_environment();
    os << "rk_decode_demo self-check\n";
    os << "headers_compiled=" << (report.headers_compiled ? "true" : "false") << '\n';
    os << "include_dirs:\n";
    for (const auto& dir : report.include_dirs) {
        os << "  - " << dir << '\n';
    }
    os << "libraries:\n";
    for (const auto& lib : report.libraries) {
        os << "  - " << lib.logical_name << " (" << lib.soname << ") loadable="
           << (lib.loadable ? "true" : "false");
        if (!lib.detail.empty()) {
            os << " detail=\"" << lib.detail << "\"";
        }
        os << '\n';
    }
    os << "all_libraries_loadable=" << (report.all_libraries_loadable ? "true" : "false") << '\n';
    os << "mpp_decoder_init_avc=" << (report.mpp_decoder_init_avc ? "true" : "false");
    if (!report.mpp_decoder_init_detail.empty()) {
        os << " detail=\"" << report.mpp_decoder_init_detail << "\"";
    }
    os << '\n';
    os << "next_step=wire MPP packet/frame decode + RGA preprocess + RKNN model execution into these adapters\n";
    return (report.all_libraries_loadable && report.mpp_decoder_init_avc) ? 0 : 2;
}

}  // namespace decode_demo
