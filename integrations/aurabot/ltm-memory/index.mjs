// Aurabot 模块：把记忆换成 long_memory（ltm）的记忆体 + 热区记忆。
//
// 做的事：
//   1. QQ 里每一句收发的消息都进 ltm（同一个 memory.db，和 DSH 的 ltm 工具共用一个记忆库）
//   2. 每轮说话前，用 ltm 的 recall 把「事实 + 热区原话 + 还没整理进热区的缓冲」拼成一段记忆块，
//      再补上「刚才几条消息」——短回复（「八点」「嗯」）没有关键词，检索不出来，
//      不补就接不上上一句（实测：她问「你猜我几点睡的」，你答「八点」，她却问「八点怎么了」）
//   3. 每轮开头换一个新的 DSH 会话，所以聊天窗口里没有更早的对话——
//      她要回忆只能靠上面的记忆块，不靠窗口上下文
//   4. remember / recall_memory 两个工具改成读写 ltm
//
// 前提：面板里要把内置「记忆」模块关掉（memory.enabled = false），否则它还会往老记忆库里写。

import os from 'node:os'
import path from 'node:path'
import { LtmBridge } from './ltm-bridge.mjs'

const DEFAULT_SRC = 'G:\\wangtianfan\\long_memory\\src'

function defaultDb() {
  const home = process.env.USERPROFILE || os.homedir()
  return path.join(home, '.dsh', 'ltm', 'memory.db')
}

function num(value, fallback) {
  const n = Number(value)
  return Number.isFinite(n) && n > 0 ? n : fallback
}

function flag(value, fallback = true) {
  if (value === undefined || value === null || value === '') return fallback
  if (typeof value === 'boolean') return value
  return !['false', '0', 'off', 'no'].includes(String(value).toLowerCase())
}

/** 把交给她的内容里的文字部分抽出来，当检索 query。 */
function textOfContent(content) {
  if (!Array.isArray(content)) return ''
  return content
    .filter((block) => block && block.type === 'text' && typeof block.text === 'string')
    .map((block) => block.text)
    .join('\n')
}

