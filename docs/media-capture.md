# Capture NV21 images and four PCM streams

Run from this repository root on the robot's aarch64 Orin board, with matching SDK runtime libraries, media service and SHM ready. Python additionally requires `sdk.MEDIA_ENABLED == True`. This example connects a client only to create MediaBus; it does not acquire motion-control ownership or send movement commands.

## Configuration template

[`config/sdk_config.json`](../config/sdk_config.json) is a checked-in reference for two cameras and four microphone streams, supplied with this example. It contains no credentials. Verify the channel names against the deployed media service; this is not a universal configuration for every firmware or board.

MediaBus `setup()` reads **`/etc/robot/sdk_config.json`**. Keeping the template in the repository does not activate it. The legacy example's first positional `config` argument configures the Motion SDK service and does not redirect MediaBus configuration. Capture mode uses the default Motion SDK service configuration.

Inspect the existing board configuration first. If it exists, back it up and merge the reviewed `streamDefine` settings while retaining other device-specific fields. Do not blindly overwrite it. For a board with no existing file, after checking the template against its media service:

```bash
sudo install -d /etc/robot
# -n preserves an existing configuration.
sudo cp -n config/sdk_config.json /etc/robot/sdk_config.json
```

The mapping in this template is:

| Stream | MediaBus channel |
| --- | --- |
| Camera 0 / 1 | `mediaServer.viChannel.0` / `.1` |
| PCM 0 / 1 / 2 / 3 | `mediaServer.aiChannel.0.0` / `.0.1` / `.0.2` / `.0.3` |

This config is a repository asset; downloading or installing only the runtime/wheel does not automatically provision `/etc/robot/sdk_config.json`.

## Capture

Build/install the SDK following the repository README, set `LD_LIBRARY_PATH` to the matching runtime, then run with a **new** output directory (its parent must already exist):

```bash
sudo env LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
  python3 examples/example_media_frames.py --capture-all /tmp/media-capture-01 20
```

An optional final argument selects the network interface, for example `eth0.100` when that is the interface configured on your board. Omit it or use `-` to keep the SDK default. `--pcm4` is an alias for `--capture-all`. Duration defaults to 20 seconds and accepts integers from 1 to 60. The legacy positional mode remains available and saves the first 10 frames per media type under `/tmp/media_frame_dump`.

Capture mode subscribes to raw camera channels 0 and 1 and raw audio channels 0 through 3. It saves:

- Five `cameraN_WIDTHxHEIGHT_ptsTIMESTAMP_INDEX.nv21` images per camera. Each contains packed Y followed by VU, without row padding; size is `width * height * 3 / 2`. Planes are copied row by row during the callback.
- Four `dmic_chN.pcm` files, one per stream, accepted only as raw PCM (`dataType=0`), 16000 Hz, 16-bit, mono. On the supported little-endian board these are S16LE files without WAV headers. At 20 seconds each file must contain **640000 bytes** (320000 samples).

Callbacks copy bounded payloads into memory; files are written after subscriptions stop and MediaBus shuts down. The maximum image dimensions accepted are 4096 x 2160; ten images at that size require about 127 MiB, plus at most 7.68 MB of PCM at 60 seconds. This mode does not save encoded video or IMU metadata.

Each stream stops accumulating PCM when it reaches the requested sample count. Capture allows up to five extra wall-clock seconds for startup/delivery. Therefore "20 seconds" means 20 seconds of received samples per stream, not proof of uninterrupted or synchronized recording. Non-increasing audio timestamps are rejected and counted. Silence is valid PCM and is not a failure.

Exit code 0 requires all six subscriptions, five saved NV21 images per camera, all four complete PCM files, and no rejected captured frames or duplicate audio timestamps. Setup/argument failures return 1; incomplete capture or save failures return 2. Inspect the per-channel summaries; partial files may remain for diagnosis and must not be treated as a complete capture.

## Inspect saved files

Use the dimensions from the image filename (replace `WIDTHxHEIGHT` and the filename below):

```bash
ffplay -f rawvideo -pixel_format nv21 -video_size WIDTHxHEIGHT camera0_WIDTHxHEIGHT_ptsTIMESTAMP_INDEX.nv21
ffplay -f s16le -ar 16000 -ac 1 dmic_ch0.pcm
ffmpeg -f s16le -ar 16000 -ac 1 -i dmic_ch0.pcm dmic_ch0.wav
```

The checks above describe example behavior; building or testing with synthetic frames does not establish that a particular board supplies these streams. Verify actual capture summaries and file sizes on the target board.
