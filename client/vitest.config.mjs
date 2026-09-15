import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'node',
    include: ['tests/**/*.test.js'],
    testTimeout: 10000,
    // better-sqlite3 为 Electron ABI 编译，Node 下无法加载：
    // 涉及 mirror-db 的模块统一 vi.mock 隔离，原生库本身不做 Node 侧单测
  },
})
