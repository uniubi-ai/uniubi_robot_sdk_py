# Changelog

## Unreleased

- Support aarch64_host runtime selection for ARM64 external-host bindings and document separate build directories and wheel/runtime pairing.
- Enable media by default on x86_64, i386, and aarch64; unify local and remote PCM capture/playback under MediaBus and AudioRawBackStream, with matching runtime libraries and examples.
- Expose the read-only `sensor.uwb.beacon_id` field. Rebuild this extension against the matching C++ SDK and device firmware.
- Add an on-board Low-level TensorRT example that rebuilds an FP32 engine from ONNX at each startup without PyTorch and validates/reorders SDK and model joint contracts explicitly.
- Initialize repository structure.
