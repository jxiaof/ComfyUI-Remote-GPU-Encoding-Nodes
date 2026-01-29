"""
ComfyUI Remote GPU Encoding
远程 GPU 视频编码节点包

功能:
- 高速视频帧传输
- 远程 NVENC 硬件编码
- 音频支持
- 帧统计分析
"""

import sys

# ============================================================================
# 节点版本选择
# ============================================================================
# 选择一个版本导入，注释掉其他版本
# ============================================================================

# 选项 1: Arrow Flight v3.0 (推荐）- 零拷贝传输，最高性能
from .nodes_arrow import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

# 选项 2: ZMQ v2.1 优化版 - 零拷贝优化，性能提升 30%
# from .nodes_zmq_optimized import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

# 选项 3: ZMQ v2.0 原版 - 基础传输，兼容性好
# from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

# ============================================================================
# 版本信息
# ============================================================================

__version__ = "3.0.0"
__author__ = "jxiaof"

WEB_DIRECTORY = None

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]


def _print_startup():
    """启动信息"""
    from .logger import Logger, Color, LOGO_PREFIX, LOGO_COMPACT

    log = Logger("Init")

    # 检测导入的版本
    if "nodes_arrow" in sys.modules:
        protocol_name = "Arrow Flight v3.0"
        protocol_features = [
            "零拷贝传输",
            "9-11 Gbps 带宽",
            "5-10ms 延迟",
            "tqdm 进度条",
        ]
    elif "nodes_zmq_optimized" in sys.modules:
        protocol_name = "ZMQ v2.1 Optimized"
        protocol_features = [
            "零拷贝优化",
            "9-11 Gbps 带宽",
            "5-10ms 延迟",
            "tqdm 进度条",
            "流式和批量传输",
        ]
    else:
        protocol_name = "ZMQ v2.0"
        protocol_features = [
            "基础传输",
            "7-9 Gbps 带宽",
            "5-15ms 延迟",
            "批量传输",
        ]

    # 紧凑横幅
    print(f"\n{Color.BRIGHT_MAGENTA}{'═' * 50}{Color.RESET}")
    print(f"  {Color.BOLD}{LOGO_COMPACT}{Color.RESET}")
    print(f"  {Color.DIM}Version {__version__} | {protocol_name}{Color.RESET}")
    print(f"{Color.BRIGHT_MAGENTA}{'═' * 50}{Color.RESET}")

    # 协议特性
    print(f"\n{Color.DIM}Protocol Features:{Color.RESET}")
    for feature in protocol_features:
        print(f"  {Color.GREEN}✓{Color.RESET} {feature}")

    # 节点列表
    print(f"\n{Color.DIM}Loaded nodes ({protocol_name}):{Color.RESET}")
    for key, name in NODE_DISPLAY_NAME_MAPPINGS.items():
        print(f"  {Color.GREEN}✓{Color.RESET} {name}")

    # 提示
    if "nodes_arrow" in sys.modules:
        print(
            f"\n{Color.DIM}💡 Tip: 当前使用 Arrow Flight，享受零拷贝传输！{Color.RESET}"
        )
    elif "nodes_zmq_optimized" in sys.modules:
        print(f"\n{Color.DIM}💡 Tip: 当前使用 ZMQ 优化版，性能提升 30%！{Color.RESET}")
    else:
        print(
            f"\n{Color.DIM}💡 Tip: 切换到 Arrow Flight 或 ZMQ 优化版可获得更高性能！{Color.RESET}"
        )

    print()


_print_startup()
