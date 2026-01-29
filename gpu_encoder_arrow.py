#!/usr/bin/env python3
"""
Remote GPU Encoding - Arrow Flight Server
远程 GPU 编码服务器（Apache Arrow Flight 版本）

这是一个独立的编码服务器，需要在 GPU 机器上单独部署。

主要特性:
- 基于 Apache Arrow Flight 的零拷贝传输
- 专业的结构化日志
- FFmpeg NVENC 硬件编码
- 音视频合并
- 多会话支持
- tqdm 专业进度条

设计说明:
- 单文件可运行，不依赖任何本地模块
- 完全基于 Arrow Flight 协议
- 专业的分层日志系统
- 高性能批量处理

使用:
    python gpu_encoder_arrow.py --bind 0.0.0.0:8815

协议版本: 3.0 (Arrow Flight)
"""

import sys
import os
import time
import signal
import argparse
import tempfile
import subprocess
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime
from contextlib import contextmanager
from enum import IntEnum

# Apache Arrow Flight
try:
    import pyarrow as pa
    import pyarrow.flight as flight

    HAS_ARROW = True
except ImportError:
    HAS_ARROW = False
    print("ERROR: pyarrow not installed. Run: pip install pyarrow")
    sys.exit(1)

# tqdm 进度条
try:
    from tqdm import tqdm

    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False


# ============================================================================
# 品牌标识
# ============================================================================

