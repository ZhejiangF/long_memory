/**
 * dsh-plugin-ltm：把 ltm 长期记忆引擎接成 DSH 的模型可见工具。
 *
 * 这是一个 host-only 的 cordis 插件：导出 name / inject / apply 三个成员，
 * 用 ctx.tools.register 注册工具，进程随插件 fiber 卸载而回收。
 */

import { MemoryBridge } from './bridge.js'
import { createTools } from './tools.js'

export const name = 'dsh-plugin-ltm'

// 等 tools 服务就绪再激活；加载顺序由服务可用性驱动。
export const inject = ['tools']

export function apply(ctx, config = {}) {
  const bridge = new MemoryBridge(config)
  const dispose = () => bridge.close()
  if (typeof ctx.effect === 'function') ctx.effect(() => dispose)
  else ctx.on('dispose', dispose)

  for (const tool of createTools({ bridge, config })) {
    ctx.tools.register(tool)
  }
}
