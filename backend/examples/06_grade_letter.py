"""title: 成绩等级判定
category: branch
difficulty: easy
tips: 5 档阶梯分类，分支覆盖典型示例；考察 90/75/60 边界
"""


def grade_letter(score: float) -> str:
    """根据分数返回等级 A/B/C/D/F。分数范围 0-100，超出则抛 ValueError。"""
    if not isinstance(score, (int, float)):
        raise TypeError("score 必须是数字")
    if score < 0 or score > 100:
        raise ValueError("score 必须在 0-100 之间")
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 40:
        return "D"
    return "F"
