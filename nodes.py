"""
ComfyUI Remote GPU Encoding Nodes
远程 GPU 编码节点

功能:
- 视频帧远程传输
- 帧统计收集
- 会话管理
"""

import torch
import numpy as np
import time
import uuid
from typing import Dict, Any, Tuple

try:
    import zmq

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


class RemoteGPUEncoder:
    """
    远程 GPU 编码器

    将视频帧发送到远程 GPU 服务器进行硬件编码

    特性:
    - 高速网络传输
    - 支持音频
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
                    {"default": True, "tooltip": "Show transfer progress"},
                ),
                "batch_mode": (
                    "BOOLEAN",
                    {"default": True, "tooltip": "Enable batch sending mode"},
                ),
                "batch_window_ms": (
                    "INT",
                    {
                        "default": 100,
                        "min": 10,
                        "max": 1000,
                        "tooltip": "Batch time window (ms)",
                    },
                ),
                "min_batch_size": (
                    "INT",
                    {
                        "default": 10,
                        "min": 1,
                        "max": 100,
                        "tooltip": "Minimum frames per batch",
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
        batch_mode: bool = True,
        batch_window_ms: int = 100,
        min_batch_size: int = 10,
    ) -> Tuple[str, str, int, float, float]:
        log = Logger("Encoder")

        if not HAS_ZMQ:
            error_msg = "ERROR: pyzmq not installed. Run: pip install pyzmq"
            log.error(error_msg)
            return (error_msg, "", 0, 0.0, 0.0)

        if len(images.shape) == 4:
            num_frames, h, w, c = images.shape
        else:
            num_frames, h, w, c = 1, *images.shape
            images = images.unsqueeze(0)

        if total_frames <= 0:
            total_frames = num_frames

        should_start = session_mode in ("auto", "start")
        should_end = session_mode in ("auto", "end")

        audio_info = parse_audio(audio)
        has_audio = audio_info["has_audio"]

        if check_network:
            log.info(f"Checking network: {encoder_address}")
            is_valid, msg = NetworkUtils.validate_endpoint(
                encoder_address, check_network=True
            )
            if not is_valid:
                log.warning(f"Network warning: {msg}")

        try:
            socket = ConnectionManager.get_socket(encoder_address, check_network=False)
        except Exception as e:
            error_msg = f"ERROR: Connection failed - {e}"
            log.error(error_msg)
            return (error_msg, "", 0, 0.0, 0.0)

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

        if should_start:
            log.header(f"Remote GPU Encoding Session")
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

        if has_audio and should_start and audio_info["data"]:
            audio_header = AudioHeader(
                audio_format=audio_info["format"],
                channels=audio_info["channels"],
                sample_rate=audio_info["sample_rate"],
                num_samples=audio_info["samples"],
                data_len=len(audio_info["data"]),
                session_id=session_id,
            )

            msg = audio_header.pack() + audio_info["data"]
            socket.send(msg, zmq.NOBLOCK)
            session["audio_bytes"] = len(audio_info["data"])
            ConnectionManager.update_stats(encoder_address, len(msg))

            log.success(f"Audio sent: {len(audio_info['data']) / 1024:.1f}KB")
            time.sleep(0.1)

        log.info(f"Sending {num_frames} frames...")
        if batch_mode:
            log.info(
                f"Batch mode: window={batch_window_ms}ms, min_size={min_batch_size}"
            )
        send_start = time.time()

        if batch_mode and batch_window_ms > 0:
            batch = []
            batch_start_time = time.time()

            for i in range(num_frames):
                frame_np = (images[i].cpu().numpy() * 255).astype(np.uint8)
                pixel_data = frame_np.tobytes()
                batch.append(pixel_data)

                elapsed = (time.time() - batch_start_time) * 1000
                should_send = (
                    len(batch) >= min_batch_size
                    or elapsed >= batch_window_ms
                    or i == num_frames - 1
                )

                if should_send:
                    batch_data = b"".join(batch)
                    start_frame = session["frames_sent"] + 1

                    header = VideoHeader(
                        msg_type=MessageType.BATCH_FRAMES,
                        pixel_format=PixelFormat.RGB24,
                        width=w,
                        height=h,
                        channels=c,
                        data_len=len(batch_data),
                        frame_num=start_frame,
                        session_id=session_id,
                        total_frames=total_frames,
                        fps=fps,
                        output_path=output_path,
                    )

                    msg = header.pack() + batch_data
                    socket.send(msg, zmq.NOBLOCK)
                    ConnectionManager.update_stats(encoder_address, len(msg))

                    batch_size = len(batch)
                    session["frames_sent"] += batch_size
                    session["bytes_sent"] += len(batch_data)

                    if show_progress:
                        elapsed_total = time.time() - session["start_time"]
                        current_fps = (
                            session["frames_sent"] / elapsed_total
                            if elapsed_total > 0
                            else 0
                        )
                        mb = session["bytes_sent"] / (1024 * 1024)
                        gbps = (
                            (mb * 8) / elapsed_total / 1000 if elapsed_total > 0 else 0
                        )

                        log.progress(
                            session["frames_sent"],
                            total_frames,
                            suffix=f"{current_fps:.1f} fps | {mb:.1f} MB | {gbps:.2f} Gbps | {batch_size}f/batch",
                        )

                    batch.clear()
                    batch_start_time = time.time()
        else:
            for i in range(num_frames):
                frame_np = (images[i].cpu().numpy() * 255).astype(np.uint8)
                pixel_data = frame_np.tobytes()

                session["frames_sent"] += 1
                session["bytes_sent"] += len(pixel_data)

                header = VideoHeader(
                    msg_type=MessageType.FRAME_DATA,
                    pixel_format=PixelFormat.RGB24,
                    width=w,
                    height=h,
                    channels=c,
                    data_len=len(pixel_data),
                    frame_num=session["frames_sent"],
                    session_id=session_id,
                    total_frames=total_frames,
                    fps=fps,
                    output_path=output_path,
                )

                msg = header.pack() + pixel_data
                socket.send(msg, zmq.NOBLOCK)
                ConnectionManager.update_stats(encoder_address, len(msg))

                if show_progress:
                    elapsed = time.time() - session["start_time"]
                    current_fps = session["frames_sent"] / elapsed if elapsed > 0 else 0
                    mb = session["bytes_sent"] / (1024 * 1024)
                    gbps = (mb * 8) / elapsed / 1000 if elapsed > 0 else 0

                    log.progress(
                        session["frames_sent"],
                        total_frames,
                        suffix=f"{current_fps:.1f} fps | {mb:.1f} MB | {gbps:.2f} Gbps",
                    )

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


class RemoteEncoderConnection:
    """远程编码器连接管理"""

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


class FrameStatistics:
    """帧统计收集器"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "Input images to analyze"}),
            },
            "optional": {
                "reset": ("BOOLEAN", {"default": False, "tooltip": "Reset statistics"}),
                "stats_id": (
                    "STRING",
                    {"default": "default", "tooltip": "Statistics group ID"},
                ),
            },
        }

    RETURN_TYPES = ("STRING", "INT", "FLOAT", "FLOAT")
    RETURN_NAMES = ("report", "total_frames", "elapsed_time", "avg_fps")
    FUNCTION = "collect"
    CATEGORY = "Remote GPU Encoding/Utils"
    OUTPUT_NODE = True

    def collect(
        self,
        images: torch.Tensor,
        reset: bool = False,
        stats_id: str = "default",
    ) -> Tuple[str, int, float, float]:
        log = Logger("Statistics")
        now = time.time()

        if reset or not SessionStorage.exists(stats_id):
            SessionStorage.set(
                stats_id,
                {
                    "start_time": now,
                    "frame_count": 0,
                    "total_bytes": 0,
                },
            )
            log.info(f"Statistics reset: {stats_id}")

        stats = SessionStorage.get(stats_id)

        if len(images.shape) == 4:
            batch, h, w, c = images.shape
        else:
            batch, h, w, c = 1, *images.shape

        bytes_per_frame = w * h * c
        stats["frame_count"] += batch
        stats["total_bytes"] += bytes_per_frame * batch

        elapsed = now - stats["start_time"]
        fps = stats["frame_count"] / elapsed if elapsed > 0 else 0
        mb = stats["total_bytes"] / (1024 * 1024)

        report = (
            f"Frames: {stats['frame_count']} | "
            f"Time: {elapsed:.2f}s | "
            f"FPS: {fps:.1f} | "
            f"Data: {mb:.1f}MB"
        )

        return (report, stats["frame_count"], round(elapsed, 3), round(fps, 2))

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")


