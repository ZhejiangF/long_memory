/**
 * 模型可见的四个工具。参数和输出都是 DSH 的 ToolDefinition 形状：
 * parameters / output.schema 用 JSON Schema，render 返回 ContentBlock[]。
 */

function textOutput() {
  return {
    schema: {
      type: 'object',
      additionalProperties: false,
      properties: {
        text: { type: 'string' },
        count: { type: 'integer' },
      },
      required: ['text', 'count'],
    },
    render: (_args, value) => [{ type: 'text', text: value.text }],
  }
}

export function createTools({ bridge, config = {} }) {
  const sessionId = config.sessionId ?? 'dsh'
  const speaker = config.speaker ?? 'user'
  const recallLimit = config.recallLimit ?? 8
  const consolidateEvery = Number(config.consolidateEvery ?? 10)
  const loadLimit = Number(config.loadLimit ?? 50)
  let remembersSinceSave = 0

  const recall = {
    name: 'memory_recall',
    description:
      '按词语关联，从长期记忆里找回与问题相关的原话和事实。回答涉及过去的人、事、约定、偏好、承诺之前先调用它；没有命中就如实说没有相关记忆，不要编造。',
    parameters: {
      type: 'object',
      additionalProperties: false,
      properties: {
        query: { type: 'string', description: '要查的词或问题，例如“猫叫什么”。' },
        limit: { type: 'integer', description: `最多返回几条，默认 ${recallLimit}，上限 50。` },
        asker: { type: 'string', description: '提问者的名字或 id，影响“谁问的”加权。' },
      },
      required: ['query'],
    },
    output: textOutput(),
    timeoutMs: 20_000,
    async execute(args, exec) {
      const result = await bridge.call(
        'recall',
        {
          query: args.query,
          limit: args.limit ?? recallLimit,
          asker: args.asker ?? speaker,
          session_id: sessionId,
          ts: nowSeconds(),
        },
        exec?.signal,
      )
      return { text: renderRecall(result), count: result.count }
    },
  }

  const remember = {
    name: 'memory_remember',
    description:
      '把一句值得长期记住的原话写进长期记忆。用户提到自己的事、约定、偏好、计划或重要人际关系时调用；原话照抄，不要总结成结论。',
    parameters: {
      type: 'object',
      additionalProperties: false,
      properties: {
        text: { type: 'string', description: '要记住的原话。' },
        speaker: { type: 'string', description: '说话人的名字或 id，默认 user。' },
        session: { type: 'string', description: '会话 id，默认沿用插件配置。' },
      },
      required: ['text'],
    },
    output: textOutput(),
    timeoutMs: 20_000,
    async execute(args, exec) {
      const result = await bridge.call(
        'ingest',
        {
          text: args.text,
          speaker: args.speaker ?? speaker,
          session_id: args.session ?? sessionId,
          ts: nowSeconds(),
        },
        exec?.signal,
      )
      let text = renderRemember(result)
      if (consolidateEvery > 0) {
        remembersSinceSave += 1
        if (remembersSinceSave >= consolidateEvery) {
          const report = await bridge.call('sleep', { ts: nowSeconds() }, exec?.signal)
          remembersSinceSave = 0
          text += `\n${renderSleep(report)}（每 ${consolidateEvery} 次写入自动整理）`
        }
      }
      return { text, count: result.buffered }
    },
  }

  const sleep = {
    name: 'memory_sleep',
    description: '把缓冲区里攒着的原话立刻整理成句子、词语关联和事实。用户说“记住这些”或会话结束前想固化记忆时调用。',
    parameters: {
      type: 'object',
      additionalProperties: false,
      properties: {},
    },
    output: textOutput(),
    timeoutMs: 20_000,
    async execute(_args, exec) {
      const report = await bridge.call('sleep', { ts: nowSeconds() }, exec?.signal)
      return { text: renderSleep(report), count: Number(report.stage_stats?.sentences ?? 0) }
    },
  }

  const status = {
    name: 'memory_status',
    description: '查看记忆体现状：已记下的消息、句子、活跃事实和缓冲区条数，以及记忆体文件位置。',
    parameters: {
      type: 'object',
      additionalProperties: false,
      properties: {},
    },
    output: textOutput(),
    timeoutMs: 20_000,
    async execute(_args, exec) {
      const stats = await bridge.call('stats', {}, exec?.signal)
      return { text: renderStatus(stats), count: stats.messages }
    },
  }

  const save = {
    name: 'memory_save',
    description:
      '保存当前记忆：把缓冲区里攒着的原话立刻整理并写进记忆体。用户说“保存记忆”“记住这些”“先存一下”时调用。',
    parameters: {
      type: 'object',
      additionalProperties: false,
      properties: {},
    },
    output: textOutput(),
    timeoutMs: 20_000,
    async execute(_args, exec) {
      const report = await bridge.call('sleep', { ts: nowSeconds() }, exec?.signal)
      remembersSinceSave = 0
      return { text: `已保存。${renderSleep(report)}`, count: Number(report.stage_stats?.sentences ?? 0) }
    },
  }

  const load = {
    name: 'memory_load',
    description:
      '加载记忆体：列出当前记住的事实和最近的对话原话。用户问“你都记得什么”“把记忆读出来”时调用。',
    parameters: {
      type: 'object',
      additionalProperties: false,
      properties: {
        limit: { type: 'integer', description: `事实和原话各取几条，默认 ${loadLimit}，上限 50。` },
      },
    },
    output: textOutput(),
    timeoutMs: 20_000,
    async execute(args, exec) {
      const data = await bridge.call('dump', { limit: args.limit ?? loadLimit }, exec?.signal)
      const count = (data.facts?.length ?? 0) + (data.sentences?.length ?? 0)
      return { text: renderLoad(data), count }
    },
  }

  const reset = {
    name: 'memory_reset',
    description:
      '清空当前记忆体：删除所有消息、句子、事实和词表，保留数据库文件与配置。用户明确要求“清空记忆”“忘掉一切”时才调用，必须带 confirm=true。',
    parameters: {
      type: 'object',
      additionalProperties: false,
      properties: {
        confirm: { type: 'boolean', description: '确认清空，必须是 true。' },
      },
      required: ['confirm'],
    },
    output: textOutput(),
    timeoutMs: 20_000,
    async execute(args, exec) {
      if (args.confirm !== true) {
        return { text: '未清空：需要 confirm=true 才会执行。', count: 0 }
      }
      const result = await bridge.call('reset', {}, exec?.signal)
      remembersSinceSave = 0
      return { text: renderReset(result), count: Number(result.cleared?.messages ?? 0) }
    },
  }

  return [recall, remember, sleep, save, load, reset, status]
}

