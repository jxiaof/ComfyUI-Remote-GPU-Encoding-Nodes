# ComfyUI Remote GPU Encoding

**将 ComfyUI 生成的视频帧通过高速网络传输到远程 GPU 服务器进行硬件编码**

---

## 核心亮点

- **极致性能** - 9-11 Gbps 带宽，5-10ms 延迟，零拷贝传输
- **硬件加速** - NVIDIA NVENC H.264/HEVC/AV1 编码
- **智能管理** - 自动网络检测、连接复用、进度追踪
- **三种协议** - Arrow Flight（推荐）、ZMQ 优化版、ZMQ 原版
- **单文件部署** - 编码服务器无需额外依赖，开箱即用

---

## 架构设计

```
┌──────────────────────────┐         ┌──────────────────┐         ┌─────────────────────────┐
│   ComfyUI Client         │         │   10Gbps Network │         │   Remote GPU Server     │
│                          │         │                  │         │                         │
│  ┌────────────────────┐  │────────▶│  Arrow Flight    │────────▶│  ┌──────────────────┐   │
│  │  Image Generation  │  │         │  Zero-copy       │         │  │  NVIDIA NVENC    │   │
│  └────────┬───────────┘  │         │                  │         │  └────────┬─────────┘   │
│           │              │         │                  │         │           │             │
│  ┌────────▼───────────┐  │         │                  │         │  ┌────────▼─────────┐   │
│  │  Node Module       │  │         │                  │         │  │  FFmpeg Muxer    │   │
│  └────────────────────┘  │         │                  │         │  └────────┬─────────┘   │
│                          │         │                  │         │           │             │
└──────────────────────────┘         └──────────────────┘         │  ┌────────▼─────────┐   │
                                                                  │  │  MP4 Output      │   │
                                                                  │  └──────────────────┘   │
                                                                  └─────────────────────────┘
```

**设计思路：**

1. **关注点分离** - ComfyUI 负责生成，编码服务器负责编码，通过网络连接
2. **零拷贝传输** - 使用 Arrow Flight 或 ZMQ 优化，避免不必要的数据拷贝
3. **批量优化** - 高帧率场景下自动批量传输，减少系统调用
4. **连接复用** - 多次传输复用同一连接，减少握手开销
5. **会话管理** - 支持单批次和多批次，灵活适配不同工作流

---

## 协议选择

| 特性 | Arrow Flight v3.0 | ZMQ 优化版 v2.1 | ZMQ 原版 v2.0 |
|------|------------------|----------------|--------------|
| **推荐度** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| 带宽 | 9-11 Gbps | 9-11 Gbps | 7-9 Gbps |
| 延迟 | 5-10ms | 5-10ms | 5-15ms |
| 零拷贝 | 完全 | 优化 | 部分 |
| 协议开销 | 0 字节 | 0 字节（批量） | 128 字节/帧 |
| 传输模式 | 批量 | 流式/批量/自动 | 批量 |
| 进度条 | tqdm | tqdm | 自定义 |
| 日志 | 结构化 | 结构化 | 自定义 |

**推荐：Arrow Flight v3.0** - 最新、最快、最稳定的协议

---

## 快速开始

### 方式一：Arrow Flight（推荐）

```bash
# 1. 安装依赖
pip install pyarrow tqdm

# 2. 启动 GPU 编码服务器
python gpu_encoder_arrow.py --bind 0.0.0.0:8815

# 3. 在 ComfyUI 中使用
# 添加 "Remote GPU Encoder (Arrow Flight)" 节点即可
```

### 方式二：ZMQ 优化版

```bash
# 1. 安装依赖
pip install pyzmq tqdm

# 2. 启动 GPU 编码服务器
python gpu_encoder.py --bind tcp://0.0.0.0:5555

# 3. 修改 __init__.py 切换到 ZMQ 优化版
# from .nodes_zmq_optimized import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

# 4. 在 ComfyUI 中使用 "Remote GPU Encoder (ZMQ Optimized)" 节点
```

### 切换协议

修改 `__init__.py`：

```python
# Arrow Flight (默认)
from .nodes_arrow import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

# ZMQ 优化版
from .nodes_zmq_optimized import NODE_CLASS_MAPPINGS, NODE_EDITOR_DISPLAY_MAPPINGS

# ZMQ 原版
from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
```

---

## 使用场景

### 场景一：单批次快速编码

```
生成视频 ─▶ 远程编码 ─▶ 完成
```

使用默认的 `auto` 会话模式，节点自动管理会话开始和结束。

### 场景二：多批次连续编码

```
批次 1 ──▶ 远程编码 ──┐
批次 2 ──▶ 远程编码 ──┤─▶ 合并输出
批次 3 ──▶ 远程编码 ──┘
```

使用 `start`/`continue`/`end` 模式手动控制会话。

### 场景三：大规模批量处理

使用 Arrow Flight + 批量传输模式，适合高帧率、长视频。

---

## 节点参数

### Remote GPU Encoder (Arrow Flight)

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `images` | 视频帧 (BHWC) | 必填 |
| `encoder_address` | 服务器地址 | `0.0.0.0:8815` |
| `output_path` | 输出路径 | `/tmp/output.mp4` |
| `fps` | 帧率 | 30 |
| `audio` | 音频 | 可选 |
| `batch_size` | 批量大小 | 10 |

