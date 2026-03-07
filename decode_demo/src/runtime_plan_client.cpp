#include "decode_demo/runtime_plan_client.hpp"

#include <chrono>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace decode_demo {
namespace {

struct JsonValue {
    enum class Type {
        kNull,
        kBool,
        kNumber,
        kString,
        kArray,
        kObject,
    };

    Type type{Type::kNull};
    bool bool_value{false};
    double number_value{0.0};
    std::string string_value;
    std::vector<JsonValue> array_value;
    std::map<std::string, JsonValue> object_value;
};

class JsonParser {
public:
    explicit JsonParser(const std::string& text) : text_(text) {}

    JsonValue parse() {
        skip_ws();
        JsonValue value = parse_value();
        skip_ws();
        if (pos_ != text_.size()) {
            throw std::runtime_error("unexpected trailing characters in runtime plan JSON");
        }
        return value;
    }

private:
    JsonValue parse_value() {
        if (pos_ >= text_.size()) {
            throw std::runtime_error("unexpected end of JSON input");
        }
        const char ch = text_[pos_];
        if (ch == '{') {
            return parse_object();
        }
        if (ch == '[') {
            return parse_array();
        }
        if (ch == '"') {
            JsonValue value;
            value.type = JsonValue::Type::kString;
            value.string_value = parse_string();
            return value;
        }
        if (ch == 't' || ch == 'f') {
            return parse_bool();
        }
        if (ch == 'n') {
            return parse_null();
        }
        if (ch == '-' || std::isdigit(static_cast<unsigned char>(ch)) != 0) {
            return parse_number();
        }
        throw std::runtime_error(std::string("unexpected JSON token: ") + ch);
    }

    JsonValue parse_object() {
        expect('{');
        JsonValue value;
        value.type = JsonValue::Type::kObject;
        skip_ws();
        if (consume('}')) {
            return value;
        }
        while (true) {
            skip_ws();
            const std::string key = parse_string();
            skip_ws();
            expect(':');
            skip_ws();
            value.object_value.emplace(key, parse_value());
            skip_ws();
            if (consume('}')) {
                break;
            }
            expect(',');
            skip_ws();
        }
        return value;
    }

    JsonValue parse_array() {
        expect('[');
        JsonValue value;
        value.type = JsonValue::Type::kArray;
        skip_ws();
        if (consume(']')) {
            return value;
        }
        while (true) {
            skip_ws();
            value.array_value.push_back(parse_value());
            skip_ws();
            if (consume(']')) {
                break;
            }
            expect(',');
            skip_ws();
        }
        return value;
    }

    JsonValue parse_bool() {
        JsonValue value;
        value.type = JsonValue::Type::kBool;
        if (match("true")) {
            value.bool_value = true;
            return value;
        }
        if (match("false")) {
            value.bool_value = false;
            return value;
        }
        throw std::runtime_error("invalid boolean literal in runtime plan JSON");
    }

    JsonValue parse_null() {
        if (!match("null")) {
            throw std::runtime_error("invalid null literal in runtime plan JSON");
        }
        return JsonValue{};
    }

    JsonValue parse_number() {
        const char* begin = text_.c_str() + pos_;
        char* end = nullptr;
        const double parsed = std::strtod(begin, &end);
        if (end == begin) {
            throw std::runtime_error("invalid numeric literal in runtime plan JSON");
        }
        pos_ += static_cast<std::size_t>(end - begin);
        JsonValue value;
        value.type = JsonValue::Type::kNumber;
        value.number_value = parsed;
        return value;
    }

    std::string parse_string() {
        expect('"');
        std::string out;
        while (pos_ < text_.size()) {
            const char ch = text_[pos_++];
            if (ch == '"') {
                return out;
            }
            if (ch != '\\') {
                out.push_back(ch);
                continue;
            }
            if (pos_ >= text_.size()) {
                throw std::runtime_error("unterminated escape sequence in runtime plan JSON");
            }
            const char escaped = text_[pos_++];
            switch (escaped) {
                case '"': out.push_back('"'); break;
                case '\\': out.push_back('\\'); break;
                case '/': out.push_back('/'); break;
                case 'b': out.push_back('\b'); break;
                case 'f': out.push_back('\f'); break;
                case 'n': out.push_back('\n'); break;
                case 'r': out.push_back('\r'); break;
                case 't': out.push_back('\t'); break;
                case 'u': append_unicode_escape(&out); break;
                default:
                    throw std::runtime_error("unsupported escape sequence in runtime plan JSON");
            }
        }
        throw std::runtime_error("unterminated string in runtime plan JSON");
    }

