import { spawn, spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { createInterface } from 'node:readline'
import { fileURLToPath } from 'node:url'

const PLUGIN_DIR = fileURLToPath(new URL('..', import.meta.url))
const PACKAGE_ROOT = path.resolve(PLUGIN_DIR, '..')
const PY_SRC = path.join(PACKAGE_ROOT, 'src')

/** 把一行请求变成 Python 侧 `Bridge.dispatch` 的一次调用。 */
export class MemoryBridge {
  constructor(config = {}) {
    this.config = config
    this.python = config.python ?? process.env.DSH_LTM_PYTHON ?? null
    this.pythonPath = config.pythonPath ?? defaultPythonPath()
    this.cwd = config.cwd ?? process.env.DSH_LTM_CWD ?? process.cwd()
    this.dbPath = config.dbPath ?? defaultDbPath()
    this.configPath = config.configPath ?? null
    this.resetOnStart = config.resetOnStart === true
    this.blank = config.blank !== false
    this.timeoutMs = config.timeoutMs ?? 30_000
    this.child = null
    this.pending = new Map()
    this.nextId = 1
    this.stderrTail = []
  }

  /** 发一条请求；op 是 Python 侧的操作名，params 原样传过去。 */
  async call(op, params = {}, signal) {
    if (signal?.aborted) throw new Error('ABORTED')
    const python = this.resolvePython()
    const child = this.ensureChild(python)
    const id = this.nextId++
    const line = `${JSON.stringify({ id, op, params })}\n`
    return await new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id)
        reject(new Error(`ltm 桥超时（${op}，${this.timeoutMs}ms）`))
      }, this.timeoutMs)
      const onAbort = () => {
        this.pending.delete(id)
        clearTimeout(timer)
        reject(new Error('ABORTED'))
      }
      this.pending.set(id, { resolve, reject, timer, onAbort, signal })
      signal?.addEventListener('abort', onAbort, { once: true })
      child.stdin.write(line, (error) => {
        if (!error) return
        this.pending.delete(id)
        clearTimeout(timer)
        reject(new Error(`ltm 桥写入失败：${error.message}`))
      })
    })
  }

  /** 关掉子进程；插件卸载或热重载时调用。 */
  close() {
    const child = this.child
    this.child = null
    if (child) {
      child.stdin.end()
      child.kill()
    }
    this.failAll(new Error('ltm 桥已关闭'))
  }

  /** 第一次调用时挑一个能跑的 Python：配置优先，其次平台默认候选。 */
  resolvePython() {
    if (this.python) return this.python
    const tried = []
    for (const candidate of pythonCandidates()) {
      tried.push(candidate)
      const probe = spawnSync(candidate, ['-c', 'pass'], { stdio: 'ignore', windowsHide: true })
      if (!probe.error && probe.status === 0) {
        this.python = candidate
        return candidate
      }
    }
    throw new Error(
      `找不到可用的 Python（试过：${tried.join('、')}）。请安装 Python 3.10+ 后重启 DSH，` +
        `或在 plugin 配置里写 python: 'C:/path/to/python.exe'。`,
    )
  }

  ensureChild(python) {
    if (this.child && this.child.exitCode === null && !this.child.killed) return this.child
    const args = ['-m', 'ltm.service.bridge', '--db', this.dbPath]
    if (this.configPath) args.push('--config', this.configPath)
    if (this.resetOnStart) args.push('--reset')
    if (this.blank) args.push('--blank')
    const env = { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' }
    if (this.pythonPath) {
      env.PYTHONPATH = [this.pythonPath, env.PYTHONPATH].filter(Boolean).join(path.delimiter)
    }
    this.stderrTail = []
    const child = spawn(python, args, {
      cwd: this.cwd,
      env,
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true,
    })
    createInterface({ input: child.stdout }).on('line', (line) => this.onLine(line))
    child.stderr.setEncoding('utf8')
    child.stderr.on('data', (chunk) => {
      this.stderrTail.push(...chunk.split(/\r?\n/).filter(Boolean))
      if (this.stderrTail.length > 20) this.stderrTail.splice(0, this.stderrTail.length - 20)
    })
    child.on('error', (error) => {
      this.child = null
      this.failAll(
        new Error(
          `无法启动 python（${python}）：${error.message}。` +
            `请在 plugin 配置里写 python: '<解释器路径>'。`,
        ),
      )
    })
    child.on('exit', (code, signal) => {
      this.child = null
      const tail = this.stderrTail.slice(-5).join(' | ')
      this.failAll(new Error(`ltm 桥退出（code=${code} signal=${signal}）：${tail}${exitHint(tail)}`))
    })
    this.child = child
    return child
  }

  onLine(line) {
    let frame
    try {
      frame = JSON.parse(line)
    } catch {
      this.stderrTail.push(`非 JSON 输出：${line.slice(0, 200)}`)
      return
    }
    const entry = this.pending.get(frame.id)
    if (!entry) return
    this.pending.delete(frame.id)
    clearTimeout(entry.timer)
    if (entry.signal) entry.signal.removeEventListener('abort', entry.onAbort)
    if (frame.ok) entry.resolve(frame.result)
    else {
      const error = new Error(frame.error?.message ?? 'ltm 桥返回错误')
      error.code = frame.error?.code
      entry.reject(error)
    }
  }

  failAll(error) {
    for (const [id, entry] of this.pending) {
      clearTimeout(entry.timer)
      if (entry.signal) entry.signal.removeEventListener('abort', entry.onAbort)
      entry.reject(error)
      this.pending.delete(id)
    }
  }
}

function defaultDbPath() {
  if (process.env.DSH_LTM_DB) return process.env.DSH_LTM_DB
  return path.join(dshHome(), 'ltm', 'memory.db')
}

/**
 * DSH 的 home 目录。宿主不一定会把 DSH_HOME 传进插件进程，
 * 但会把工作目录设成 `<DSH_HOME>/profiles/<name>`，从那里回推。
 */
function dshHome() {
  if (process.env.DSH_HOME) return process.env.DSH_HOME
  const parts = process.cwd().split(path.sep)
  const index = parts.lastIndexOf('profiles')
  if (index > 0) return parts.slice(0, index).join(path.sep) || path.sep
  return path.join(os.homedir(), '.dsh')
}

function defaultPythonPath() {
  if (process.env.DSH_LTM_PYTHONPATH) return process.env.DSH_LTM_PYTHONPATH
  return existsSync(path.join(PY_SRC, 'ltm')) ? PY_SRC : null
}

function pythonCandidates() {
  return process.platform === 'win32' ? ['python', 'py'] : ['python3', 'python']
}

function exitHint(stderr) {
  if (/No module named 'ltm'/.test(stderr)) {
    return '（Python 找不到 ltm：确认插件自带的 src 目录可读，或 pip install ltm-memory）'
  }
  if (/No module named 'yaml'/.test(stderr)) {
    return '（读取 YAML 配置需要 PyYAML：pip install PyYAML，或去掉 configPath）'
  }
  if (/No module named 'jieba'/.test(stderr)) {
    return '（可选依赖缺失：pip install jieba 可提升中文分词质量）'
  }
  return ''
}
