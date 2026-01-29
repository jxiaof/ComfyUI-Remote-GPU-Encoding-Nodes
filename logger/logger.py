"""
Remote GPU Encoding - Logger
专业日志系统

特性:
- 品牌化输出
- 彩色终端
- 进度条支持
"""

import sys
import time
import logging
from datetime import datetime
from typing import Optional, Any
from enum import Enum
from dataclasses import dataclass
import threading


# ============================================================================
# 品牌标识
# ============================================================================

LOGO_PREFIX = "[RemoteGPU]"
LOGO_BANNER = """
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║     ██████╗ ███████╗███╗   ███╗ ██████╗ ████████╗███████╗     ║
║     ██╔══██╗██╔════╝████╗ ████║██╔═══██╗╚══██╔══╝██╔════╝     ║
║     ██████╔╝█████╗  ██╔████╔██║██║   ██║   ██║   █████╗       ║
║     ██╔══██╗██╔══╝  ██║╚██╔╝██║██║   ██║   ██║   ██╔══╝       ║
║     ██║  ██║███████╗██║ ╚═╝ ██║╚██████╔╝   ██║   ███████╗     ║
║     ╚═╝  ╚═╝╚══════╝╚═╝     ╚═╝ ╚═════╝    ╚═╝   ╚══════╝     ║
║                                                               ║
║              ██████╗ ██████╗ ██╗   ██╗                        ║
║             ██╔════╝ ██╔══██╗██║   ██║                        ║
║             ██║  ███╗██████╔╝██║   ██║                        ║
║             ██║   ██║██╔═══╝ ██║   ██║                        ║
║             ╚██████╔╝██║     ╚██████╔╝                        ║
║              ╚═════╝ ╚═╝      ╚═════╝                         ║
║                                                               ║
║         ENCODING      High-Speed Video Encoding               ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
"""

LOGO_COMPACT = "🎬 Remote GPU Encoding"


# ============================================================================
# 颜色定义
# ============================================================================