    void append_unicode_escape(std::string* out) {
        if (pos_ + 4 > text_.size()) {
            throw std::runtime_error("truncated unicode escape in runtime plan JSON");
        }
        unsigned int codepoint = 0;
        for (int i = 0; i < 4; ++i) {
            codepoint <<= 4;
            const char ch = text_[pos_++];
            if (ch >= '0' && ch <= '9') {
                codepoint |= static_cast<unsigned int>(ch - '0');
            } else if (ch >= 'a' && ch <= 'f') {
                codepoint |= static_cast<unsigned int>(10 + ch - 'a');
            } else if (ch >= 'A' && ch <= 'F') {
                codepoint |= static_cast<unsigned int>(10 + ch - 'A');
            } else {
                throw std::runtime_error("invalid unicode escape in runtime plan JSON");
            }
        }
        if (codepoint <= 0x7F) {
            out->push_back(static_cast<char>(codepoint));
        } else if (codepoint <= 0x7FF) {
            out->push_back(static_cast<char>(0xC0 | ((codepoint >> 6) & 0x1F)));
            out->push_back(static_cast<char>(0x80 | (codepoint & 0x3F)));
        } else {
            out->push_back(static_cast<char>(0xE0 | ((codepoint >> 12) & 0x0F)));
            out->push_back(static_cast<char>(0x80 | ((codepoint >> 6) & 0x3F)));
            out->push_back(static_cast<char>(0x80 | (codepoint & 0x3F)));
        }
    }

    void skip_ws() {
        while (pos_ < text_.size() && std::isspace(static_cast<unsigned char>(text_[pos_])) != 0) {
            ++pos_;
        }
    }

    bool consume(char ch) {
        if (pos_ < text_.size() && text_[pos_] == ch) {
            ++pos_;
            return true;
        }
        return false;
    }

    void expect(char ch) {
        if (!consume(ch)) {
            throw std::runtime_error(std::string("expected JSON character: ") + ch);
        }
    }

    bool match(const char* literal) {
        std::size_t i = 0;
        while (literal[i] != '\0') {
            if (pos_ + i >= text_.size() || text_[pos_ + i] != literal[i]) {
                return false;
            }
            ++i;
        }
        pos_ += i;
        return true;
    }

    const std::string& text_;
    std::size_t pos_{0};
};

const JsonValue* object_get(const JsonValue& value, const char* key) {
    if (value.type != JsonValue::Type::kObject) {
        return nullptr;
    }
    const auto it = value.object_value.find(key);
    if (it == value.object_value.end()) {
        return nullptr;
    }
    return &it->second;
}

std::string json_string(const JsonValue* value, const std::string& fallback = std::string()) {
    if (value == nullptr || value->type == JsonValue::Type::kNull) {
        return fallback;
    }
    if (value->type != JsonValue::Type::kString) {
        throw std::runtime_error("runtime plan field has unexpected non-string type");
    }
    return value->string_value;
}

bool json_bool(const JsonValue* value, bool fallback = false) {
    if (value == nullptr || value->type == JsonValue::Type::kNull) {
        return fallback;
    }
    if (value->type != JsonValue::Type::kBool) {
        throw std::runtime_error("runtime plan field has unexpected non-bool type");
    }
    return value->bool_value;
}

double json_number(const JsonValue* value, double fallback = 0.0) {
    if (value == nullptr || value->type == JsonValue::Type::kNull) {
        return fallback;
    }
    if (value->type != JsonValue::Type::kNumber) {
        throw std::runtime_error("runtime plan field has unexpected non-number type");
    }
    return value->number_value;
}

int json_int(const JsonValue* value, int fallback = 0) {
    return static_cast<int>(json_number(value, static_cast<double>(fallback)));
}

const std::vector<JsonValue>& json_array(const JsonValue* value, const char* field_name) {
    if (value == nullptr || value->type != JsonValue::Type::kArray) {
        throw std::runtime_error(std::string("runtime plan field is not an array: ") + field_name);
    }
    return value->array_value;
}

const JsonValue& require_object_field(const JsonValue& object, const char* key) {
    const JsonValue* value = object_get(object, key);
    if (value == nullptr) {
        throw std::runtime_error(std::string("missing runtime plan field: ") + key);
    }
    if (value->type != JsonValue::Type::kObject) {
        throw std::runtime_error(std::string("runtime plan field is not an object: ") + key);
    }
    return *value;
}

const JsonValue& require_array_field(const JsonValue& object, const char* key) {
    const JsonValue* value = object_get(object, key);
    if (value == nullptr) {
        throw std::runtime_error(std::string("missing runtime plan field: ") + key);
    }
    if (value->type != JsonValue::Type::kArray) {
        throw std::runtime_error(std::string("runtime plan field is not an array: ") + key);
    }
    return *value;
}

std::string shell_escape_single_quoted(const std::string& value) {
    std::string escaped;
    escaped.reserve(value.size() + 8);
    escaped.push_back(static_cast<char>(39));
    for (char ch : value) {
        if (ch == static_cast<char>(39)) {
            escaped += "'\''";
        } else {
            escaped.push_back(ch);
        }
    }
    escaped.push_back(static_cast<char>(39));
    return escaped;
}

std::string run_command_capture_stdout(const std::string& command, int* exit_code) {
#if defined(_WIN32)
    FILE* pipe = _popen(command.c_str(), "rb");
#else
    FILE* pipe = popen(command.c_str(), "r");
#endif
    if (pipe == nullptr) {
        throw std::runtime_error("failed to launch runtime plan fetch command");
    }

    std::string output;
    char buffer[4096];
    while (true) {
        const std::size_t read_bytes = std::fread(buffer, 1, sizeof(buffer), pipe);
        if (read_bytes > 0) {
            output.append(buffer, read_bytes);
        }
        if (read_bytes < sizeof(buffer)) {
            if (std::feof(pipe) != 0) {
                break;
            }
            if (std::ferror(pipe) != 0) {
#if defined(_WIN32)
                _pclose(pipe);
#else
                pclose(pipe);
#endif
                throw std::runtime_error("failed while reading runtime plan fetch command output");
            }
        }
    }

#if defined(_WIN32)
    const int status = _pclose(pipe);
#else
    const int status = pclose(pipe);
#endif
    if (exit_code != nullptr) {
        *exit_code = status;
    }
    return output;
}

std::string build_runtime_plan_request_body(double budget) {
    std::ostringstream output;
    output << std::fixed << std::setprecision(3) << "{\"budget\": " << budget << '}';
    return output.str();
}

void ensure_parent_dir(const std::string& path) {
    if (path.empty()) {
        return;
    }
    const auto parent = std::filesystem::path(path).parent_path();
    if (!parent.empty()) {
        std::filesystem::create_directories(parent);
    }
}

void write_text_file(const std::string& path, const std::string& content) {
    if (path.empty()) {
        return;
    }
    ensure_parent_dir(path);
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output.is_open()) {
        throw std::runtime_error("failed to open runtime plan cache for write: " + path);
    }
    output.write(content.data(), static_cast<std::streamsize>(content.size()));
}

