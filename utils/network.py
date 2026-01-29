import socket
from typing import Tuple
from ..logger import Logger


class NetworkUtils:
    """网络工具类"""

    _log = Logger("Network")

    @classmethod
    def parse_endpoint(cls, endpoint: str) -> Tuple[str, str, int]:
        """
        解析端点地址

        Returns:
            (protocol, host, port)
        """
        try:
            if "://" in endpoint:
                protocol, rest = endpoint.split("://", 1)
            else:
                protocol, rest = "tcp", endpoint

            if ":" in rest:
                host, port_str = rest.rsplit(":", 1)
                port = int(port_str)
            else:
                host, port = rest, 5555

            return protocol, host, port
        except Exception as e:
            cls._log.error(f"Invalid endpoint format: {endpoint}")
            raise ValueError(f"Invalid endpoint: {endpoint}")

    @classmethod
    def check_host_reachable(
        cls, host: str, port: int, timeout: float = 2.0
    ) -> Tuple[bool, str]:
        """
        检查主机是否可达

        Returns:
            (is_reachable, message)
        """
        if host in ("0.0.0.0", "127.0.0.1", "localhost", "*"):
            return True, "Local bind address"

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()

            if result == 0:
                return True, f"Host {host}:{port} is reachable"
            else:
                return cls._ping_host(host, timeout)
        except socket.gaierror:
            return False, f"Cannot resolve hostname: {host}"
        except socket.timeout:
            return False, f"Connection timeout: {host}:{port}"
        except Exception as e:
            return False, f"Network error: {e}"

    @classmethod
    def _ping_host(cls, host: str, timeout: float) -> Tuple[bool, str]:
        """尝试 ping 主机"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            for port in [22, 80, 443]:
                try:
                    result = sock.connect_ex((host, port))
                    if result == 0:
                        sock.close()
                        return True, f"Host {host} is reachable"
                except:
                    pass
            sock.close()
            return True, f"Host {host} may be reachable (no open ports found)"
        except:
            return False, f"Cannot reach host: {host}"

    @classmethod
    def validate_endpoint(
        cls, endpoint: str, check_network: bool = True
    ) -> Tuple[bool, str]:
        """
        验证端点地址

        Args:
            endpoint: 端点地址
            check_network: 是否检查网络连通性

        Returns:
            (is_valid, message)
        """
        try:
            protocol, host, port = cls.parse_endpoint(endpoint)

            if protocol not in ("tcp", "ipc"):
                return False, f"Unsupported protocol: {protocol}"

            if port < 1 or port > 65535:
                return False, f"Invalid port: {port}"

            if check_network and protocol == "tcp":
                return cls.check_host_reachable(host, port)

            return True, "Endpoint format valid"
        except ValueError as e:
            return False, str(e)
