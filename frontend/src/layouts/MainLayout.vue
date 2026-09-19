<template>
  <el-container class="layout">
    <el-aside width="220px" class="aside">
      <div class="logo">
        <el-icon :size="22"><Cloudy /></el-icon>
        <span>钟毓云盘</span>
      </div>
      <el-menu
        :default-active="$route.path"
        router
        background-color="#1e293b"
        text-color="#cbd5e1"
        active-text-color="#60a5fa"
        class="menu"
      >
        <el-menu-item index="/files">
          <el-icon><Folder /></el-icon>
          <span>我的文件</span>
        </el-menu-item>
        <el-menu-item index="/shares">
          <el-icon><Share /></el-icon>
          <span>我的分享</span>
        </el-menu-item>
        <el-menu-item index="/profile">
          <el-icon><User /></el-icon>
          <span>个人中心</span>
        </el-menu-item>
        <el-menu-item v-if="appStore.departmentDrive === true" index="/department-files">
          <el-icon><Files /></el-icon>
          <span>部门网盘</span>
        </el-menu-item>
        <template v-if="showDepartmentMenu">
          <el-menu-item index="/departments">
            <el-icon><OfficeBuilding /></el-icon>
            <span>部门管理</span>
          </el-menu-item>
          <el-menu-item index="/admin/permissions">
            <el-icon><Lock /></el-icon>
            <span>权限管理</span>
          </el-menu-item>
          <el-menu-item index="/admin/logs">
            <el-icon><Document /></el-icon>
            <span>操作日志</span>
          </el-menu-item>
        </template>
        <el-sub-menu v-if="userStore.isAdmin" index="admin-group">
          <template #title>
            <el-icon><Setting /></el-icon>
            <span>系统管理</span>
          </template>
          <el-menu-item index="/admin/dashboard">
            <el-icon><Monitor /></el-icon>
            <span>监控仪表盘</span>
          </el-menu-item>
          <el-menu-item index="/admin/backup">
            <el-icon><FolderOpened /></el-icon>
            <span>备份恢复</span>
          </el-menu-item>
          <el-menu-item index="/admin/users">
            <el-icon><UserFilled /></el-icon>
            <span>用户管理</span>
          </el-menu-item>
          <el-menu-item index="/admin/plugins">
            <el-icon><Cpu /></el-icon>
            <span>插件管理</span>
          </el-menu-item>
          <el-menu-item index="/admin/settings">
            <el-icon><Tools /></el-icon>
            <span>系统设置</span>
          </el-menu-item>
        </el-sub-menu>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <div class="title">私有云盘系统</div>
        <el-dropdown @command="onCommand">
          <span class="user-area">
            <el-avatar :size="28" class="avatar">
              {{ userStore.user?.username?.charAt(0).toUpperCase() }}
            </el-avatar>
            <span class="username">{{ userStore.user?.username }}</span>
            <el-tag v-if="userStore.isAdmin" size="small" type="danger" effect="plain">
              管理员
            </el-tag>
            <el-icon><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="profile">个人中心</el-dropdown-item>
              <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>

      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useAppStore } from '../stores/app'
import { useUserStore } from '../stores/user'

const router = useRouter()
const userStore = useUserStore()
const appStore = useAppStore()

// 部门共享功能开启且当前用户具备管理入口（超管或部门管理员）时展示菜单
const showDepartmentMenu = computed(
  () => appStore.departmentDrive === true && userStore.canManageDrive,
)

onMounted(async () => {
  if (!userStore.isLogin) return
  if (appStore.departmentDrive === null) {
    await appStore.fetchFeatureFlags()
  }
  if (appStore.departmentDrive && !userStore.adminDeptsLoaded) {
    await userStore.fetchAdminDepts()
  }
})

async function onCommand(command) {
  if (command === 'profile') {
    router.push('/profile')
  } else if (command === 'logout') {
    await ElMessageBox.confirm('确定退出登录吗？', '提示', { type: 'warning' })
    await userStore.logout()
    router.replace('/login')
  }
}
</script>

<style scoped>
.layout {
  height: 100vh;
}

.aside {
  background-color: #1e293b;
  display: flex;
  flex-direction: column;
}

.logo {
  height: 60px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 20px;
  color: #f8fafc;
  font-size: 18px;
  font-weight: 600;
  letter-spacing: 1px;
}

.menu {
  border-right: none;
  flex: 1;
}

.header {
  background: #fff;
  border-bottom: 1px solid #e5e7eb;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.title {
  color: #334155;
  font-weight: 600;
}

.user-area {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  color: #475569;
}

.avatar {
  background: #2563eb;
  color: #fff;
}

.username {
  font-size: 14px;
}

.main {
  background: #f5f7fa;
  padding: 20px;
}
</style>