LOGO_PREFIX = "[ArrowGPU]"
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
║         ARROW FLIGHT SERVER    Zero-Copy Encoding             ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
"""


# ============================================================================
# 日志系统
# ============================================================================


class LogLevel(IntEnum):
    """日志级别"""

    DEBUG = 10
    INFO = 20
    SUCCESS = 25
    WARNING = 30
    ERROR = 40


class Color:
    """ANSI 颜色码"""

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
    """
    专业日志系统

    特性:
    - 结构化输出
    - 分层日志
    - 进度条集成
    - 多输出支持
    """

    LEVEL_COLORS = {
        LogLevel.DEBUG: Color.DIM,
        LogLevel.INFO: Color.CYAN,
        LogLevel.SUCCESS: Color.GREEN,
        LogLevel.WARNING: Color.YELLOW,
        LogLevel.ERROR: Color.RED,
    }

    LEVEL_LABELS = {
        LogLevel.DEBUG: "DEBUG",
        LogLevel.INFO: "INFO ",
        LogLevel.SUCCESS: " OK  ",
        LogLevel.WARNING: "WARN ",
        LogLevel.ERROR: "ERROR",
    }

    def __init__(self, tag: str = "Main", level: LogLevel = LogLevel.INFO):
        self.tag = tag
        self.level = level

    def _colorize(self, text: str, color: str) -> str:
        return f"{color}{text}{Color.RESET}"

    def _timestamp(self) -> str:
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    def _format(self, level: LogLevel, message: str) -> str:
        if level.value < self.level.value:
            return ""

        label = self.LEVEL_LABELS[level]
        color = self.LEVEL_COLORS[level]
        ts = self._timestamp()

        return (
            f"{Color.MAGENTA}{LOGO_PREFIX}{Color.RESET} "
            f"{Color.DIM}{ts}{Color.RESET} "
            f"{color}[{label}]{Color.RESET} "
            f"{Color.BLUE}[{self.tag:<12s}]{Color.RESET} "
            f"{message}"
        )

    def _log(self, level: LogLevel, message: str):
        formatted = self._format(level, message)
        if formatted:
            print(formatted)

    # 日志方法
    def debug(self, msg: str):
        self._log(LogLevel.DEBUG, msg)

    def info(self, msg: str):
        self._log(LogLevel.INFO, msg)

    def success(self, msg: str):
        self._log(LogLevel.SUCCESS, msg)

    def warning(self, msg: str):
        self._log(LogLevel.WARNING, msg)

    def error(self, msg: str):
        self._log(LogLevel.ERROR, msg)

    # 特殊输出
    def header(self, title: str, width: int = 70):
        line = "─" * width
        print(f"\n{Color.CYAN}{line}{Color.RESET}")
        print(f"  {Color.BOLD}{title}{Color.RESET}")
        print(f"{Color.CYAN}{line}{Color.RESET}")

    def separator(self, width: int = 70):
        print(f"{Color.DIM}{'─' * width}{Color.RESET}")

    def kv(self, key: str, value: Any, indent: int = 2):
        print(f"{' ' * indent}{Color.DIM}{key}:{Color.RESET} {value}")

    def banner(self):
        print(f"{Color.CYAN}{LOGO_BANNER}{Color.RESET}")


# ============================================================================
# 数据结构
# ============================================================================


@dataclass
class SessionInfo:
    """编码会话信息"""

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
# FFmpeg 编码器
# ============================================================================


class FFmpegEncoder:
    """
    FFmpeg NVENC 硬件编码器

    特性:
    - CUDA 硬件加速
    - 可配置编码参数
    - 实时进度反馈
    """

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
        log: Optional[Logger] = None,
    ):
        self.log = log or Logger("FFmpeg")
        self.output = output
        self.width = width
        self.height = height
        self.fps = fps
        self.frame_count = 0
        self.start_time = time.time()
        self.process: Optional[subprocess.Popen] = None

        self.log.info(f"Initializing encoder: {width}×{height}@{fps}fps")
        self.log.kv("Output", output)
        self.log.kv("Codec", codec)
        self.log.kv("Preset", preset)
        self.log.kv("Bitrate", bitrate)
        self.log.kv("GPU", gpu)

        # 确保输出目录存在
        output_dir = os.path.dirname(output)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        # 计算缓冲区大小
        if "M" in bitrate:
            bufsize = f"{int(bitrate.replace('M', '')) * 2}M"
        else:
            bufsize = "40M"

        # 构建 FFmpeg 命令
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

        self.log.debug(f"FFmpeg command: {' '.join(cmd)}")

        # 启动进程
        try:
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                bufsize=width * height * 3 * 10,
            )
            self.log.success("Encoder initialized")
        except Exception as e:
            self.log.error(f"FFmpeg initialization failed: {e}")
            raise

    def write(self, frame_data: bytes) -> bool:
        """写入帧数据"""
        if not self.process or self.process.poll() is not None:
            self.log.error("FFmpeg process not running")
            return False

        try:
            self.process.stdin.write(frame_data)
            self.process.stdin.flush()
            self.frame_count += 1
            return True
        except (BrokenPipeError, OSError) as e:
            self.log.error(f"Write failed: {e}")
            return False
        except Exception as e:
            self.log.error(f"Unexpected error: {e}")
            return False

    def close(self) -> bool:
        """关闭编码器"""
        self.log.info("Finalizing video...")

        if not self.process:
            return False

        try:
            # 关闭 stdin
            if self.process.stdin:
                self.process.stdin.close()

            # 等待完成
            try:
                returncode = self.process.wait(timeout=120)
            except subprocess.TimeoutExpired:
                self.log.error("FFmpeg timeout, killing...")
                self.process.kill()
                returncode = -1

            # 检查返回码
            if returncode != 0:
                stderr = self.process.stderr.read().decode()[-500:]
                self.log.error(f"FFmpeg failed (code {returncode}):\n{stderr}")
                return False

            # 统计
            elapsed = time.time() - self.start_time
            fps = self.frame_count / elapsed if elapsed > 0 else 0

            self.log.success(
                f"Encoded {self.frame_count} frames in {elapsed:.2f}s ({fps:.1f} fps)"
            )
            return True

        except Exception as e:
            self.log.error(f"Close error: {e}")
            return False
        finally:
            self.process = None


# ============================================================================
# 音视频合并器
# ============================================================================


class AudioMerger:
    """音视频合并器"""

    def __init__(self, log: Optional[Logger] = None):
        self.log = log or Logger("Merger")

    def merge(
        self,
        video_path: str,
        audio_data: bytes,
        output_path: str,
        sample_rate: int,
        channels: int,
    ) -> bool:
        """
        合并音视频

        Args:
            video_path: 视频文件路径
            audio_data: 音频数据 (PCM_F32LE)
            output_path: 输出路径
            sample_rate: 采样率
            channels: 通道数

        Returns:
            是否成功
        """
        self.log.header("Merging Audio + Video")
        self.log.kv("Video", video_path)
        self.log.kv(
            "Audio", f"{len(audio_data) / 1024:.1f}KB, {sample_rate}Hz, {channels}ch"
        )
        self.log.kv("Output", output_path)

        if not os.path.exists(video_path):
            self.log.error(f"Video not found: {video_path}")
            return False

        # 创建临时音频文件
        with tempfile.NamedTemporaryFile(suffix=".raw", delete=False, mode="wb") as f:
            audio_tmp = f.name
            f.write(audio_data)

        try:
            # 构建 FFmpeg 命令
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                video_path,
                "-f",
                "f32le",
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

            # 检查输出
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
                    os.unlink(audio_tmp)
                except:
                    pass


# ============================================================================
# Arrow Flight 服务器
# ============================================================================


class VideoFlightHandler(flight.ServerMiddleware):
    """Arrow Flight 视频处理处理器"""

    def __init__(self, args, logger: Logger):
        super().__init__()
        self.args = args
        self.log = logger
        self.sessions: Dict[str, SessionInfo] = {}
        self.encoder: Optional[FFmpegEncoder] = None
        self.merger = AudioMerger(logger)
        self.current_session: Optional[SessionInfo] = None

    def do_get(self, context, descriptor):
        """处理 GET 请求（会话信息查询）"""
        path = descriptor.path
        self.log.debug(f"GET request: {path}")

        # 解析路径
        parts = path.split("/")
        if len(parts) < 2:
            raise flight.FlightServerError("Invalid path")

        action = parts[0]

        if action == "session_info" and len(parts) >= 2:
            session_id = parts[1]
            if session_id in self.sessions:
                session = self.sessions[session_id]
                info = {
                    "session_id": session.session_id,
                    "frames": session.frames_received,
                    "fps": session.fps_actual,
                    "elapsed": session.elapsed,
                }
                data = pa.array([json.dumps(info)])
                return flight.RecordBatchStream(
                    pa.RecordBatch.from_pydict({"info": data})
                )

        raise flight.FlightNotFoundError("Session not found")

    def do_put(self, context, descriptor, reader, writer):
        """处理 PUT 请求（视频/音频数据传输）"""
        path = descriptor.path
        self.log.debug(f"PUT request: {path}")

        # 解析路径
        parts = path.split("/")
        if len(parts) < 2:
            raise flight.FlightServerError("Invalid path")

        action = parts[0]
        session_id = parts[1]

        # 处理会话开始
        if action == "session_start":
            self._handle_session_start(session_id, descriptor, reader, writer)
        # 处理视频帧
        elif action == "video_frames":
            self._handle_video_frames(session_id, reader, writer)
        # 处理音频数据
        elif action == "audio_data":
            self._handle_audio_data(session_id, reader, writer)
        # 处理会话结束
        elif action == "session_end":
            self._handle_session_end(session_id)
        else:
            raise flight.FlightServerError(f"Unknown action: {action}")

    def _handle_session_start(self, session_id: str, descriptor, reader, writer):
        """处理会话开始"""
        self.log.header(f"Session Start: {session_id}")

        # 解析元数据
        metadata_bytes = descriptor.descriptor
        if metadata_bytes:
            try:
                metadata_dict = json.loads(metadata_bytes.to_pybytes())
                self.log.kv("Metadata", json.dumps(metadata_dict, indent=2))
            except Exception as e:
                self.log.warning(f"Failed to parse metadata: {e}")

        # 读取会话配置
        for batch in reader:
            data = batch.to_pydict()
            self.log.debug(f"Session config: {data}")
            break

        # 创建会话
        session = SessionInfo(
            session_id=session_id,
            output_path=f"/tmp/video_{session_id}.mp4",
            width=1920,
            height=1080,
            fps=30,
            total_frames=0,
            has_audio=False,
        )

        self.sessions[session_id] = session
        self.current_session = session

        self.log.kv("Session ID", session_id)
        self.log.kv("Output", session.output_path)
        self.log.success("Session started")

    def _handle_video_frames(self, session_id: str, reader, writer):
        """处理视频帧接收"""
        if session_id not in self.sessions:
            raise flight.FlightServerError(f"Session not found: {session_id}")

        session = self.sessions[session_id]
        self.log.info(f"Receiving video frames for session: {session_id}")

        # 启动编码器（如果还没有）
        if not self.encoder:
            self.encoder = FFmpegEncoder(
                output=session.output_path,
                width=session.width,
                height=session.height,
                fps=session.fps,
                codec=self.args.codec,
                preset=self.args.preset,
                bitrate=self.args.bitrate,
                gpu=self.args.gpu,
                log=self.log,
            )
            self.log.separator()

        # 接收并处理帧
        frame_size = session.width * session.height * 3
        total_frames = 0

        with tqdm(
            total=session.total_frames,
            desc="Arrow Flight",
            unit="frame",
            file=sys.stdout,
        ) as pbar:
            for batch in reader:
                # 获取像素数据
                pixel_data = batch.column("pixel_data").to_numpy()
                frame_start = batch.column("frame_start")[0].as_py()
                frame_end = batch.column("frame_end")[0].as_py()

                # 处理每一帧
                for i in range(frame_start, frame_end):
                    start = i * frame_size
                    end = start + frame_size

                    if end > len(pixel_data):
                        self.log.error(f"Frame {i}: data size mismatch")
                        continue

                    frame_bytes = pixel_data[start:end].tobytes()

                    # 写入 FFmpeg
                    if not self.encoder.write(frame_bytes):
                        self.log.error(f"Frame {i}: write failed")
                        break

                    # 更新统计
                    session.frames_received += 1
                    session.bytes_received += len(frame_bytes)

                    # 更新进度条
                    pbar.update(1)
                    pbar.set_postfix_str(
                        f"{session.fps_actual:.1f} fps | "
                        f"{session.mb_received:.1f} MB | "
                        f"{session.throughput_gbps:.2f} Gbps"
                    )

                total_frames += frame_end - frame_start

        self.log.separator()

    def _handle_audio_data(self, session_id: str, reader, writer):
        """处理音频数据接收"""
        if session_id not in self.sessions:
            raise flight.FlightServerError(f"Session not found: {session_id}")

        session = self.sessions[session_id]
        self.log.info(f"Receiving audio data for session: {session_id}")

        # 接收音频
        for batch in reader:
            audio_data = batch.column("audio_data").to_numpy().tobytes()
            session.audio_data = audio_data
            self.log.success(f"Audio received: {len(audio_data) / 1024:.1f}KB")
            break

    def _handle_session_end(self, session_id: str):
        """处理会话结束"""
        if session_id not in self.sessions:
            raise flight.FlightServerError(f"Session not found: {session_id}")

        session = self.sessions[session_id]
        self.log.header(f"Session End: {session_id}")

        # 关闭编码器
        video_ok = False
        if self.encoder:
            video_ok = self.encoder.close()
            self.encoder = None

        # 合并音频
        if video_ok and session.audio_data:
            self.log.info("Merging audio...")
            self.merger.merge(
                video_path=session.output_path,
                audio_data=session.audio_data,
                output_path=session.output_path,
                sample_rate=session.audio_sample_rate,
                channels=session.audio_channels,
            )

        # 输出统计
        self.log.separator()
        self.log.kv("Frames", session.frames_received)
        self.log.kv("Data", f"{session.mb_received:.2f} MB")
        self.log.kv("Time", f"{session.elapsed:.2f}s")
        self.log.kv("Speed", f"{session.fps_actual:.2f} fps")
        self.log.kv("Bandwidth", f"{session.throughput_gbps:.3f} Gbps")
        self.log.separator()

        # 输出文件信息
        if os.path.exists(session.output_path):
            size_mb = os.path.getsize(session.output_path) / (1024 * 1024)
            self.log.success(f"OUTPUT: {session.output_path} ({size_mb:.2f}MB)")
            self.log.kv("Size", f"{size_mb:.2f} MB")

        # 清理会话
        del self.sessions[session_id]
        self.current_session = None

        self.log.success(f"Session complete")


class ArrowVideoServer(flight.FlightServerBase):
    """Arrow Flight 视频服务器"""

    def __init__(self, args, logger: Logger, location=None):
        super().__init__(location=location)
        self.args = args
        self.log = logger
        self.handler = VideoFlightHandler(args, logger)

    def do_put(self, context, descriptor, reader, writer):
        """PUT 请求入口"""
        self.handler.do_put(context, descriptor, reader, writer)

    def do_get(self, context, descriptor):
        """GET 请求入口"""
        return self.handler.do_get(context, descriptor)


# ============================================================================
# 主程序
# ============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Remote GPU Encoding - Arrow Flight Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --bind 0.0.0.0:8815
  %(prog)s --bind 0.0.0.0:8815 --codec hevc_nvenc --bitrate 30M
  %(prog)s --bind 0.0.0.0:8815 --output-dir /mnt/videos
        """,
    )

    parser.add_argument(
        "--bind",
        "-b",
        default="0.0.0.0:8815",
        help="Bind address (default: 0.0.0.0:8815)",
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

    # 创建日志
    log = Logger("Main")

    # 显示横幅
    log.banner()

    # 配置信息
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

    # 创建服务器
    location = flight.Location.for_grpc_tcp(args.bind)
    server = ArrowVideoServer(args, log, location=location)

    # 信号处理
    shutdown = False

    def signal_handler(sig, frame):
        nonlocal shutdown
        if shutdown:
            sys.exit(1)
        shutdown = True
        log.warning("Shutdown requested...")
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    log.header("Waiting for Sessions")
    log.info("Press Ctrl+C to stop")

    try:
        print(
            f"\n{Color.BOLD}{Color.GREEN}Starting Arrow Flight Server...{Color.RESET}"
        )
        print(f"{Color.BOLD}Listening on: {args.bind}{Color.RESET}\n")

        total_sessions = 0
        idle_start = time.time()

        while not shutdown:
            # 空闲超时检查
            if not server.handler.current_session and args.idle_timeout > 0:
                idle_time = time.time() - idle_start
                if idle_time > args.idle_timeout:
                    log.info(f"Idle timeout ({args.idle_timeout}s)")
                    break

            time.sleep(1)

        log.separator()
        log.success(f"Total sessions: {total_sessions}. Goodbye!")

    except KeyboardInterrupt:
        log.warning("Interrupted by user")
    except Exception as e:
        log.error(f"Fatal error: {e}")
        import traceback

        traceback.print_exc()
    finally:
        server.shutdown()


if __name__ == "__main__":
    import json

    main()
