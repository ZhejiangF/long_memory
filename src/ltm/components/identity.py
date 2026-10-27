"""成员、别名、代词。有歧义的称呼只在关系明确时解析。"""

from __future__ import annotations


class IdentityBook:
    def __init__(self, members: list[dict]) -> None:
        self.members = members
        self.by_id = {m["id"]: m for m in members}
        self.alias_owner: dict[str, list[str]] = {}
        for m in members:
            for alias in [m["name"], *m.get("aliases", [])]:
                self.alias_owner.setdefault(alias, []).append(m["id"])
        # 张悦口中的「哥」才是张磊。其他人说「哥」不解析。
        self.contextual = {("zhangyue", "哥"): "zhanglei"}

    def name_of(self, speaker_id: str) -> str:
        found = self.by_id.get(speaker_id)
        return found["name"] if found else speaker_id

    def speaker_token(self, speaker_id: str) -> str:
        return "@" + self.name_of(speaker_id)

    def resolve_mentions(self, text: str, speaker_id: str) -> list[str]:
        found: list[str] = []
        for alias, owners in self.alias_owner.items():
            if alias and alias in text and owners[0] != speaker_id:
                if len(owners) == 1:
                    found.append(owners[0])
        special = self.contextual.get((speaker_id, "哥"))
        if special and "哥" in text and special not in found:
            found.append(special)
        # 去重并保持顺序
        out: list[str] = []
        for item in found:
            if item not in out and item != "self":
                out.append(item)
        return out

    def mentioned_ids_in_query(self, text: str) -> list[str]:
        found: list[str] = []
        for alias, owners in sorted(self.alias_owner.items(), key=lambda kv: -len(kv[0])):
            if alias and alias in text:
                for owner in owners:
                    if owner not in found and owner != "self":
                        found.append(owner)
        return found
