"""title: 个人所得税（5 段累进）
category: branch
difficulty: medium
tips: 5 段阶梯税率，分支覆盖关键；建议 structured + 100/100/90/100 阈值
"""


def calculate_tax(income: float) -> float:
    """按 5 段累进税率计算个人所得税。
    0 - 5000:        0%
    5000 - 8000:     3%
    8000 - 17000:    10%
    17000 - 30000:   20%
    >= 30000:        25%
    """
    if income < 0:
        raise ValueError("收入不能为负数")
    if income <= 5000:
        return 0.0
    if income <= 8000:
        return (income - 5000) * 0.03
    if income <= 17000:
        return 3000 * 0.03 + (income - 8000) * 0.10
    if income <= 30000:
        return 3000 * 0.03 + 9000 * 0.10 + (income - 17000) * 0.20
    return 3000 * 0.03 + 9000 * 0.10 + 13000 * 0.20 + (income - 30000) * 0.25
