# 把 long_memory（ltm）接成 Aurabot 的记忆

> 目标：让 QQ 里的「大肥鱼」用 ltm 的**记忆体**和**热区**说话，而不是靠聊天窗口里越滚越长的上下文。
> 本文记录改了什么、为什么这么改、哪里容易坏，以及怎么证明它真的没在读长上下文。
>
> 实测环境：Windows 10、DSH 桌面版（profile `desktop`）、Aurabot `dsh-aurabot-qq 1.0.5`、ltm 本仓库、Python 3.12.11。
> 数据实测于 2026-10-27。

---

## 0. 结论先行

| 你要确认的 | 实测答案 |
|---|---|
| **会不会读对话框上下文？** | **不会。** 每轮都是一个全新 DSH 会话，窗口里只有当前这一条消息；每条消息只入库一次 |
| **回复是不是基于热区 + 记忆体？** | **是。** 模型输入 = 人格 +【长期记忆】(事实 + 热区原话 + 未整理缓冲) + 当前句，没有第三个来源 |

关键数字（11 条唯一消息的那段对话）：

| 指标 | 数值 |
|---|---|
| OneBot 实际派发次数 | 22 |
| 唯一消息 | 11 |
| 入库条数 | 11（重置前 2 + 重置后 9） |
| 同人同文 10 秒内重复 | **0** |
| 含「【长期记忆】」的入库记录 | **0**（记忆块不回灌） |
| QQ 会话快照 | 11 个，全部 `turns=1`、`QQ 消息=1`、`含记忆块=true` |

---

## 1. 为什么要接

Aurabot 自己带一个记忆模块：JSON 存储、中文二元切词 + BM25、小档案、相处经验。它是**另一套记忆**，和 ltm 的记忆体不共享。

接过来要解决三件事：

1. **同一份记忆**：Aurabot 和 DSH 的 `memory_*` 工具都写 `~/.dsh/ltm/memory.db`，一个库。
2. **热区 + 记忆体**：每轮先从库里想起，再有话说。
3. **不吃长上下文**：QQ 聊得越久，窗口越大，token 和延迟都会跟着涨。改成每轮新窗口 + 记忆块，成本就封在「一次检索 + 一段固定预算的记忆」上。

---

## 2. 数据流

```
QQ ── SnowLuma(OneBot v11) ──▶ Aurabot 聊天中枢
                                   │
                    ┌──────────────┴───────────────┐
                    │ activity('in')               │ pushToSession()
                    ▼                              ▼
             ltm-memory 模块                  prompt 钩子（每轮）
             ├ 去重（3 秒窗口）                 ├ 归档旧会话 → 开新会话
             └ ingest ──▶ ltm 子进程            ├ 等入库队列排空
                          │                     ├ recall(这句话)
                          ▼                     ├ dump(事实 top N)
                  ~/.dsh/ltm/memory.db           └ 拼【长期记忆】放在最前
                   （与 DSH memory_* 共用）              │
                                                         ▼
                                                  交给她（模型）
```

一轮的生命周期：

```
收消息 → activity → 入库(queue) ─┐
                                 ├→ prompt 钩子: await queue → recall+dump → 记忆块 + 原消息
                                 │                                   → resetChat(旧会话归档)
                                 │                                   → 新会话 followup
                                 └→ 她回话 → 会话事件 → 发 QQ → activity('out') → 入库
```

---

## 3. 前置条件

| 项 | 要求 |
|---|---|
| Aurabot | 已装好并能收发消息（总开关开、OneBot `connected`） |
| Python | 能 `import ltm`。用本仓库源码时把 `src` 加进 `PYTHONPATH` |
| 数据库 | 默认 `~/.dsh/ltm/memory.db`（没有会自动建） |
| 内置记忆模块 | **必须关掉**（见 §5） |

---

## 4. 接入步骤

