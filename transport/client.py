"""
Arrow Flight Video Client
基于 Apache Arrow Flight 的视频帧发送客户端

特性:
- 零拷贝传输
- 批量传输优化
- 进度条支持 (tqdm)
- 自动重连
"""

import time
import uuid

import pyarrow as pa
import pyarrow.flight as flight
import torch
import numpy as np
from tqdm import tqdm
from typing import Optional, Tuple, Any

from .protocol import (
    VideoFrameMetadata,
    AudioMetadata,
    SessionInfo,
    FlightDescriptorType,
    create_session_descriptor,
    create_frames_descriptor,
    create_audio_descriptor,
)
from ..logger import Logger


class ArrowVideoClient:
    """
    Arrow Flight 视频发送客户端

    使用 Arrow Flight 实现零拷贝视频传输
    """

    def __init__(self, endpoint: str, timeout: float = 30.0):
        """
        初始化客户端

        Args:
            endpoint: Arrow Flight 服务端点 (grpc://host:port)
            timeout: 连接超时时间（秒）
        """
        self.endpoint = endpoint
        self.timeout = timeout
        self.client: Optional[flight.FlightClient] = None
        self.session_id: Optional[str] = None
        self.log = Logger("ArrowClient")

        self._connect()

    def _connect(self):
        """连接到服务端"""
        try:
            self.log.info(f"Connecting to Arrow Flight: {self.endpoint}")
            if ":" in self.endpoint:
                host, port = self.endpoint.split(":")
                port = int(port)
            else:
                host = self.endpoint
                port = 8815
            location = flight.Location.for_grpc_tcp(host, port)
            self.client = flight.FlightClient(location)
            self.log.success(f"Connected to: {self.endpoint}")
        except Exception as e:
            self.log.error(f"Connection failed: {e}")
            raise

    def start_session(
        self,
        width: int,
        height: int,
        channels: int,
        fps: int,
        total_frames: int,
        output_path: str,
        format: str = "RGB24",
    ) -> str:
        """
        开始新的编码会话

        Args:
            width: 视频宽度
            height: 视频高度
            channels: 通道数
            fps: 帧率
            total_frames: 总帧数
            output_path: 输出路径
            format: 像素格式

        Returns:
            session_id: 会话ID
        """
        self.session_id = str(uuid.uuid4())

        metadata = VideoFrameMetadata(
            width=width,
            height=height,
            channels=channels,
            fps=fps,
            total_frames=total_frames,
            format=format,
            output_path=output_path,
        )

        self.log.header(f"Starting Arrow Flight Session")
        self.log.kv("Session ID", self.session_id)
        self.log.kv("Endpoint", self.endpoint)
        self.log.kv("Output", output_path)
        self.log.kv("Resolution", f"{width}×{height}")
        self.log.kv("Frames", total_frames)
        self.log.kv("FPS", fps)
        self.log.separator()

        # 创建描述符
        descriptor = create_session_descriptor(self.session_id, metadata.to_dict())

        # 发送会话开始信号
        info = self.client.get_flight_info(descriptor)
        self.log.success("Session started")

        return self.session_id

    def send_audio(self, audio_data: bytes, sample_rate: int, channels: int):
        """
        发送音频数据

        Args:
            audio_data: 音频数据 (bytes)
            sample_rate: 采样率
            channels: 通道数
        """
        if not self.session_id:
            raise RuntimeError("No active session. Call start_session() first.")

        metadata = AudioMetadata(
            sample_rate=sample_rate,
            channels=channels,
            samples=len(audio_data) // (4 * channels),  # PCM_F32LE
        )

        # 创建描述符
        descriptor = create_audio_descriptor(self.session_id)
        descriptor.descriptor = pa.serialize_pandas(metadata.to_dict()).to_buffer()

        # 创建音频 Arrow Array (零拷贝)
        audio_array = pa.array(
            np.frombuffer(audio_data, dtype=np.float32),
            type=pa.float32(),
        )

        # 发送音频
        batch = pa.RecordBatch.from_pydict({"audio_data": audio_array})
        writer, _ = self.client.do_put(descriptor)
        writer.write_batch(batch)
        writer.close()

        self.log.success(f"Audio sent: {len(audio_data) / 1024:.1f} KB")

    def send_frames(
        self,
        frames: torch.Tensor,
        batch_size: int = 10,
        show_progress: bool = True,
    ) -> Tuple[int, float, float]:
        """
        发送视频帧（零拷贝）

        Args:
            frames: 视频帧 tensor (N, H, W, C)
            batch_size: 批量大小
            show_progress: 是否显示进度条

        Returns:
            (frames_sent, fps_actual, data_mb)
        """
        if not self.session_id:
            raise RuntimeError("No active session. Call start_session() first.")

        # GPU → CPU (唯一拷贝)
        frames_np = (frames.cpu().numpy() * 255).astype(np.uint8)

        num_frames = len(frames_np)
        self.log.info(f"Sending {num_frames} frames in batches of {batch_size}...")

        total_bytes = 0
        start_time = time.time()

        # 批量发送
        with tqdm(
            total=num_frames,
            desc="Arrow Flight",
            unit="frame",
            disable=not show_progress,
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]",
        ) as pbar:
            for i in range(0, num_frames, batch_size):
                batch = frames_np[i : i + batch_size]

                # 创建 Arrow Array (零拷贝)
                batch_flat = batch.flatten()
                frames_array = pa.array(batch_flat, type=pa.uint8())

                # 创建 RecordBatch
                batch_record = pa.RecordBatch.from_pydict(
                    {
                        "pixel_data": frames_array,
                        "frame_start": pa.array([i]),
                        "frame_end": pa.array([min(i + batch_size, num_frames)]),
                    }
                )

                # 发送 (零拷贝)
                descriptor = create_frames_descriptor(self.session_id)
                writer, _ = self.client.do_put(descriptor)
                writer.write_batch(batch_record)
                writer.close()

                total_bytes += batch.nbytes
                pbar.update(len(batch))

                # 更新进度条信息
                elapsed = time.time() - start_time
                fps = pbar.n / elapsed if elapsed > 0 else 0
                mb = total_bytes / (1024 * 1024)
                gbps = (mb * 8) / elapsed / 1000 if elapsed > 0 else 0
                pbar.set_postfix_str(f"{fps:.1f} fps | {mb:.1f} MB | {gbps:.2f} Gbps")

        # 统计
        elapsed = time.time() - start_time
        fps_actual = num_frames / elapsed if elapsed > 0 else 0
        data_mb = total_bytes / (1024 * 1024)
        throughput_gbps = (data_mb * 8) / elapsed / 1000 if elapsed > 0 else 0

        self.log.success(
            f"Transfer complete: {num_frames} frames | "
            f"{fps_actual:.1f} fps | {throughput_gbps:.2f} Gbps"
        )

        return num_frames, fps_actual, data_mb

    def end_session(self):
        """结束会话"""
        if not self.session_id:
            return

        descriptor = flight.FlightDescriptor.for_path(
            f"{FlightDescriptorType.SESSION_END}/{self.session_id}"
        )

        try:
            info = self.client.get_flight_info(descriptor)
            self.log.success("Session ended")
        except Exception as e:
            self.log.warning(f"Session end signal failed: {e}")

        self.session_id = None

    def __enter__(self):
        """上下文管理器支持"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """自动清理"""
        self.end_session()
        if self.client:
            self.client.close()


class ArrowVideoSender:
    """
    Arrow Video Sender 高层封装

    用于在 ComfyUI 节点中使用
    """

    _clients: dict = {}

    @classmethod
    def get_client(cls, endpoint: str) -> ArrowVideoClient:
        """获取或创建客户端（连接复用）"""
        if endpoint not in cls._clients:
            cls._clients[endpoint] = ArrowVideoClient(endpoint)
        return cls._clients[endpoint]

    @classmethod
    def release_client(cls, endpoint: str):
        """释放客户端"""
        if endpoint in cls._clients:
            client = cls._clients[endpoint]
            client.end_session()
            del cls._clients[endpoint]

    @classmethod
    def release_all(cls):
        """释放所有客户端"""
        for endpoint in list(cls._clients.keys()):
            cls.release_client(endpoint)
