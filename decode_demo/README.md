# RK3588 Decode Demo

Minimal C++ scaffold for the RK3588 data-plane side of the project.

Current scope:

- verifies the host has MPP, RGA, and RKNN runtime libraries available
- compiles against Rockchip headers from the target device
- establishes a dedicated `decode_demo` CMake target for future `MPP -> RGA -> RKNN` work
- aligns with the Python control-plane contract exposed by `POST /api/v1/inference/plan`
- decodes the first frame from a local Annex-B H.264/H.265 elementary stream with MPP
- runs RGA color-convert + letterbox resize on the decoded DMA frame
- optionally loads an RKNN model, runs one-frame inference, and emits YOLOv5 detection boxes plus raw tensor summaries

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

Fetch the official RK3588 YOLOv5 sample model:

```bash
python3 tools/fetch_rknn_model.py \
  --output artifacts/models/yolov5s-640-640.rknn
```

Run the C++ executable with the generated manifest or a prepared elementary stream:

```bash
./build/rk_decode_demo --plan-file artifacts/inference-plan.manifest.tsv
./build/rk_decode_demo --stream artifacts/preview-clip.h264
./build/rk_decode_demo --stream artifacts/preview-clip.h264 --rga-width 640 --rga-height 640
./build/rk_decode_demo --stream artifacts/preview-clip.h264 --model artifacts/models/yolov5s-640-640.rknn
```

Expected pipeline output fields for `--stream`:

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
- `rga_scaled_width`
- `rga_scaled_height`
- `rga_pad_x`
- `rga_pad_y`
- `rga_scale`
- `rknn_model_ok`
- `rknn_ok`
- `rknn_detection_count`
- `detection_<n>_*`
- `rknn_output_<n>_sample_values`

Planned next steps:

1. Resolve manifest-selected streams into MPP input automatically.
2. Convert YOLOv5 detections into the Python runtime result contract.
3. Add optional label-file loading instead of the built-in COCO-80 list.
4. Extend the same path to additional RKNN models.
