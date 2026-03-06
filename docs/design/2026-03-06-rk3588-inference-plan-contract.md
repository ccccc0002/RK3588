# RK3588 Inference Plan Contract

Date: 2026-03-06
Status: Drafted and implemented in Python control-plane
Endpoint: `POST /api/v1/inference/plan`

## Goal

Provide a stable control-plane contract that a RK3588 data-plane process can consume for:

- MPP decode stream selection
- RGA pre-processing scheduling
- RKNN model/base-library binding
- On-box execution resource resolution without a local-only asset map
- Per-stream sample FPS control under budget pressure

## Request

```json
{
  "budget": 10.0
}
```

## Response shape

```json
{
  "success": true,
  "data": {
    "budget": 10.0,
    "degraded": false,
    "total_cost": 4.8,
    "stream_count": 1,
    "ready_stream_count": 1,
    "streams": [
      {
        "tenant_id": "t1",
        "site_id": "s1",
        "box_id": "b1",
        "device_id": "cam-1",
        "protocol": "rtsp",
        "stream_url": "rtsp://10.0.0.10/live",
        "ingest_spec": {
          "protocol": "rtsp",
          "stream_url": "rtsp://10.0.0.10/live"
        },
        "capabilities": {
          "ocr": true,
          "face": true
        },
        "fps_in": 12.0,
        "sample_fps": 8.0,
        "estimated_cost": 8.0,
        "priority": 3,
        "complexity": 2.0,
        "workloads": [
          {
            "capability": "face",
            "algorithm_id": "face-detector",
            "algorithm_version": "1.0.0",
            "algorithm_status": "active",
            "base_library_id": "lib-face-core",
            "base_library_version": "2026.03",
            "binding_status": "ready",
            "execution": {
              "stream_uri": "file:///data/cam-1/latest.h264",
              "model_uri": "file:///models/face-detector.rknn",
              "result_uri": "file:///data/results/cam-1__face.json",
              "sample_period_ms": 125,
              "frames_per_sample": 2,
              "max_samples_per_run": 3,
              "execution_ready": true
            }
          },
          {
            "capability": "ocr",
            "algorithm_id": "ocr-engine",
            "algorithm_version": "2.0.0",
            "algorithm_status": "active",
            "base_library_id": "lib-ocr-core",
            "base_library_version": "2026.03",
            "binding_status": "ready"
          }
        ],
        "workload_count": 2,
        "ready_workload_count": 2,
        "binding_ready": true
      }
    ]
  }
}
```

## Resolution rules

1. Only enabled devices are included.
2. Scheduler uses the latest `fps_in` telemetry when present, otherwise defaults to `8.0`.
3. Stream priority is derived from device capabilities:
   - `face` -> priority `3`
   - `ocr` -> priority `2`
   - neither -> priority `1`
4. Stream complexity is:
   - base `1.0`
   - `+0.6` when `face` is enabled
   - `+0.4` when `ocr` is enabled
5. Algorithm resolution is deterministic:
   - only `active` algorithms are considered
   - matching is by `capabilities[]`
   - the lexicographically first `(algorithm_id, version)` match is selected
6. Base-library resolution is explicit and per-device/per-capability via existing mapping records.
7. Optional execution resources can be supplied through:
   - `device.execution_hints.stream_uri`
   - `device.execution_hints.result_root_uri`
   - `device.execution_hints.max_samples_per_run`
   - `base_library_mapping.execution_hints.model_uri`
   - `base_library_mapping.execution_hints.result_uri`
8. When `result_uri` is not provided on the mapping but `result_root_uri` exists on the device, the runtime derives:
   - `<result_root_uri>/<device_id>__<capability>.json`
9. Sampling execution metadata is derived deterministically:
   - `sample_period_ms = round(1000 / sample_fps)`
   - `frames_per_sample = round(fps_in / sample_fps)`, clamped to at least `1`

## Binding status semantics

- `ready`: algorithm and base-library both resolved
- `missing_algorithm`: base-library mapping exists, algorithm does not
- `missing_base_library`: algorithm exists, base-library mapping does not
- `missing_algorithm_and_base_library`: neither exists

## Expected RK3588 data-plane usage

A C++ inference core can poll this endpoint and then:

1. Group streams by `device_id` and `protocol`.
2. Initialize MPP decode sessions from `stream_url` / `ingest_spec`.
3. Apply `sample_fps` as the sampling throttle.
4. For each `workload` with `binding_status == "ready"`:
   - prefer `execution.stream_uri` / `execution.model_uri` / `execution.result_uri` when present
   - apply `execution.sample_period_ms` or `execution.frames_per_sample` as the sampling throttle metadata
   - load the corresponding RKNN model/base-library
   - run RGA resize/crop as needed
   - execute inference for the capability
5. Use a local fallback asset map only when execution resources are absent from the contract.
6. Skip or alarm on any workload with non-ready binding state.

## Next data-plane work

1. Create the remote C++ demo project under `/home/zql/ks/rk3588/decode_demo`.
2. Add a small client that fetches `/api/v1/inference/plan` and materializes it into native structs.
3. Implement single-stream `MPP -> RGA -> RKNN` happy-path inference.
4. Feed results back to the Python runtime through a dedicated result/reporting endpoint.
