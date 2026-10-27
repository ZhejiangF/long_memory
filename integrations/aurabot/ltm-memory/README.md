# ltm-memory —— 用 long_memory 当 Aurabot 的记忆

这个模块把「大肥鱼」的记忆换成 [`long_memory`](../..)（ltm）引擎：
同一个 `~/.dsh/ltm/memory.db`，和 DSH 里的 `memory_*` 工具共用一个记忆库。

## 它怎么工作

1. **入库**：QQ 里每一条收到 / 发出的消息都进 ltm（`speaker` 用 `qq:<QQ号>`，她自己用 `self`）。
   她发出去的 `<sticker:…>`、`|||` 这些发送标记会先洗掉。
2. **想起**：每一轮说话前，用当前这句话去 ltm 检索，把结果拼成一段【长期记忆】放在这一轮最前面：
   - 常驻事实（记忆体，按重要度 / 强度排序）
   - 和这句话相关的事实
   - 热区原话（`[时间｜谁] …`）
   - 还没整理进热区的缓冲（`[未整理｜谁] …`）
3. **不看窗口**：每轮开头归档旧会话、开一个新的 DSH 会话，所以聊天窗口里只有这一句。
   她要回忆只能靠上面那段记忆块。
4. **工具**：`remember` / `recall_memory` 改成写 / 读 ltm。

## 前提

面板「扩展」页里内置的 **记忆** 模块要关掉（`config.json` 的 `memory.enabled = false`），
否则它还会往老的记忆库里写一份。

## 设置（面板「扩展」页 → LTM 长期记忆）

| 键 | 默认 | 说明 |
|---|---|---|
| `python` | `python` | 要能 `import ltm` |
| `srcPath` | `G:\wangtianfan\long_memory\src` | 加进 `PYTHONPATH` |
| `dbPath` | 空 → `~/.dsh/ltm/memory.db` | 和 ltm 工具共用一个库 |
| `napSentences` | `12` | 攒够几句就整理进热区；越小热区长得越快，整理也越频繁 |
| `recallLimit` | `8` | 每轮想起几条 |
| `factsLimit` | `8` | 记忆块里常驻事实几条 |
| `budget` | `1800` | 记忆块字数上限 |
| `freshWindow` | 开 | 每轮开新会话（关掉的话她又能看见窗口里的旧对话） |
| `ingestGroups` | 开 | 群里别人的话也记 |

## 接口（排查用）

- `GET /aurabot/api/ext/ltm-memory/state` —— 设置、库统计、最近的句子 / 事实、上一轮的记忆块
- `POST /aurabot/api/ext/ltm-memory/reset` —— 清空记忆库（删库里的全部记忆，不可恢复）

## 已知取舍

- **每轮一个新会话**：每条 QQ 消息会在 `~/.dsh/sessions/--…Aurabot-qq-chats--/` 下留一个归档会话（约 10–15 KB）。
  想省这个开销就把 `freshWindow` 关掉，但那样窗口里的旧对话又会被她看到。
- **规则抽取只认陈述句**：`我叫…` `我对…过敏` `我住在…` `我…生日` `我喜欢…` 才会进事实表；问句只当原话。
- **两个进程写一个库**：DSH 的 ltm 插件和这个模块各起一个 Python 桥。库里已加 `busy_timeout=5000`，
  同时写会排队而不是报 `database is locked`。
