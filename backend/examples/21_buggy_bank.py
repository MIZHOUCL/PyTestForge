"""title: 银行取款未检查余额
category: buggy
difficulty: medium
tips: withdraw 应在余额不足时抛 ValueError，但这里直接扣到负数。诊断应指出业务约束缺失
"""


class BankAccount:
    """简单银行账户。"""

    def __init__(self, owner: str, balance: float = 0.0):
        self.owner = owner
        self._balance = float(balance)

    @property
    def balance(self) -> float:
        return self._balance

    def deposit(self, amount: float) -> float:
        if amount <= 0:
            raise ValueError("存款金额必须为正数")
        self._balance += amount
        return self._balance

    def withdraw(self, amount: float) -> float:
        """取款。余额不足时应抛 ValueError。"""
        if amount <= 0:
            raise ValueError("取款金额必须为正数")
        # ← bug：缺少 if amount > self._balance: raise ValueError(...)
        self._balance -= amount
        return self._balance