1. **装 ltm 插件**（DSH 侧，可选但推荐，两边共用一个库）

   ```powershell
   & "$env:LOCALAPPDATA\Programs\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd" plugin --profile desktop add "git+https://github.com/ZhejiangF/long_memory.git"
   ```

2. **把模块放进 Aurabot 的数据目录**（升级不会覆盖）

   ```
   %USERPROFILE%\.dsh\plugins-data\aurabot\modules\ltm-memory\
       index.mjs
       ltm-bridge.mjs
       README.md
   ```

   本仓库里的副本在 [`integrations/aurabot/ltm-memory/`](integrations/aurabot/ltm-memory/)，直接复制过去。

   ```powershell
   Copy-Item integrations\aurabot\ltm-memory\* `
     "$env:USERPROFILE\.dsh\plugins-data\aurabot\modules\ltm-memory\" -Force
   ```

3. **关掉内置记忆模块**（不关就会两套记忆并存、各写一份）

   面板「心情与记忆」页，或者直接改 `%USERPROFILE%\.dsh\plugins-data\aurabot\config.json`：

   ```json
   { "memory": { "enabled": false } }
   ```

   等价于调一次接口：

   ```powershell
   Invoke-RestMethod -Uri "http://127.0.0.1:58515/aurabot/api/save" -Method Post `
     -ContentType "application/json; charset=utf-8" `
     -Body ([Text.Encoding]::UTF8.GetBytes('{"memory":{"enabled":false}}'))
   ```

4. **等 3 秒**，Aurabot 会自动扫描 `modules/` 并加载。面板「扩展」页应出现 **LTM 长期记忆**，状态 `running`、无报错。

5. **确认桥接正常**

   ```powershell
   Invoke-RestMethod "http://127.0.0.1:58515/aurabot/api/ext/ltm-memory/state"
   ```

   返回里有 `stats.db`、`stats.messages`、`last.text`（上一轮的记忆块）。第一次是空库，正常。

6. **发一句试试**，观察 `stats.messages` 涨 2（你 1 + 她 1）。

---

## 5. 改动清单

| 位置 | 改动 | 说明 |
|---|---|---|
| `~/.dsh/plugins-data/aurabot/modules/ltm-memory/index.mjs` | 新增 | 入库、检索、记忆块、每轮新会话、`remember`/`recall_memory` |
| `…/ltm-memory/ltm-bridge.mjs` | 新增 | JSONL 桥子进程（和 `dsh-plugin/src/bridge.js` 同协议） |
| `aurabot/config.json` | `memory.enabled = false` | 关内置记忆，避免两套记忆 |
| `src/ltm/adapters/sqlite_store.py` | 加 `PRAGMA busy_timeout=5000` | 两个进程写同一个库时排队而不是 `database is locked` |

**没有改** Aurabot 的 `node_modules` 源码——模块走的是插件官方扩展接口（`src/modules/API.md`），升级不丢。

---

## 6. 关键实现

### 6.1 为什么不用 `api.context`

`api.context(({chat}) => '…')` 看起来最顺手，但它是**同步**的——`modules.js` 里用 `if (t) parts.push(String(t))` 直接取返回值。ltm 检索要走子进程，只能异步。

所以记忆块走 **`prompt` 钩子**（`filter()` 支持 `await`），把记忆块拼进这一轮的用户消息最前面：

```js
api.on('prompt', async (content, info = {}) => {
  const { chat, senderId, queryText, steer } = info
  if (!chat || chat.kind === 'system') return content
  if (o.freshWindow && !steer) api.core.hub.resetChat(chat.chatId)   // ① 先换窗口
  const query = queryText || textOfContent(content)
  await tail                                                          // ② 等入库队列
  const block = await compose(chat, query, senderId)                  // ③ recall + dump
  return [{ type: 'text', text: block }, ...tidy(content)]            // ④ 放在最前
})
```

顺序不能反：`resetChat` 必须发生在 `pushToSession` 内部、`agentFor()` 建会话之前——而 `prompt` 钩子正好在这个位置被调用（`hub.js` 里 `hooks.prompt()` 在 `agentFor()` 之前）。

### 6.2 入库

```js
api.on('activity', (event) => {
  if (event.kind === 'in') {
    names.set(uid, event.owner ? '主人' : event.nickname)   // 显示用
    if (isRepeated(chatId, uid, event.text)) return          // 去重
    ingest(event.text, `qq:${uid}`, event.chatId)
  } else if (event.kind === 'out') {
    const said = cleanOut(event.reply)                       // 洗掉发送标记
    if (said) ingest(said, 'self', event.chatId)
  }
})
```

`ingest` 串在一条 Promise 队列上，保证「这句先入库，再检索」，不会读到自己还没写进去的话。

### 6.3 记忆块

```js
const rec  = await ltm.call('recall', { query, asker, limit: 8 })  // 事实 + 热区原话 + 未整理
const dump = await ltm.call('dump',   { limit: 8 })                // 记忆体（按强度取 top N）
```

渲染成三段：

```
【长期记忆】你脑子里现在只有下面这些。聊天窗口是空的……
■ 你记得的事：            ← dump.facts（记忆体）
- 主人也喜欢海，还喜欢山
■ 和这次有关的：          ← recall 里的 fact（去重后）
■ 想起来的原话：          ← recall 里的 sentence / buffer
[2026-10-27 19:27｜主人] 真好，我也喜欢这样      （已整理进热区）
[未整理｜self] 嗯…那以后带你看海看山 我都陪着    （还在缓冲区）
```

`recall` 本身就同时返回 `fact`、`sentence`（热区）、`buffer`（还没整理进热区）三种来源，所以「窗口里刚说、还没进热区」的内容不会丢——正好对应「除非上下文还没保存到热区」这个例外。

### 6.4 每轮新会话

```js
if (o.freshWindow && !steer) api.core.hub.resetChat(chat.chatId)
```

`resetChat` 归档旧会话并从映射里删掉，紧接着 `agentFor()` 建一个新的。效果：窗口里只有这一轮。

`steer`（她还在跑，这句插进去）时跳过——那种情况归档会把正在跑的会话抽掉。

### 6.5 桥

```js
spawn(python, ['-m', 'ltm.service.bridge', '--db', dbPath, '--blank', '--nap-sentences', '12'], …)
```

`--blank` 很关键：不带它，ltm 会预置阶段一那批人名（张磊、林夏……），抽取时会错误地把陌生人认成他们。

---

## 7. 容易出错的地方（都是实测踩到的）

| # | 坑 | 症状 | 处理 |
|---|---|---|---|
| 1 | 忘了关内置记忆 | 面板里还是老记忆，两套并存 | `memory.enabled=false` |
| 2 | 想用 `api.context` 注入记忆 | 记忆块变成 `[object Promise]` | 改走 `prompt` 钩子（`filter` 支持 async，`context` 不支持） |
| 3 | 在 `prompt` 里先检索后等入库 | 刚说的那句检索不到 | 先 `await tail`，再 `recall` |
| 4 | 每条消息被派发两次 | 记忆里同样的话两条，事实权重翻倍 | 入库 3 秒去重 + 提示词折叠重复行 |
| 5 | 她的回复带 `<sticker:开心>`、`|||` | 记忆里全是发送标记 | `cleanOut()` 先洗再入库 |
| 6 | 两个进程写同一个 SQLite | 偶发 `database is locked`，那条记忆丢了 | 仓库里加 `PRAGMA busy_timeout=5000` |
| 7 | Python 找不到 `ltm` | 模块报「起不来 python」 | 设 `srcPath`，会拼进 `PYTHONPATH` |
| 8 | 不加 `--blank` | 事实里出现「张磊」这类样板人名 | 桥里固定带 `--blank` |
| 9 | 事实表一直是空的 | 以为抽取坏了 | **规则抽取只认陈述句**，问句（「你为什么喜欢海？」）只当原话 |
| 10 | `napSentences` 太大 | 热区一直空，只剩「未整理」 | 默认 12（ltm 默认 600 是给离线批处理用的） |
| 11 | 每轮新会话的代价 | `~/.dsh/sessions/…Aurabot-qq-chats--/` 每条消息多一个归档（10–15 KB） | 能接受就留；不接受关 `freshWindow`，但窗口就会重新变长 |
| 12 | 在受限沙箱里跑 node 测试 | `spawn EPERM`（Node 用管道 stdio 起子进程被拒） | 桥只在 DSH 进程里跑；测试改用 Python 直连 `ltm.service.bridge` |
| 13 | 模块写坏 | 面板显示报错 | 插件会自动回退内置模块，不会让她突然少项本事；改完 3 秒自动重载 |
| 14 | 同一个人 3 秒内连发两条一模一样的 | 第二条被当成重复丢掉 | 已知取舍；要更准得按 OneBot `message_id` 去重，而 `activity` 事件里没这个字段 |

---

## 8. 怎么自己验证

### 8.1 看库

```powershell
$env:PYTHONIOENCODING="utf-8"
python -c "import sqlite3;c=sqlite3.connect(r'C:\Users\User\.dsh\ltm\memory.db');c.row_factory=sqlite3.Row;rows=list(c.execute('SELECT msg_id,ts,speaker_id,text FROM messages ORDER BY msg_id'));print('总消息',len(rows));print('重复',len(rows)-len({(r['speaker_id'],r['text'].strip()) for r in rows}));print('含记忆块',sum(1 for r in rows if '长期记忆' in (r['text'] or '')))"
```

期望：`重复 0`、`含记忆块 0`。（注意：跨天重复同一句话会正常计为两条，所以这个粗查只适合连续对话。）

### 8.2 对聊天流水

Aurabot 自己的流水在 `~/.dsh/plugins-data/aurabot/chatlog/<日期>.jsonl`，每条收到的消息一行——**它记录的是派发次数，不是唯一消息数**：

```powershell
python -c "import json,collections,os;p=os.path.expanduser('~/.dsh/plugins-data/aurabot/chatlog/2026-10-27.jsonl');rows=[json.loads(l) for l in open(p,encoding='utf-8') if l.strip()];inb=[r for r in rows if r.get('who')!='bot'];print('派发',len(inb));print('唯一',len({(r.get('who'),r.get('text')) for r in inb}))"
```

实测：派发 22、唯一 11 —— 每条消息被派发两遍（同一秒），入库去重后正好 11 条。

### 8.3 打开会话快照，看她到底收到了什么

DSH 的会话是 zstd 帧拼接的 jsonl，`zstdDecompressSync` 只解第一帧，得逐帧解：

```powershell
node -e "
const {readFileSync}=require('node:fs');const {zstdDecompressSync}=require('node:zlib');
const b=readFileSync(process.argv[1]);const pos=[];
for(let i=0;i+3<b.length;i++){if(b[i]===0x28&&b[i+1]===0xB5&&b[i+2]===0x2F&&b[i+3]===0xFD)pos.push(i)}
pos.push(b.length);let all='';
for(let k=0;k<pos.length-1;k++){try{all+=zstdDecompressSync(b.subarray(pos[k],pos[k+1])).toString('utf8')}catch(e){}}
for(const l of all.split('\n').filter(Boolean)){const e=JSON.parse(l);
  if(e.type==='turn/start')console.log('== 新一轮 ==');
  if(e.type==='user/message'){const c=(e.data&&e.data.content)||[];console.log(c.map(x=>x.text||'').join('\n'))}}
