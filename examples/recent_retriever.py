"""示例：不改核心代码，也能登记一个新检索器。"""

from ltm.core.registry import register


@register("retriever", "recent_only")
class RecentOnly:
    def __init__(self, store, limit: int = 20) -> None:
        self.store = store
        self.limit = limit

    def latest_texts(self) -> list[str]:
        return [row["text"] for row in self.store.recent_messages(self.limit)]