std::string read_text_file(const std::string& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input.is_open()) {
        throw std::runtime_error("failed to open runtime plan cache: " + path);
    }
    std::ostringstream buffer;
    buffer << input.rdbuf();
    return buffer.str();
}

RuntimePlanFetchResult fetch_runtime_plan_once(const RuntimePlanFetchOptions& options) {
    const std::string request_url = options.runtime_url + "/api/v1/inference/plan";
    const std::string request_body = build_runtime_plan_request_body(options.budget);
    const std::string marker = "__RK_HTTP_STATUS__:";

    std::string command = "curl -sS -X POST --max-time 15 -H 'Content-Type: application/json' ";
    if (!options.token.empty()) {
        command += "-H ";
        command += shell_escape_single_quoted("Authorization: Bearer " + options.token);
        command += ' ';
    }
    command += "--data ";
    command += shell_escape_single_quoted(request_body);
    command += ' ';
    command += shell_escape_single_quoted(request_url);
    command += " -w ";
    command += shell_escape_single_quoted("\n" + marker + "%{http_code}");

    int exit_code = 0;
    const std::string output = run_command_capture_stdout(command, &exit_code);
    if (exit_code != 0) {
        throw std::runtime_error("runtime plan request command failed with exit code " + std::to_string(exit_code));
    }

    const std::size_t marker_pos = output.rfind(marker);
    if (marker_pos == std::string::npos) {
        throw std::runtime_error("runtime plan fetch response missing HTTP status marker");
    }

    RuntimePlanFetchResult result;
    result.request_url = request_url;
    result.cache_path = options.cache_path;
    result.response_body = output.substr(0, marker_pos);
    if (!result.response_body.empty() && result.response_body.back() == static_cast<char>(10)) {
        result.response_body.pop_back();
    }
    const std::string status_text = output.substr(marker_pos + marker.size());
    result.http_status = std::strtol(status_text.c_str(), nullptr, 10);
    if (result.http_status != 200) {
        throw std::runtime_error("runtime plan request returned HTTP " + std::to_string(result.http_status) + ": " + result.response_body);
    }

    result.manifest = parse_runtime_plan_json(result.response_body);
    return result;
}

}  // namespace

