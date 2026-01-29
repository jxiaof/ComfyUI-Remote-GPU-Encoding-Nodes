# 快速开始指南

## 选择协议版本

### Arrow Flight (推荐)

**特点：**
- 🚀 零拷贝传输
- ⚡ 9-11 Gbps 带宽
- 📊 tqdm 专业进度条
- 📝 结构化日志

**快速开始：**
```bash
# 1. 安装依赖
pip install pyarrow tqdm

# 2. 启动服务器
python gpu_encoder_arrow.py --bind 0.0.0.0:8815

# 3. 切换到 Arrow Flight
# 修改 __init__.py:
from .nodes_arrow import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

# 4. 启动 ComfyUI
python main.py
```

详见：[ARROW_MIGRATION.md](ARROW_MIGRATION.md)

---

### ZMQ 优化版

**特点：**
- 🚀 零拷贝优化
- ⚡ 9-11 Gbps 带宽
- 📊 tqdm 专业进度条
- 🔄 流式和批量传输

**快速开始：**
```bash
# 1. 安装依赖
pip install pyzmq tqdm

# 2. 启动服务器
python gpu_encoder.py --bind tcp://0.0.0.0:5555

# 3. 切换到 ZMQ 优化版
# 修改 __init__.py:
from .nodes_zmq_optimized import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

# 4. 启动 ComfyUI
python main.py
```

详见：[ZMQ_OPTIMIZATION.md](ZMQ_OPTIMIZATION.md)

---

### ZMQ 原版

**特点：**
- ⚡ 7-9 Gbps 带宽
- 📊 自定义进度条
- 🔄 批量传输

**快速开始：**
```bash
# 保持默认配置
# 使用原版 ZMQ 节点
```

---

## 性能对比

| 协议 | 带宽 | 延迟 | 零拷贝 | 推荐度 |
|------|------|------|--------|--------|
| **Arrow Flight** | **9-11 Gbps** | **5-10ms** | ✅ | ⭐⭐⭐⭐⭐ |
| **ZMQ 优化版** | **9-11 Gbps** | **5-10ms** | ✅ | ⭐⭐⭐⭐⭐ |
| ZMQ 原版 | 7-9 Gbps | 5-15ms | 部分 | ⭐⭐⭐ |

## 推荐方案

### 追求极致性能 → Arrow Flight

选择 Arrow Flight，享受：
- 最高的传输性能
- 最现代的架构
- 最完善的特性

**使用场景：**
- 大规模视频编码
- 对性能要求极高
- 长期项目

### 兼容性和稳定性 → ZMQ 优化版

选择 ZMQ 优化版，享受：
- 与原版完全兼容
- 30% 性能提升
- 流式和批量传输

**使用场景：**
- 现有项目升级
- 需要快速迁移
- 对稳定性要求高

---

## 切换步骤

### 切换到 Arrow Flight

```bash
# 1. 安装依赖
pip install pyarrow tqdm

# 2. 启动新服务器
python gpu_encoder_arrow.py --bind 0.0.0.0:8815

# 3. 修改 __init__.py
sed -i 's/from .nodes import/from .nodes_arrow import/' __init__.py

# 4. 重启 ComfyUI
python main.py
```

### 切换到 ZMQ 优化版

```bash
# 1. 安装依赖
pip install pyzmq tqdm

# 2. 保持服务器不变
# gpu_encoder.py 保持不变

# 3. 修改 __init__.py
sed -i 's/from .nodes import/from .nodes_zmq_optimized import/' __init__.py

# 4. 重启 ComfyUI
python main.py
```

---

## 测试验证

### 测试 Arrow Flight

1. 启动服务器
2. 运行测试工作流
3. 检查进度条是否正常
4. 验证输出文件

### 测试 ZMQ 优化版

1. 启动服务器
2. 运行测试工作流
3. 检查 tqdm 进度条
4. 验证传输模式选择

---

## 回退方案

### 回退到 ZMQ 原版

```bash
# 修改 __init__.py
sed -i 's/from .nodes_zmq_optimized import/from .nodes import/' __init__.py
```

### 回退到 ZMQ

```bash
# 修改 __init__.py
sed -i 's/from .nodes_arrow import/from .nodes import/' __init__.py
```

---

## 获取帮助

- [ARROW_MIGRATION.md](ARROW_MIGRATION.md) - Arrow Flight 详细指南
- [ZMQ_OPTIMIZATION.md](ZMQ_OPTIMIZATION.md) - ZMQ 优化详细指南
- [TESTING.md](TESTING.md) - 测试清单
- [README.md](README.md) - 项目文档

---

**开始升级，享受更快的视频编码体验！** 🚀