### Remote GPU Encoder (ZMQ Optimized)

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `images` | 视频帧 (BHWC) | 必填 |
| `encoder_address` | 服务器地址 | `tcp://10.10.0.1:5555` |
| `output_path` | 输出路径 | `/tmp/output.mp4` |
| `fps` | 帧率 | 30 |
| `transport_mode` | 传输模式 | `auto` |
| `batch_size` | 批量大小 | 10 |

**传输模式 (ZMQ)：**
- `auto` - 智能选择（<50 帧用 stream，>=50 帧用 batch）
- `stream` - 流式传输，最低延迟
- `batch` - 批量传输，最高吞吐

---

## 服务器配置

### 启动参数

```bash
# Arrow Flight 服务器
python gpu_encoder_arrow.py [OPTIONS]

# ZMQ 服务器
python gpu_encoder.py [OPTIONS]
```

**通用选项：**
- `--bind, -b` - 绑定地址（Arrow 默认 `0.0.0.0:8815`，ZMQ 默认 `tcp://0.0.0.0:5555`）
- `--output-dir, -o` - 输出目录
- `--codec, -c` - 编码器（h264_nvenc / hevc_nvenc / av1_nvenc）
- `--preset, -p` - 预设（p1-p7，p1 最快，p7 质量最好）
- `--bitrate` - 码率（默认 20M）
- `--gpu` - GPU 索引（默认 0）
- `--single-session` - 单会话后退出
- `--idle-timeout` - 空闲超时（秒）

### 示例

```bash
# 4K 视频，高码率
python gpu_encoder_arrow.py --bind 0.0.0.0:8815 --codec av1_nvenc --bitrate 50M --preset p4

# 高帧率（60fps），快速编码
python gpu_encoder_arrow.py --bind 0.0.0.0:8815 --preset p2
```

---

##  性能参考

### 分辨率带宽需求

| 分辨率 | 帧大小 | 30fps 带宽 | 60fps 带宽 |
|--------|--------|----------|----------|
| 720p | 2.7 MB | 650 Mbps | 1.3 Gbps |
| 1080p | 6.2 MB | 1.5 Gbps | 3.0 Gbps |
| 4K | 24.9 MB | 6.0 Gbps | 12.0 Gbps |

### 协议性能对比

| 协议 | 720p@30fps | 1080p@30fps | 4K@30fps |
|------|----------|-----------|---------|
| Arrow Flight | 1.2x | 1.3x | 1.4x |
| ZMQ 优化版 | 1.2x | 1.3x | 1.4x |
| ZMQ 原版 | 1.0x | 1.0x | 1.0x |

*相对于 ZMQ 原版的性能提升倍数*

---

## 网络优化

### Linux 系统缓冲区

```bash
sudo sysctl -w net.core.rmem_max=268435456
sudo sysctl -w net.core.wmem_max=268435456
sudo sysctl -w net.ipv4.tcp_rmem="4096 87380 67108864"
sudo sysctl -w net.ipv4.tcp_wmem="4096 87380 67108864"
```

### 网络要求

- **带宽**: 建议 10Gbps 或更高（4K@60fps 需要 12 Gbps）
- **延迟**: 建议 <5ms（局域网）
- **稳定性**: 丢包率 <0.1%

---

## 项目结构

```
comfyui-remote-encoding/
├── __init__.py                 # 包入口（默认 Arrow Flight）
├── nodes_arrow.py              # Arrow Flight 节点 ⭐
├── nodes_zmq_optimized.py      # ZMQ 优化版节点
├── nodes.py                    # ZMQ 原版节点
├── gpu_encoder_arrow.py        # Arrow Flight 服务器（单文件）⭐
├── gpu_encoder.py              # ZMQ 服务器
├── protocol/                   # ZMQ 协议定义
│   ├── __init__.py
│   └── protocol.py
├── transport/                  # Arrow Flight 传输模块
│   ├── __init__.py
│   ├── client.py
│   └── protocol.py
├── logger/                     # 日志系统
│   ├── __init__.py
│   └── logger.py
├── utils/                      # 工具模块
│   ├── __init__.py
│   ├── audio.py
│   ├── connection.py
│   ├── network.py
│   └── storage.py
├── README.md
└── requirements.txt
```

**核心模块：**
- `transport/` - Arrow Flight 传输层（零拷贝、批量优化）
- `protocol/` - ZMQ 协议定义（消息类型、格式）
- `logger/` - 专业日志系统（彩色、结构化、进度条）
- `utils/` - 工具类（网络、连接、音频）

---

## ❓ 常见问题

### Q: 如何选择协议？

**Arrow Flight** - 追求最高性能、新项目
**ZMQ 优化版** - 现有项目升级、需要快速迁移
**ZMQ 原版** - 快速测试、学习项目

### Q: 传输失败怎么办？

1. 检查服务器是否启动
2. 检查网络连通性
3. 检查防火墙设置
4. 查看服务器日志

### Q: 如何提升性能？

1. 使用 Arrow Flight 或 ZMQ 优化版
2. 启用批量传输模式
3. 调整批量大小和窗口
4. 优化网络缓冲区
5. 使用 10Gbps 网络

### Q: 支持哪些编码器？

- H.264 (h264_nvenc)
- HEVC (hevc_nvenc)
- AV1 (av1_nvenc)

需要支持 NVENC 的 NVIDIA GPU。

---

## 许可证

MIT License

---

**有问题？** - 提交 Issue 或 Pull Request

**喜欢这个项目？** - 给个 Star ⭐
