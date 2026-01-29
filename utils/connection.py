import time
import atexit
from typing import Dict, Any, Optional
from ..logger import Logger, LOGO_PREFIX

try:
    import zmq

    HAS_ZMQ = True
except ImportError:
    HAS_ZMQ = False


class ConnectionManager:
    """
    连接池管理器

    特性:
    - 连接复用
    - 自动重连
    - 优雅关闭
    - 状态监控
    """

    _context: Optional["zmq.Context"] = None
    _sockets: Dict[str, Dict[str, Any]] = {}
    _initialized = False
    _log = Logger("Connection")

    @classmethod
    def _ensure_context(cls):
        """确保 Context 存在"""
        if cls._context is None:
            if not HAS_ZMQ:
                raise RuntimeError(
                    "pyzmq is not installed. Please run: pip install pyzmq"
                )
            cls._context = zmq.Context()

            if not cls._initialized:
                atexit.register(cls.shutdown)
                cls._initialized = True
                cls._log.debug("Context initialized")

    @classmethod
    def get_socket(
        cls,
        endpoint: str,
        socket_type: Optional[int] = None,
        check_network: bool = True,
    ) -> "zmq.Socket":
        """
        获取或创建 Socket

        Args:
            endpoint: 端点地址
            socket_type: Socket 类型 (默认 PUB)
            check_network: 是否检查网络

        Returns:
            zmq.Socket 实例
        """
        if socket_type is None:
            socket_type = zmq.PUB

        cls._ensure_context()

        if check_network:
            from .network import NetworkUtils

            is_valid, msg = NetworkUtils.validate_endpoint(endpoint, check_network=True)
            if not is_valid:
                cls._log.warning(f"Network check: {msg}")

        if endpoint in cls._sockets:
            info = cls._sockets[endpoint]
            sock = info["socket"]

            try:
                sock.getsockopt(zmq.EVENTS)
                info["access_count"] += 1
                cls._log.debug(f"Reusing connection: {endpoint}")
                return sock
            except zmq.ZMQError:
                cls._log.warning(f"Connection invalid, recreating: {endpoint}")
                cls.release(endpoint)

        cls._log.info(f"Creating connection: {endpoint}")

        sock = cls._context.socket(socket_type)

        sock.setsockopt(zmq.LINGER, 0)
        sock.setsockopt(zmq.SNDHWM, 500)
        sock.setsockopt(zmq.SNDBUF, 256 * 1024 * 1024)
        sock.setsockopt(zmq.TCP_KEEPALIVE, 1)
        sock.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 60)

        try:
            sock.bind(endpoint)
        except zmq.ZMQError as e:
            if "Address already in use" in str(e):
                cls._log.warning(f"Port busy, forcing release: {endpoint}")
                cls._force_release_port(endpoint)
                time.sleep(0.5)
                sock = cls._context.socket(socket_type)
                sock.setsockopt(zmq.LINGER, 0)
                sock.setsockopt(zmq.SNDHWM, 500)
                sock.setsockopt(zmq.SNDBUF, 256 * 1024 * 1024)
                sock.bind(endpoint)
            else:
                raise

        cls._sockets[endpoint] = {
            "socket": sock,
            "type": socket_type,
            "created_at": time.time(),
            "access_count": 1,
            "messages_sent": 0,
            "bytes_sent": 0,
        }

        time.sleep(0.3)

        cls._log.success(f"Connection ready: {endpoint}")
        return sock

    @classmethod
    def _force_release_port(cls, endpoint: str):
        """强制释放端口"""
        if endpoint in cls._sockets:
            cls.release(endpoint)

        if cls._context:
            try:
                cls._context.term()
            except:
                pass
        cls._context = zmq.Context()

    @classmethod
    def release(cls, endpoint: str):
        """释放指定端点"""
        if endpoint not in cls._sockets:
            cls._log.warning(f"Connection not found: {endpoint}")
            return

        info = cls._sockets[endpoint]
        try:
            info["socket"].close(linger=0)
            cls._log.success(
                f"Released: {endpoint} "
                f"(messages: {info['messages_sent']}, "
                f"data: {info['bytes_sent'] / 1024 / 1024:.1f}MB)"
            )
        except Exception as e:
            cls._log.warning(f"Release error: {e}")

        del cls._sockets[endpoint]

    @classmethod
    def release_all(cls):
        """释放所有连接"""
        endpoints = list(cls._sockets.keys())
        for ep in endpoints:
            cls.release(ep)
        cls._log.success(f"Released {len(endpoints)} connections")

    @classmethod
    def shutdown(cls):
        """关闭管理器"""
        for ep, info in list(cls._sockets.items()):
            try:
                info["socket"].close(linger=0)
            except:
                pass
        cls._sockets.clear()

        if cls._context:
            try:
                cls._context.term()
            except:
                pass
            cls._context = None

    @classmethod
    def update_stats(cls, endpoint: str, bytes_sent: int):
        """更新统计"""
        if endpoint in cls._sockets:
            info = cls._sockets[endpoint]
            info["messages_sent"] += 1
            info["bytes_sent"] += bytes_sent

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        """获取状态"""
        status = {"active_connections": len(cls._sockets), "connections": {}}

        for ep, info in cls._sockets.items():
            age = time.time() - info["created_at"]
            status["connections"][ep] = {
                "messages": info["messages_sent"],
                "data_mb": round(info["bytes_sent"] / 1024 / 1024, 2),
                "uptime_seconds": round(age, 1),
                "access_count": info["access_count"],
            }

        return status

    @classmethod
    def get_status_string(cls) -> str:
        """获取状态字符串"""
        if not cls._sockets:
            return "No active connections"

        lines = [f"{LOGO_PREFIX} Active Connections:"]
        for ep, info in cls._sockets.items():
            age = time.time() - info["created_at"]
            lines.append(
                f"  • {ep}: "
                f"{info['messages_sent']} msgs, "
                f"{info['bytes_sent'] / 1024 / 1024:.1f} MB, "
                f"uptime: {age:.0f}s"
            )
        return "\n".join(lines)
