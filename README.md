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

仓库根目录就是 npm 包：`package.json` 的 `dsh.bundle.patch` 指向 `dsh-plugin/cordis.patch.yml`，`files` 带上 `src/ltm`，装上后模型多出 `memory_recall`、`memory_remember`、`memory_sleep`、`memory_status` 四个工具。

```bash
dsh plugin --profile web add "git+https://github.com/ZhejiangF/long_memory.git"
dsh --profile web --dump-config      # 组合树里应出现 id: ltm-memory
```

只要求 DSH 0.2.x、Node.js ≥ 22.19、Python 3.10+；默认不需要任何 Python 第三方包。本地开发用 `dsh plugin --profile web add "file:$(pwd)"`。

记忆体默认落在 `<DSH_HOME>/ltm/memory.db`，首次启动是空库，不会读 `results/` 下的旧记忆。安装细节、配置项和验证命令见 [dsh-plugin/README.md](dsh-plugin/README.md)，发布说明见 [RELEASE.md](RELEASE.md)。

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
| `dsh-plugin/` | DSH 插件入口：cordis 入口、四个模型可见工具、python 桥 |
| `tests/` | 公式、插件注册、桥协议 |
