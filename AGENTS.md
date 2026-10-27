# 给所有 AI agent 的项目规则

本文件是这个仓库的唯一规则入口，不依赖 Cursor、Claude 或别的某一种工具。改代码前先读它。设计细节在 `长期记忆方案评估与实现.md`，验证步骤在两个 `验证_*.md`。

## 这是什么

一个可安装的 Python 插件（包名 `ltm`），给聊天式 agent 提供长期记忆：原话进缓冲区，攒够一批再整理；用词语关联找回原话；用事实和性格决定什么值得加权。宿主自己的模型只负责把检索结果说成人话。

同时，仓库根目录本身是一个 DSH 插件包（npm 名 `dsh-plugin-ltm`）。

## 分层，不要打破

- `ltm.core`：数据结构、注册表、事件、默认配置。不要 import 适配器或功能模块。
- `ltm.adapters`：时钟、数据库、嵌入、离线回答器。可以换掉，不要把业务规则写进这里。
- `ltm.components`：分词、身份、抽取、检索、提示词、强度公式。
- `ltm.service`：唯一对外组装点。宿主只调用 `build_agent` 和 `ChatAgent.handle`。

上层可以调用下层。下层不要反向依赖上层。

## 扩展时怎么做

1. 新的检索、抽取或回答器写成独立模块，用 `ltm.core.registry.register` 登记一个名字。
2. 用配置选择实现，不要在 `MemoryService` 里写 `if 某种算法`。
3. 给数据结构加字段时必须有默认值。数据库只加表或加带默认值的列，并在 `schema_meta` 里记版本。
4. 不要调用 `time.time()` 当记忆的“现在”。时间只来自传入的 `Clock`。耗时测量可以用 `time.perf_counter()`。
5. 不要把阶段一脚本里的人名写进记忆核心来通过测试。
6. 回复耗时不含小睡和夜间整理。整理时间放在 `sleep_ms`。

## DSH 插件

- 仓库根目录就是 npm 包；`dsh-plugin/` 是 cordis 外壳：`src/index.js` 只注册工具，`src/bridge.js` 只按行转发 JSON。
- `package.json` 的 `files` 必须带上 `src/ltm` 和 `config/default.yaml`，否则别人装完没有记忆引擎。
- 记忆规则、参数校验、清空记忆体都在 `ltm.*`；不要在 JS 里重写检索、抽取或遗忘公式。
- 插件默认用空白记忆体（新库、`resetOnStart: false`）。不要把 `results/` 下的旧库接成默认路径。
- 默认不引入第三方 Python 依赖：`PyYAML` 只能按需导入，`jieba` 缺失要有回退。
- 桥协议改动要同时改 `tests/test_bridge.py` 和 `dsh-plugin/test/tools.test.mjs`。
- 改完跑：`python -m pytest -q`、`node dsh-plugin/test/tools.test.mjs`、`node dsh-plugin/test/e2e.mjs`。

## 验证

```bash
pip install -e ".[dev]"
pytest
python eval/stage1/run_stage1.py
python eval/stage2/smoke.py
node dsh-plugin/test/tools.test.mjs
node dsh-plugin/test/e2e.mjs
```

阶段一检查 100 轮群聊能不能记对。阶段二冒烟检查每天几百条时，提示词和缓冲区有没有上限。完整一年的设定写在 `验证_阶段二_一年长期测试.md`。`e2e.mjs` 要拉起 python 子进程，受限沙箱里会 `spawn EPERM`，要在正常权限下跑。

## 更多说明

扩展步骤和插件示例见 `skills/ltm-memory/SKILL.md`。
