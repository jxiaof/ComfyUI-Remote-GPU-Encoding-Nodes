# Arrow Flight 测试清单

## 测试前准备

### 依赖检查
```bash
# 检查 pyarrow
python -c "import pyarrow; print(f'pyarrow: {pyarrow.__version__}')"

# 检查 tqdm
python -c "import tqdm; print('tqdm: OK')"

# 检查 pytorch
python -c "import torch; print(f'pytorch: {torch.__version__}')"
```

### 文件检查
```bash
# 确保所有文件存在
ls -l gpu_encoder_arrow.py
ls -l transport/__init__.py
ls -l transport/client.py
ls -l transport/protocol.py
ls -l nodes_arrow.py
```

## 测试清单

### 1. Arrow Flight 服务端测试

#### 启动服务器
```bash
python gpu_encoder_arrow.py --bind 0.0.0.0:8815
```

**预期输出：**
```
╔═════════════════════════════════════════════════════════════╗
║     ██████╗ ███████╗███╗   ███╗ ██████╗ ████████╗███████╗     ║
║     ╚══════╝╚══════╝╚═╝     ╚═╝ ╚═════╝    ╚═╝   ╚══════╝     ║
║         ARROW FLIGHT SERVER    Zero-Copy Encoding             ║
╚═════════════════════════════════════════════════════════════╝

═══════════════════════════════════════════════════════════════
  Configuration
────────────────────────────────────────────────────────────────
  Bind Address: 0.0.0.0:8815
  Output Dir: (from sender)
  Codec: h264_nvenc
  Preset: p4
  Bitrate: 20M
  GPU: 0
═══════════════════════════════════════════════════════════════

Starting Arrow Flight Server...
Listening on: 0.0.0.0:8815

═══════════════════════════════════════════════════════════════
  Waiting for Sessions
────────────────────────────────────────────────────────────────
```

#### 检查端口
```bash
# 检查端口是否监听
netstat -an | grep 8815
# 或
lsof -i :8815
```

### 2. Arrow Flight 客户端测试

#### 测试连接
```python
import pyarrow.flight as flight

# 创建客户端
client = flight.FlightClient(flight.Location.for_grpc_tcp("0.0.0.0:8815"))
print("✓ Connection successful")
```

### 3. ComfyUI 节点测试

#### 切换到 Arrow Flight
```python
# 修改 __init__.py
from .nodes_arrow import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
```

#### 启动 ComfyUI
```bash
python main.py
```

#### 检查节点加载
在 ComfyUI UI 中，应该能看到：
- ✅ Remote GPU Encoder (Arrow Flight)

### 4. 端到端测试

#### 测试工作流
1. 在 ComfyUI 中创建简单工作流：
   ```
   [Empty Latent Image] → [VAE Decode] → [Remote GPU Encoder (Arrow Flight)]
   ```

2. 配置参数：
   - `encoder_address`: `0.0.0.0:8815`
   - `output_path`: `/tmp/test.mp4`
   - `fps`: `30`

3. 执行工作流

#### 预期结果

**客户端日志：**
```
[ArrowGPU] [INFO ] [ArrowClient] Connecting to Arrow Flight: grpc://0.0.0.0:8815
[ArrowGPU] [ OK  ] [ArrowClient] Connected to: grpc://0.0.0.0:8815
[ArrowGPU] [INFO ] [ArrowEncoder] Starting Arrow Flight Session
...
Arrow Flight: 100%|████████████████| 30/30 [00:00<00:00, 30.0fps, 1.5 MB, 0.6 Gbps]
[ArrowGPU] [ OK  ] [ArrowEncoder] Transfer complete: 30 frames | 30.0 fps | 0.6 Gbps
```

**服务端日志：**
```
[ArrowGPU] [INFO ] [Main] Session Start: xxx
...
[ArrowGPU] [INFO ] [FFmpeg] Initializing encoder: 512×512@30fps
[ArrowGPU] [ OK  ] [FFmpeg] Encoder initialized
[ArrowGPU] [INFO ] [Main] Receiving video frames for session: xxx

Arrow Flight: 100%|████████████████| 30/30 [00:00<00:00, 30.0fps, 1.5 MB, 0.6 Gbps]

[ArrowGPU] [INFO ] [FFmpeg] Finalizing video...
[ArrowGPU] [ OK  ] [FFmpeg] Encoded 30 frames in 0.05s (540.8 fps)
[ArrowGPU] [SUCCESS] [Main] OUTPUT: /tmp/test.mp4 (0.01MB)
[ArrowGPU] [SUCCESS] [Main] Session complete
```

#### 检查输出文件
```bash
# 检查文件是否存在
ls -lh /tmp/test.mp4

# 播放文件
ffplay /tmp/test.mp4
```

### 5. 性能测试

#### 测试不同分辨率

| 分辨率 | 帧数 | 预期带宽 | 预期时间 |
|--------|------|---------|---------|
| 512×512 | 30 | ~0.6 Gbps | ~1s |
| 1080p | 100 | ~1.8 Gbps | ~3s |
| 4K | 30 | ~7.5 Gbps | ~5s |

