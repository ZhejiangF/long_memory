"""长期记忆插件的公共入口。其他运行时只应依赖这里导出的名字。"""

from ltm.core.models import Message, Query, TurnResult
from ltm.service.factory import build_agent
from ltm.version import __version__

__all__ = [
    "Message",
    "Query",
    "TurnResult",
    "build_agent",
    "__version__",
]
