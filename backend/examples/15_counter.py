"""title: 计数器
category: oop
difficulty: easy
tips: 状态 + 多键操作；考察 increment/decrement/most_common/reset
"""


class Counter:
    """简单计数器：按 key 统计次数，支持增减、查询、排序。"""

    def __init__(self):
        self._counts = {}

    def increment(self, key: str, by: int = 1) -> int:
        if not isinstance(key, str):
            raise TypeError("key 必须是字符串")
        if by <= 0:
            raise ValueError("by 必须是正整数")
        self._counts[key] = self._counts.get(key, 0) + by
        return self._counts[key]

    def decrement(self, key: str, by: int = 1) -> int:
        if key not in self._counts:
            raise KeyError(key)
        if by <= 0:
            raise ValueError("by 必须是正整数")
        self._counts[key] -= by
        if self._counts[key] <= 0:
            del self._counts[key]
            return 0
        return self._counts[key]

    def get(self, key: str) -> int:
        return self._counts.get(key, 0)

    def total(self) -> int:
        return sum(self._counts.values())

    def most_common(self, top_n: int = 1) -> list:
        if top_n <= 0:
            raise ValueError("top_n 必须是正整数")
        items = sorted(self._counts.items(), key=lambda kv: (-kv[1], kv[0]))
        return items[:top_n]

    def reset(self) -> None:
        self._counts.clear()