class FrameCounter:
    """简单帧计数器"""

    _counters: Dict[str, Dict] = {}

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "Input images"}),
            },
            "optional": {
                "reset": ("BOOLEAN", {"default": False, "tooltip": "Reset counter"}),
                "counter_id": (
                    "STRING",
                    {"default": "counter", "tooltip": "Counter ID"},
                ),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT", "FLOAT", "STRING")
    RETURN_NAMES = ("images", "count", "elapsed", "info")
    FUNCTION = "count"
    CATEGORY = "Remote GPU Encoding/Utils"

    def count(
        self,
        images: torch.Tensor,
        reset: bool = False,
        counter_id: str = "counter",
    ) -> Tuple[torch.Tensor, int, float, str]:
        now = time.time()

        if reset or counter_id not in self._counters:
            self._counters[counter_id] = {"start": now, "count": 0}

        counter = self._counters[counter_id]
        batch = images.shape[0] if len(images.shape) == 4 else 1
        counter["count"] += batch

        elapsed = now - counter["start"]
        fps = counter["count"] / elapsed if elapsed > 0 else 0

        info = f"Frame {counter['count']} | {elapsed:.2f}s | {fps:.1f} fps"

        return (images, counter["count"], round(elapsed, 3), info)

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")


NODE_CLASS_MAPPINGS = {
    "RemoteGPUEncoder": RemoteGPUEncoder,
    "RemoteEncoderConnection": RemoteEncoderConnection,
    "FrameStatistics": FrameStatistics,
    "FrameCounter": FrameCounter,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RemoteGPUEncoder": "Remote GPU Encoder",
    "RemoteEncoderConnection": "Encoder Connection",
    "FrameStatistics": "Frame Statistics",
    "FrameCounter": "Frame Counter",
}