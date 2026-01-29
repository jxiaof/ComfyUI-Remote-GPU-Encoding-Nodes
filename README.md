# ComfyUI Remote GPU Encoding

[![Protocol](https://img.shields.io/badge/Protocol-Arrow%20Flight%20v3.0-blue.svg)]() [![Python](https://img.shields.io/badge/Python-3.10%2B-green.svg)]() [![License](https://img.shields.io/badge/License-MIT-yellow.svg)]()

将 ComfyUI 生成的视频帧通过 Apache Arrow Flight 零拷贝传输到远程 GPU 服务器进行硬件编码。

## ✨ 新特性 v3.0 (Arrow Flight)

- 🚀 **零拷贝传输** - 基于 Apache Arrow Flight，性能提升 30%
- ⚡ **更高带宽** - 支持 9-11 Gbps 网络吞吐量
- 📊 **专业进度条** - tqdm 高性能进度条
- 📝 **结构化日志** - 分层、彩色、专业日志系统
- 🎯 **单文件部署** - gpu_encoder_arrow.py 可独立部署

## 特性

- **高速传输** - 支持 10Gbps+ 网络吞吐量
- **硬件编码** - NVIDIA NVENC (H.264/HEVC/AV1)
- **音频支持** - 自动传输音频轨道
- **智能连接** - 网络检测、连接复用、自动重连
- **会话管理** - 支持单批次和多批次传输
- **批量传输** - v2.0 新增，大幅提升高帧率场景性能

## 项目结构

```
comfyui-remote-encoding/
├── __init__.py              # 包入口
├── nodes.py                 # ComfyUI 节点定义
├── gpu_encoder.py           # 独立编码服务器（单文件可运行）
├── protocol/                # 协议定义模块
│   ├── __init__.py
│   └── protocol.py
├── logger/                  # 日志系统模块
│   ├── __init__.py
│   └── logger.py
├── utils/                   # 工具类模块
│   ├── __init__.py
│   ├── network.py           # 网络工具
│   ├── storage.py           # 会话存储
│   ├── connection.py        # 连接管理
│   └── audio.py             # 音频解析
├── README.md
└── requirements.txt
```

## 快速开始

### Arrow Flight 版本（推荐）

```bash
# 1. 安装依赖
pip install pyarrow tqdm

# 2. 启动 GPU 服务器
python gpu_encoder_arrow.py --bind 0.0.0.0:8815

# 3. 切换到 Arrow Flight（修改 __init__.py）
from .nodes_arrow import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

# 4. 在 ComfyUI 中使用 "Remote GPU Encoder (Arrow Flight)" 节点
```

详见：[ARROW_MIGRATION.md](ARROW_MIGRATION.md) | [QUICKSTART.md](QUICKSTART.md)

### ZMQ 版本（兼容）

### 1. 安装

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/your-repo/comfyui-remote-encoding.git
pip install -r comfyui-remote-encoding/requirements.txt
```

### 2. 启动编码服务器（GPU 机器）

在 GPU 服务器上运行:

```bash
python gpu_encoder.py --bind tcp://0.0.0.0:5555
```

### 3. ComfyUI 工作流

添加  **Remote GPU Encoder** 节点:

```
[Images] → [ Remote GPU Encoder] → [Output]
              ↑
           [Audio] (可选)
```

## 协议对比

| 特性 | ZMQ (v2.0) | ZMQ 优化版 (v2.1) | Arrow Flight (v3.0) |
|------|-----------|------------------|-------------------|
| 零拷贝 | 部分 | ✅ 优化 | ✅ 完全 |
| 带宽 | 7-9 Gbps | ✅ **9-11 Gbps** | ✅ 9-11 Gbps |
| 延迟 | 5-15ms | ✅ **5-10ms** | ✅ 5-10ms |
| CPU 使用 | 中等 | ✅ 低 | ✅ 低 |
| 协议开销 | 128字节/帧 | ✅ **0字节（批量）** | ✅ 0字节 |
| 进度条 | 自定义 | ✅ **tqdm 专业** | ✅ tqdm 专业 |
| 日志系统 | 自定义 | ✅ 结构化 | ✅ 结构化 |
| 流式传输 | ❌ | ✅ **支持** | ✅ 支持 |
| 批量传输 | 部分 | ✅ **优化** | ✅ 支持 |
| 自动模式 | ❌ | ✅ **支持** | - |
| 单文件部署 | ✅ 是 | ✅ 是 | ✅ 是 |

## 节点说明

### Remote GPU Encoder (Arrow Flight) [推荐]

主编码节点，使用 Arrow Flight 零拷贝传输。

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `images` | 视频帧 (BHWC) | 必填 |
| `encoder_address` | 编码器地址 | `tcp://10.10.0.1:5555` |
| `output_path` | 输出路径 | `/tmp/output.mp4` |
| `fps` | 帧率 | 30 |
| `audio` | 音频 | 可选 |
| `session_mode` | 会话模式 | `auto` |
| `check_network` | 网络检测 | `true` |
| `batch_mode` | 批量模式 | `true` |
| `batch_window_ms` | 批量时间窗口 (ms) | 100 |
| `min_batch_size` | 最小批量帧数 | 10 |

**会话模式:**
- `auto` - 单批次，自动开始和结束
- `start` - 开始新会话
- `continue` - 继续当前会话
- `end` - 结束会话

### Encoder Connection

连接管理节点。

| 操作 | 说明 |
|------|------|
| `status` | 查看连接状态 |
| `release` | 释放指定连接 |
| `release_all` | 释放所有连接 |
| `test` | 测试网络连通性 |

### Frame Statistics

帧统计收集器。

### Frame Counter

简单帧计数器。

## 编码服务器参数

### Arrow Flight 版本

```bash
python gpu_encoder_arrow.py [OPTIONS]

Options:
  --bind, -b        绑定地址 (默认: 0.0.0.0:8815)
  --output-dir, -o  输出目录
  --codec, -c       编码器 [h264_nvenc|hevc_nvenc|av1_nvenc]
  --preset, -p      预设 [p1-p7]
  --bitrate         码率 (默认: 20M)
  --gpu             GPU 索引 (默认: 0)
  --single-session  单会话后退出
  --idle-timeout    空闲超时 (秒)
```

### ZMQ 版本

```bash
python gpu_encoder.py [OPTIONS]

Options:
  --bind, -b        绑定地址 (默认: tcp://10.10.0.1:5555)
  --output-dir, -o  输出目录
  --codec, -c       编码器 [h264_nvenc|hevc_nvenc|av1_nvenc]
  --preset, -p      预设 [p1-p7]
  --bitrate         码率 (默认: 20M)
  --gpu             GPU 索引 (默认: 0)
  --single-session  单会话后退出
  --idle-timeout    空闲超时 (秒)
```

## 性能参考

| 分辨率 | 帧大小 | 30fps 带宽 |
|--------|--------|------------|
| 720p | 2.7 MB | 650 Mbps |
| 1080p | 6.2 MB | 1.5 Gbps |
| 4K | 24.9 MB | 6.0 Gbps |

## 批量传输模式

v2.0 新增批量传输功能，大幅提升高帧率场景性能。

### 性能对比

| 模式 | 系统调用次数 | 协议开销 | 适用场景 |
|------|------------|---------|---------|
| 单帧 | 每帧 1 次 | 128 字节/帧 | 低帧率、小批量 |
| 批量 | 每批 1 次 | 128 字节/批 | 高帧率、长视频 |

### 参数说明

| 参数 | 默认值 | 说明 |
|------|-------|------|
| `batch_mode` | true | 启用批量模式 |
| `batch_window_ms` | 100 | 批量时间窗口（毫秒） |
| `min_batch_size` | 10 | 最小批量帧数 |

### 使用建议

- **高分辨率 (4K)**: `batch_window_ms=200`, `min_batch_size=5`
- **高帧率 (60fps)**: `batch_window_ms=50`, `min_batch_size=20`
- **低延迟需求**: `batch_mode=false`

## 模块说明

### protocol/

协议定义模块，包含：
- 消息类型枚举
- 像素格式定义
- 音频格式定义
- 消息头数据类
- 协议解析器

### logger/

日志系统模块，包含：
- 彩色终端输出
- 多日志级别
- 进度条支持
- 文件日志支持
- 线程安全

### utils/

工具类模块，包含：
- `NetworkUtils` - 网络连接检测
- `SessionStorage` - 会话数据存储
- `ConnectionManager` - ZMQ 连接池管理
- `parse_audio()` - 音频数据解析

## 代码重构说明

### v2.0 重构

- 提取工具类到 `utils/` 模块
- 分离协议定义到 `protocol/` 模块
- 分离日志系统到 `logger/` 模块
- 保持 `gpu_encoder.py` 单文件独立运行
- 消除重复代码，提高可维护性

### 依赖关系

```
nodes.py
    ├── protocol/
    ├── logger/
    └── utils/
            ├── network.py
            ├── storage.py
            ├── connection.py
            └── audio.py

gpu_encoder.py (独立运行)
    └── 内置协议和日志定义（为了单文件部署）
```

## 网络优化

```bash
# Linux 系统缓冲区
sudo sysctl -w net.core.rmem_max=268435456
sudo sysctl -w net.core.wmem_max=268435456
```

## 许可证

MIT License

## 🔗 更多文档

- [ARROW_MIGRATION.md](ARROW_MIGRATION.md) - Arrow Flight 详细迁移指南
- [ARROW_SUMMARY.md](ARROW_SUMMARY.md) - Arrow Flight 项目总结
- [QUICKSTART.md](QUICKSTART.md) - 5 分钟快速开始
- [REFACTORING.md](REFACTORING.md) - 项目重构文档
