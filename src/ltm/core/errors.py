class LTMError(Exception):
    """插件内部错误的基类。"""


class DuplicatePluginError(LTMError):
    """同一个插槽里注册了两个同名实现。"""


class UnknownPluginError(LTMError):
    """配置点名的实现没有注册。"""


class MessageError(LTMError):
    """消息缺少时间、会话或说话人。"""
