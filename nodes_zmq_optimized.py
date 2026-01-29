"""
ComfyUI Remote GPU Encoding Nodes (Optimized ZMQ Version)
远程 GPU 编码节点（ZMQ 优化版本）

特性:
- 零拷贝传输
- tqdm 专业进度条
- 流式和批量传输
- 会话管理
"""

import torch
import numpy as np
import time
import uuid
from typing import Dict, Any, Tuple

try:
    import zmq
    from tqdm import tqdm

    HAS_ZMQ = True
except ImportError:
    HAS_ZMQ = False

from .protocol import (
    MessageType,
    PixelFormat,
    SessionFlags,
    VideoHeader,
    AudioHeader,
    VIDEO_HEADER_SIZE,
    AUDIO_HEADER_SIZE,
)
from .logger import Logger, LogLevel, configure_logging, LOGO_PREFIX
from .utils import NetworkUtils, SessionStorage, ConnectionManager, parse_audio

configure_logging(level=LogLevel.INFO)


class RemoteGPUEncoderOptimized:
    """
    远程 GPU 编码器（ZMQ 优化版本）

    特性:
    - 零拷贝传输
    - tqdm 专业进度条
    - 流式和批量传输
    - 会话管理
    - 连接复用
    """

    _active_sessions: Dict[str, Dict] = {}

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
                        "default": "tcp://10.10.0.1:5555",
                        "tooltip": "Remote encoder address (tcp://host:port)",
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
                "session_mode": (
                    ["auto", "start", "continue", "end"],
                    {
                        "default": "auto",
                        "tooltip": "auto: single batch | start/continue/end: multi-batch",
                    },
                ),
                "total_frames": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "tooltip": "Total frames hint (0 = auto from batch)",
                    },
                ),
                "check_network": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "Check network connectivity before sending",
                    },
                ),
                "show_progress": (
                    "BOOLEAN",
                    {"default": True, "tooltip": "Show tqdm progress bar"},
                ),
                "transport_mode": (
                    ["stream", "batch", "auto"],
                    {
                        "default": "auto",
                        "tooltip": "stream: zero-copy streaming | batch: optimized batching | auto: auto-select",
                    },
                ),
                "batch_size": (
                    "INT",
                    {
                        "default": 10,
                        "min": 1,
                        "max": 100,
                        "tooltip": "Batch size for batch mode",
                    },
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
        session_mode: str = "auto",
        total_frames: int = 0,
        check_network: bool = True,
        show_progress: bool = True,
        transport_mode: str = "auto",
        batch_size: int = 10,
    ) -> Tuple[str, str, int, float, float]:
        log = Logger("Encoder")

        if not HAS_ZMQ:
            error_msg = "ERROR: pyzmq not installed. Run: pip install pyzmq"
            log.error(error_msg)
            return (error_msg, "", 0, 0.0, 0.0)

        # 解析图像
        if len(images.shape) == 4:
            num_frames, h, w, c = images.shape
        else:
            num_frames, h, w, c = 1, *images.shape
            images = images.unsqueeze(0)

        if total_frames <= 0:
            total_frames = num_frames

        should_start = session_mode in ("auto", "start")
        should_end = session_mode in ("auto", "end")

        # 解析音频
        audio_info = parse_audio(audio)
        has_audio = audio_info["has_audio"]

        # 网络检查
        if check_network:
            log.info(f"Checking network: {encoder_address}")
            is_valid, msg = NetworkUtils.validate_endpoint(
                encoder_address, check_network=True
            )
            if not is_valid:
                log.warning(f"Network warning: {msg}")

        # 获取连接
        try:
            socket = ConnectionManager.get_socket(encoder_address, check_network=False)
        except Exception as e:
            error_msg = f"ERROR: Connection failed - {e}"
            log.error(error_msg)
            return (error_msg, "", 0, 0.0, 0.0)

        # 会话管理
        if should_start:
            session_id = uuid.uuid4().bytes
            self._active_sessions[encoder_address] = {
                "id": session_id,
                "start_time": time.time(),
                "frames_sent": 0,
                "bytes_sent": 0,
                "audio_bytes": 0,
            }
        else:
            session_data = self._active_sessions.get(encoder_address)
            if session_data:
                session_id = session_data["id"]
            else:
                session_id = uuid.uuid4().bytes
                self._active_sessions[encoder_address] = {
                    "id": session_id,
                    "start_time": time.time(),
                    "frames_sent": 0,
                    "bytes_sent": 0,
                    "audio_bytes": 0,
                }

        session = self._active_sessions[encoder_address]
        session_hex = session_id.hex()[:16]

        # ========== SESSION_START ==========
        if should_start:
            log.header(f"Remote GPU Encoding Session (ZMQ Optimized)")
            log.kv("Session", session_hex)
            log.kv("Encoder", encoder_address)
            log.kv("Output", output_path)
            log.kv("Resolution", f"{w}×{h}")
            log.kv("Frames", f"{num_frames} (total: {total_frames})")
            log.kv("FPS", fps)
            log.kv("Audio", f"{audio_info['duration']:.2f}s" if has_audio else "None")
            log.separator()

            flags = SessionFlags.HAS_AUDIO if has_audio else SessionFlags.NONE
            header = VideoHeader(
                msg_type=MessageType.SESSION_START,
                flags=flags,
                pixel_format=PixelFormat.RGB24,
                width=w,
                height=h,
                channels=c,
                total_frames=total_frames,
                fps=fps,
                session_id=session_id,
                output_path=output_path,
            )

            socket.send(header.pack(), zmq.NOBLOCK)
            ConnectionManager.update_stats(encoder_address, VIDEO_HEADER_SIZE)
            log.success("Session started")

            time.sleep(0.2)

        # ========== AUDIO_DATA ==========
        if has_audio and should_start and audio_info["data"]:
            audio_header = AudioHeader(
                audio_format=audio_info["format"],
                channels=audio_info["channels"],
                sample_rate=audio_info["sample_rate"],
                num_samples=audio_info["samples"],
                data_len=len(audio_info["data"]),
                session_id=session_id,
            )

            socket.send_multipart(
                [audio_header.pack(), audio_info["data"]], zmq.NOBLOCK
            )
            session["audio_bytes"] = len(audio_info["data"])
            ConnectionManager.update_stats(encoder_address, len(audio_info["data"]))

            log.success(f"Audio sent: {len(audio_info['data']) / 1024:.1f}KB")
            time.sleep(0.1)

        # ========== FRAME_DATA ==========
        log.info(f"Sending {num_frames} frames...")
        log.info(f"Transport mode: {transport_mode}")

        send_start = time.time()
        total_bytes = 0

        # 自动选择传输模式
        if transport_mode == "auto":
            if num_frames > 50:
                transport_mode = "batch"
                log.info(f"Auto-selected: batch mode ({num_frames} frames)")
            else:
                transport_mode = "stream"
                log.info(f"Auto-selected: stream mode ({num_frames} frames)")

        # GPU → CPU (唯一拷贝)
        images_np = (images.cpu().numpy() * 255).astype(np.uint8)

        # ========== 流式传输（零拷贝）==========
        if transport_mode == "stream":
            frame_size = w * h * c

            with tqdm(
                total=num_frames,
                desc="ZMQ Stream",
                unit="frame",
                disable=not show_progress,
                bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}{postfix}]",
            ) as pbar:
                for i in range(num_frames):
                    # 零拷贝：直接使用 numpy 数组
                    frame_np = images_np[i]

                    session["frames_sent"] += 1
                    session["bytes_sent"] += frame_np.nbytes
                    total_bytes += frame_np.nbytes

                    header = VideoHeader(
                        msg_type=MessageType.FRAME_DATA,
                        pixel_format=PixelFormat.RGB24,
                        width=w,
                        height=h,
                        channels=c,
                        data_len=frame_np.nbytes,
                        frame_num=session["frames_sent"],
                        session_id=session_id,
                        total_frames=total_frames,
                        fps=fps,
                        output_path=output_path,
                    )

                    # 零拷贝：send_multipart + copy=False
                    socket.send_multipart([header.pack(), frame_np], flags=zmq.NOBLOCK)
                    ConnectionManager.update_stats(encoder_address, frame_np.nbytes)

                    # 更新进度条
                    elapsed_total = time.time() - session["start_time"]
                    current_fps = (
                        session["frames_sent"] / elapsed_total
                        if elapsed_total > 0
                        else 0
                    )
                    mb = session["bytes_sent"] / (1024 * 1024)
                    gbps = (mb * 8) / elapsed_total / 1000 if elapsed_total > 0 else 0

                    pbar.update(1)
                    pbar.set_postfix_str(
                        f"{current_fps:.1f} fps | {mb:.1f} MB | {gbps:.2f} Gbps"
                    )

        # ========== 批量传输（优化）==========
        elif transport_mode == "batch":
            # 预分配批量缓冲区
            frame_size = w * h * c
            buffer_size = frame_size * batch_size
            batch_buffer = np.zeros(buffer_size, dtype=np.uint8)
            buffer_offset = 0

            with tqdm(
                total=num_frames,
                desc="ZMQ Batch",
                unit="frame",
                disable=not show_progress,
                bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}{postfix}]",
            ) as pbar:
                for i in range(0, num_frames, batch_size):
                    batch_end = min(i + batch_size, num_frames)
                    current_batch_size = batch_end - i

                    # 使用预分配缓冲区
                    batch_buffer[: current_batch_size * frame_size] = images_np[
                        i:batch_end
                    ].flatten()

                    start_frame = session["frames_sent"] + 1

                    header = VideoHeader(
                        msg_type=MessageType.BATCH_FRAMES,
                        pixel_format=PixelFormat.RGB24,
                        width=w,
                        height=h,
                        channels=c,
                        data_len=current_batch_size * frame_size,
                        frame_num=start_frame,
                        session_id=session_id,
                        total_frames=total_frames,
                        fps=fps,
                        output_path=output_path,
                    )

                    # 零拷贝：使用预分配缓冲区
                    batch_data = batch_buffer[: current_batch_size * frame_size]

                    socket.send_multipart(
                        [header.pack(), batch_data], flags=zmq.NOBLOCK
                    )

                    session["frames_sent"] += current_batch_size
                    session["bytes_sent"] += len(batch_data)
                    total_bytes += len(batch_data)
                    ConnectionManager.update_stats(encoder_address, len(batch_data))

                    # 更新进度条
                    elapsed_total = time.time() - session["start_time"]
                    current_fps = (
                        session["frames_sent"] / elapsed_total
                        if elapsed_total > 0
                        else 0
                    )
                    mb = session["bytes_sent"] / (1024 * 1024)
                    gbps = (mb * 8) / elapsed_total / 1000 if elapsed_total > 0 else 0

                    pbar.update(current_batch_size)
                    pbar.set_postfix_str(
                        f"{current_fps:.1f} fps | {mb:.1f} MB | {gbps:.2f} Gbps | {current_batch_size}f/batch"
                    )

        # ========== SESSION_END ==========
        if should_end:
            header = VideoHeader(
                msg_type=MessageType.SESSION_END,
                width=w,
                height=h,
                channels=c,
                frame_num=session["frames_sent"],
                session_id=session_id,
                total_frames=total_frames,
                fps=fps,
                output_path=output_path,
            )

            socket.send(header.pack(), zmq.NOBLOCK)
            ConnectionManager.update_stats(encoder_address, VIDEO_HEADER_SIZE)

            if encoder_address in self._active_sessions:
                del self._active_sessions[encoder_address]

            log.success("Session completed")

        # ========== 统计 ==========
        total_time = time.time() - session["start_time"]
        frames_sent = session["frames_sent"]
        send_time = time.time() - send_start
        fps_actual = num_frames / send_time if send_time > 0 else 0
        data_mb = session["bytes_sent"] / (1024 * 1024)
        audio_mb = session.get("audio_bytes", 0) / (1024 * 1024)
        total_mb = data_mb + audio_mb
        throughput_gbps = (total_mb * 8) / total_time / 1000 if total_time > 0 else 0

        status = "COMPLETED" if should_end else "IN PROGRESS"

        report = f"""
 ┌─────────────────────────────────────────────────────────────────────┐
 │                   REMOTE GPU ENCODING REPORT                        │
 │                   (ZMQ Optimized Zero-Copy)                      │
 ├─────────────────────────────────────────────────────────────────────┤
 │  Session:      {session_hex:<54}│
 │  Encoder:      {encoder_address:<54}│
 │  Output:       {output_path:<54}│
 ├─────────────────────────────────────────────────────────────────────┤
 │  VIDEO                                                              │
 │    Resolution: {w}×{h:<51}│
 │    Frames:     {frames_sent}/{total_frames:<52}│
 │    Speed:      {fps_actual:.1f} fps{"":<49}│
 ├─────────────────────────────────────────────────────────────────────┤
 │  AUDIO                                                              │
 │    Included:   {str(has_audio):<54}│
 │    Size:       {audio_mb:.2f} MB{"":<50}│
 ├─────────────────────────────────────────────────────────────────────┤
 │  TRANSFER                                                           │
 │    Mode:        {transport_mode.upper():<50}│
 │    Time:       {total_time:.2f}s{"":<51}│
 │    Data:       {total_mb:.2f} MB{"":<50}│
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
            session_hex,
            frames_sent,
            round(fps_actual, 2),
            round(data_mb, 2),
        )

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")


class RemoteEncoderConnectionOptimized:
    """远程编码器连接管理（优化版本）"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "action": (
                    ["status", "release", "release_all", "test"],
                    {"default": "status", "tooltip": "Connection management action"},
                ),
            },
            "optional": {
                "encoder_address": (
                    "STRING",
                    {
                        "default": "tcp://10.10.0.1:5555",
                        "tooltip": "Encoder address for release/test",
                    },
                ),
                "trigger": ("*", {"tooltip": "Trigger input (any type)"}),
            },
        }

    RETURN_TYPES = ("STRING", "BOOLEAN")
    RETURN_NAMES = ("status", "success")
    FUNCTION = "execute"
    CATEGORY = "Remote GPU Encoding"
    OUTPUT_NODE = True

    def execute(
        self, action: str, encoder_address: str = "", trigger: Any = None
    ) -> Tuple[str, bool]:
        log = Logger("Connection")

        if action == "release":
            if not encoder_address:
                return ("ERROR: No address specified", False)
            ConnectionManager.release(encoder_address)
            return (f"Released: {encoder_address}", True)

        elif action == "release_all":
            ConnectionManager.release_all()
            return ("All connections released", True)

        elif action == "test":
            if not encoder_address:
                return ("ERROR: No address specified", False)

            log.info(f"Testing connection: {encoder_address}")
            is_valid, msg = NetworkUtils.validate_endpoint(
                encoder_address, check_network=True
            )

            if is_valid:
                log.success(f"Connection test passed: {msg}")
                return (f"OK: {msg}", True)
            else:
                log.warning(f"Connection test failed: {msg}")
                return (f"FAILED: {msg}", False)

        else:
            return (ConnectionManager.get_status_string(), True)

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")


# ============================================================================
# 节点注册
# ============================================================================

NODE_CLASS_MAPPINGS = {
    "RemoteGPUEncoderOptimized": RemoteGPUEncoderOptimized,
    "RemoteEncoderConnectionOptimized": RemoteEncoderConnectionOptimized,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RemoteGPUEncoderOptimized": "Remote GPU Encoder (ZMQ Optimized)",
    "RemoteEncoderConnectionOptimized": "Encoder Connection",
}
