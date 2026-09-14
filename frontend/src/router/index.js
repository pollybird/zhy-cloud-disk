import { createRouter, createWebHistory } from 'vue-router'
import { useAppStore } from '../stores/app'
import { useUserStore } from '../stores/user'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/install',
      name: 'install',
      component: () => import('../views/setup/SetupView.vue'),
      meta: { public: true, setup: true },
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/auth/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/register',
      name: 'register',
      component: () => import('../views/auth/RegisterView.vue'),
      meta: { public: true },
    },
    {
      path: '/share/:code',
      name: 'share-access',
      component: () => import('../views/share-access/ShareAccessView.vue'),
      meta: { public: true },
    },
    {
      path: '/',
      component: () => import('../layouts/MainLayout.vue'),
      children: [
        { path: '', redirect: '/files' },
        {
          path: 'files',
          name: 'files',
          component: () => import('../views/files/FilesView.vue'),
        },
        {
          path: 'shares',
          name: 'shares',
          component: () => import('../views/shares/MySharesView.vue'),
        },
        {
          path: 'profile',
          name: 'profile',
          component: () => import('../views/profile/ProfileView.vue'),
        },
        {
          path: 'admin/users',
          name: 'admin-users',
          component: () => import('../views/admin/UsersView.vue'),
          meta: { requiresAdmin: true },
        },
        {
          path: 'admin/plugins',
          name: 'admin-plugins',
          component: () => import('../views/admin/PluginsView.vue'),
          meta: { requiresAdmin: true },
        },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const appStore = useAppStore()
  if (!appStore.statusLoaded) {
    await appStore.fetchStatus()
  }

  // 安装态拦截
  if (appStore.installed === false && to.path !== '/install') {
    return { path: '/install', replace: true }
  }
  if (appStore.installed === true && to.path === '/install') {
    return { path: '/login', replace: true }
  }

  // 公开页面直接放行
  if (to.meta.public) {
    return true
  }

  // 登录态拦截
  const userStore = useUserStore()
  if (!userStore.isLogin) {
    return { path: '/login', query: { redirect: to.fullPath }, replace: true }
  }
  if (!userStore.user) {
    try {
      await userStore.fetchInfo()
    } catch (e) {
      userStore.clear()
      return { path: '/login', query: { redirect: to.fullPath }, replace: true }
    }
  }

  // 角色拦截
  if (to.meta.requiresAdmin && !userStore.isAdmin) {
    return { path: '/files', replace: true }
  }

  return true
})

export default router
