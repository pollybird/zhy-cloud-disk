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
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

// 守卫：未配置强制进向导；已配置禁止回到向导
router.beforeEach(async (to) => {
  const settings = await window.zhy.getSettings()
  if (!settings.configured && to.name !== 'setup') return { name: 'setup' }
  if (settings.configured && to.name === 'setup') return { name: 'sync' }
})

export default router
