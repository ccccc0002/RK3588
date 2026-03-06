# RK3588 Decode Demo

Minimal C++ scaffold for the RK3588 data-plane side of the project.

Current scope:

- verifies the host has MPP, RGA, and RKNN runtime libraries available
- compiles against Rockchip headers from the target device
- establishes a dedicated `decode_demo` CMake target for future `MPP -> RGA -> RKNN` work
- aligns with the Python control-plane contract exposed by `POST /api/v1/inference/plan`

Build:

```bash
cd /home/zql/ks/rk3588/decode_demo
cmake -S . -B build
cmake --build build -j4
```

Self-check:

```bash
./build/rk_decode_demo --self-check
```

Fetch runtime plan into a local JSON artifact:

```bash
python3 tools/fetch_inference_plan.py \
  --runtime-url http://127.0.0.1:18080 \
  --budget 12 \
  --token <bearer-token> \
  --output artifacts/inference-plan.json
```

Planned next steps:

1. Accept an inference-plan JSON file produced by the Python runtime.
2. Initialize MPP decode for one RTSP/file stream.
3. Use RGA for resize/color conversion to RKNN input tensors.
4. Load an `.rknn` model and run one-frame inference.
5. Return structured detections back to the Python runtime.

