"""
ZMQ Video Streaming Protocol Definition
视频流传输协议定义

协议版本: 2.0
支持: 视频帧、音频数据、会话控制
"""

import struct
from enum import IntEnum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import time


# ============================================================================
# 协议版本
# ============================================================================

PROTOCOL_VERSION = 2
PROTOCOL_MAGIC = 0x5A4D5646  # "ZMVF" - ZMQ Video Frame


# ============================================================================
# 消息类型
# ============================================================================


class MessageType(IntEnum):
    """消息类型枚举"""

    SESSION_START = 1  # 会话开始
    SESSION_END = 2  # 会话结束
    FRAME_DATA = 3  # 视频帧数据
    AUDIO_DATA = 4  # 音频数据
    HEARTBEAT = 5  # 心跳包
    ERROR = 6  # 错误消息
    BATCH_FRAMES = 7  # 批量帧传输


class PixelFormat(IntEnum):
    """像素格式"""

    UNKNOWN = 0
    RGB24 = 1  # RGB 8bit per channel
    RGBA32 = 2  # RGBA 8bit per channel
    BGR24 = 3  # BGR 8bit per channel


class AudioFormat(IntEnum):
    """音频格式"""

    NONE = 0
    PCM_F32LE = 1  # 32-bit float, little-endian
    PCM_S16LE = 2  # 16-bit signed int, little-endian
    PCM_S24LE = 3  # 24-bit signed int, little-endian


class SessionFlags(IntEnum):
    """会话标志位"""

    NONE = 0
    HAS_AUDIO = 1 << 0  # 包含音频
    REALTIME = 1 << 1  # 实时模式
    LOSSLESS = 1 << 2  # 无损模式


# ============================================================================
# 消息头格式定义
# ============================================================================

# 视频帧头格式 (128 bytes)
# | magic(4) | version(1) | msg_type(1) | flags(1) | pixel_fmt(1) | = 8 bytes
# | width(4) | height(4) | channels(4) | data_len(4) | = 16 bytes
# | frame_num(8) | timestamp_us(8) | = 16 bytes
# | session_id(16) | = 16 bytes
# | total_frames(4) | fps(4) | = 8 bytes
# | output_path(60) | reserved(4) | = 64 bytes
# Total = 128 bytes

VIDEO_HEADER_FORMAT = "<I B B B B I I I I Q Q 16s I I 60s 4x"
VIDEO_HEADER_SIZE = 128

# 音频数据头格式 (64 bytes)
# | magic(4) | version(1) | msg_type(1) | audio_fmt(1) | channels(1) | = 8 bytes
# | sample_rate(4) | num_samples(4) | data_len(4) | reserved(4) | = 16 bytes
# | timestamp_us(8) | = 8 bytes
# | session_id(16) | = 16 bytes
# | reserved(16) | = 16 bytes
# Total = 64 bytes

AUDIO_HEADER_FORMAT = "<I B B B B I I I 4x Q 16s 16x"
AUDIO_HEADER_SIZE = 64

# 批量帧头格式 (128 bytes)
# | magic(4) | version(1) | msg_type(1) | flags(1) | pixel_fmt(1) | = 8 bytes
# | width(4) | height(4) | channels(4) | = 12 bytes
# | batch_size(2) | start_frame(2) | = 4 bytes
# | data_len(4) | = 4 bytes
# | timestamp_us(8) | = 8 bytes
# | session_id(16) | = 16 bytes
# | total_frames(4) | fps(4) | = 8 bytes
# | output_path(60) | reserved(4) | = 64 bytes
# Total = 128 bytes

BATCH_HEADER_FORMAT = "<I B B B B I I I H H I Q 16s I I 60s 4x"
BATCH_HEADER_SIZE = 128


# ============================================================================
# 数据类
# ============================================================================


