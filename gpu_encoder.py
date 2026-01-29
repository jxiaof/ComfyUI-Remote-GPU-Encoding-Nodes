#!/usr/bin/env python3
"""
Remote GPU Encoding - Encoder Server
远程 GPU 编码服务器

这是一个独立的编码服务器，需要在 GPU 机器上单独部署。

功能:
- 接收视频帧（通过 ZMQ）
- NVENC 硬件编码（通过 FFmpeg）
- 音视频合并
- 多会话支持
- 批量帧处理

使用:
    python gpu_encoder.py --bind tcp://0.0.0.0:5555 --codec h264_nvenc

协议版本: 2.0
"""

import zmq
import subprocess
import sys
import signal
import time
import argparse
import os
import tempfile
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
import struct


# ============================================================================
# 品牌标识
# ============================================================================

LOGO_PREFIX = "[RemoteGPU]"
LOGO_BANNER = """
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║     ██████╗ ███████╗███╗   ███╗ ██████╗ ████████╗███████╗     ║
║     ██╔══██╗██╔════╝████╗ ████║██╔═══██╗╚══██╔══╝██╔════╝     ║
║     ██████╔╝█████╗  ██╔████╔██║██║   ██║   ██║   █████╗       ║
║     ██╔══██╗██╔══╝  ██║╚██╔╝██║██║   ██║   ██║   ██╔══╝       ║
║     ██║  ██║███████╗██║ ╚═╝ ██║╚██████╔╝   ██║   ███████╗     ║
║     ╚═╝  ╚═╝╚══════╝╚═╝     ╚═╝ ╚═════╝    ╚═╝   ╚══════╝     ║
║                                                               ║
║              ██████╗ ██████╗ ██╗   ██╗                        ║
║             ██╔════╝ ██╔══██╗██║   ██║                        ║
║             ██║  ███╗██████╔╝██║   ██║                        ║
║             ██║   ██║██╔═══╝ ██║   ██║                        ║
║             ╚██████╔╝██║     ╚██████╔╝                        ║
║              ╚═════╝ ╚═╝      ╚═════╝                         ║
║                                                               ║
║         ENCODER SERVER    NVENC Hardware Encoding             ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
"""


# ============================================================================
# 协议常量（与 protocol/protocol.py 保持一致）
# ============================================================================

PROTOCOL_MAGIC = 0x5A4D5646


class MessageType(IntEnum):
    SESSION_START = 1
    SESSION_END = 2
    FRAME_DATA = 3
    AUDIO_DATA = 4
    HEARTBEAT = 5
    BATCH_FRAMES = 7


class AudioFormat(IntEnum):
    NONE = 0
    PCM_F32LE = 1
    PCM_S16LE = 2


class SessionFlags(IntEnum):
    NONE = 0
    HAS_AUDIO = 1


# ============================================================================
# 颜色和日志（简化版，与 logger/logger.py 类似但更轻量）
# ============================================================================


class Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"