function renderRecall(result) {
  if (!result.count) return '没有找到相关记忆。'
  const lines = result.items.map((item, index) => `${index + 1}. ${item.rendered || item.text}`)
  return `命中 ${result.count} 条：\n${lines.join('\n')}`
}

function renderRemember(result) {
  const buffered = result.buffered ?? 0
  const naps = (result.sleep ?? []).map(renderSleep)
  const head = `已记下（${result.speaker_id}），缓冲区 ${buffered} 句。`
  return naps.length ? `${head}\n${naps.join('\n')}` : head
}

function renderSleep(report) {
  const stats = report?.stage_stats ?? {}
  const sentences = stats.sentences ?? 0
  const facts = stats.facts ?? 0
  return `整理完成：句子 ${sentences}，事实 ${facts}，用时 ${report?.duration_ms ?? 0}ms。`
}

function renderStatus(stats) {
  const bytes = formatBytes(stats.db_bytes)
  return [
    `记忆体：${stats.db}（${bytes}）`,
    `消息 ${stats.messages}，句子 ${stats.sentences}，缓冲区 ${stats.buffer}`,
    `事实：活跃 ${stats.facts_active}，休眠 ${stats.facts_dormant}；词表 ${stats.vocab}`,
  ].join('\n')
}

function renderLoad(data) {
  const facts = data?.facts ?? []
  const sentences = data?.sentences ?? []
  if (!facts.length && !sentences.length) return '记忆体是空的。'
  const lines = []
  if (facts.length) {
    lines.push(`事实 ${facts.length} 条：`)
    facts.forEach((fact, index) => {
      lines.push(`${index + 1}. ${fact.owner}｜${fact.text}（重要度 ${fact.importance}）`)
    })
  }
  if (sentences.length) {
    lines.push(`最近原话 ${sentences.length} 条：`)
    for (const sentence of sentences.slice(0, 10)) {
      lines.push(`- ${sentence.speaker}：${sentence.text}`)
    }
  }
  return lines.join('\n')
}

function renderReset(result) {
  const cleared = result?.cleared ?? {}
  return `已清空记忆体：消息 ${cleared.messages ?? 0}，句子 ${cleared.sentences ?? 0}，事实 ${cleared.facts ?? 0}。`
}

function formatBytes(value) {
  const size = Number(value ?? 0)
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)}MB`
  if (size >= 1024) return `${(size / 1024).toFixed(1)}KB`
  return `${size}B`
}

function nowSeconds() {
  return Math.floor(Date.now() / 1000)
}