@dataclass
class VideoHeader:
    """视频帧头"""

    magic: int = PROTOCOL_MAGIC
    version: int = PROTOCOL_VERSION
    msg_type: MessageType = MessageType.FRAME_DATA
    flags: int = 0
    pixel_format: PixelFormat = PixelFormat.RGB24
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

    def pack(self) -> bytes:
        """打包为字节"""
        output_bytes = self.output_path.encode("utf-8")[:59].ljust(60, b"\x00")
        return struct.pack(
            VIDEO_HEADER_FORMAT,
            self.magic,
            self.version,
            int(self.msg_type),
            self.flags,
            int(self.pixel_format),
            self.width,
            self.height,
            self.channels,
            self.data_len,
            self.frame_num,
            self.timestamp_us or int(time.time() * 1_000_000),
            self.session_id
            if isinstance(self.session_id, bytes)
            else self.session_id.encode(),
            self.total_frames,
            self.fps,
            output_bytes,
        )

    @classmethod
    def unpack(cls, data: bytes) -> "VideoHeader":
        """从字节解包"""
        if len(data) < VIDEO_HEADER_SIZE:
            raise ValueError(f"Data too short: {len(data)} < {VIDEO_HEADER_SIZE}")

        unpacked = struct.unpack(VIDEO_HEADER_FORMAT, data[:VIDEO_HEADER_SIZE])
        return cls(
            magic=unpacked[0],
            version=unpacked[1],
            msg_type=MessageType(unpacked[2]),
            flags=unpacked[3],
            pixel_format=PixelFormat(unpacked[4]),
            width=unpacked[5],
            height=unpacked[6],
            channels=unpacked[7],
            data_len=unpacked[8],
            frame_num=unpacked[9],
            timestamp_us=unpacked[10],
            session_id=unpacked[11],
            total_frames=unpacked[12],
            fps=unpacked[13],
            output_path=unpacked[14].rstrip(b"\x00").decode("utf-8", errors="ignore"),
        )

    @property
    def has_audio(self) -> bool:
        return bool(self.flags & SessionFlags.HAS_AUDIO)

    @property
    def session_id_hex(self) -> str:
        return self.session_id.hex()[:16]


@dataclass
class BatchFramesHeader:
    """批量帧头"""

    magic: int = PROTOCOL_MAGIC
    version: int = PROTOCOL_VERSION
    msg_type: MessageType = MessageType.BATCH_FRAMES
    flags: int = 0
    pixel_format: PixelFormat = PixelFormat.RGB24
    width: int = 0
    height: int = 0
    channels: int = 3
    batch_size: int = 0
    start_frame: int = 0
    data_len: int = 0
    timestamp_us: int = 0
    session_id: bytes = field(default_factory=lambda: b"\x00" * 16)
    total_frames: int = 0
    fps: int = 30
    output_path: str = ""

    def pack(self) -> bytes:
        """打包为字节"""
        output_bytes = self.output_path.encode("utf-8")[:59].ljust(60, b"\x00")
        return struct.pack(
            BATCH_HEADER_FORMAT,
            self.magic,
            self.version,
            int(self.msg_type),
            self.flags,
            int(self.pixel_format),
            self.width,
            self.height,
            self.channels,
            self.batch_size,
            self.start_frame,
            self.data_len,
            self.timestamp_us or int(time.time() * 1_000_000),
            self.session_id
            if isinstance(self.session_id, bytes)
            else self.session_id.encode(),
            self.total_frames,
            self.fps,
            output_bytes,
        )

    @classmethod
    def unpack(cls, data: bytes) -> "BatchFramesHeader":
        """从字节解包"""
        if len(data) < BATCH_HEADER_SIZE:
            raise ValueError(f"Data too short: {len(data)} < {BATCH_HEADER_SIZE}")

        unpacked = struct.unpack(BATCH_HEADER_FORMAT, data[:BATCH_HEADER_SIZE])
        return cls(
            magic=unpacked[0],
            version=unpacked[1],
            msg_type=MessageType(unpacked[2]),
            flags=unpacked[3],
            pixel_format=PixelFormat(unpacked[4]),
            width=unpacked[5],
            height=unpacked[6],
            channels=unpacked[7],
            batch_size=unpacked[8],
            start_frame=unpacked[9],
            data_len=unpacked[10],
            timestamp_us=unpacked[11],
            session_id=unpacked[12],
            total_frames=unpacked[13],
            fps=unpacked[14],
            output_path=unpacked[15].rstrip(b"\x00").decode("utf-8", errors="ignore"),
        )


@dataclass
class AudioHeader:
    """音频数据头"""

    magic: int = PROTOCOL_MAGIC
    version: int = PROTOCOL_VERSION
    msg_type: MessageType = MessageType.AUDIO_DATA
    audio_format: AudioFormat = AudioFormat.PCM_F32LE
    channels: int = 2
    sample_rate: int = 44100
    num_samples: int = 0
    data_len: int = 0
    timestamp_us: int = 0
    session_id: bytes = field(default_factory=lambda: b"\x00" * 16)

    def pack(self) -> bytes:
        """打包为字节"""
        return struct.pack(
            AUDIO_HEADER_FORMAT,
            self.magic,
            self.version,
            int(self.msg_type),
            int(self.audio_format),
            self.channels,
            self.sample_rate,
            self.num_samples,
            self.data_len,
            self.timestamp_us or int(time.time() * 1_000_000),
            self.session_id
            if isinstance(self.session_id, bytes)
            else self.session_id.encode(),
        )

    @classmethod
    def unpack(cls, data: bytes) -> "AudioHeader":
        """从字节解包"""
        if len(data) < AUDIO_HEADER_SIZE:
            raise ValueError(f"Data too short: {len(data)} < {AUDIO_HEADER_SIZE}")

        unpacked = struct.unpack(AUDIO_HEADER_FORMAT, data[:AUDIO_HEADER_SIZE])
        return cls(
            magic=unpacked[0],
            version=unpacked[1],
            msg_type=MessageType(unpacked[2]),
            audio_format=AudioFormat(unpacked[3]),
            channels=unpacked[4],
            sample_rate=unpacked[5],
            num_samples=unpacked[6],
            data_len=unpacked[7],
            timestamp_us=unpacked[8],
            session_id=unpacked[9],
        )

    @property
    def duration_seconds(self) -> float:
        return self.num_samples / self.sample_rate if self.sample_rate > 0 else 0