class Logger:
    """日志类"""

    def __init__(self, tag: str):
        self.tag = tag

    def _ts(self) -> str:
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    def _fmt(self, level: str, color: str, msg: str) -> str:
        return (
            f"{Color.MAGENTA}{LOGO_PREFIX}{Color.RESET} "
            f"{Color.DIM}{self._ts()}{Color.RESET} "
            f"{color}[{level:5s}]{Color.RESET} "
            f"{Color.BLUE}[{self.tag:<10s}]{Color.RESET} "
            f"{msg}"
        )

    def debug(self, msg: str):
        print(self._fmt("DEBUG", Color.DIM, msg))

    def info(self, msg: str):
        print(self._fmt("INFO", Color.CYAN, msg))

    def success(self, msg: str):
        print(self._fmt("OK", Color.GREEN, msg))

    def warning(self, msg: str):
        print(self._fmt("WARN", Color.YELLOW, msg))

    def error(self, msg: str):
        print(self._fmt("ERROR", Color.RED, msg))

    def data(self, msg: str):
        print(self._fmt("DATA", Color.MAGENTA, msg))

    def progress(self, current: int, total: int, suffix: str = ""):
        if total <= 0:
            return

        pct = current / total
        width = 30
        filled = int(width * pct)
        bar = "█" * filled + "░" * (width - filled)

        line = (
            f"\r{Color.MAGENTA}{LOGO_PREFIX}{Color.RESET} "
            f"{Color.DIM}{self._ts()}{Color.RESET} "
            f"{Color.MAGENTA}[RECV ]{Color.RESET} "
            f"[{bar}] {pct * 100:5.1f}% ({current}/{total})"
        )

        if suffix:
            line += f" | {suffix}"

        sys.stdout.write(line + "    ")
        sys.stdout.flush()

        if current >= total:
            print()

    def header(self, title: str):
        line = "─" * 60
        print(
            f"\n{Color.MAGENTA}{LOGO_PREFIX}{Color.RESET} {Color.CYAN}{line}{Color.RESET}"
        )
        print(
            f"{Color.MAGENTA}{LOGO_PREFIX}{Color.RESET}   {Color.BOLD}{title}{Color.RESET}"
        )
        print(
            f"{Color.MAGENTA}{LOGO_PREFIX}{Color.RESET} {Color.CYAN}{line}{Color.RESET}"
        )

    def separator(self):
        print(
            f"{Color.MAGENTA}{LOGO_PREFIX}{Color.RESET} {Color.DIM}{'─' * 60}{Color.RESET}"
        )

    def kv(self, key: str, value: Any, indent: int = 2):
        print(
            f"{Color.MAGENTA}{LOGO_PREFIX}{Color.RESET} "
            f"{' ' * indent}{Color.DIM}{key}:{Color.RESET}".ljust(35)
            + f" {value}"
        )


# ============================================================================
# 数据结构
# ============================================================================


@dataclass
class VideoMessage:
    """视频消息"""

    msg_type: MessageType
    flags: int = 0
    width: int = 0
    height: int = 0
    channels: int = 3
    data_len: int = 0
    frame_num: int = 0
    timestamp_us: int = 0
    session_id: bytes = field(default_factory=lambda: b"\x00" * 16)
    total_frames: int = 0
    fps: int = 30
    output_path: str = ""
    data: Optional[bytes] = None

    @property
    def has_audio(self) -> bool:
        return bool(self.flags & SessionFlags.HAS_AUDIO)

    @property
    def session_hex(self) -> str:
        return self.session_id.hex()[:16]


@dataclass
class AudioMessage:
    """音频消息"""

    audio_format: AudioFormat = AudioFormat.PCM_F32LE
    channels: int = 2
    sample_rate: int = 44100
    num_samples: int = 0
    data_len: int = 0
    session_id: bytes = field(default_factory=lambda: b"\x00" * 16)
    data: Optional[bytes] = None

    @property
    def duration(self) -> float:
        return self.num_samples / self.sample_rate if self.sample_rate > 0 else 0


@dataclass
class Session:
    """编码会话"""

    session_id: str
    output_path: str
    width: int
    height: int
    fps: int
    total_frames: int
    has_audio: bool

    start_time: float = field(default_factory=time.time)
    frames_received: int = 0
    bytes_received: int = 0

    audio_data: Optional[bytes] = None
    audio_sample_rate: int = 44100
    audio_channels: int = 2
    audio_format: AudioFormat = AudioFormat.PCM_F32LE

    @property
    def elapsed(self) -> float:
        return time.time() - self.start_time

    @property
    def fps_actual(self) -> float:
        return self.frames_received / self.elapsed if self.elapsed > 0 else 0

    @property
    def mb_received(self) -> float:
        return self.bytes_received / (1024 * 1024)

    @property
    def throughput_gbps(self) -> float:
        return (self.bytes_received * 8) / self.elapsed / 1e9 if self.elapsed > 0 else 0


# ============================================================================
# 消息解析器
# ============================================================================


