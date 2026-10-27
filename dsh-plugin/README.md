# dsh-plugin-ltm

DSH 的长期记忆插件。原话先进缓冲区，攒够一批像睡眠一样整理；用词语关联找回原话，用事实权重和性格门控决定留在长期记忆里的内容。

插件只做协议翻译：七个模型可见工具经一行一个 JSON 的 stdio 桥，调用包内 `src/ltm` 的同一套记忆规则。**没有第三方 Python 依赖**——`PyYAML` 只在读自定义 YAML 配置时才需要，`jieba` 缺失时自动退回词表切分。

## 包结构

仓库根目录就是 npm 包（`package.json`），插件入口在 `dsh-plugin/`：

| 路径 | 作用 |
|---|---|
| `package.json` | `dsh.bundle.patch` 指向补丁；`main` 指向 `dsh-plugin/src/index.js`；`files` 带上 `src/ltm` |
| `dsh-plugin/cordis.patch.yml` | bundle 补丁：一条 `insert`，把 `ltm-memory` 行插进组合树 |
| `dsh-plugin/src/index.js` | cordis 插件入口：`name` / `inject: ['tools']` / `apply(ctx, config)` |
| `dsh-plugin/src/tools.js` | 七个 `ToolDefinition`，`parameters` 与 `output.schema` 都是 JSON Schema |
| `dsh-plugin/src/bridge.js` | 长驻 `python -m ltm.service.bridge`，按行收发 JSON；自动挑 `python`/`python3` |
| `src/ltm` | 记忆引擎本体（随包分发，不重复实现） |

host-only：没有 `dsh.client`，不需要构建 client bundle，没有 npm 依赖。

## 安装

```bash
# 从 GitHub 直接装（推荐，钉一个 commit 更稳）
dsh plugin --profile web add "git+https://github.com/ZhejiangF/long_memory.git#<commit>"

# 本地开发：在仓库根目录
dsh plugin --profile web add "file:$(pwd)"

# 装完重启 dsh、刷新页面，再确认组合树里有这一行
dsh --profile web --dump-config
```

要求：DSH 0.2.x（在 `0.2.1-rc.2` 上验证）、Node.js ≥ 22.19、**Python 3.10+**。

Python 依赖：默认零依赖。只有两种情况需要额外装：

```bash
pip install PyYAML   # 仅当你在 config 里给 configPath 指向一个 YAML
pip install jieba    # 可选，装了中文分词更准；不装会自动退回词表切分
```

`python` 不在 PATH 或名字不同（例如只装了 `python3`）时，插件会自动依次尝试 `python`、`py`（Windows）/ `python3`、`python`（其它系统）；仍找不到就在配置里写死：

```yaml
python: 'C:/path/to/python.exe'
```

## 工具

| 工具 | 何时用 | 返回 |
|---|---|---|
| `memory_recall` | 回答涉及过去的人、事、约定、偏好之前 | 命中的原话与事实；没有就明说没有 |
| `memory_remember` | 用户提到自己的事、约定、偏好、计划 | 已记下，缓冲区剩几句 |
| `memory_sleep` | 用户说“记住这些”，或会话结束前 | 这次整理出的句子、事实数与耗时 |
| `memory_save` | 用户说“保存记忆”“先存一下” | 已保存，句子/事实数与耗时 |
| `memory_load` | 用户问“你都记得什么”“把记忆读出来” | 活跃事实 + 最近原话 |
| `memory_reset` | 用户明确要求“清空记忆”，必须 `confirm=true` | 清掉的消息/句子/事实条数 |
| `memory_status` | 想知道记忆体现状 | 消息/句子/事实/缓冲区条数与文件位置 |

写入走缓冲区，攒够一批才整理；`memory_status` 里的 `buffer` 就是还没整理的原话条数。

**自动整理**：每写入 `consolidateEvery` 次原话（默认 10 次）会自动整理一次并落库，不依赖定时器；`memory_save` 可以随时手动整理。原计划的「每天九点定时保存」没有实现，也不需要——按次数整理在空闲时就能完成。

## 配置项

