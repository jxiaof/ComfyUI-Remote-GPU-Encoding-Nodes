"""
Arrow Flight Video Streaming Protocol
基于 Apache Arrow Flight 的高性能视频流传输协议

特性:
- 零拷贝传输
- 元数据支持
- 批量传输优化
- 会话管理
"""

import pyarrow as pa
import pyarrow.flight as flight
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import uuid
import time


class FlightDescriptorType:
    """Flight 描述符类型"""

    SESSION_START = "session_start"
    SESSION_END = "session_end"
    VIDEO_FRAMES = "video_frames"
    AUDIO_DATA = "audio_data"


@dataclass
class VideoFrameMetadata:
    """视频帧元数据"""

    width: int
    height: int
    channels: int
    fps: int
    total_frames: int
    format: str = "RGB24"
    output_path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "channels": self.channels,
            "fps": self.fps,
            "total_frames": self.total_frames,
            "format": self.format,
            "output_path": self.output_path,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VideoFrameMetadata":
        return cls(**data)


@dataclass
class AudioMetadata:
    """音频元数据"""

    sample_rate: int
    channels: int
    samples: int
    format: str = "PCM_F32LE"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "samples": self.samples,
            "format": self.format,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AudioMetadata":
        return cls(**data)


@dataclass
class SessionInfo:
    """会话信息"""

    session_id: str
    start_time: float
    output_path: str
    has_audio: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "start_time": self.start_time,
            "output_path": self.output_path,
            "has_audio": self.has_audio,
        }


def create_session_descriptor(
    session_id: str, metadata: Dict[str, Any]
) -> flight.FlightDescriptor:
    """创建会话描述符"""
    import json

    # 将元数据编码为 path 的一部分
    metadata_str = json.dumps(metadata)
    encoded_path = f"{FlightDescriptorType.SESSION_START}/{session_id}/{metadata_str}"

    return flight.FlightDescriptor.for_path(encoded_path)


def create_frames_descriptor(session_id: str) -> flight.FlightDescriptor:
    """创建帧描述符"""
    return flight.FlightDescriptor.for_path(
        f"{FlightDescriptorType.VIDEO_FRAMES}/{session_id}"
    )


def create_audio_descriptor(session_id: str) -> flight.FlightDescriptor:
    """创建音频描述符"""
    return flight.FlightDescriptor.for_path(
        f"{FlightDescriptorType.AUDIO_DATA}/{session_id}"
    )
