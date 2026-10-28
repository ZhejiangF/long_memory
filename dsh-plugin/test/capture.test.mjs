import assert from 'node:assert/strict'
import test from 'node:test'

import { describeCapture, textOf } from '../src/capture.js'

const session = { id: 's-1' }

function userEvent(text, kind = 'user', time = 1_700_000_000_000) {
  return {
    type: 'user/message',
    time,
    data: {
      id: 'm1',
      role: 'user',
      content: [{ type: 'text', text }],
      source: { kind },
    },
  }
}

function assistantEvent(text, time = 1_700_000_060_000) {
  return {
    type: 'assistant/message',
    time,
    data: {
      turn: 1,
      step: 1,
      message: {
        id: 'm2',
        role: 'assistant',
        content: [{ type: 'text', text }],
        source: { kind: 'model' },
      },
    },
  }
}

test('提取文本只取 text 块', () => {
  assert.equal(
    textOf({ content: [{ type: 'text', text: '你好' }, { type: 'image', data: 'x' }, { type: 'text', text: '再见' }] }),
    '你好\n再见',
  )
  assert.equal(textOf({ content: [] }), '')
  assert.equal(textOf({}), '')
})

test('真人发言会被记下', () => {
  const payload = describeCapture(session, userEvent('我家猫叫橘子。'), {})
  assert.equal(payload.text, '我家猫叫橘子。')
  assert.equal(payload.speaker, 'user')
  assert.equal(payload.session_id, 's-1')
  assert.equal(payload.ts, 1_700_000_000)
})

test('插件注入的上下文不记', () => {
  assert.equal(describeCapture(session, userEvent('AGENTS.md 内容', 'plugin'), {}), null)
  assert.equal(describeCapture(session, userEvent('goal 续跑', 'model'), {}), null)
})

test('助手回复会被记下，可关闭', () => {
  const payload = describeCapture(session, assistantEvent('好的，我记住了。'), {})
  assert.equal(payload.speaker, 'self')
  assert.equal(payload.text, '好的，我记住了。')

  assert.equal(describeCapture(session, assistantEvent('不记这条'), { captureAssistant: false }), null)
})

test('空消息、非对话事件、缺参数都返回 null', () => {
  assert.equal(describeCapture(session, userEvent('   '), {}), null)
  assert.equal(describeCapture(session, { type: 'tool/result', time: 1, data: {} }, {}), null)
  assert.equal(describeCapture(null, userEvent('x'), {}), null)
  assert.equal(describeCapture(session, null, {}), null)
})

test('没有 event.time 时退回当前时间', () => {
  const before = Math.floor(Date.now() / 1000)
  const payload = describeCapture(session, userEvent('没有时间戳', 'user', null), {})
  assert.ok(payload.ts >= before)
})