class MessageParser:
    """消息解析器"""

    VIDEO_HEADER_FORMAT = "<I B B B B I I I I Q Q 16s I I 60s 4x"
    VIDEO_HEADER_SIZE = 128

    AUDIO_HEADER_FORMAT = "<I B B B B I I I 4x Q 16s 16x"
    AUDIO_HEADER_SIZE = 64

    BATCH_HEADER_FORMAT = "<I B B B B I I I H H I Q 16s I I 60s 4x"
    BATCH_HEADER_SIZE = 128

    LEGACY_VIDEO_FORMAT = "<BBBB IIII Q Q 16s I I 64s 4x"
    LEGACY_VIDEO_SIZE = 128

    LEGACY_AUDIO_FORMAT = "<BBBB IIII Q 16s 20x"
    LEGACY_AUDIO_SIZE = 64

    @classmethod
    def parse(cls, data: bytes) -> Optional[VideoMessage | AudioMessage]:
        """解析消息"""
        if len(data) < 4:
            return None

        magic = struct.unpack("<I", data[:4])[0]

        if magic == PROTOCOL_MAGIC:
            return cls._parse_new(data)
        else:
            return cls._parse_legacy(data)

    @classmethod
    def _parse_new(cls, data: bytes) -> Optional[VideoMessage | AudioMessage]:
        """解析新协议"""
        if len(data) < 6:
            return None

        msg_type = MessageType(data[5])

        if msg_type == MessageType.AUDIO_DATA:
            if len(data) < cls.AUDIO_HEADER_SIZE:
                return None

            hdr = struct.unpack(cls.AUDIO_HEADER_FORMAT, data[: cls.AUDIO_HEADER_SIZE])
            return AudioMessage(
                audio_format=AudioFormat(hdr[3]),
                channels=hdr[4],
                sample_rate=hdr[5],
                num_samples=hdr[6],
                data_len=hdr[7],
                session_id=hdr[9],
                data=data[cls.AUDIO_HEADER_SIZE :]
                if len(data) > cls.AUDIO_HEADER_SIZE
                else None,
            )

        if msg_type == MessageType.BATCH_FRAMES:
            if len(data) < cls.BATCH_HEADER_SIZE:
                return None

            hdr = struct.unpack(cls.BATCH_HEADER_FORMAT, data[: cls.BATCH_HEADER_SIZE])
            return VideoMessage(
                msg_type=MessageType.BATCH_FRAMES,
                flags=hdr[3],
                width=hdr[5],
                height=hdr[6],
                channels=hdr[7],
                data_len=hdr[10],
                frame_num=hdr[9],
                timestamp_us=hdr[11],
                session_id=hdr[12],
                total_frames=hdr[13],
                fps=hdr[14],
                output_path=hdr[15].rstrip(b"\x00").decode("utf-8", errors="ignore"),
                data=data[cls.BATCH_HEADER_SIZE :]
                if len(data) > cls.BATCH_HEADER_SIZE
                else None,
            )

        if len(data) < cls.VIDEO_HEADER_SIZE:
            return None

        hdr = struct.unpack(cls.VIDEO_HEADER_FORMAT, data[: cls.VIDEO_HEADER_SIZE])
        return VideoMessage(
            msg_type=MessageType(hdr[2]),
            flags=hdr[3],
            width=hdr[5],
            height=hdr[6],
            channels=hdr[7],
            data_len=hdr[8],
            frame_num=hdr[9],
            timestamp_us=hdr[10],
            session_id=hdr[11],
            total_frames=hdr[12],
            fps=hdr[13],
            output_path=hdr[14].rstrip(b"\x00").decode("utf-8", errors="ignore"),
            data=data[cls.LEGACY_VIDEO_SIZE :]
            if len(data) > cls.LEGACY_VIDEO_SIZE
            else None,
        )

        if len(data) < cls.VIDEO_HEADER_SIZE:
            return None

        hdr = struct.unpack(cls.VIDEO_HEADER_FORMAT, data[: cls.VIDEO_HEADER_SIZE])
        return VideoMessage(
            msg_type=MessageType(hdr[2]),
            flags=hdr[3],
            width=hdr[5],
            height=hdr[6],
            channels=hdr[7],
            data_len=hdr[8],
            frame_num=hdr[9],
            timestamp_us=hdr[10],
            session_id=hdr[11],
            total_frames=hdr[12],
            fps=hdr[13],
            output_path=hdr[14].rstrip(b"\x00").decode("utf-8", errors="ignore"),
            data=data[cls.VIDEO_HEADER_SIZE :]
            if len(data) > cls.VIDEO_HEADER_SIZE
            else None,
        )

    @classmethod
    def _parse_legacy(cls, data: bytes) -> Optional[VideoMessage | AudioMessage]:
        """解析旧协议"""
        if len(data) < 4:
            return None

        msg_type = data[0]

        if msg_type == MessageType.AUDIO_DATA and len(data) >= cls.LEGACY_AUDIO_SIZE:
            hdr = struct.unpack(cls.LEGACY_AUDIO_FORMAT, data[: cls.LEGACY_AUDIO_SIZE])
            return AudioMessage(
                audio_format=AudioFormat(hdr[1]),
                channels=hdr[2],
                sample_rate=hdr[4],
                num_samples=hdr[5],
                data_len=hdr[6],
                session_id=hdr[9],
                data=data[cls.LEGACY_AUDIO_SIZE :]
                if len(data) > cls.LEGACY_AUDIO_SIZE
                else None,
            )

        if len(data) >= cls.LEGACY_VIDEO_SIZE:
            hdr = struct.unpack(cls.LEGACY_VIDEO_FORMAT, data[: cls.LEGACY_VIDEO_SIZE])
            return VideoMessage(
                msg_type=MessageType(hdr[0]),
                flags=hdr[1],
                width=hdr[4],
                height=hdr[5],
                channels=hdr[6],
                data_len=hdr[7],
                frame_num=hdr[8],
                timestamp_us=hdr[9],
                session_id=hdr[10],
                total_frames=hdr[11],
                fps=hdr[12],
                output_path=hdr[13].rstrip(b"\x00").decode("utf-8", errors="ignore"),
                data=data[cls.LEGACY_VIDEO_SIZE :]
                if len(data) > cls.LEGACY_VIDEO_SIZE
                else None,
            )

        return None


