cmake_minimum_required(VERSION 3.16)
project(rk_decode_demo LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_path(RK_MPP_INCLUDE_DIR rk_mpi.h PATHS /usr/include/rockchip /usr/local/include/rockchip)
find_path(RGA_INCLUDE_DIR im2d.h PATHS /usr/include/rga /usr/local/include/rga)
find_path(RKNN_INCLUDE_DIR rknn_api.h PATHS
    /usr/include
    /usr/local/include
    /home/zql/ks/third_party/rknn_model_zoo/3rdparty/rknpu2/include
)

find_library(RK_MPP_LIB rockchip_mpp PATHS /usr/lib /usr/lib/aarch64-linux-gnu /lib/aarch64-linux-gnu)
find_library(RGA_LIB rga PATHS /usr/lib /usr/lib/aarch64-linux-gnu /lib/aarch64-linux-gnu)
find_library(RKNN_LIB rknnrt PATHS /usr/lib /usr/lib/aarch64-linux-gnu /lib/aarch64-linux-gnu)
find_library(DL_LIB dl)

add_executable(rk_decode_demo
    src/execution_asset.cpp
    src/main.cpp
    src/mpp_decode.cpp
    src/plan_manifest.cpp
    src/result_json.cpp
    src/rknn_runner.cpp
    src/runtime_plan_client.cpp
    src/runtime_probe.cpp
)

target_include_directories(rk_decode_demo PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${RK_MPP_INCLUDE_DIR}
    ${RGA_INCLUDE_DIR}
    ${RKNN_INCLUDE_DIR}
)

if(RK_MPP_LIB)
    target_link_libraries(rk_decode_demo PRIVATE ${RK_MPP_LIB})
endif()
if(RGA_LIB)
    target_link_libraries(rk_decode_demo PRIVATE ${RGA_LIB})
endif()
if(RKNN_LIB)
    target_link_libraries(rk_decode_demo PRIVATE ${RKNN_LIB})
endif()
if(DL_LIB)
    target_link_libraries(rk_decode_demo PRIVATE ${DL_LIB})
endif()

target_compile_definitions(rk_decode_demo PRIVATE
    RK_DECODE_DEMO_RK_MPP_INCLUDE_DIR="${RK_MPP_INCLUDE_DIR}"
    RK_DECODE_DEMO_RGA_INCLUDE_DIR="${RGA_INCLUDE_DIR}"
    RK_DECODE_DEMO_RKNN_INCLUDE_DIR="${RKNN_INCLUDE_DIR}"
)

message(STATUS "RK_MPP_INCLUDE_DIR=${RK_MPP_INCLUDE_DIR}")
message(STATUS "RGA_INCLUDE_DIR=${RGA_INCLUDE_DIR}")
message(STATUS "RKNN_INCLUDE_DIR=${RKNN_INCLUDE_DIR}")
message(STATUS "RK_MPP_LIB=${RK_MPP_LIB}")
message(STATUS "RGA_LIB=${RGA_LIB}")
message(STATUS "RKNN_LIB=${RKNN_LIB}")

