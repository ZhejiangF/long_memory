import assert from 'node:assert/strict'
import test from 'node:test'

import { apply, inject, name } from '../src/index.js'
import { createTools } from '../src/tools.js'

function fakeBridge(results = {}) {
  const calls = []
  return {
    calls,
    async call(op, params) {
      calls.push({ op, params })
      return results[op] ?? {}
    },
  }
}

test('插件导出 cordis 插件需要的三个成员', () => {
  assert.equal(name, 'dsh-plugin-ltm')
  assert.deepEqual(inject, ['tools'])
  assert.equal(typeof apply, 'function')
})

test('apply 注册四个记忆工具，并在卸载时回收桥', () => {
  const registered = []
  const disposers = []
  const ctx = {
    effect(fn) {
      disposers.push(fn())
    },
    tools: { register(tool) { registered.push(tool) } },
  }
  apply(ctx, {})
  assert.deepEqual(
    registered.map((tool) => tool.name).sort(),
    ['memory_recall', 'memory_remember', 'memory_sleep', 'memory_status'],
  )
  for (const tool of registered) {
    assert.equal(typeof tool.description, 'string')
    assert.equal(tool.parameters.type, 'object')
    assert.equal(tool.output.schema.type, 'object')
    assert.equal(typeof tool.execute, 'function')
    assert.equal(typeof tool.output.render, 'function')
  }
  assert.equal(disposers.length, 1)
  disposers[0]()
})

test('memory_recall 把结果渲染成可读文本并回报条数', async () => {
  const bridge = fakeBridge({
    recall: {
      count: 2,
      items: [
        { text: '我家猫叫橘子。', rendered: '张磊：我家猫叫橘子。' },
        { text: '橘子昨天吐毛球。', rendered: '林夏：橘子昨天吐毛球。' },
      ],
    },
  })
  const [recall] = createTools({ bridge, config: { recallLimit: 5 } })
  const value = await recall.execute({ query: '猫叫什么' }, { signal: undefined })
  assert.equal(value.count, 2)
  assert.match(value.text, /命中 2 条/)
  assert.match(value.text, /橘子/)
  assert.deepEqual(bridge.calls[0].params.query, '猫叫什么')
  assert.equal(bridge.calls[0].params.limit, 5)
  assert.deepEqual(recall.output.render({ query: 'x' }, value), [{ type: 'text', text: value.text }])
})

test('memory_recall 没有命中时如实说没有', async () => {
  const bridge = fakeBridge({ recall: { count: 0, items: [] } })
  const [recall] = createTools({ bridge, config: {} })
  const value = await recall.execute({ query: '无关问题' }, {})
  assert.equal(value.text, '没有找到相关记忆。')
})

test('memory_remember 用配置的默认说话人和会话', async () => {
  const bridge = fakeBridge({ ingest: { speaker_id: 'zhanglei', buffered: 3, sleep: [] } })
  const [, remember] = createTools({ bridge, config: { sessionId: '生活群', speaker: '张磊' } })
  const value = await remember.execute({ text: '我家猫叫橘子。' }, {})
  assert.equal(bridge.calls[0].op, 'ingest')
  assert.equal(bridge.calls[0].params.speaker, '张磊')
  assert.equal(bridge.calls[0].params.session_id, '生活群')
  assert.match(value.text, /缓冲区 3 句/)
})

test('memory_sleep 和 memory_status 渲染引擎回报的数字', async () => {
  const bridge = fakeBridge({
    sleep: { kind: 'nap', duration_ms: 12.3, stage_stats: { sentences: 4, facts: 1 } },
    stats: { db: 'x.db', db_bytes: 2048, messages: 9, sentences: 4, buffer: 2, facts_active: 1, facts_dormant: 0, vocab: 30 },
  })
  const tools = createTools({ bridge, config: {} })
  const sleep = tools.find((tool) => tool.name === 'memory_sleep')
  const status = tools.find((tool) => tool.name === 'memory_status')
  const slept = await sleep.execute({}, {})
  assert.match(slept.text, /句子 4，事实 1/)
  const stats = await status.execute({}, {})
  assert.match(stats.text, /消息 9/)
  assert.match(stats.text, /2\.0KB/)
})