# ============================================================================
# 接收器
# ============================================================================


class Receiver:
    """消息接收器"""

    def __init__(self, endpoint: str):
        self.log = Logger("Receiver")
        self.endpoint = endpoint
        self.running = True

        self.log.info(f"Connecting to: {endpoint}")

        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.SUB)

        self.socket.setsockopt(zmq.RCVHWM, 500)
        self.socket.setsockopt(zmq.RCVBUF, 256 * 1024 * 1024)
        self.socket.setsockopt(zmq.TCP_KEEPALIVE, 1)
        self.socket.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 60)

        self.socket.connect(endpoint)
        self.socket.setsockopt_string(zmq.SUBSCRIBE, "")

        self.log.success(f"Connected: {endpoint}")

    def receive(self, timeout_ms: int = 1000) -> Optional[VideoMessage | AudioMessage]:
        """接收消息"""
        self.socket.setsockopt(zmq.RCVTIMEO, timeout_ms)

        try:
            data = self.socket.recv()
        except zmq.Again:
            return None
        except zmq.ZMQError as e:
            self.log.error(f"Receive error: {e}")
            return None

        return MessageParser.parse(data)

    def close(self):
        """关闭"""
        self.running = False
        self.socket.close()
        self.context.term()
        self.log.info("Connection closed")


# ============================================================================
# FFmpeg 编码器
# ============================================================================


class FFmpegEncoder:
    """FFmpeg 编码器"""

    def __init__(
        self,
        output: str,
        width: int,
        height: int,
        fps: int,
        codec: str = "h264_nvenc",
        preset: str = "p4",
        bitrate: str = "20M",
        gpu: int = 0,
    ):
        self.log = Logger("FFmpeg")
        self.output = output
        self.frame_count = 0
        self.start_time = time.time()

        self.log.info(f"Init: {width}×{height}@{fps}fps → {output}")

        output_dir = os.path.dirname(output)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        if "M" in bitrate:
            bufsize = f"{int(bitrate.replace('M', '')) * 2}M"
        else:
            bufsize = "40M"

        cmd = [
            "ffmpeg",
            "-y",
            "-hwaccel",
            "cuda",
            "-hwaccel_device",
            str(gpu),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{width}x{height}",
            "-r",
            str(fps),
            "-i",
            "-",
            "-c:v",
            codec,
            "-preset",
            preset,
            "-b:v",
            bitrate,
            "-maxrate",
            bitrate,
            "-bufsize",
            bufsize,
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            output,
        ]

        self.process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            bufsize=width * height * 3 * 10,
        )

        self.log.success("Encoder ready")

    def write(self, frame_data: bytes) -> bool:
        """写入帧"""
        try:
            self.process.stdin.write(frame_data)
            self.frame_count += 1
            return True
        except Exception as e:
            self.log.error(f"Write error: {e}")
            return False

    def close(self) -> bool:
        """关闭"""
        self.log.info("Finalizing video...")

        try:
            if self.process.stdin:
                self.process.stdin.close()

            self.process.wait(timeout=120)

            if self.process.returncode != 0:
                stderr = self.process.stderr.read().decode()[-500:]
                self.log.error(f"FFmpeg error:\n{stderr}")
                return False

            elapsed = time.time() - self.start_time
            self.log.success(
                f"Encoded {self.frame_count} frames in {elapsed:.2f}s "
                f"({self.frame_count / elapsed:.1f} fps)"
            )
            return True

        except subprocess.TimeoutExpired:
            self.log.error("FFmpeg timeout")
            self.process.kill()
            return False
        except Exception as e:
            self.log.error(f"Close error: {e}")
            return False


