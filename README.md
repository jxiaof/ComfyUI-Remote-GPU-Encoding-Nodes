# ComfyUI Remote GPU Encoding

[![Protocol](https://img.shields.io/badge/Protocol-v2.0-blue.svg)]() [![Python](https://img.shields.io/badge/Python-3.10%2B-green.svg)]() [![License](https://img.shields.io/badge/License-MIT-yellow.svg)]()

将 ComfyUI 生成的视频帧通过高速网络传输到远程 GPU 服务器进行硬件编码。

## 特性

- **高速传输** - 支持 10Gbps+ 网络吞吐量
- **硬件编码** - NVIDIA NVENC (H.264/HEVC/AV1)
- **音频支持** - 自动传输音频轨道
- **智能连接** - 网络检测、连接复用、自动重连
- **会话管理** - 支持单批次和多批次传输

## 安装

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/your-repo/comfyui-remote-encoding.git
pip install -r comfyui-remote-encoding/requirements.txt
```

## 快速开始

### 1. 启动编码服务器

在 GPU 服务器上运行:

```bash
python gpu_encoder.py --bind tcp://0.0.0.0:5555
```

### 2. ComfyUI 工作流

添加  **Remote GPU Encoder** 节点:

```
[Images] → [ Remote GPU Encoder] → [Output]
              ↑
           [Audio] (可选)
```

## 节点说明

### Remote GPU Encoder

主编码节点，将视频帧发送到远程服务器。

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `images` | 视频帧 (BHWC) | 必填 |
| `encoder_address` | 编码器地址 | `tcp://10.10.0.1:5555` |
| `output_path` | 输出路径 | `/tmp/output.mp4` |
| `fps` | 帧率 | 30 |
| `audio` | 音频 | 可选 |
| `session_mode` | 会话模式 | `auto` |
| `check_network` | 网络检测 | `true` |

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

## 网络优化

```bash
# Linux 系统缓冲区
sudo sysctl -w net.core.rmem_max=268435456
sudo sysctl -w net.core.wmem_max=268435456
```

## 许可证

MIT License