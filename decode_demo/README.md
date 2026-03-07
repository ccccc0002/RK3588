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
- can resolve `stream/model/output` automatically from a plan manifest when the control-plane includes execution resources
- can fetch `/api/v1/inference/plan` directly from the Python runtime with bearer auth and execute it without an exported manifest file
- still supports a local execution asset map as a fallback when those execution resources are absent
- writes structured result JSON artifacts for later runtime/reporting integration
- executes every ready workload in a manifest run and emits a batch summary JSON index
- can submit single-result or batch-result artifacts back to the Python runtime via `/api/v1/inference/results`

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
  --input /home/zql/ks/data/media/live-preview/cam-entrance-01/latest-clip.mp4 \
  --output artifacts/latest-clip.h264
```

Fetch the official RK3588 YOLOv5 sample model:

```bash
python3 tools/fetch_rknn_model.py \
  --output artifacts/models/yolov5s-640-640.rknn
```

Render an execution asset map for automatic manifest-driven execution:

```bash
python3 tools/render_execution_asset_map.py \
  --output artifacts/execution-assets.tsv \
  --device-id cam-1 \
  --capability face \
  --algorithm-id face-detector \
  --algorithm-version 1.0.0 \
  --base-library-id lib-face-core \
  --base-library-version 2026.03 \
  --stream-path artifacts/latest-clip.h264 \
  --model-path artifacts/models/yolov5s-640-640.rknn \
  --result-path artifacts/results/cam-1.json
```

Run the C++ executable with a prepared elementary stream:

```bash
./build/rk_decode_demo --stream artifacts/latest-clip.h264 --model artifacts/models/yolov5s-640-640.rknn --output artifacts/results/manual.json
```

Run the same pipeline from a manifest plus asset map:

```bash
./build/rk_decode_demo \
  --plan-file artifacts/inference-plan.manifest.tsv \
  --asset-map artifacts/execution-assets.tsv
```

Run the same pipeline by fetching the plan directly from the Python runtime:

```bash
./build/rk_decode_demo \
  --runtime-url http://127.0.0.1:18080 \
  --token <bearer-token> \
  --budget 12 \
  --runtime-plan-cache artifacts/runtime-plan-cache.json \
  --runtime-plan-attempts 3 \
  --runtime-plan-backoff-ms 500
```

When the manifest contains multiple ready workloads, `rk_decode_demo` now executes each workload in sequence, writes one per-workload result JSON, and emits a batch summary JSON (default: `artifacts/results/manifest-run-summary.json`). If the manifest carries `execution.stream_uri` / `execution.model_uri` / `execution.result_uri`, the demo can run without `--asset-map`.

For `--runtime-url`, the demo retries failed plan fetches, saves the last successful plan JSON to `--runtime-plan-cache`, and automatically falls back to that cache when the control-plane is temporarily unavailable.

When a workload carries `execution.frames_per_sample > 1` or `execution.max_samples_per_run > 1`, the demo decodes multiple frames from the Annex-B stream, runs RKNN on each sampled frame, and keeps the best successful sample as the compatibility result JSON for that workload. The batch summary records the requested and actual sample counts for each workload.

Expected pipeline output fields for `--stream` / `--plan-file` / `--runtime-url`:

- `selected_*` manifest workload fields
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
- `output=<result.json>`

Result JSON contains:

- selected workload metadata
- decode metadata
- RGA letterbox metadata
- inference metadata
- detection list with class, confidence, and box coordinates

Batch summary JSON contains:

- one item per manifest-selected workload
- root-level plan provenance fields such as `plan_source`, `runtime_plan_url`, `runtime_plan_http_status`, `runtime_plan_attempt_count`, `runtime_plan_used_cache`, and `runtime_plan_cache_path` when execution came from `--runtime-url`
- resolved stream/model/output paths
- per-workload exit code and stage status
- per-workload detection counts
- per-workload `frames_per_sample`, `requested_sample_count`, and `sampled_frame_count`

Submit result artifacts back to the Python runtime:

```bash
python3 tools/submit_inference_result.py \
  --runtime-url http://127.0.0.1:18080 \
  --token <bearer-token> \
  --input artifacts/results/manifest-run-summary.json
```

Planned next steps:

1. Extend the result JSON schema with optional sampling metadata for per-workload debugging and auditing.
2. Add optional label-file loading instead of the built-in COCO-80 list.
3. Add long-running decode session management for continuous stream polling instead of file-based clips.
4. Add observability counters for runtime-plan live fetches vs cache fallbacks in long-running service mode.