# ============================================================================
# 音视频合并器
# ============================================================================


class AudioMerger:
    """音视频合并"""

    def __init__(self):
        self.log = Logger("Merger")

    def merge(
        self,
        video_path: str,
        audio_data: bytes,
        output_path: str,
        sample_rate: int,
        channels: int,
        audio_format: AudioFormat,
    ) -> bool:
        """合并"""
        self.log.header("Merging Audio + Video")
        self.log.kv("Video", video_path)
        self.log.kv(
            "Audio", f"{len(audio_data) / 1024:.1f}KB, {sample_rate}Hz, {channels}ch"
        )
        self.log.kv("Output", output_path)

        if not os.path.exists(video_path):
            self.log.error(f"Video not found: {video_path}")
            return False

        audio_tmp = tempfile.mktemp(suffix=".raw")

        try:
            with open(audio_tmp, "wb") as f:
                f.write(audio_data)

            fmt_map = {
                AudioFormat.PCM_F32LE: "f32le",
                AudioFormat.PCM_S16LE: "s16le",
            }
            pcm_fmt = fmt_map.get(audio_format, "f32le")

            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                video_path,
                "-f",
                pcm_fmt,
                "-ar",
                str(sample_rate),
                "-ac",
                str(channels),
                "-i",
                audio_tmp,
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-shortest",
                output_path,
            ]

            self.log.info("Running FFmpeg merge...")

            result = subprocess.run(cmd, capture_output=True, timeout=300)

            if result.returncode != 0:
                self.log.error(f"Merge failed:\n{result.stderr.decode()[-300:]}")
                return False

            if os.path.exists(output_path):
                size_mb = os.path.getsize(output_path) / (1024 * 1024)
                self.log.success(f"Merged: {output_path} ({size_mb:.2f}MB)")
                return True

            return False

        except subprocess.TimeoutExpired:
            self.log.error("Merge timeout")
            return False
        except Exception as e:
            self.log.error(f"Merge error: {e}")
            return False
        finally:
            if os.path.exists(audio_tmp):
                try:
                    os.remove(audio_tmp)
                except:
                    pass