class Color:
    """ANSI 颜色码"""
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    
    # 前景色
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    
    # 亮色
    BRIGHT_RED = '\033[91m'
    BRIGHT_GREEN = '\033[92m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_BLUE = '\033[94m'
    BRIGHT_MAGENTA = '\033[95m'
    BRIGHT_CYAN = '\033[96m'


class LogLevel(Enum):
    """日志级别"""
    DEBUG = 10
    INFO = 20
    SUCCESS = 25
    WARNING = 30
    ERROR = 40


# ============================================================================
# 日志配置
# ============================================================================

@dataclass
class LogConfig:
    """日志配置"""
    level: LogLevel = LogLevel.INFO
    show_timestamp: bool = True
    show_level: bool = True
    show_tag: bool = True
    tag_width: int = 12
    use_color: bool = True
    file_path: Optional[str] = None


# ============================================================================
# 日志类
# ============================================================================

class Logger:
    """
    Remote GPU Encoding 日志类
    
    使用:
        log = Logger("Encoder")
        log.info("Starting encoding...")
        log.success("Done!")
    """
    
    _config = LogConfig()
    _file_handler: Optional[logging.FileHandler] = None
    _lock = threading.Lock()
    _progress_active = False
    
    LEVEL_COLORS = {
        LogLevel.DEBUG: Color.DIM,
        LogLevel.INFO: Color.BRIGHT_CYAN,
        LogLevel.SUCCESS: Color.BRIGHT_GREEN,
        LogLevel.WARNING: Color.BRIGHT_YELLOW,
        LogLevel.ERROR: Color.BRIGHT_RED,
    }
    
    LEVEL_LABELS = {
        LogLevel.DEBUG: 'DEBUG',
        LogLevel.INFO: 'INFO ',
        LogLevel.SUCCESS: ' OK  ',
        LogLevel.WARNING: 'WARN ',
        LogLevel.ERROR: 'ERROR',
    }
    
    def __init__(self, tag: str = "Main"):
        self.tag = tag
    
    @classmethod
    def configure(cls, config: LogConfig):
        """配置日志"""
        cls._config = config
        if config.file_path:
            cls._file_handler = logging.FileHandler(config.file_path, encoding='utf-8')
    
    def _timestamp(self) -> str:
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]
    
    def _colorize(self, text: str, color: str) -> str:
        if not self._config.use_color:
            return text
        return f"{color}{text}{Color.RESET}"
    
    def _format(self, level: LogLevel, message: str) -> str:
        parts = []
        
        # Logo 前缀
        parts.append(self._colorize(LOGO_PREFIX, Color.BRIGHT_MAGENTA))
        
        # 时间戳
        if self._config.show_timestamp:
            parts.append(self._colorize(self._timestamp(), Color.DIM))
        
        # 级别
        if self._config.show_level:
            label = self.LEVEL_LABELS[level]
            color = self.LEVEL_COLORS[level]
            parts.append(self._colorize(f"[{label}]", color))
        
        # 标签
        if self._config.show_tag:
            tag = f"[{self.tag:<{self._config.tag_width}}]"
            parts.append(self._colorize(tag, Color.BLUE))
        
        # 消息
        parts.append(message)
        
        return " ".join(parts)
    
    def _log(self, level: LogLevel, message: str):
        if level.value < self._config.level.value:
            return
        
        formatted = self._format(level, message)
        
        with self._lock:
            if self._progress_active:
                sys.stdout.write('\r' + ' ' * 120 + '\r')
            
            print(formatted)
            
            if self._file_handler:
                import re
                plain = re.sub(r'\033\[[0-9;]*m', '', formatted)
                self._file_handler.stream.write(plain + '\n')
                self._file_handler.flush()
    
    # 日志方法
    def debug(self, msg: str):
        self._log(LogLevel.DEBUG, msg)
    
    def info(self, msg: str):
        self._log(LogLevel.INFO, msg)
    
    def success(self, msg: str):
        self._log(LogLevel.SUCCESS, msg)
    
    def warning(self, msg: str):
        self._log(LogLevel.WARNING, msg)
    
    def error(self, msg: str):
        self._log(LogLevel.ERROR, msg)
    
    # 别名
    ok = success
    warn = warning
    
    # ========================================================================
    # 特殊输出
    # ========================================================================
    
    def header(self, title: str, width: int = 65):
        """输出标题"""
        with self._lock:
            line = "─" * width
            print(f"\n{self._colorize(LOGO_PREFIX, Color.BRIGHT_MAGENTA)} "
                  f"{self._colorize(line, Color.CYAN)}")
            print(f"{self._colorize(LOGO_PREFIX, Color.BRIGHT_MAGENTA)} "
                  f"  {self._colorize(title, Color.BOLD)}")
            print(f"{self._colorize(LOGO_PREFIX, Color.BRIGHT_MAGENTA)} "
                  f"{self._colorize(line, Color.CYAN)}")
    
    def separator(self, width: int = 65):
        """输出分隔线"""
        with self._lock:
            print(f"{self._colorize(LOGO_PREFIX, Color.BRIGHT_MAGENTA)} "
                  f"{self._colorize('─' * width, Color.DIM)}")
    
    def kv(self, key: str, value: Any, key_width: int = 14):
        """输出键值对"""
        with self._lock:
            prefix = self._colorize(LOGO_PREFIX, Color.BRIGHT_MAGENTA)
            k = self._colorize(f"  {key}:", Color.DIM)
            print(f"{prefix} {k:<{key_width + 14}} {value}")
    
    def progress(self, current: int, total: int, suffix: str = "", width: int = 30):
        """显示进度条"""
        if total <= 0:
            return
        
        pct = current / total
        filled = int(width * pct)
        bar = '█' * filled + '░' * (width - filled)
        
        line = (
            f"\r{self._colorize(LOGO_PREFIX, Color.BRIGHT_MAGENTA)} "
            f"{self._colorize(self._timestamp(), Color.DIM)} "
            f"{self._colorize('[SEND ]', Color.BRIGHT_MAGENTA)} "
            f"[{bar}] {pct*100:5.1f}% ({current}/{total})"
        )
        
        if suffix:
            line += f" | {suffix}"
        
        with self._lock:
            Logger._progress_active = True
            sys.stdout.write(line + "    ")
            sys.stdout.flush()
            
            if current >= total:
                print()
                Logger._progress_active = False
    
    def banner(self, compact: bool = True):
        """输出品牌横幅"""
        with self._lock:
            if compact:
                print(f"\n{self._colorize(LOGO_COMPACT, Color.BRIGHT_MAGENTA)}\n")
            else:
                print(self._colorize(LOGO_BANNER, Color.BRIGHT_CYAN))


# ============================================================================
# 便捷函数
# ============================================================================

def get_logger(tag: str = "Main") -> Logger:
    """获取日志实例"""
    return Logger(tag)


def configure_logging(
    level: LogLevel = LogLevel.INFO,
    use_color: bool = True,
    file_path: Optional[str] = None
):
    """配置日志系统"""
    Logger.configure(LogConfig(
        level=level,
        use_color=use_color,
        file_path=file_path
    ))