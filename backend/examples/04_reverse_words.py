"""title: 字符串反转单词序
category: basic
difficulty: easy
tips: 字符串处理 + 空白边界；考察空串/单词/多空白几种输入
"""


def reverse_words(text: str) -> str:
    """将句子按空白拆分后逆序拼接：'hello  world py' -> 'py world hello'。"""
    if not isinstance(text, str):
        raise TypeError("text 必须是字符串")
    words = text.split()
    return " ".join(reversed(words))
