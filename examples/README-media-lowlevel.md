# Low-level MediaBus example / 低级媒体示例

`example_media_frames_lowlevel.py` creates MediaBus through a Low-level client. For media-only use, prefer `example_media_frames.py` (High-level).

Low-level connect() may switch motion ownership to the brain. No motor enable or motor commands are issued. On normal completion or handled failure, this example attempts to restore factory motion mode before disconnecting. Restoration failure is reported with a nonzero exit code. Forced termination cannot guarantee restoration. Do not run alongside another controller.

Low-level 连接可能切换到大脑运控模式。示例不使能电机、不发送电机控制帧；正常退出或可处理的失败路径会尝试恢复出厂运控模式，失败会报错。强制终止无法保证恢复，请勿与其他控制程序同时运行。

Requires local aarch64/Orin deployment. MediaBus configuration and capture arguments match the existing media example. Use --capture-all <new-output-dir> 5 eth0.100; the output directory must not already exist.