" "C:\Users\User\.dsh\sessions\--C-Users-User-Aurabot-qq-chats--\<会话ID>\session.v4.jsonl.zstd"
```

---

## 9. 证明一：不读对话框上下文

### 9.1 每个会话只有一轮、一条消息

扫 `~/.dsh/sessions/--C-Users-User-Aurabot-qq-chats--/` 下全部会话：

| 会话 | turns | QQ 消息 | 含【长期记忆】 |
|---|---|---|---|
| 11 个 QQ 私聊会话 | 全部 `1` | 全部 `1` | 全部 `true` |
| 1 个空间日记会话（system） | 1 | 0 | false（系统会话，本来就不该有） |

如果窗口在累积，第二个会话的 `turns` 会变成 2、`QQ 消息` 会变成 2。实际全部是 1。

### 9.2 每条消息只入库一次

- OneBot 派发 **22** 次，唯一 **11** 条，库里 **11** 条
- 10 秒内同人同文重复：**0**
- 含「【长期记忆】」的入库记录：**0** —— 记忆块只出现在提示词里，不会被当成新消息回灌

### 9.3 直观证据

这一轮她的输入（会话快照原文）：

```
【长期记忆】你脑子里现在只有下面这些。聊天窗口是空的：除了这些和这次的新消息，更早的对话你都不记得，也别假装记得。
■ 你记得的事：
- 主人也喜欢海，还喜欢山
■ 想起来的原话：
[2026-10-27 19:26｜主人] 你为什么喜欢海
[2026-10-27 19:25｜self] 讲海的那种就很好

