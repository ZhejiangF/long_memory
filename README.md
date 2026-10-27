# ltm-memory

聊天 agent 的长期记忆插件。原话先进入缓冲区，攒够一批再像睡眠一样整理；用词语之间的关联找回原话，用事实权重和性格门控决定什么留在长期记忆里。

它不绑定某一种编辑器或模型。宿主调用 `build_agent`，自己的模型只负责把已经检索出的记忆说成回复。

## 安装

```bash
pip install -e ".[dev]"
```

依赖是 PyYAML（只有读自定义 YAML 配置时才需要）和 jieba（缺失时自动退回词表切分）。嵌入默认用进程内的哈希向量，不需要下载模型。

## 调用

```python
from ltm import Message, build_agent

agent = build_agent("memory.db")
result = agent.handle(
    Message(ts=1_700_000_000, session_id="生活群", speaker_id="zhanglei",
            text="我家猫叫橘子。", addressee_ids=("self",)),
    need_reply=True,
)
print(result.reply)
```

`result.total_ms` 只包含检索、拼装提示词和生成。整理记忆的时间在 `result.sleep_ms`。

## 作为 DSH 插件

仓库根目录就是 npm 包：`package.json` 的 `dsh.bundle.patch` 指向 `dsh-plugin/cordis.patch.yml`，`files` 带上 `src/ltm`。装上后模型多出这些工具：`memory_recall`、`memory_remember`、`memory_sleep`、`memory_save`、`memory_load`、`memory_reset`、`memory_status`。

```bash
dsh plugin --profile web add "git+https://github.com/ZhejiangF/long_memory.git"
dsh --profile web --dump-config      # 组合树里应出现 id: ltm-memory
```

只要求 DSH 0.2.x、Node.js ≥ 22.19、Python 3.10+；默认不需要任何 Python 第三方包。本地开发用 `dsh plugin --profile web add "file:$(pwd)"`。

记忆体默认落在 `<DSH_HOME>/ltm/memory.db`，首次启动是空库，不会读 `results/` 下的旧记忆。安装细节、配置项和验证命令见 [dsh-plugin/README.md](dsh-plugin/README.md)，发布说明见 [RELEASE.md](RELEASE.md)。

## 作为 Aurabot 的记忆（QQ 机器人）

[Aurabot](https://github.com/accomplish07zrh-eng/dsh-aurabot-qq)（大肥鱼）默认用它自带的记忆。换成 ltm 之后：

- QQ 里每一条收到 / 发出的消息都进 `~/.dsh/ltm/memory.db`——**和上面的 `memory_*` 工具共用一个库**；
- 每轮先 `recall` 一次（事实 + 热区原话 + 还没整理进热区的缓冲），拼成`【长期记忆】`放在这一轮最前面；
- **每轮开一个新会话**，聊天窗口里只有当前这一条，聊多久 token 都不会跟着涨；
- `remember` / `recall_memory` 两个工具改成读写 ltm。

```bash
# 模块放到 Aurabot 的数据目录（插件升级不覆盖）
cp -r integrations/aurabot/ltm-memory ~/.dsh/plugins-data/aurabot/modules/
```

然后把面板里的内置「记忆」模块关掉（`memory.enabled = false`），否则两套记忆会各写一份。

接法、14 条实测踩坑，以及「会不会读对话框上下文 / 回复是不是基于热区和记忆体」的完整证据，见 **[Aurabot接入.md](Aurabot接入.md)**。

## 性格

助手有四个风格特质：**关怀、热情、简洁、幽默**（基线 0.5 / 0.5 / 0.5 / 0.3）。

- **每次整理都会更新**：小睡、手动保存、夜间整理后，用这批事实做证据——过敏/饮食禁忌/亲属类事实提升「关怀」，偏好/运动/居住类提升「热情」。
- **防漂移**：每天总变化 ≤ `max_daily_delta`（0.02），权重限制在 0.05–0.95，并持续向基线回归；锁定的特质不动。
- **影响回复**：提示词里有 `【我的性格】`，权重达标时追加指令（关怀 ≥ 0.6 → 体现关心；热情 ≥ 0.6 → 语气热络；简洁 ≥ 0.7 → 三句话以内；幽默 ≥ 0.6 → 适当幽默）。性格只改措辞，不参与检索打分。

实现细节和未实现的设计项见 `长期记忆方案评估与实现.md` 4.6.6。

## 视频与本地媒体 MCP

仓库里附带一套 16:9 讲解视频的生成流水线，以及三个本地 stdio MCP：

- `mcp/image_server.py`：生成背景图、封面、带中文标签的示意图。
- `mcp/video_server.py`：ffmpeg 探测、拼接、混音、烧字幕、抽帧。
- `mcp/audio_server.py`：Edge 神经 TTS、批量合成、音频拼接。

注册方法、工具清单和验证命令见 [mcp/README.md](mcp/README.md)；成片与逐帧流水线见
[video/README.md](video/README.md)，视频介绍（含完整使用方法）在
`video/output/视频介绍.md`。

## 验证

```bash
pytest
python eval/stage1/run_stage1.py
python eval/stage2/smoke.py
node dsh-plugin/test/tools.test.mjs
```

## 给其他 AI agent

改这个仓库之前读 [AGENTS.md](AGENTS.md)。扩展步骤在 [skills/ltm-memory/SKILL.md](skills/ltm-memory/SKILL.md)。设计说明在 `长期记忆方案评估与实现.md`。

## 目录

| 路径 | 职责 |
|---|---|
| `src/ltm/core` | 数据结构、插件注册、默认配置 |
| `src/ltm/adapters` | 时钟、SQLite、嵌入、离线回答器 |
| `src/ltm/components` | 分词、身份、抽取、检索、提示词、遗忘公式 |
| `src/ltm/service` | 组装、对话入口、给 DSH 用的 JSONL 桥 |
| `eval/` | 阶段一对话和阶段二容量冒烟 |
| `dsh-plugin/` | DSH 插件入口：cordis 入口、七个模型可见工具、python 桥 |
| `tests/` | 公式、插件注册、桥协议 |
