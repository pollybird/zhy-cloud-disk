import { defineConfig } from 'vitest/config'

// 前端单元测试：纯函数逻辑（node 环境，无需 jsdom）
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.js'],
  },
})
