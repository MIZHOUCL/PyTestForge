"""title: 加法实现写成了减法（典型 source_bug）
category: buggy
difficulty: easy
tips: 期望：诊断器判 source_bug，置信度 ≥ 0.9，建议改 return a + b
"""


def add(a: int, b: int) -> int:
    """两数相加。"""
    return a - b  # ← bug：减法
