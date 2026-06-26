"""title: BMI 体型分类
category: branch
difficulty: easy
tips: 4 区间 + 入参校验；BMI = weight / height^2
"""


def bmi_category(weight_kg: float, height_m: float) -> str:
    """根据体重（kg）和身高（m）返回 BMI 分类。
    < 18.5     偏瘦
    18.5-24    正常
    24-28      超重
    >= 28      肥胖
    """
    if weight_kg <= 0 or height_m <= 0:
        raise ValueError("体重和身高必须为正数")
    bmi = weight_kg / (height_m ** 2)
    if bmi < 18.5:
        return "偏瘦"
    if bmi < 24:
        return "正常"
    if bmi < 28:
        return "超重"
    return "肥胖"
