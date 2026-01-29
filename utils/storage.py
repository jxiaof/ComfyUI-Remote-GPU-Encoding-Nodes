from typing import Dict, Optional
from ..logger import Logger


class SessionStorage:
    """会话数据存储"""

    _data: Dict[str, Dict] = {}

    @classmethod
    def get(cls, key: str) -> Optional[Dict]:
        return cls._data.get(key)

    @classmethod
    def set(cls, key: str, data: Dict):
        cls._data[key] = data

    @classmethod
    def delete(cls, key: str):
        if key in cls._data:
            del cls._data[key]

    @classmethod
    def exists(cls, key: str) -> bool:
        return key in cls._data

    @classmethod
    def clear(cls):
        cls._data.clear()