PlanManifest parse_runtime_plan_json(const std::string& payload) {
    const JsonValue root = JsonParser(payload).parse();
    if (root.type != JsonValue::Type::kObject) {
        throw std::runtime_error("runtime plan payload root must be an object");
    }
    const JsonValue& data = require_object_field(root, "data");
    const JsonValue& streams = require_array_field(data, "streams");

    PlanManifest manifest;
    manifest.budget = json_number(object_get(data, "budget"));
    manifest.degraded = json_bool(object_get(data, "degraded"));
    manifest.total_cost = json_number(object_get(data, "total_cost"));
    manifest.stream_count = json_int(object_get(data, "stream_count"));
    manifest.ready_stream_count = json_int(object_get(data, "ready_stream_count"));

    for (const auto& stream : streams.array_value) {
        if (stream.type != JsonValue::Type::kObject) {
            throw std::runtime_error("runtime plan stream entry must be an object");
        }
        const std::string tenant_id = json_string(object_get(stream, "tenant_id"));
        const std::string site_id = json_string(object_get(stream, "site_id"));
        const std::string box_id = json_string(object_get(stream, "box_id"));
        const std::string device_id = json_string(object_get(stream, "device_id"));
        const std::string protocol = json_string(object_get(stream, "protocol"));
        const std::string stream_url = json_string(object_get(stream, "stream_url"));
        const double fps_in = json_number(object_get(stream, "fps_in"));
        const double sample_fps = json_number(object_get(stream, "sample_fps"));
        const double estimated_cost = json_number(object_get(stream, "estimated_cost"));
        const int priority = json_int(object_get(stream, "priority"));
        const double complexity = json_number(object_get(stream, "complexity"));
        const JsonValue& workloads = require_array_field(stream, "workloads");

        for (const auto& workload : workloads.array_value) {
            if (workload.type != JsonValue::Type::kObject) {
                throw std::runtime_error("runtime plan workload entry must be an object");
            }
            ManifestWorkload item;
            item.tenant_id = tenant_id;
            item.site_id = site_id;
            item.box_id = box_id;
            item.device_id = device_id;
            item.protocol = protocol;
            item.stream_url = stream_url;
            item.fps_in = fps_in;
            item.sample_fps = sample_fps;
            item.estimated_cost = estimated_cost;
            item.priority = priority;
            item.complexity = complexity;
            item.capability = json_string(object_get(workload, "capability"));
            item.algorithm_id = json_string(object_get(workload, "algorithm_id"));
            item.algorithm_version = json_string(object_get(workload, "algorithm_version"));
            item.base_library_id = json_string(object_get(workload, "base_library_id"));
            item.base_library_version = json_string(object_get(workload, "base_library_version"));
            item.binding_status = json_string(object_get(workload, "binding_status"));

            const JsonValue* execution = object_get(workload, "execution");
            if (execution != nullptr && execution->type == JsonValue::Type::kObject) {
                item.execution_ready = json_bool(object_get(*execution, "execution_ready"));
                item.stream_uri = json_string(object_get(*execution, "stream_uri"));
                item.model_uri = json_string(object_get(*execution, "model_uri"));
                item.result_uri = json_string(object_get(*execution, "result_uri"));
                item.sample_period_ms = json_int(object_get(*execution, "sample_period_ms"));
                item.frames_per_sample = json_int(object_get(*execution, "frames_per_sample"));
                item.max_samples_per_run = json_int(object_get(*execution, "max_samples_per_run"), 1);
            }
            manifest.workloads.push_back(std::move(item));
        }
    }
    return manifest;
}

RuntimePlanFetchResult fetch_runtime_plan(const RuntimePlanFetchOptions& options) {
    if (options.runtime_url.empty()) {
        throw std::runtime_error("runtime_url must not be empty");
    }

    const int max_attempts = options.max_attempts > 0 ? options.max_attempts : 1;
    const int retry_backoff_ms = options.retry_backoff_ms >= 0 ? options.retry_backoff_ms : 0;
    std::string last_error;

    for (int attempt = 1; attempt <= max_attempts; ++attempt) {
        try {
            RuntimePlanFetchResult result = fetch_runtime_plan_once(options);
            result.attempt_count = attempt;
            result.used_cache = false;
            if (!options.cache_path.empty()) {
                write_text_file(options.cache_path, result.response_body);
            }
            return result;
        } catch (const std::exception& ex) {
            last_error = ex.what();
            if (attempt < max_attempts && retry_backoff_ms > 0) {
                const int sleep_ms = retry_backoff_ms * attempt;
                std::this_thread::sleep_for(std::chrono::milliseconds(sleep_ms));
            }
        }
    }

    if (!options.cache_path.empty() && std::filesystem::exists(options.cache_path)) {
        RuntimePlanFetchResult cached;
        cached.request_url = options.runtime_url + "/api/v1/inference/plan";
        cached.cache_path = options.cache_path;
        cached.http_status = 0;
        cached.attempt_count = max_attempts;
        cached.used_cache = true;
        cached.response_body = read_text_file(options.cache_path);
        cached.manifest = parse_runtime_plan_json(cached.response_body);
        return cached;
    }

    throw std::runtime_error("runtime plan fetch failed after " + std::to_string(max_attempts) +
                             " attempt(s): " + last_error);
}

}  // namespace decode_demo
