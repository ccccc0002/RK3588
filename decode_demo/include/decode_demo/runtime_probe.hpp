#pragma once

#include <iosfwd>
#include <string>
#include <vector>

namespace decode_demo {

struct LibraryProbe {
    std::string logical_name;
    std::string soname;
    bool loadable{false};
    std::string resolved_path;
    std::string detail;
};

struct ProbeReport {
    std::vector<std::string> include_dirs;
    std::vector<LibraryProbe> libraries;
    bool headers_compiled{true};
    bool all_libraries_loadable{false};
};

ProbeReport probe_runtime_environment();
int run_self_check(std::ostream& os);

}  // namespace decode_demo