补丁里的 `config` 整段替换，不深合并。

| 键 | 默认 | 说明 |
|---|---|---|
| `dbPath` | `<DSH_HOME>/ltm/memory.db` | 记忆体文件；`:memory:` 表示不落盘 |
| `blank` | `true` | 空白记忆体：不预置任何人名，成员随第一次出现变成 `@名字` |
| `resetOnStart` | `false` | 启动时先清空旧记忆；换空白记忆体时用一次 |
| `python` | 自动探测 | 跑桥的解释器 |
| `pythonPath` | 包内 `src` | 加进 `PYTHONPATH`，让子进程找到 `ltm` |
| `configPath` | 无 | 覆盖用的 YAML（需要 PyYAML） |
| `sessionId` | `dsh` | 工具写入时的会话 id |
| `speaker` | `user` | 没指定说话人时的默认值 |
| `recallLimit` | `8` | 召回默认条数，上限 50 |
| `loadLimit` | `50` | `memory_load` 事实与原话各取几条，上限 50 |
| `consolidateEvery` | `10` | 每写入几次原话自动整理一次；`0` 表示关闭 |
| `napSentences` | `600` | 缓冲区攒到几句就「小睡」（批量整理）。日常聊天建议 20–60，或用 `consolidateEvery` |
| `nightHour` | `3` | 夜间整理的时刻（0–23）。按消息时间戳跨过该时刻补做，不是定时器 |
| `timeoutMs` | `30000` | 单次桥调用超时 |

## 小睡与夜间整理

「小睡」不是休眠，是**批量整理**：把缓冲区里攒着的原话一次性整理成句子、词语关联和事实。

- **小睡**：缓冲区达到 `napSentences`（默认 600 句），或手动 `memory_save` / `memory_sleep` 时触发。
- **夜间整理**：每条消息进来时比较前后两条消息的时间戳；跨过了 `nightHour`（默认 3 点）就对每个跨过的夜晚补做一次——先强制小睡，再按强度、重要度、留存率把该忘的事实标成 `dormant`（不删除）。
- 它**不是定时器**：夜里没人说话不会发生任何事，第二天第一条消息进来时补做；连续几天没说话会一次补做多个夜晚。
- 整理耗时记在 `sleep_ms`，不算进回复耗时。

调到日常节奏（整段替换 `ltm-memory` 的 config）：

```yaml
- id: ltm-memory
  config:
    consolidateEvery: 10
    napSentences: 40
    nightHour: 3
```

## 空白记忆体

- 默认路径是一个**新文件**，和仓库里 `results/` 下的东西没有关系。
- 默认 `blank: true`：连示例人名也不预置，记忆体里从零开始。
- 想重新从空白开始：删掉 `dbPath` 指向的文件，或把 `resetOnStart` 改成 `true` 启动一次再改回来。也可以直接清空一次（启动后按 Ctrl+C 退出）：

```bash
python -m ltm.service.bridge --db <dbPath> --reset
```

## 验证

```bash
python -m pytest -q                        # 含 bridge 协议测试
node dsh-plugin/test/tools.test.mjs        # 工具定义与渲染
node dsh-plugin/test/e2e.mjs               # Node → python 引擎，端到端
```

`e2e.mjs` 要拉起子进程并读管道；受限沙箱里会报 `spawn EPERM`，需要在正常权限下运行。

## 发版

推 `v*` 标签会由 `.github/workflows/release.yml` 自动创建 GitHub Release：正文取 `RELEASE.md` 里对应版本的那一段，附件是 `npm pack` 出来的 `.tgz`（可离线安装）。

```bash
git tag -a v0.1.2 -m "v0.1.2: 一句话说明"
git push origin v0.1.2
```

安装指定版本：

```bash
dsh plugin --profile web add "git+https://github.com/ZhejiangF/long_memory.git#v0.1.2"
```

## 限制

- 宿主进程必须能跑 Python 3.10+；插件不内嵌解释器。
- 只注册工具，不自动抓会话消息。要“自动记住”需要在 DSH 的会话事件上再加一层监听。
- 桥是单进程串行处理；并发工具调用会排队。
