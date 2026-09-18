"""领域异常：参数非法与无可行解，分开建模。"""


class ParamError(Exception):
    """输入参数非法。携带出问题的参数名与可读说明。"""

    def __init__(self, param: str, message: str):
        self.param = param
        self.message = message
        super().__init__(f"[{param}] {message}")


class InfeasibleError(Exception):
    """市场价格落在无套利界外（或期限为零），隐含波动率不可行。"""
