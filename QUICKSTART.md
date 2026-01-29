# Arrow Flight 快速开始

## 🚀 5 分钟快速开始

### 1. 安装依赖

```bash
pip install pyarrow tqdm
```

### 2. 启动 GPU 服务器

```bash
# 在 GPU 机器上
python gpu_encoder_arrow.py --bind 0.0.0.0:8815
```

### 3. 切换到 Arrow Flight

```python
# 修改 __init__.py
# 从：
from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

# 改为：
from .nodes_arrow import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
```

### 4. 重启 ComfyUI

```bash
python main.py
```

### 5. 在 ComfyUI 中使用

添加 "Remote GPU Encoder (Arrow Flight)" 节点，配置：
- `encoder_address`: `0.0.0.0:8815`
- `output_path`: `/tmp/output.mp4`
- `fps`: `30`

## 📊 性能对比

| 协议 | 带宽 | 延迟 | 零拷贝 |
|------|------|------|--------|
| ZMQ | 7-9 Gbps | 5-15ms | 部分 |
| Arrow Flight | **9-11 Gbps** | **5-10ms** | **完全** |

## 📝 详细文档

- `ARROW_MIGRATION.md` - 完整迁移指南
- `ARROW_SUMMARY.md` - 项目总结
- `README.md` - 项目文档

## 🎯 开始使用 Arrow Flight，享受更快的视频编码！
