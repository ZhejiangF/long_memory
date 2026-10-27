---
name: ltm-memory
description: >-
  Extend or verify the ltm long-term memory plugin: associative word graph,
  fact strength, personality gating, and nap/night consolidation. Use when
  editing this repository, adding a memory plugin, or running the staged
  dialogue checks.
---

# 长期记忆插件

规则以仓库根目录的 `AGENTS.md` 为准。本文件只写动手时的步骤。

## 先确认改动落在哪一层

- 换存储、嵌入、时钟、回答器：`src/ltm/adapters/`
- 换检索、抽取、打分：`src/ltm/components/`
- 改对外调用方式：`src/ltm/service/`
- 不在 `core` 里写业务分支

## 加一个插件

```python
from ltm.core.registry import register

@register("retriever", "recent_only")
def build(store, cfg):
    return RecentRetriever(store, cfg)
```

然后在配置的 `plugins` 里写上这个名字。不要为了接上它去改 `MemoryService` 的主流程。

## 接 DSH

仓库根目录就是 npm 包（`package.json`），`dsh-plugin/` 是 cordis 外壳，和 Python 侧只通过 JSONL 桥（`ltm.service.bridge`）通信。

- 加一个模型可见工具：在 `dsh-plugin/src/tools.js` 里写一个工具定义（`parameters`、`output.schema` 是 JSON Schema），再放进 `createTools` 返回的数组。
- 改协议：在 `src/ltm/service/bridge.py` 加 `_op_xxx` 并注册进 `_handlers()`，同步补 `tests/test_bridge.py`。
- 不要把检索、抽取逻辑写进 JS，那属于 `ltm.components`。
- 发布前确认 `package.json` 的 `files` 覆盖 `dsh-plugin/src`、`dsh-plugin/cordis.patch.yml`、`src/ltm`、`config/default.yaml`：`npm pack --dry-run` 能列全才算能装。

## 改完必跑

```bash
pytest
python eval/stage1/run_stage1.py
node dsh-plugin/test/tools.test.mjs
```

阶段一未通过时，先看打印出来的失败轮次：检索结果里有没有目标原话。有原话但回答错，改回答器；没有原话，改检索或抽取。不要把标准答案写进核心代码。

## 不要做的事

- 把规则或技能放进某一种编辑器的私有目录，导致别的 agent 看不到
- 在回复路径上调用抽取模型或重建整张图
- 让 `total_ms` 包含睡眠整理时间
