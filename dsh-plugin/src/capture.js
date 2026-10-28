/**
 * 从 DSH 会话事件里提取要写进记忆的一条消息。
 *
 * 和 Python 库的 ChatAgent.handle 对齐：真人发言和助手回复都进缓冲区；
 * 插件注入的上下文（AGENTS.md、skill 目录、goal 续跑等）不算对话，跳过。
 */

/** 拼出消息里的纯文本；非文本块（图片、工具结果）忽略。 */
export function textOf(message) {
  const blocks = Array.isArray(message?.content) ? message.content : []
  return blocks
    .filter((block) => block && block.type === 'text' && typeof block.text === 'string')
    .map((block) => block.text)
    .join('\n')
    .trim()
}

function seconds(time) {
  const value = Number(time)
  return Number.isFinite(value) && value > 0 ? Math.floor(value / 1000) : Math.floor(Date.now() / 1000)
}

/**
 * @returns 可直接传给桥 `ingest` 的参数；不该记的返回 null。
 */
export function describeCapture(session, event, config = {}) {
  if (!session || !event || !event.type) return null
  const sessionId = String(session.id ?? config.sessionId ?? 'dsh')

  if (event.type === 'user/message') {
    const message = event.data
    // 只抓真人输入：插件注入的上下文 source.kind 是 'plugin'，goal 续跑也不是新话。
    if (!message || message.source?.kind !== 'user') return null
    const text = textOf(message)
    if (!text) return null
    return { text, speaker: config.userSpeaker ?? 'user', session_id: sessionId, ts: seconds(event.time) }
  }

  if (event.type === 'assistant/message') {
    if (config.captureAssistant === false) return null
    const text = textOf(event.data?.message)
    if (!text) return null
    return { text, speaker: config.selfSpeaker ?? 'self', session_id: sessionId, ts: seconds(event.time) }
  }

  return null
}
