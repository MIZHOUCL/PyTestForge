"""title: 成绩边界用了严格大于（B 段错位）
category: buggy
difficulty: easy
tips: docstring 写 90 分以上为 A，但代码用 > 90，导致 90 分被判为 B。诊断应指出边界 off-by-one
"""


def grade_letter(score: float) -> str:
    """根据分数返回等级，90+ A / 75+ B / 60+ C / 40+ D / 其他 F。"""
    if score < 0 or score > 100:
        raise ValueError("score 必须在 0-100 之间")
    if score > 90:  # ← bug：应为 >= 90
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 40:
        return "D"
    return "F"
