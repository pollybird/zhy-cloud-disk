import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'sync',
    component: () => import('./views/SyncView.vue'),
  },
  {
    path: '/setup',
    name: 'setup',
    component: () => import('./views/SetupWizard.vue'),
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('./views/SettingsView.vue'),
  },
  {
    path: '/department',
    name: 'department',
    component: () => import('./views/DepartmentView.vue'),
  },
  {
    // 兜底：未知路径统一回到首页，避免出现空白页
    path: '/:pathMatch(.*)*',
    redirect: '/',
  },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

// 守卫：未配置强制进向导；已配置禁止回到向导
// 判定标准必须与主进程 isConfigured() 保持一致（configured + serverUrl + syncPath），
// 否则配置残缺时（如 syncPath 丢失）主进程不恢复凭据而渲染层进入主页，
// 会导致所有请求报 "Invalid URL" 的死锁状态。
router.beforeEach(async (to) => {
  const settings = await window.zhy.getSettings()
  const ready = Boolean(
    settings.configured && settings.serverUrl && settings.syncPath,
  )
  if (!ready && to.name !== 'setup') return { name: 'setup' }
  if (ready && to.name === 'setup') return { name: 'sync' }
})

export default router
