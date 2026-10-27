// ltm JSONL 桥（Aurabot 模块版）。
//
// 和 long_memory 仓库里 dsh-plugin/src/bridge.js 说同一套协议：一行一个请求，
// 一行一个响应。区别只在于它跑在 Aurabot 的模块进程里，每个模块一份子进程，
// 并且默认带 --blank（不预置阶段一那批人名）。
//
// 协议操作：ping / ingest / recall / sleep / stats / reset / dump

import { spawn } from 'node:child_process'
import path from 'node:path'
import { createInterface } from 'node:readline'

export class LtmBridge {
  constructor(opts = {}) {
    this.python = opts.python || 'python'
    this.srcPath = opts.srcPath || ''
    this.dbPath = opts.dbPath || ''
    this.napSentences = Number(opts.napSentences) || 12
    this.timeoutMs = Number(opts.timeoutMs) || 60000
    this.child = null
    this.pending = new Map()
    this.nextId = 1
    this.stderrTail = []
  }

  /** 发一条请求，等 Python 回一行。 */
  call(op, params = {}) {
    return new Promise((resolve, reject) => {
      let child
      try {
        child = this.ensure()
      } catch (error) {
        reject(error)
        return
      }
      const id = this.nextId++
      const timer = setTimeout(() => {
        this.pending.delete(id)
        reject(new Error(`ltm 桥超时（${op}，${this.timeoutMs}ms）`))
      }, this.timeoutMs)
      this.pending.set(id, { resolve, reject, timer })
      const line = JSON.stringify({ id, op, params }) + '\n'
      child.stdin.write(line, (error) => {
        if (!error) return
        this.pending.delete(id)
        clearTimeout(timer)
        reject(new Error(`ltm 桥写入失败：${error.message}`))
      })
    })
  }

  close() {
    const child = this.child
    this.child = null
    if (child) {
      try {
        child.stdin.end()
        child.kill()
      } catch (error) {}
    }
    this.failAll(new Error('ltm 桥已关闭'))
  }

  ensure() {
    const live = this.child
    if (live && live.exitCode === null && !live.killed) return live
    const args = [
      '-m',
      'ltm.service.bridge',
      '--db',
      this.dbPath,
      '--blank',
      '--nap-sentences',
      String(this.napSentences),
    ]
    const env = { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' }
    if (this.srcPath) env.PYTHONPATH = [this.srcPath, env.PYTHONPATH].filter(Boolean).join(path.delimiter)
    this.stderrTail = []
    const child = spawn(this.python, args, {
      env,
      cwd: this.srcPath || process.cwd(),
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true,
    })
    createInterface({ input: child.stdout }).on('line', (line) => this.onLine(line))
    child.stderr.setEncoding('utf8')
    child.stderr.on('data', (chunk) => {
      this.stderrTail.push(...String(chunk).split(/\r?\n/).filter(Boolean))
      if (this.stderrTail.length > 20) this.stderrTail.splice(0, this.stderrTail.length - 20)
    })
    child.on('error', (error) => {
      this.child = null
      this.failAll(new Error(`起不来 python（${this.python}）：${error.message}`))
    })
    child.on('exit', (code, signal) => {
      this.child = null
      const tail = this.stderrTail.slice(-4).join(' | ')
      this.failAll(new Error(`ltm 桥退出（code=${code} signal=${signal}）${tail ? '：' + tail : ''}`))
    })
    this.child = child
    return child
  }

  onLine(line) {
    let frame
    try {
      frame = JSON.parse(line)
    } catch (error) {
      this.stderrTail.push(`非 JSON 输出：${String(line).slice(0, 200)}`)
      return
    }
    const entry = this.pending.get(frame.id)
    if (!entry) return
    this.pending.delete(frame.id)
    clearTimeout(entry.timer)
    if (frame.ok) entry.resolve(frame.result)
    else entry.reject(new Error((frame.error && frame.error.message) || 'ltm 桥返回错误'))
  }

  failAll(error) {
    for (const [id, entry] of this.pending) {
      clearTimeout(entry.timer)
      entry.reject(error)
      this.pending.delete(id)
    }
  }
}
