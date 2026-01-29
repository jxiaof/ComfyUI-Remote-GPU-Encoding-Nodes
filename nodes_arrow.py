"""
ComfyUI Remote GPU Encoding Nodes (Arrow Flight Version)
远程 GPU 编码节点（Apache Arrow Flight 版本）

功能:
- 零拷贝视频帧传输
- 高性能批量传输
- 专业进度条
- 会话管理
- 音频支持
"""

import torch
import numpy as np
import time
from typing import Dict, Any, Tuple

try:
    from .transport import ArrowVideoClient, ArrowVideoSender

    HAS_ARROW = True
except ImportError:
    HAS_ARROW = False

from .logger import Logger, LogLevel, configure_logging, LOGO_PREFIX
from .utils import parse_audio

configure_logging(level=LogLevel.INFO)


class RemoteGPUEncoderArrow:
    """
    远程 GPU 编码器 (Arrow Flight 版本)

    使用 Apache Arrow Flight 实现零拷贝传输到远程 GPU 服务器

    特性:
    - 零拷贝传输
    - 高性能批量传输
    - tqdm 专业进度条
    - 连接复用
    - 会话管理
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": (
                    "IMAGE",
                    {"tooltip": "Video frames to encode (BHWC format)"},
                ),
                "encoder_address": (
                    "STRING",
                    {
                        "default": "0.0.0.0:8815",
                        "tooltip": "Arrow Flight server address (host:port)",
                    },
                ),
                "output_path": (
                    "STRING",
                    {
                        "default": "/tmp/output.mp4",
                        "tooltip": "Output video path on encoder server",
                    },
                ),
                "fps": (
                    "INT",
                    {
                        "default": 30,
                        "min": 1,
                        "max": 120,
                        "tooltip": "Video frame rate",
                    },
                ),
            },
            "optional": {
                "audio": ("AUDIO", {"tooltip": "Optional audio track"}),
                "batch_size": (
                    "INT",
                    {
                        "default": 10,
                        "min": 1,
                        "max": 100,
                        "tooltip": "Batch size for Arrow Flight transfer",
                    },
                ),
                "show_progress": (
                    "BOOLEAN",
                    {"default": True, "tooltip": "Show tqdm progress bar"},
                ),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "INT", "FLOAT", "FLOAT")
    RETURN_NAMES = ("report", "session_id", "frames_sent", "fps_actual", "data_mb")
    FUNCTION = "encode"
    CATEGORY = "Remote GPU Encoding"
    OUTPUT_NODE = True

    def encode(
        self,
        images: torch.Tensor,
        encoder_address: str,
        output_path: str,
        fps: int = 30,
        audio: Any = None,
        batch_size: int = 10,
        show_progress: bool = True,
    ) -> Tuple[str, str, int, float, float]:
        log = Logger("ArrowEncoder")

        if not HAS_ARROW:
            error_msg = "ERROR: pyarrow not installed. Run: pip install pyarrow"
            log.error(error_msg)
            return (error_msg, "", 0, 0.0, 0.0)

        # 解析图像
        if len(images.shape) == 4:
            num_frames, h, w, c = images.shape
        else:
            num_frames, h, w, c = 1, *images.shape
            images = images.unsqueeze(0)

        # 解析音频
        audio_info = parse_audio(audio)
        has_audio = audio_info["has_audio"]

        # 获取客户端
        client = ArrowVideoSender.get_client(f"grpc://{encoder_address}")

        try:
            # 开始会话
            session_id = client.start_session(
                width=w,
                height=h,
                channels=c,
                fps=fps,
                total_frames=num_frames,
                output_path=output_path,
                format="RGB24",
            )

            # 发送音频
            if has_audio and audio_info["data"]:
                client.send_audio(
                    audio_data=audio_info["data"],
                    sample_rate=audio_info["sample_rate"],
                    channels=audio_info["channels"],
                )

            # 发送视频帧
            frames_sent, fps_actual, data_mb = client.send_frames(
                frames=images,
                batch_size=batch_size,
                show_progress=show_progress,
            )

            # 结束会话
            client.end_session()

            # 生成报告
            audio_mb = audio_info.get("data", b"").__len__() / (1024 * 1024)
            total_mb = data_mb + audio_mb
            throughput_gbps = (total_mb * 8) / 1000 if fps_actual > 0 else 0

            status = "COMPLETED"

            report = f"""
 ┌─────────────────────────────────────────────────────────────────────┐
 │                   REMOTE GPU ENCODING REPORT                        │
 │                   (Arrow Flight Zero-Copy)                         │
 ├─────────────────────────────────────────────────────────────────────┤
 │  Session:      {session_id:<54}│
 │  Encoder:      grpc://{encoder_address:<45}│
 │  Output:       {output_path:<54}│
 ├─────────────────────────────────────────────────────────────────────┤
 │  VIDEO                                                              │
 │    Resolution: {w}×{h:<51}│
 │    Frames:     {frames_sent:<53}│
 │    Speed:      {fps_actual:.1f} fps{"":<49}│
 ├─────────────────────────────────────────────────────────────────────┤
 │  AUDIO                                                              │
 │    Included:   {str(has_audio):<54}│
 │    Size:       {audio_mb:.2f} MB{"":<50}│
 ├─────────────────────────────────────────────────────────────────────┤
 │  TRANSFER                                                           │
 │    Data:       {data_mb:.2f} MB{"":<50}│
 │    Bandwidth:  {throughput_gbps:.2f} Gbps{"":<47}│
 ├─────────────────────────────────────────────────────────────────────┤
 │  Status:       {status:<54}│
 └─────────────────────────────────────────────────────────────────────┘
 """

            log.separator()
            log.success(
                f"Transfer complete: {num_frames} frames | "
                f"{fps_actual:.1f} fps | {throughput_gbps:.2f} Gbps"
            )

            return (
                report.strip(),
                session_id,
                frames_sent,
                round(fps_actual, 2),
                round(data_mb, 2),
            )

        except Exception as e:
            error_msg = f"ERROR: Encoding failed - {e}"
            log.error(error_msg)
            return (error_msg, "", 0, 0.0, 0.0)

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")


# ============================================================================
# 节点注册
# ============================================================================

NODE_CLASS_MAPPINGS = {
    "RemoteGPUEncoderArrow": RemoteGPUEncoderArrow,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RemoteGPUEncoderArrow": "Remote GPU Encoder (Arrow Flight)",
}
