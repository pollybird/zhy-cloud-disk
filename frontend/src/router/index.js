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
          path: 'department-files',
          name: 'department-files',
          component: () => import('../views/department/DepartmentFilesView.vue'),
          // 部门成员均可访问（文件视图内部按 access 控制按钮显隐）
          meta: { departmentFeature: true },
        },
        {
          path: 'departments',
          name: 'departments',
          component: () => import('../views/department/DepartmentsView.vue'),
          meta: { departmentFeature: true, departmentManager: true },
        },
        {
          path: 'department-members',
          name: 'department-members',
          component: () => import('../views/department/DepartmentMembersView.vue'),
          meta: { departmentFeature: true, departmentManager: true },
        },
        {
          path: 'admin/permissions',
          name: 'admin-permissions',
          component: () => import('../views/department/PermissionManageView.vue'),
          meta: { departmentFeature: true, departmentManager: true },
        },
        {
          path: 'admin/logs',
          name: 'admin-logs',
          component: () => import('../views/department/OperationLogView.vue'),
          meta: { departmentFeature: true, departmentManager: true },
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
        {
          path: 'admin/dashboard',
          name: 'admin-dashboard',
          component: () => import('../views/admin/DashboardView.vue'),
          meta: { requiresAdmin: true },
        },
        {
          path: 'admin/backup',
          name: 'admin-backup',
          component: () => import('../views/admin/BackupView.vue'),
          meta: { requiresAdmin: true },
        },
        {
          path: 'admin/settings',
          name: 'admin-settings',
          component: () => import('../views/admin/SettingsView.vue'),
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

  // 1.1.0 部门共享功能拦截
  if (to.meta.departmentFeature) {
    if (appStore.departmentDrive === null) {
      await appStore.fetchFeatureFlags()
    }
    if (!appStore.departmentDrive) {
      return { path: '/files', replace: true }
    }
    // 管理类页面仅超管或部门管理员可进入；部门网盘普通成员即可访问
    if (to.meta.departmentManager && !userStore.canManageDrive) {
      if (!userStore.adminDeptsLoaded) {
        await userStore.fetchAdminDepts()
      }
      if (!userStore.canManageDrive) {
        return { path: '/department-files', replace: true }
      }
    }
  }

  return true
})

export default router
