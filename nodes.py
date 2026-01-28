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
import socket
import atexit
from typing import Dict, Any, Optional, Tuple

# 本地模块
from .protocol import (
    MessageType, PixelFormat, AudioFormat, SessionFlags,
    VideoHeader, AudioHeader, VIDEO_HEADER_SIZE, AUDIO_HEADER_SIZE,
)
from .logger import Logger, LogLevel, configure_logging, LOGO_PREFIX

# ZMQ 导入
try:
    import zmq
    HAS_ZMQ = True
except ImportError:
    HAS_ZMQ = False


# ============================================================================
# 日志初始化
# ============================================================================

configure_logging(level=LogLevel.INFO)


# ============================================================================
# 网络工具
# ============================================================================

class NetworkUtils:
    """网络工具类"""

    _log = Logger("Network")

    @classmethod
    def parse_endpoint(cls, endpoint: str) -> Tuple[str, str, int]:
        """
        解析端点地址

        Returns:
            (protocol, host, port)
        """
        try:
            # tcp://10.10.0.1:5555
            if "://" in endpoint:
                protocol, rest = endpoint.split("://", 1)
            else:
                protocol, rest = "tcp", endpoint

            if ":" in rest:
                host, port_str = rest.rsplit(":", 1)
                port = int(port_str)
            else:
                host, port = rest, 5555

            return protocol, host, port
        except Exception as e:
            cls._log.error(f"Invalid endpoint format: {endpoint}")
            raise ValueError(f"Invalid endpoint: {endpoint}")

    @classmethod
    def check_host_reachable(cls, host: str, port: int, timeout: float = 2.0) -> Tuple[bool, str]:
        """
        检查主机是否可达

        Returns:
            (is_reachable, message)
        """
        # 跳过本地地址检测
        if host in ("0.0.0.0", "127.0.0.1", "localhost", "*"):
            return True, "Local bind address"

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()

            if result == 0:
                return True, f"Host {host}:{port} is reachable"
            else:
                # 端口未开放不代表主机不可达，尝试 ping
                return cls._ping_host(host, timeout)
        except socket.gaierror:
            return False, f"Cannot resolve hostname: {host}"
        except socket.timeout:
            return False, f"Connection timeout: {host}:{port}"
        except Exception as e:
            return False, f"Network error: {e}"

    @classmethod
    def _ping_host(cls, host: str, timeout: float) -> Tuple[bool, str]:
        """尝试 ping 主机"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            # 尝试连接常用端口
            for port in [22, 80, 443]:
                try:
                    result = sock.connect_ex((host, port))
                    if result == 0:
                        sock.close()
                        return True, f"Host {host} is reachable"
                except:
                    pass
            sock.close()
            return True, f"Host {host} may be reachable (no open ports found)"
        except:
            return False, f"Cannot reach host: {host}"

    @classmethod
    def validate_endpoint(cls, endpoint: str, check_network: bool = True) -> Tuple[bool, str]:
        """
        验证端点地址

        Args:
            endpoint: 端点地址
            check_network: 是否检查网络连通性

        Returns:
            (is_valid, message)
        """
        try:
            protocol, host, port = cls.parse_endpoint(endpoint)

            if protocol not in ("tcp", "ipc"):
                return False, f"Unsupported protocol: {protocol}"

            if port < 1 or port > 65535:
                return False, f"Invalid port: {port}"

            if check_network and protocol == "tcp":
                return cls.check_host_reachable(host, port)

            return True, "Endpoint format valid"
        except ValueError as e:
            return False, str(e)


# ============================================================================
# 存储管理
# ============================================================================

class SessionStorage:
    """会话数据存储"""
    _data: Dict[str, Dict] = {}

    @classmethod
    def get(cls, key: str) -> Optional[Dict]:
        return cls._data.get(key)

    @classmethod
    def set(cls, key: str, data: Dict):
        cls._data[key] = data

    @classmethod
    def delete(cls, key: str):
        if key in cls._data:
            del cls._data[key]

    @classmethod
    def exists(cls, key: str) -> bool:
        return key in cls._data

    @classmethod
    def clear(cls):
        cls._data.clear()


# ============================================================================
# 连接管理器
# ============================================================================

class ConnectionManager:
    """
    连接池管理器

    特性:
    - 连接复用
    - 自动重连
    - 优雅关闭
    - 状态监控
    """

    _context: Optional['zmq.Context'] = None
    _sockets: Dict[str, Dict[str, Any]] = {}
    _initialized = False
    _log = Logger("Connection")

    @classmethod
    def _ensure_context(cls):
        """确保 Context 存在"""
        if cls._context is None:
            if not HAS_ZMQ:
                raise RuntimeError(
                    "pyzmq is not installed. Please run: pip install pyzmq"
                )
            cls._context = zmq.Context()

            if not cls._initialized:
                atexit.register(cls.shutdown)
                cls._initialized = True
                cls._log.debug("Context initialized")

    @classmethod
    def get_socket(
        cls,
        endpoint: str,
        socket_type: int = None,
        check_network: bool = True
    ) -> 'zmq.Socket':
        """
        获取或创建 Socket

        Args:
            endpoint: 端点地址
            socket_type: Socket 类型 (默认 PUB)
            check_network: 是否检查网络

        Returns:
            zmq.Socket 实例
        """
        if socket_type is None:
            socket_type = zmq.PUB

        cls._ensure_context()

        # 网络检查
        if check_network:
            is_valid, msg = NetworkUtils.validate_endpoint(
                endpoint, check_network=True)
            if not is_valid:
                cls._log.warning(f"Network check: {msg}")

        # 检查现有连接
        if endpoint in cls._sockets:
            info = cls._sockets[endpoint]
            sock = info["socket"]

            try:
                sock.getsockopt(zmq.EVENTS)
                info["access_count"] += 1
                cls._log.debug(f"Reusing connection: {endpoint}")
                return sock
            except zmq.ZMQError:
                cls._log.warning(f"Connection invalid, recreating: {endpoint}")
                cls.release(endpoint)

        # 创建新 socket
        cls._log.info(f"Creating connection: {endpoint}")

        sock = cls._context.socket(socket_type)

        # 配置
        sock.setsockopt(zmq.LINGER, 0)
        sock.setsockopt(zmq.SNDHWM, 500)
        sock.setsockopt(zmq.SNDBUF, 256 * 1024 * 1024)
        sock.setsockopt(zmq.TCP_KEEPALIVE, 1)
        sock.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 60)

        try:
            sock.bind(endpoint)
        except zmq.ZMQError as e:
            if "Address already in use" in str(e):
                cls._log.warning(f"Port busy, forcing release: {endpoint}")
                cls._force_release_port(endpoint)
                time.sleep(0.5)
                sock = cls._context.socket(socket_type)
                sock.setsockopt(zmq.LINGER, 0)
                sock.setsockopt(zmq.SNDHWM, 500)
                sock.setsockopt(zmq.SNDBUF, 256 * 1024 * 1024)
                sock.bind(endpoint)
            else:
                raise

        cls._sockets[endpoint] = {
            "socket": sock,
            "type": socket_type,
            "created_at": time.time(),
            "access_count": 1,
            "messages_sent": 0,
            "bytes_sent": 0
        }

        time.sleep(0.3)

        cls._log.success(f"Connection ready: {endpoint}")
        return sock

    @classmethod
    def _force_release_port(cls, endpoint: str):
        """强制释放端口"""
        if endpoint in cls._sockets:
            cls.release(endpoint)

        if cls._context:
            try:
                cls._context.term()
            except:
                pass
        cls._context = zmq.Context()

    @classmethod
    def release(cls, endpoint: str):
        """释放指定端点"""
        if endpoint not in cls._sockets:
            cls._log.warning(f"Connection not found: {endpoint}")
            return

        info = cls._sockets[endpoint]
        try:
            info["socket"].close(linger=0)
            cls._log.success(
                f"Released: {endpoint} "
                f"(messages: {info['messages_sent']}, "
                f"data: {info['bytes_sent'] / 1024 / 1024:.1f}MB)"
            )
        except Exception as e:
            cls._log.warning(f"Release error: {e}")

        del cls._sockets[endpoint]

    @classmethod
    def release_all(cls):
        """释放所有连接"""
        endpoints = list(cls._sockets.keys())
        for ep in endpoints:
            cls.release(ep)
        cls._log.success(f"Released {len(endpoints)} connections")

    @classmethod
    def shutdown(cls):
        """关闭管理器"""
        for ep, info in list(cls._sockets.items()):
            try:
                info["socket"].close(linger=0)
            except:
                pass
        cls._sockets.clear()

        if cls._context:
            try:
                cls._context.term()
            except:
                pass
            cls._context = None

    @classmethod
    def update_stats(cls, endpoint: str, bytes_sent: int):
        """更新统计"""
        if endpoint in cls._sockets:
            info = cls._sockets[endpoint]
            info["messages_sent"] += 1
            info["bytes_sent"] += bytes_sent

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        """获取状态"""
        status = {
            "active_connections": len(cls._sockets),
            "connections": {}
        }

        for ep, info in cls._sockets.items():
            age = time.time() - info["created_at"]
            status["connections"][ep] = {
                "messages": info["messages_sent"],
                "data_mb": round(info["bytes_sent"] / 1024 / 1024, 2),
                "uptime_seconds": round(age, 1),
                "access_count": info["access_count"]
            }

        return status

    @classmethod
    def get_status_string(cls) -> str:
        """获取状态字符串"""
        if not cls._sockets:
            return "No active connections"

        lines = [f"{LOGO_PREFIX} Active Connections:"]
        for ep, info in cls._sockets.items():
            age = time.time() - info["created_at"]
            lines.append(
                f"  • {ep}: "
                f"{info['messages_sent']} msgs, "
                f"{info['bytes_sent'] / 1024 / 1024:.1f} MB, "
                f"uptime: {age:.0f}s"
            )
        return "\n".join(lines)


# ============================================================================
# 音频解析工具
# ============================================================================

def parse_audio(audio: Any) -> Dict[str, Any]:
    """
    解析 ComfyUI 音频格式

    支持格式:
    - dict: {"waveform": tensor, "sample_rate": int}
    - tuple: (tensor, sample_rate)
    - tensor: 直接波形数据
    """
    log = Logger("Audio")
    result = {
        "has_audio": False,
        "data": None,
        "sample_rate": 44100,
        "channels": 2,
        "samples": 0,
        "duration": 0.0,
        "format": AudioFormat.PCM_F32LE
    }

    if audio is None:
        return result

    try:
        # 解析不同格式
        if isinstance(audio, dict):
            waveform = audio.get("waveform")
            sample_rate = audio.get("sample_rate", 44100)
        elif isinstance(audio, (tuple, list)) and len(audio) >= 2:
            waveform = audio[0]
            sample_rate = audio[1] if isinstance(audio[1], int) else 44100
        else:
            waveform = audio
            sample_rate = 44100

        if waveform is None:
            return result

        # 转换为 numpy
        if isinstance(waveform, torch.Tensor):
            audio_np = waveform.cpu().numpy()
        else:
            audio_np = np.array(waveform)

        # 确保 float32
        if audio_np.dtype != np.float32:
            if np.issubdtype(audio_np.dtype, np.integer):
                max_val = np.iinfo(audio_np.dtype).max
                audio_np = audio_np.astype(np.float32) / max_val
            else:
                audio_np = audio_np.astype(np.float32)

        # 解析形状
        if len(audio_np.shape) == 1:
            channels, samples = 1, audio_np.shape[0]
        elif len(audio_np.shape) == 2:
            channels, samples = audio_np.shape[0], audio_np.shape[1]
        elif len(audio_np.shape) == 3:
            audio_np = audio_np[0]
            channels, samples = audio_np.shape[0], audio_np.shape[1]
        else:
            log.warning(f"Unexpected audio shape: {audio_np.shape}")
            return result

        audio_np = np.ascontiguousarray(audio_np)

        result = {
            "has_audio": True,
            "data": audio_np.tobytes(),
            "sample_rate": sample_rate,
            "channels": channels,
            "samples": samples,
            "duration": samples / sample_rate,
            "format": AudioFormat.PCM_F32LE
        }

        log.debug(
            f"Audio: {channels}ch, {sample_rate}Hz, "
            f"{samples} samples ({result['duration']:.2f}s)"
        )

    except Exception as e:
        log.error(f"Audio parse failed: {e}")

    return result


# ============================================================================
# 远程 GPU 编码器节点 (主节点)
# ============================================================================

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
                "images": ("IMAGE", {
                    "tooltip": "Video frames to encode (BHWC format)"
                }),
                "encoder_address": ("STRING", {
                    "default": "tcp://10.10.0.1:5555",
                    "tooltip": "Remote encoder address (tcp://host:port)"
                }),
                "output_path": ("STRING", {
                    "default": "/tmp/output.mp4",
                    "tooltip": "Output video path on encoder server"
                }),
                "fps": ("INT", {
                    "default": 30,
                    "min": 1,
                    "max": 120,
                    "tooltip": "Video frame rate"
                }),
            },
            "optional": {
                "audio": ("AUDIO", {
                    "tooltip": "Optional audio track"
                }),
                "session_mode": (["auto", "start", "continue", "end"], {
                    "default": "auto",
                    "tooltip": "auto: single batch | start/continue/end: multi-batch"
                }),
                "total_frames": ("INT", {
                    "default": 0,
                    "min": 0,
                    "tooltip": "Total frames hint (0 = auto from batch)"
                }),
                "check_network": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Check network connectivity before sending"
                }),
                "show_progress": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Show transfer progress"
                }),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "INT", "FLOAT", "FLOAT")
    RETURN_NAMES = ("report", "session_id", "frames_sent",
                    "fps_actual", "data_mb")
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
    ) -> Tuple[str, str, int, float, float]:

        log = Logger("Encoder")

        # 检查依赖
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

        # 会话模式
        should_start = session_mode in ("auto", "start")
        should_end = session_mode in ("auto", "end")

        # 解析音频
        audio_info = parse_audio(audio)
        has_audio = audio_info["has_audio"]

        # 网络检查
        if check_network:
            log.info(f"Checking network: {encoder_address}")
            is_valid, msg = NetworkUtils.validate_endpoint(
                encoder_address, check_network=True)
            if not is_valid:
                log.warning(f"Network warning: {msg}")

        # 获取连接
        try:
            socket = ConnectionManager.get_socket(
                encoder_address, check_network=False)
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
                "audio_bytes": 0
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
                    "audio_bytes": 0
                }

        session = self._active_sessions[encoder_address]
        session_hex = session_id.hex()[:16]

        # ========== SESSION_START ==========
        if should_start:
            log.header(f"Remote GPU Encoding Session")
            log.kv("Session", session_hex)
            log.kv("Encoder", encoder_address)
            log.kv("Output", output_path)
            log.kv("Resolution", f"{w}×{h}")
            log.kv("Frames", f"{num_frames} (total: {total_frames})")
            log.kv("FPS", fps)
            log.kv(
                "Audio", f"{audio_info['duration']:.2f}s" if has_audio else "None")
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
                output_path=output_path
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
                session_id=session_id
            )

            msg = audio_header.pack() + audio_info["data"]
            socket.send(msg, zmq.NOBLOCK)
            session["audio_bytes"] = len(audio_info["data"])
            ConnectionManager.update_stats(encoder_address, len(msg))

            log.success(f"Audio sent: {len(audio_info['data']) / 1024:.1f}KB")
            time.sleep(0.1)

        # ========== FRAME_DATA ==========
        log.info(f"Sending {num_frames} frames...")
        send_start = time.time()

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
                output_path=output_path
            )

            msg = header.pack() + pixel_data
            socket.send(msg, zmq.NOBLOCK)
            ConnectionManager.update_stats(encoder_address, len(msg))

            if show_progress:
                elapsed = time.time() - session["start_time"]
                current_fps = session["frames_sent"] / \
                    elapsed if elapsed > 0 else 0
                mb = session["bytes_sent"] / (1024 * 1024)
                gbps = (mb * 8) / elapsed / 1000 if elapsed > 0 else 0

                log.progress(
                    session["frames_sent"],
                    total_frames,
                    suffix=f"{current_fps:.1f} fps | {mb:.1f} MB | {gbps:.2f} Gbps"
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
                output_path=output_path
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
        throughput_gbps = (total_mb * 8) / total_time / \
            1000 if total_time > 0 else 0

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
│    Speed:      {fps_actual:.1f} fps{'':<49}│
├─────────────────────────────────────────────────────────────────────┤
│  AUDIO                                                              │
│    Included:   {str(has_audio):<54}│
│    Size:       {audio_mb:.2f} MB{'':<50}│
├─────────────────────────────────────────────────────────────────────┤
│  TRANSFER                                                           │
│    Time:       {total_time:.2f}s{'':<51}│
│    Data:       {total_mb:.2f} MB{'':<50}│
│    Bandwidth:  {throughput_gbps:.2f} Gbps{'':<47}│
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
            round(data_mb, 2)
        )

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")


# ============================================================================
# Connection Manager Node (连接管理)
# ============================================================================

class RemoteEncoderConnection:
    """远程编码器连接管理"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "action": (["status", "release", "release_all", "test"], {
                    "default": "status",
                    "tooltip": "Connection management action"
                }),
            },
            "optional": {
                "encoder_address": ("STRING", {
                    "default": "tcp://10.10.0.1:5555",
                    "tooltip": "Encoder address for release/test"
                }),
                "trigger": ("*", {
                    "tooltip": "Trigger input (any type)"
                }),
            }
        }

    RETURN_TYPES = ("STRING", "BOOLEAN")
    RETURN_NAMES = ("status", "success")
    FUNCTION = "execute"
    CATEGORY = "Remote GPU Encoding"
    OUTPUT_NODE = True

    def execute(
        self,
        action: str,
        encoder_address: str = "",
        trigger: Any = None
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
                encoder_address, check_network=True)

            if is_valid:
                log.success(f"Connection test passed: {msg}")
                return (f"OK: {msg}", True)
            else:
                log.warning(f"Connection test failed: {msg}")
                return (f"FAILED: {msg}", False)

        else:  # status
            return (ConnectionManager.get_status_string(), True)

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")


# ============================================================================
# Frame Statistics Node (帧统计)
# ============================================================================

class FrameStatistics:
    """帧统计收集器"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {
                    "tooltip": "Input images to analyze"
                }),
            },
            "optional": {
                "reset": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Reset statistics"
                }),
                "stats_id": ("STRING", {
                    "default": "default",
                    "tooltip": "Statistics group ID"
                }),
            }
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
            SessionStorage.set(stats_id, {
                "start_time": now,
                "frame_count": 0,
                "total_bytes": 0,
            })
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

        return (
            report,
            stats["frame_count"],
            round(elapsed, 3),
            round(fps, 2)
        )

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")


# ============================================================================
# Simple Frame Counter (简单计数器)
# ============================================================================

class FrameCounter:
    """简单帧计数器"""

    _counters: Dict[str, Dict] = {}

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {
                    "tooltip": "Input images"
                }),
            },
            "optional": {
                "reset": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Reset counter"
                }),
                "counter_id": ("STRING", {
                    "default": "counter",
                    "tooltip": "Counter ID"
                }),
            }
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


# ============================================================================
# 节点注册
# ============================================================================

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
