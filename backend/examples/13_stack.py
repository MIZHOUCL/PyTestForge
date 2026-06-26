"""title: 栈（Stack）
category: oop
difficulty: easy
tips: 经典数据结构；考察 push/pop/peek/is_empty/size + 空栈异常
"""


class Stack:
    """先进后出栈，基于 list 实现。"""

    def __init__(self):
        self._items = []

    def push(self, item) -> None:
        self._items.append(item)

    def pop(self):
        if not self._items:
            raise IndexError("pop from empty stack")
        return self._items.pop()

    def peek(self):
        if not self._items:
            raise IndexError("peek from empty stack")
        return self._items[-1]

    def is_empty(self) -> bool:
        return len(self._items) == 0

    def size(self) -> int:
        return len(self._items)

    def clear(self) -> None:
        self._items.clear()