# ============================================================================
# 主程序
# ============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Remote GPU Encoding - Encoder Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --bind tcp://0.0.0.0:5555
  %(prog)s --bind tcp://0.0.0.0:5555 --codec hevc_nvenc --bitrate 30M
  %(prog)s --bind tcp://0.0.0.0:5555 --output-dir /mnt/videos
        """,
    )

    parser.add_argument(
        "--bind",
        "-b",
        default="tcp://10.10.0.1:5555",
        help="Bind address (default: tcp://10.10.0.1:5555)",
    )
    parser.add_argument(
        "--output-dir", "-o", default="", help="Override output directory"
    )
    parser.add_argument(
        "--codec",
        "-c",
        default="h264_nvenc",
        choices=["h264_nvenc", "hevc_nvenc", "av1_nvenc"],
        help="Video codec (default: h264_nvenc)",
    )
    parser.add_argument(
        "--preset",
        "-p",
        default="p4",
        choices=["p1", "p2", "p3", "p4", "p5", "p6", "p7"],
        help="Encoder preset (p1=fastest, p7=best)",
    )
    parser.add_argument("--bitrate", default="20M", help="Video bitrate (default: 20M)")
    parser.add_argument(
        "--gpu", type=int, default=0, help="GPU device index (default: 0)"
    )
    parser.add_argument(
        "--single-session", action="store_true", help="Exit after first session"
    )
    parser.add_argument(
        "--idle-timeout",
        type=int,
        default=0,
        help="Exit after N seconds idle (0=disabled)",
    )

    args = parser.parse_args()

    log = Logger("Main")

    # 显示横幅
    print(f"{Color.CYAN}{LOGO_BANNER}{Color.RESET}")

    # 配置
    log.header("Configuration")
    log.kv("Bind Address", args.bind)
    log.kv("Output Dir", args.output_dir or "(from sender)")
    log.kv("Codec", args.codec)
    log.kv("Preset", args.preset)
    log.kv("Bitrate", args.bitrate)
    log.kv("GPU", args.gpu)
    log.kv("Single Session", args.single_session)
    log.kv(
        "Idle Timeout", f"{args.idle_timeout}s" if args.idle_timeout > 0 else "disabled"
    )
    log.separator()

    # 创建组件
    receiver = Receiver(args.bind)
    encoder: Optional[FFmpegEncoder] = None
    session: Optional[Session] = None
    merger = AudioMerger()

    total_sessions = 0
    idle_start = time.time()

    # 信号处理
    shutdown = False

    def signal_handler(sig, frame):
        nonlocal shutdown
        if shutdown:
            sys.exit(1)
        shutdown = True
        log.warning("Shutdown requested...")
        receiver.running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    log.header("Waiting for Sessions")
    log.info("Press Ctrl+C to stop")

    try:
        while receiver.running:
            msg = receiver.receive(timeout_ms=1000)

            if msg is None:
                idle_time = time.time() - idle_start

                if (
                    not session
                    and args.idle_timeout > 0
                    and idle_time > args.idle_timeout
                ):
                    log.info(f"Idle timeout ({args.idle_timeout}s)")
                    break

                if not session and int(idle_time) % 30 == 0 and int(idle_time) > 0:
                    log.info(f"Idle: {idle_time:.0f}s | Sessions: {total_sessions}")

                continue

            idle_start = time.time()

            # ===== 音频 =====
            if isinstance(msg, AudioMessage):
                if session and msg.data:
                    session.audio_data = msg.data
                    session.audio_sample_rate = msg.sample_rate
                    session.audio_channels = msg.channels
                    session.audio_format = msg.audio_format

                    log.data(
                        f"Audio: {len(msg.data) / 1024:.1f}KB, "
                        f"{msg.sample_rate}Hz, {msg.channels}ch, "
                        f"{msg.duration:.2f}s"
                    )
                continue

            # ===== 视频 =====
            if not isinstance(msg, VideoMessage):
                continue

            # ----- SESSION_START -----
            if msg.msg_type == MessageType.SESSION_START:
                if session and encoder:
                    encoder.close()
                    encoder = None

                if args.output_dir:
                    filename = (
                        os.path.basename(msg.output_path)
                        or f"video_{msg.session_hex}.mp4"
                    )
                    output_path = os.path.join(args.output_dir, filename)
                else:
                    output_path = msg.output_path or f"/tmp/video_{msg.session_hex}.mp4"

                log.header("Session Start")
                log.kv("Session", msg.session_hex)
                log.kv("Resolution", f"{msg.width}×{msg.height}")
                log.kv("Frames", msg.total_frames)
                log.kv("FPS", msg.fps)
                log.kv("Audio", msg.has_audio)
                log.kv("Output", output_path)
                log.separator()

                session = Session(
                    session_id=msg.session_hex,
                    output_path=output_path,
                    width=msg.width,
                    height=msg.height,
                    fps=msg.fps if msg.fps > 0 else 30,
                    total_frames=msg.total_frames,
                    has_audio=msg.has_audio,
                )

                log.info("Waiting for frames...")
                continue

            # ----- SESSION_END -----
            if msg.msg_type == MessageType.SESSION_END:
                print()
                log.header("Session End")

                if not session:
                    continue

                log.kv("Frames", session.frames_received)
                log.kv("Data", f"{session.mb_received:.2f} MB")
                log.kv("Time", f"{session.elapsed:.2f}s")
                log.kv("Speed", f"{session.fps_actual:.2f} fps")
                log.kv("Bandwidth", f"{session.throughput_gbps:.3f} Gbps")
                log.kv("Audio", session.has_audio)
                if session.audio_data:
                    log.kv("Audio Size", f"{len(session.audio_data) / 1024:.1f} KB")
                log.separator()

                video_ok = False
                if encoder:
                    video_ok = encoder.close()
                    encoder = None

                final_output = session.output_path

                if video_ok and session.audio_data:
                    log.info("Merging audio...")

                    video_only = session.output_path + ".video_only.mp4"

                    try:
                        if os.path.exists(session.output_path):
                            os.rename(session.output_path, video_only)

                            merge_ok = merger.merge(
                                video_path=video_only,
                                audio_data=session.audio_data,
                                output_path=final_output,
                                sample_rate=session.audio_sample_rate,
                                channels=session.audio_channels,
                                audio_format=session.audio_format,
                            )

                            if merge_ok and os.path.exists(video_only):
                                os.remove(video_only)
                            elif not merge_ok:
                                log.warning("Merge failed, keeping video-only")
                                if os.path.exists(video_only):
                                    os.rename(video_only, final_output)

                    except Exception as e:
                        log.error(f"Merge error: {e}")

                elif video_ok:
                    log.info("No audio, video-only output")

                if os.path.exists(final_output):
                    size_mb = os.path.getsize(final_output) / (1024 * 1024)
                    log.separator()
                    log.success(f"OUTPUT: {final_output}")
                    log.kv("Size", f"{size_mb:.2f} MB")
                    log.kv("Audio", "Yes" if session.audio_data else "No")

                session = None
                total_sessions += 1

                log.success(f"Session complete! Total: {total_sessions}")

                if args.single_session:
                    break

                log.info("Waiting for next session...")
                continue

            # ----- BATCH_FRAMES -----
            if msg.msg_type == MessageType.BATCH_FRAMES:
                if not session or not msg.data:
                    continue

                if encoder is None:
                    encoder = FFmpegEncoder(
                        output=session.output_path,
                        width=session.width,
                        height=session.height,
                        fps=session.fps,
                        codec=args.codec,
                        preset=args.preset,
                        bitrate=args.bitrate,
                        gpu=args.gpu,
                    )
                    log.separator()

                frame_size = msg.width * msg.height * 3
                batch_size = len(msg.data) // frame_size

                batch_success = True
                for i in range(batch_size):
                    offset = i * frame_size
                    frame_data = msg.data[offset : offset + frame_size]

                    if len(frame_data) != frame_size:
                        log.error(f"Batch frame {i}: size mismatch")
                        batch_success = False
                        break

                    if not encoder.write(frame_data):
                        log.error(f"Batch frame {i}: write failed")
                        batch_success = False
                        break

                    session.frames_received += 1
                    session.bytes_received += len(frame_data)

                if not batch_success:
                    log.error("Batch processing failed")
                    break

                log.progress(
                    session.frames_received,
                    session.total_frames,
                    f"{session.fps_actual:.1f}fps | "
                    f"{session.mb_received:.1f}MB | "
                    f"{session.throughput_gbps:.2f}Gbps | {batch_size}f/batch",
                )

            # ----- FRAME_DATA -----
            if msg.msg_type == MessageType.FRAME_DATA:
                if not session or not msg.data:
                    continue

                if encoder is None:
                    encoder = FFmpegEncoder(
                        output=session.output_path,
                        width=session.width,
                        height=session.height,
                        fps=session.fps,
                        codec=args.codec,
                        preset=args.preset,
                        bitrate=args.bitrate,
                        gpu=args.gpu,
                    )
                    log.separator()

                if not encoder.write(msg.data):
                    log.error("Frame write failed!")
                    break

                session.frames_received += 1
                session.bytes_received += len(msg.data)

                log.progress(
                    msg.frame_num,
                    msg.total_frames,
                    f"{session.fps_actual:.1f}fps | "
                    f"{session.mb_received:.1f}MB | "
                    f"{session.throughput_gbps:.2f}Gbps",
                )

    except Exception as e:
        log.error(f"Fatal: {e}")
        import traceback

        traceback.print_exc()

    finally:
        log.separator()
        if encoder:
            encoder.close()
        receiver.close()
        log.success(f"Total sessions: {total_sessions}. Goodbye!")


if __name__ == "__main__":
    main()