【私聊】869744523(869744523)：好啊，你真好
```

**没有第二条历史消息。**

---

## 10. 证明二：回复基于热区 + 记忆体

### 10.1 模型输入只有三样

1. 系统提示词：只有人格（preset 里 `persona.complete: true`，把 DSH 的助手身份整个顶掉）
2. 用户消息：`【长期记忆】` 块 + 当前这一句
3. 工具定义

内置记忆模块的 `contextFor()` 在 `memory.enabled=false` 时返回空串，所以没有第二个记忆来源。

### 10.2 反面验证（最有说服力的一次）

18:11 那一轮，窗口是全新的，你问：

> 我刚才说我喜欢干什么？

她答：

> 打游戏啊，你自己刚才说的

这句话不可能来自窗口（窗口里只有这一问），唯一来源是记忆块里的：

```
[未整理｜主人] 你好，我平时喜欢打游戏
```

### 10.3 正面验证

19:28 那一轮的记忆块里有 2 条事实 + 6 条热区原话，她的回复顺着「喜欢海 / 山」接话，**没有提**更早的「打游戏」「看电影」——那些当时不在块里（还没轮到，缓冲区 4 条、阈值 12 句）。说明她的注意力确实被块的内容限定了。

---

## 11. 取得的效果与代价

**效果**

- 窗口长度恒定为 1 条消息，**不随聊天时长增长**
- 每轮固定的记忆预算（默认 1800 字），检索 + 渲染走一次 recall + 一次 dump
- 记忆存在 ltm 里，和 DSH 的 `memory_*` 工具是同一个库，可以互相看见

**代价**

- 每轮一个新会话：`~/.dsh/sessions/…Aurabot-qq-chats--/` 下每条消息多一个归档目录（10–15 KB）
- 事实靠规则抽，只认陈述句，宽松时会抽到「真好，主人也喜欢这样」这种
- 记忆块预算 1800 字，长尾问题会被截断

---

## 12. 关掉 / 回滚

| 想做什么 | 怎么做 |
|---|---|
| 暂时不用 ltm 记忆 | 面板「扩展」页把 **LTM 长期记忆** 关掉 |
| 恢复窗口上下文 | 设置里关 `每轮开新会话` |
| 回到 Aurabot 自带记忆 | 关掉本模块，把 `memory.enabled` 改回 `true` |
| 彻底删掉 | 删 `~/.dsh/plugins-data/aurabot/modules/ltm-memory/` |
| 清空记忆 | `POST /aurabot/api/ext/ltm-memory/reset`（不可恢复） |

`~/.dsh/ltm/memory.db` 是共用库，**删文件夹不会删记忆**。
