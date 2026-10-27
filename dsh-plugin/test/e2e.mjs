/**
 * 端到端：Node 桥真的拉起 python -m ltm.service.bridge，走完
 * 写入 → 整理 → 召回 → 状态 四个工具。
 *
 * 运行：node dsh-plugin/test/e2e.mjs
 */

import assert from 'node:assert/strict'
import { mkdtempSync, rmSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { MemoryBridge } from '../src/bridge.js'
import { createTools } from '../src/tools.js'

const dir = mkdtempSync(path.join(os.tmpdir(), 'ltm-e2e-'))
const bridge = new MemoryBridge({ dbPath: path.join(dir, 'memory.db'), timeoutMs: 60_000 })
const tools = createTools({ bridge, config: {} })
const byName = (toolName) => tools.find((tool) => tool.name === toolName)

try {
  const ping = await bridge.call('ping', {})
  assert.equal(ping.pong, true)

  const remembered = await byName('memory_remember').execute(
    { text: '我家猫叫橘子。', speaker: '张磊' },
    {},
  )
  assert.equal(remembered.count, 1)

  const slept = await byName('memory_sleep').execute({}, {})
  assert.match(slept.text, /整理完成/)

  const recalled = await byName('memory_recall').execute({ query: '猫叫什么' }, {})
  assert.ok(recalled.count >= 1, '召回应该至少命中一条')
  assert.match(recalled.text, /橘子/)

  const status = await byName('memory_status').execute({}, {})
  assert.match(status.text, /消息 1/)

  const loaded = await byName('memory_load').execute({}, {})
  assert.match(loaded.text, /橘子/)

  const saved = await byName('memory_save').execute({}, {})
  assert.match(saved.text, /已保存/)

  const cleared = await byName('memory_reset').execute({ confirm: true }, {})
  assert.match(cleared.text, /已清空记忆体/)

  const afterReset = await byName('memory_status').execute({}, {})
  assert.match(afterReset.text, /消息 0/)

  console.log('E2E OK')
  console.log(status.text.replace(/\n/g, ' | '))
  console.log(loaded.text.replace(/\n/g, ' | '))
  console.log(cleared.text)
} finally {
  bridge.close()
  await new Promise((resolve) => setTimeout(resolve, 300))
  try {
    rmSync(dir, { recursive: true, force: true })
  } catch {
    // Windows 上刚退出的子进程可能还占着 -wal 文件，临时目录留给系统清理。
  }
}
