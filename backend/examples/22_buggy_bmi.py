"""title: BMI 区间错位（24 应归正常但被判超重）
category: buggy
difficulty: medium
tips: 区间应为 [18.5,24)=正常 [24,28)=超重，但这里 24 整数边界被错分到超重
"""


def bmi_category(weight_kg: float, height_m: float) -> str:
    """BMI 分类：偏瘦 / 正常 / 超重 / 肥胖。"""
    if weight_kg <= 0 or height_m <= 0:
        raise ValueError("体重和身高必须为正数")
    bmi = weight_kg / (height_m ** 2)
    if bmi < 18.5:
        return "偏瘦"
    if bmi <= 24:  # ← bug：应为 bmi < 24
        return "正常"
    if bmi < 28:
        return "超重"
    return "肥胖"
