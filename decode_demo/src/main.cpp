#include "decode_demo/runtime_probe.hpp"

#include <algorithm>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>

namespace {

struct Options {
    bool self_check{false};
    std::string stream;
    std::string model;
    std::string plan_file;
};

Options parse_args(int argc, char** argv) {
    Options options;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--self-check") {
            options.self_check = true;
        } else if (arg == "--stream" && i + 1 < argc) {
            options.stream = argv[++i];
        } else if (arg == "--model" && i + 1 < argc) {
            options.model = argv[++i];
        } else if (arg == "--plan-file" && i + 1 < argc) {
            options.plan_file = argv[++i];
        } else if (arg == "--help" || arg == "-h") {
            std::cout << "Usage: rk_decode_demo [--self-check] [--stream <url_or_path>] [--model <file.rknn>] [--plan-file <plan.json>]\n";
            std::exit(0);
        } else {
            std::cerr << "Unknown argument: " << arg << '\n';
            std::exit(1);
        }
    }
    return options;
}

void print_path_summary(const std::string& label, const std::string& value) {
    if (value.empty()) {
        return;
    }
    std::cout << label << '=' << value;
    if (std::filesystem::exists(value) && std::filesystem::is_regular_file(value)) {
        std::cout << " exists=true size=" << std::filesystem::file_size(value);
    } else {
        std::cout << " exists=" << (std::filesystem::exists(value) ? "true" : "false");
    }
    std::cout << '\n';
}

void print_plan_summary(const std::string& plan_file) {
    if (plan_file.empty()) {
        return;
    }
    std::ifstream input(plan_file, std::ios::binary);
    if (!input) {
        std::cerr << "failed to open plan file: " << plan_file << '\n';
        std::exit(2);
    }
    input.seekg(0, std::ios::end);
    const auto size = input.tellg();
    input.seekg(0, std::ios::beg);
    std::string preview;
    preview.resize(static_cast<std::size_t>(std::min<std::streamoff>(size, 240)));
    input.read(preview.data(), static_cast<std::streamsize>(preview.size()));
    std::cout << "plan_file=" << plan_file << " bytes=" << size << '\n';
    std::cout << "plan_preview=" << preview << '\n';
}

}  // namespace

int main(int argc, char** argv) {
    const Options options = parse_args(argc, argv);

    if (options.self_check) {
        return decode_demo::run_self_check(std::cout);
    }

    std::cout << "rk_decode_demo pipeline skeleton\n";
    print_path_summary("model", options.model);
    if (!options.stream.empty()) {
        std::cout << "stream=" << options.stream << '\n';
    }
    print_plan_summary(options.plan_file);
    std::cout << "status=not_yet_executing_real_pipeline\n";
    std::cout << "next=implement MPP demux/decode, RGA resize, and RKNN init/run using the resolved inference plan\n";
    return 0;
}
