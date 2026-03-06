# RK3588 Decode Demo

Minimal C++ scaffold for the RK3588 data-plane side of the project.

Current scope:

- verifies the host has MPP, RGA, and RKNN runtime libraries available
- compiles against Rockchip headers from the target device
- establishes a dedicated `decode_demo` CMake target for future `MPP -> RGA -> RKNN` work
- aligns with the Python control-plane contract exposed by `POST /api/v1/inference/plan`
- decodes the first frame from a local Annex-B H.264/H.265 elementary stream with MPP
- optionally runs one in-process RGA color-convert + resize probe on the decoded DMA frame

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

Render the JSON plan into a TSV manifest that `rk_decode_demo` can consume directly:

```bash
python3 tools/render_plan_manifest.py \
  --input artifacts/inference-plan.json \
  --output artifacts/inference-plan.manifest.tsv
```

Prepare a local Annex-B stream from MP4 for MPP decode testing:

```bash
python3 tools/prepare_annexb_stream.py \
  --input /home/zql/ks/data/media/simulated/cam-entrance-01/preview-clip.mp4 \
  --output artifacts/preview-clip.h264
```

Run the C++ executable with the generated manifest or a prepared elementary stream:

```bash
./build/rk_decode_demo --plan-file artifacts/inference-plan.manifest.tsv
./build/rk_decode_demo --stream artifacts/preview-clip.h264
./build/rk_decode_demo --stream artifacts/preview-clip.h264 --rga-width 640 --rga-height 640
```

Expected decode output fields for `--stream`:

- `decode_ok`
- `decode_coding`
- `decode_pixel_format`
- `decode_detail`
- `decode_width`
- `decode_height`
- `decode_hor_stride`
- `decode_ver_stride`
- `decode_dma_fd`
- `rga_requested`
- `rga_ok`
- `rga_detail`
- `rga_output_width`
- `rga_output_height`
- `rga_output_channels`
- `rga_output_bytes`

Planned next steps:

1. Resolve manifest-selected streams into MPP input automatically.
2. Feed the RGA output directly into RKNN tensors.
3. Load an `.rknn` model and run one-frame inference.
4. Return structured detections back to the Python runtime.