#### 测试不同批量大小

| batch_size | 预期效果 |
|------------|---------|
| 5 | 更低延迟，更高开销 |
| 10 | 平衡（推荐）|
| 20 | 更高吞吐量，更高延迟 |

### 6. 错误处理测试

#### 测试连接失败
```python
# 尝试连接到不存在的服务器
client = flight.FlightClient(flight.Location.for_grpc_tcp("invalid-host:9999"))
# 应该抛出异常
```

#### 测试服务器未启动
```python
# 在服务器未启动时尝试连接
# 应该抛出连接异常
```

#### 测试编码失败
```bash
# 故意使用错误的编码参数
python gpu_encoder_arrow.py --codec invalid_codec
# 应该显示错误信息
```

### 7. 零拷贝验证

#### 验证内存使用
```bash
# 监控内存使用
python gpu_encoder_arrow.py --bind 0.0.0.0:8815 &
PID=$!
watch -n 1 "ps -p $PID -o pid,vsz,rss,cmd"
```

#### 验证 CPU 使用
```bash
# 监控 CPU 使用
top -p $PID
```

预期：
- ✅ CPU 使用 < 50%
- ✅ 内存稳定
- ✅ 无内存泄漏

### 8. 并发测试

#### 测试多会话
```bash
# 启动多个客户端同时发送
python client_test.py &  # 客户端 1
python client_test.py &  # 客户端 2
python client_test.py &  # 客户端 3
```

预期：
- ✅ 所有会话正常处理
- ✅ 无数据混乱
- ✅ 正确的会话隔离

### 9. 长时间运行测试

#### 测试稳定性
```bash
# 运行 1 小时
timeout 3600 python gpu_encoder_arrow.py --bind 0.0.0.0:8815
```

预期：
- ✅ 无内存泄漏
- ✅ 无连接泄漏
- ✅ 稳定的性能

### 10. 网络测试

#### 测试高延迟网络
```bash
# 模拟高延迟网络
sudo tc qdisc add dev eth0 root netem delay 100ms
# 运行测试
# 恢复网络
sudo tc qdisc del dev eth0 root
```

#### 测试丢包
```bash
# 模拟丢包
sudo tc qdisc add dev eth0 root netem loss 5%
# 运行测试
# 恢复网络
sudo tc qdisc del dev eth0 root
```

## 测试检查清单

### 功能测试
- [ ] Arrow Flight 服务端启动成功
- [ ] Arrow Flight 客户端连接成功
- [ ] ComfyUI 节点加载成功
- [ ] 视频帧发送成功
- [ ] 视频编码成功
- [ ] 输出文件正确
- [ ] 音频合并成功
- [ ] 会话管理正常

### 性能测试
- [ ] 零拷贝工作正常
- [ ] 带宽达到预期 (9-11 Gbps)
- [ ] 延迟在预期范围 (5-10ms)
- [ ] CPU 使用合理 (< 50%)
- [ ] 内存稳定
- [ ] 批量传输有效

### 错误处理
- [ ] 连接失败处理正确
- [ ] 编码失败处理正确
- [ ] 超时处理正确
- [ ] 错误信息清晰

### 稳定性
- [ ] 并发会话正常
- [ ] 长时间运行稳定
- [ ] 无内存泄漏
- [ ] 无连接泄漏
- [ ] 资源正确释放

## 测试报告模板

### 测试日期
- 开始时间：
- 结束时间：
- 测试人员：

### 测试环境
- OS:
- Python:
- pyarrow:
- pytorch:
- GPU:
- FFmpeg:

### 测试结果

| 测试项 | 结果 | 备注 |
|--------|------|------|
| 服务端启动 | ☐ PASS / ☐ FAIL |  |
| 客户端连接 | ☐ PASS / ☐ FAIL |  |
| 视频传输 | ☐ PASS / ☐ FAIL |  |
| 视频编码 | ☐ PASS / ☐ FAIL |  |
| 性能测试 | ☐ PASS / ☐ FAIL |  |
| 稳定性测试 | ☐ PASS / ☐ FAIL |  |

### 发现的问题
1.
2.
3.

### 建议
1.
2.
3.

## 问题排查

### 常见问题

**Q: 服务器无法启动**
```bash
# 检查依赖
pip install pyarrow tqdm

# 检查端口占用
netstat -an | grep 8815

# 检查 FFmpeg
ffmpeg -version
```

**Q: 客户端无法连接**
```bash
# 检查防火墙
sudo ufw status

# 检查网络连接
ping <server-ip>
telnet <server-ip> 8815
```

**Q: 编码失败**
```bash
# 检查 GPU
nvidia-smi

# 检查 CUDA
python -c "import torch; print(torch.cuda.is_available())"

# 检查 FFmpeg 编码器
ffmpeg -codecs | grep nvenc
```

**Q: 性能不达预期**
```bash
# 调整批量大小
# 增加网络缓冲区
# 检查网络带宽
```

## 结论

测试通过后，可以安全地将生产环境迁移到 Arrow Flight。
