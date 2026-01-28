"""
ComfyUI Remote GPU Encoding
远程 GPU 视频编码节点包

功能:
- 高速视频帧传输
- 远程 NVENC 硬件编码
- 音频支持
- 帧统计分析
"""

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__version__ = "2.0.0"
__author__ = "jxiaof"

WEB_DIRECTORY = None

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']


def _print_startup():
    """启动信息"""
    from .logger import Logger, Color, LOGO_COMPACT
    
    log = Logger("Init")
    
    # 紧凑横幅
    print(f"\n{Color.BRIGHT_MAGENTA}{'═' * 50}{Color.RESET}")
    print(f"  {Color.BOLD}{LOGO_COMPACT}{Color.RESET}")
    print(f"  {Color.DIM}Version {__version__} | High-Speed Video Encoding{Color.RESET}")
    print(f"{Color.BRIGHT_MAGENTA}{'═' * 50}{Color.RESET}")
    
    # 节点列表
    print(f"\n{Color.DIM}Loaded nodes:{Color.RESET}")
    for key, name in NODE_DISPLAY_NAME_MAPPINGS.items():
        print(f"  {Color.GREEN}✓{Color.RESET} {name}")
    print()


_print_startup()