@dataclass
class Message:
    """通用消息容器"""

    header: VideoHeader | AudioHeader | BatchFramesHeader
    data: Optional[bytes] = None

    @property
    def msg_type(self) -> MessageType:
        return self.header.msg_type

    @property
    def is_video(self) -> bool:
        return isinstance(self.header, (VideoHeader, BatchFramesHeader))

    @property
    def is_audio(self) -> bool:
        return isinstance(self.header, AudioHeader)


# ============================================================================
# 协议解析器
# ============================================================================


class ProtocolParser:
    """协议解析器"""

    @staticmethod
    def parse(data: bytes) -> Optional[Message]:
        """解析原始数据为消息"""
        if len(data) < 8:
            return None

        # 检查魔数
        magic = struct.unpack("<I", data[:4])[0]
        if magic != PROTOCOL_MAGIC:
            # 兼容旧协议（无魔数）
            return ProtocolParser._parse_legacy(data)

        # 获取消息类型
        msg_type = MessageType(data[5])

        if msg_type == MessageType.AUDIO_DATA:
            if len(data) < AUDIO_HEADER_SIZE:
                return None
            header = AudioHeader.unpack(data)
            payload = (
                data[AUDIO_HEADER_SIZE:] if len(data) > AUDIO_HEADER_SIZE else None
            )
        elif msg_type == MessageType.BATCH_FRAMES:
            if len(data) < BATCH_HEADER_SIZE:
                return None
            header = BatchFramesHeader.unpack(data)
            payload = (
                data[BATCH_HEADER_SIZE:] if len(data) > BATCH_HEADER_SIZE else None
            )
        else:
            if len(data) < VIDEO_HEADER_SIZE:
                return None
            header = VideoHeader.unpack(data)
            payload = (
                data[VIDEO_HEADER_SIZE:] if len(data) > VIDEO_HEADER_SIZE else None
            )

        return Message(header=header, data=payload)

    @staticmethod
    def _parse_legacy(data: bytes) -> Optional[Message]:
        """解析旧版协议（向后兼容）"""
        if len(data) < 4:
            return None

        msg_type = data[0]

        # 旧版音频头
        if msg_type == MessageType.AUDIO_DATA and len(data) >= 64:
            try:
                old_format = "<BBBB IIII Q 16s 20x"
                hdr = struct.unpack(old_format, data[:64])
                header = AudioHeader(
                    msg_type=MessageType(hdr[0]),
                    audio_format=AudioFormat(hdr[1]),
                    channels=hdr[2],
                    sample_rate=hdr[4],
                    num_samples=hdr[5],
                    data_len=hdr[6],
                    timestamp_us=hdr[8],
                    session_id=hdr[9],
                )
                return Message(
                    header=header, data=data[64:] if len(data) > 64 else None
                )
            except:
                return None

        # 旧版视频头
        if len(data) >= 128:
            try:
                old_format = "<BBBB IIII Q Q 16s I I 64s 4x"
                hdr = struct.unpack(old_format, data[:128])
                header = VideoHeader(
                    msg_type=MessageType(hdr[0]),
                    flags=hdr[1],
                    pixel_format=PixelFormat(hdr[2]),
                    width=hdr[4],
                    height=hdr[5],
                    channels=hdr[6],
                    data_len=hdr[7],
                    frame_num=hdr[8],
                    timestamp_us=hdr[9],
                    session_id=hdr[10],
                    total_frames=hdr[11],
                    fps=hdr[12],
                    output_path=hdr[13]
                    .rstrip(b"\x00")
                    .decode("utf-8", errors="ignore"),
                )
                return Message(
                    header=header, data=data[128:] if len(data) > 128 else None
                )
            except:
                return None

        return None