export default {
  id: 'ltm-memory',
  name: 'LTM 长期记忆',
  version: '0.1.2',
  api: 1,
  description: '用 long_memory（ltm）的记忆体和热区记忆说话：每轮先想起，再回；不靠聊天窗口的上下文',
  defaults: {
    python: 'python',
    srcPath: DEFAULT_SRC,
    dbPath: '',
    napSentences: 12,
    recallLimit: 8,
    factsLimit: 8,
    recentCount: 6,
    budget: 1800,
    freshWindow: true,
    ingestGroups: true,
  },
  settings: [
    { key: 'python', label: 'Python 解释器', type: 'text', hint: '要能 import ltm；默认用 PATH 里的 python' },
    { key: 'srcPath', label: 'ltm 源码目录', type: 'text', hint: '会加进 PYTHONPATH' },
    { key: 'dbPath', label: '记忆库路径', type: 'text', hint: '留空就跟着 DSH 用 ~/.dsh/ltm/memory.db（和 ltm 工具共用一个库）' },
    { key: 'napSentences', label: '攒几句整理进热区', type: 'number', min: 4, max: 600, step: 1, hint: '越小越快进热区，整理也越频繁' },
    { key: 'recallLimit', label: '每轮想起几条', type: 'number', min: 1, max: 50, step: 1 },
    { key: 'factsLimit', label: '常驻事实几条', type: 'number', min: 0, max: 50, step: 1 },
    { key: 'recentCount', label: '带上刚才几条消息', type: 'number', min: 0, max: 20, step: 1, hint: '短回复要靠它接上上一句；0 = 不带' },
    { key: 'budget', label: '记忆块字数上限', type: 'number', min: 200, max: 8000, step: 100 },
    { key: 'freshWindow', label: '每轮开新会话', type: 'switch', hint: '打开后聊天窗口里没有更早的对话，只靠记忆块' },
    { key: 'ingestGroups', label: '群里的话也记', type: 'switch' },
  ],

  setup(api) {
    const options = () => {
      const s = api.settings() || {}
      return {
        python: String(s.python || 'python'),
        srcPath: String(s.srcPath || DEFAULT_SRC),
        dbPath: String(s.dbPath || defaultDb()),
        napSentences: num(s.napSentences, 12),
        recallLimit: num(s.recallLimit, 8),
        factsLimit: Number(s.factsLimit) >= 0 ? Number(s.factsLimit) : 8,
        recentCount: Number(s.recentCount) >= 0 ? Number(s.recentCount) : 6,
        budget: num(s.budget, 1800),
        freshWindow: flag(s.freshWindow, true),
        ingestGroups: flag(s.ingestGroups, true),
      }
    }

    let bridge = null
    let bridgeKey = ''
    let tail = Promise.resolve() // 入库串行，保证「先记下这句，再想起」
    let lastBlock = { at: 0, chatId: '', text: '' }
    const names = new Map() // QQ 号 → 昵称，只用来把 qq:123 显示成人名
    const recentIn = new Map() // 同一条消息会被派发两次，按 3 秒窗口去重

    /** 同一个聊天里、同一个人、同样的字，3 秒内只算一次。 */
    function isRepeated(chatId, speaker, text) {
      const key = `${chatId}|${speaker}|${text}`
      const now = Date.now()
      const prev = recentIn.get(key) || 0
      recentIn.set(key, now)
      if (recentIn.size > 400) {
        for (const [k, t] of recentIn) if (now - t > 60_000) recentIn.delete(k)
      }
      return now - prev < 3000
    }

    /** 设置变了就换一个子进程（库和解释器都可能是新的）。 */
    function ltm() {
      const o = options()
      const key = [o.python, o.srcPath, o.dbPath, o.napSentences].join('|')
      if (bridge && bridgeKey === key) return bridge
      if (bridge) bridge.close()
      bridge = new LtmBridge(o)
      bridgeKey = key
      return bridge
    }

    function ingest(text, speaker, sessionId, meta) {
      const body = String(text || '').trim()
      if (!body) return tail
      const ts = Date.now() / 1000
      tail = tail
        .then(() => ltm().call('ingest', { text: body, speaker, session_id: sessionId, ts, meta: meta || {} }))
        .catch((error) => api.log.warn(`ltm 入库失败：${error.message}`))
      return tail
    }

    /** 她发出去的话带着 <sticker:名字>、<voice>、||| 这些发送标记，入库前先洗掉。 */
    function cleanOut(text) {
      return String(text || '')
        .replace(/<sticker:[^>]*>/g, '')
        .replace(/<\/?voice>/g, '')
        .replace(/<poke>/g, '')
        .replace(/\|\|\|/g, ' ')
        .replace(/[ \t]{2,}/g, ' ')
        .trim()
    }

    // ---- 1. 聊天流水进 ltm ----
    api.on('activity', (event) => {
      if (!event || !event.chatId) return
      const o = options()
      if (event.chatId.startsWith('group:') && !o.ingestGroups) return
      if (event.kind === 'in') {
        const uid = String(event.userId || '')
        if (uid) {
          // 主人统一叫「主人」，别的人用群名片 / 昵称，都没有就留 qq:号
          const cfg = api.config() || {}
          names.set(uid, event.owner ? String(cfg.ownerName || '主人') : String(event.nickname || `qq:${uid}`))
        }
        if (isRepeated(event.chatId, uid, event.text)) return
        ingest(event.text, `qq:${uid}`, event.chatId)
      } else if (event.kind === 'out') {
        const said = cleanOut(event.reply)
        if (said) ingest(said, 'self', event.chatId)
      }
    })

    /** Aurabot 会把同一条消息派发两次，交给她之前先把重复的行折掉。 */
    function tidy(content) {
      if (!Array.isArray(content)) return content
      return content.map((block) => {
        if (!block || block.type !== 'text' || typeof block.text !== 'string') return block
        if (!block.text.includes('【私聊】')) return block
        const lines = []
        for (const line of block.text.split('\n')) {
          if (lines.length && lines[lines.length - 1] === line) continue
          lines.push(line)
        }
        return { ...block, text: lines.join('\n') }
      })
    }

    // ---- 2. 每轮：开新窗口 + 把记忆块放在最前面 ----
    api.on('prompt', async (content, info = {}) => {
      const { chat, senderId, queryText, steer } = info || {}
      if (!chat || chat.kind === 'system') return content
      const o = options()
      if (o.freshWindow && !steer) {
        try {
          api.core.hub.resetChat(chat.chatId)
        } catch (error) {
          api.log.debug(`换新会话失败：${error.message}`)
        }
      }
      const query = String(queryText || textOfContent(content) || '').slice(-600).trim()
      if (!query) return content
      await tail // 这句先入库，再检索，顺序不能反
      const block = await compose(chat, query, senderId)
      if (!block) return tidy(content)
      lastBlock = { at: Date.now(), chatId: chat.chatId, text: block }
      return [{ type: 'text', text: block }, ...(Array.isArray(content) ? tidy(content) : [])]
    })

    /** 记忆块：常驻事实（记忆体）+ 检索到的内容 + 刚才几条消息。 */
    async function compose(chat, query, senderId) {
      const o = options()
      const asker = senderId ? `qq:${senderId}` : 'self'
      let recalled = null
      let dumped = null
      try {
        recalled = await ltm().call('recall', {
          query,
          asker,
          session_id: chat.chatId,
          limit: o.recallLimit,
        })
      } catch (error) {
        api.log.warn(`ltm 检索失败：${error.message}`)
      }
      if (o.factsLimit > 0 || o.recentCount > 0) {
        try {
          // 多要一条：最后那条就是这次刚入库的这句话，渲染时去掉
          dumped = await ltm().call('dump', {
            limit: o.factsLimit,
            session_id: chat.chatId,
            recent: o.recentCount + 1,
          })
        } catch (error) {
          api.log.debug(`ltm 读库失败：${error.message}`)
        }
      }
      if (!recalled && !dumped) return ''
      return render(o, recalled, dumped, query)
    }

    /** 把检索结果里的 qq:123 换成昵称、把会话号从原话里去掉，免得她读到一堆编号。 */
    function pretty(text) {
      return String(text || '')
        .replace(/｜(?:private|group|system):[^｜]*｜/g, '｜')
        .replace(/｜self\]/g, '｜她]')
        .replace(/qq:(\d+)/g, (all, uid) => names.get(uid) || all)
    }

    function render(o, recalled, dumped, query) {
      const header =
        '【长期记忆】你脑子里现在只有下面这些。聊天窗口是空的：除了这些和这次的新消息，更早的对话你都不记得，也别假装记得。'
      const seen = new Set()
      const facts = []
      for (const fact of (dumped && dumped.facts) || []) {
        const text = String(fact.text || '').trim()
        if (!text || seen.has(text)) continue
        seen.add(text)
        facts.push(`- ${pretty(text)}`)
      }

      const items = (recalled && recalled.items) || []
      const hitFacts = []
      const words = []
      for (const item of items) {
        const text = String(item.text || '').trim()
        if (item.source === 'fact') {
          if (text && !seen.has(text)) {
            seen.add(text)
            hitFacts.push(`- ${pretty(text)}`)
          }
        } else if (item.rendered) {
          const line = pretty(item.rendered)
          if (line && !words.includes(line)) words.push(line)
        }
      }

      // 刚才几条消息：短回复没有关键词，检索不出来，必须整段带上
      const recent = []
      const dumpedRecent = (dumped && dumped.recent) || []
      const list = dumpedRecent.slice()
      const lastOne = list[list.length - 1]
      if (lastOne && String(lastOne.text || '').trim() === String(query || '').trim()) list.pop()
      const shown = words.join('\n')
      for (const item of list) {
        const parts = String(item.text || '')
          .split(/\n+/)
          .map((s) => s.trim())
          .filter(Boolean)
        const keep = parts.filter((p) => !shown.includes(p))
        if (!keep.length) continue
        const who = item.speaker === 'self' ? '她' : pretty(item.speaker || '谁')
        recent.push(`- ${who}：${keep.join(' / ')}`)
      }

      const factBlock = facts.length ? ['■ 你记得的事：', ...facts] : []
      const hitBlock = hitFacts.length ? ['■ 和这次有关的：', ...hitFacts] : []
      const wordsHead = '■ 想起来的原话（标「未整理」的是刚说不久、还没并进热区的）：'
      const recentBlock = recent.length ? ['■ 刚才的对话：', ...recent] : []

      // 超预算时先砍「想起来的原话」，事实和刚才的对话留着
      let keep = words.length
      let out = ''
      for (;;) {
        const mid = keep > 0 ? [wordsHead, ...words.slice(0, keep)] : []
        out = [header, ...factBlock, ...hitBlock, ...mid, ...recentBlock].join('\n')
        if (out.length <= o.budget || keep === 0) break
        keep -= 1
      }
      if (!factBlock.length && !hitBlock.length && !words.length) {
        out = [header, '（关于这次，暂时没想起什么）', ...recentBlock].join('\n')
      }
      if (out.length > o.budget) out = `${out.slice(0, o.budget)}\n（记忆太多，后面的截掉了）`
      return out
    }

    // ---- 3. 工具：她自己记 / 她自己去翻 ----
    api.tool(({ chat }) => {
      if (!chat || chat.kind === 'system') return []
      return [
        api.defineTool({
          name: 'remember',
          description: '把一件值得长期记住的事写进长期记忆（名字、喜好、过敏、约定、重要的事）。一条只写一件事，主语写清楚；日常琐事不用记，记的时候安静地记。',
          properties: {
            text: { type: 'string', description: '一句话，主语写清楚，比如「主人 对芒果过敏」' },
          },
          required: ['text'],
          execute: async ({ text }) => {
            const body = String(text || '').trim()
            if (!body) return { ok: false, message: '要记的内容是空的' }
            await ingest(body, chat.kind === 'private' ? `qq:${chat.userId}` : 'self', chat.chatId, { manual: true })
            return { ok: true, message: '记住了' }
          },
        }),
        api.defineTool({
          name: 'recall_memory',
          description: '翻长期记忆：想不起对方以前说过什么、喜欢什么、约过什么时用，query 写关键词或一句话。',
          properties: {
            query: { type: 'string', description: '想找什么' },
          },
          required: ['query'],
          execute: async ({ query }) => {
            await tail
            try {
              const r = await ltm().call('recall', {
                query: String(query || ''),
                asker: `qq:${chat.userId || ''}`,
                session_id: chat.chatId,
                limit: options().recallLimit,
              })
              const lines = (r.items || []).map((it) => pretty(it.rendered || it.text)).filter(Boolean)
              return lines.length
                ? { ok: true, message: lines.join('\n') }
                : { ok: true, message: '没想起相关的事' }
            } catch (error) {
              return { ok: false, message: `记忆库没打开：${error.message}` }
            }
          },
        }),
      ]
    })

    // ---- 4. 规则：告诉她窗口里没有旧对话 ----
    api.rule(() =>
      '你的长期记忆在每轮开头给你的【长期记忆】里，聊天窗口里没有更早的对话。' +
        '「刚才的对话」那几行是紧挨着这次的上下文，接话要接得上；再往前的事，记忆里没有就是不知道，' +
        '直接问对方，不要猜，也不要说「你之前说过」除非记忆里有。',
    )

    // ---- 5. 面板/排查用 ----
    api.route('/state', async () => {
      const o = options()
      const out = { ok: true, settings: o, last: lastBlock }
      try {
        out.stats = await ltm().call('stats', {})
        out.recent = await ltm().call('dump', { limit: 10 })
      } catch (error) {
        out.ok = false
        out.message = error.message
      }
      return out
    })

    /** 清空记忆库（调试 / 重新开始用）。 */
    api.route('/reset', async () => {
      const r = await ltm().call('reset', {})
      lastBlock = { at: 0, chatId: '', text: '' }
      return { ok: true, ...r }
    })

    api.onDispose(() => {
      if (bridge) bridge.close()
    })
    api.log.info(`LTM 记忆已接上：${options().dbPath}`)
    return {
      remember: (text, chatId) => ingest(text, 'self', chatId || 'system:memory', { manual: true }),
      recall: async (query, chatId) =>
        ltm().call('recall', { query, asker: 'self', session_id: chatId || 'system:memory', limit: 8 }),
      stats: () => ltm().call('stats', {}),
    }
  },
}
