// 打包前清掉 __pycache__，避免把本地字节码带进 npm 包。
import { rmSync, readdirSync, statSync } from 'node:fs'
import path from 'node:path'

const root = process.argv[2] ?? process.cwd()

function walk(dir) {
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name)
    let stat
    try {
      stat = statSync(full)
    } catch {
      continue
    }
    if (stat.isDirectory()) {
      if (name === '__pycache__') {
        try {
          rmSync(full, { recursive: true, force: true })
        } catch {
          // 受限环境删不掉字节码不影响运行，继续打包即可。
        }
        continue
      }
      walk(full)
    }
  }
}

walk(path.join(root, 'src'))
