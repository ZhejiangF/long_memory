# v0.2.0 — 保存 / 加载 / 清空 + 按次数自动整理

四个动作都能在对话里直接用了，不需要 UI 按钮：

| 动作 | 工具 | 说明 |
|---|---|---|
| 保存记忆 | `memory_save` | 立刻整理缓冲区并落库 |
| 加载记忆体 | `memory_load` | 列出活跃事实与最近原话 |
| 清空当前记忆 | `memory_reset` | 必须带 `confirm=true`，清掉消息/句子/事实/词表 |
| 查看现状 | `memory_status` | 原有的状态工具 |

同时把「定时保存」换成「按次数整理」：每写入 `consolidateEvery`（默认 10）次原话自动整理一次；设为 `0` 关闭。没有实现每天九点的定时器，也不需要它。

升级：link 安装重启即可；git/npm 安装重新 `add` 或点 Update。已有记忆体不清空。

# v0.1.1 — DSH 长期记忆插件

修复首次安装后第一次调用就失败的问题：记忆体的父目录（`<DSH_HOME>/ltm/`）以前没人创建，SQLite 会报 `unable to open database file`；现在桥启动时自动建目录。另外，宿主不传 `DSH_HOME` 时，从工作目录 `…/profiles/<name>` 回推 DSH home，记忆体不再落进 profile 目录。

升级：`dsh plugin --profile desktop remove dsh-plugin-ltm` 后重新 `add`，或 npm 版直接 Update。已有记忆体不会被清空。

# v0.1.0 — DSH 长期记忆插件

把仓库里的 ltm 长期记忆引擎接成 DSH 的 cordis 插件：装上之后，模型多出四个记忆工具，记忆体默认是空的、落在 `<DSH_HOME>/ltm/memory.db`。

## 这是什么

- **原话优先**：用户说过的话先进缓冲区，攒够一批才像睡眠一样整理成句子、词语关联和事实。
- **词语关联召回**：不是向量近似，而是沿着词与词之间的边找回原话。
- **事实与性格门控**：决定哪些内容值得长期保留，久不用的会进入休眠。
- **模型只负责说话**：插件的工具返回已经检索好的记忆，宿主模型不参与记忆规则。

## 安装

要求：DSH 0.2.x（在 `0.2.1-rc.2` 上验证）、Node.js ≥ 22.19、Python 3.10+。

```bash
dsh plugin --profile web add "git+https://github.com/ZhejiangF/long_memory.git"
```

装完重启 dsh、刷新页面。确认组合树里有这一段：

```bash
dsh --profile web --dump-config | grep -A 3 ltm-memory
```

本地开发（仓库根目录）：

```bash
dsh plugin --profile web add "file:$(pwd)"
```

## 依赖

**默认零 Python 依赖。** 只有这两种情况需要额外装：

```bash
pip install PyYAML   # 仅当 config 里给了 configPath 指向 YAML
pip install jieba    # 可选，装了中文分词更准；不装会退回词表切分
```

`python` 不在 PATH 或名字不同也没关系：插件会依次尝试 `python`、`py`（Windows）/ `python3`、`python`（其它系统）。都不行就在配置里写 `python: 'C:/path/to/python.exe'`。

## 工具

| 工具 | 用途 |
|---|---|
| `memory_recall` | 回答涉及过去的人、事、约定、偏好之前，先查记忆 |
| `memory_remember` | 用户提到自己的事、约定、偏好、计划时，照抄原话写进去 |
| `memory_sleep` | 用户说“记住这些”或会话结束前，立刻整理缓冲区 |
| `memory_status` | 查看消息/句子/事实/缓冲区条数与记忆体文件位置 |

## 用法

一次典型对话：

1. 用户说「我家猫叫橘子。」
2. 模型调用 `memory_remember(text="我家猫叫橘子。", speaker="张磊")` → 返回「已记下（张磊），缓冲区 1 句。」
3. 会话结束前调用 `memory_sleep()` → 返回「整理完成：句子 1，事实 1，用时 12.3ms。」
4. 下次用户问「我家猫叫什么？」→ `memory_recall(query="猫叫什么")` → 返回「命中 1 条：张磊：我家猫叫橘子。」

记忆体默认在 `<DSH_HOME>/ltm/memory.db`，是一个普通 SQLite 文件：备份就是复制它，清空就是删掉它（或把配置里的 `resetOnStart` 改成 `true` 启动一次）。

## 配置

补丁里的 `config` 整段替换，不深合并。常用项：

| 键 | 默认 | 说明 |
|---|---|---|
| `dbPath` | `<DSH_HOME>/ltm/memory.db` | 记忆体文件；`:memory:` 表示不落盘 |
| `blank` | `true` | 空白记忆体：不预置任何人名 |
| `resetOnStart` | `false` | 启动时清空旧记忆 |
| `python` | 自动探测 | 跑桥的解释器路径 |
| `recallLimit` | `8` | 召回默认条数 |

其余见 [dsh-plugin/README.md](dsh-plugin/README.md)。

## 验证

```bash
python -m pytest -q
node dsh-plugin/test/tools.test.mjs
node dsh-plugin/test/e2e.mjs
```

## 已知限制

- 需要宿主机器有 Python 3.10+，插件不内嵌解释器。
- 只注册工具，不自动抓会话消息；要自动记住需要在会话事件上再加监听。
- 桥是单进程串行处理，并发工具调用会排队。
- 在 DSH 的 Developer Preview 阶段，插件 API 可能有破坏性变更。

## 许可证

MIT。
