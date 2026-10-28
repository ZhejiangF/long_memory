/**
 * dsh-plugin-ltm：把 ltm 长期记忆引擎接进 DSH。
 *
 * 和 Python 库的 ChatAgent.handle 一样：每条真人发言和助手回复都会自动进缓冲区，
 * 攒够阈值再整理；工具只负责查询、手动保存、加载和清空。
 *
 * host-only 的 cordis 插件：导出 name / inject / apply，进程随 fiber 卸载回收。
 */

import { MemoryBridge } from './bridge.js'
import { describeCapture } from './capture.js'
import { createTools } from './tools.js'

export const name = 'dsh-plugin-ltm'

// 等 tools 服务就绪再激活；加载顺序由服务可用性驱动。
export const inject = ['tools']

export function apply(ctx, config = {}) {
  const bridge = new MemoryBridge(config)
  const dispose = () => bridge.close()
  if (typeof ctx.effect === 'function') ctx.effect(() => dispose)
  else ctx.on('dispose', dispose)

  if (config.autoCapture !== false) {
    ctx.on('session/event', (session, event) => {
      const payload = describeCapture(session, event, config)
      if (!payload) return
      // 事件是 emit 模式：不能阻塞，也不能把异常抛回会话。
      bridge.call('ingest', payload).catch((error) => {
        console.error('[dsh-plugin-ltm] 自动记下失败：', error?.message ?? error)
      })
    })
  }

  for (const tool of createTools({ bridge, config })) {
    ctx.tools.register(tool)
  }
}
