"""title: 银行账户
category: oop
difficulty: medium
tips: 多方法 + 状态保持 + 多种异常；考察 deposit/withdraw/transfer 互相影响
"""


class BankAccount:
    """简单银行账户：存取款 + 转账 + 余额查询。"""

    def __init__(self, owner: str, balance: float = 0.0):
        if not isinstance(owner, str) or not owner:
            raise ValueError("owner 不能为空")
        if balance < 0:
            raise ValueError("初始余额不能为负数")
        self.owner = owner
        self._balance = float(balance)
        self._tx_log = []

    @property
    def balance(self) -> float:
        return self._balance

    def deposit(self, amount: float) -> float:
        if amount <= 0:
            raise ValueError("存款金额必须为正数")
        self._balance += amount
        self._tx_log.append(("deposit", amount))
        return self._balance

    def withdraw(self, amount: float) -> float:
        if amount <= 0:
            raise ValueError("取款金额必须为正数")
        if amount > self._balance:
            raise ValueError("余额不足")
        self._balance -= amount
        self._tx_log.append(("withdraw", amount))
        return self._balance

    def transfer(self, other: "BankAccount", amount: float) -> None:
        if not isinstance(other, BankAccount):
            raise TypeError("only transfer to another BankAccount")
        self.withdraw(amount)
        other.deposit(amount)

    def history(self) -> list:
        return list(self._tx_log)
