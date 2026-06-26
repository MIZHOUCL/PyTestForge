"""title: LRU 缓存
category: oop
difficulty: hard
tips: 容量淘汰 + 访问顺序更新；考察 get/put + 容量边界 + 重复 key
"""

from collections import OrderedDict


class LRUCache:
    """基于 OrderedDict 的 LRU 缓存：put 放入或更新；get 返回值并把 key 移到最近使用。"""

    def __init__(self, capacity: int):
        if not isinstance(capacity, int):
            raise TypeError("capacity 必须是整数")
        if capacity <= 0:
            raise ValueError("capacity 必须是正整数")
        self.capacity = capacity
        self._data = OrderedDict()

    def get(self, key):
        if key not in self._data:
            return None
        self._data.move_to_end(key)
        return self._data[key]

    def put(self, key, value) -> None:
        if key in self._data:
            self._data.move_to_end(key)
            self._data[key] = value
            return
        self._data[key] = value
        if len(self._data) > self.capacity:
            self._data.popitem(last=False)

    def __contains__(self, key) -> bool:
        return key in self._data

    def __len__(self) -> int:
        return len(self._data)

    def keys(self) -> list:
        return list(self._data.keys())
