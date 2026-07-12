import { createRouter, createWebHistory } from 'vue-router'
import type { RouteLocationNormalized, RouteLocationRaw, RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

export const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'dashboard',
    component: () => import('@/views/DashboardView.vue'),
    meta: { requiresAuth: true },
  },
  // 尚未實作的頁面先以共用佔位立路由，殼的導覽今天就可點；完成一頁換一頁。
  {
    path: '/transactions',
    name: 'transactions',
    component: () => import('@/views/TransactionsView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/transactions/new',
    name: 'transaction-new',
    component: () => import('@/views/TransactionFormView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/transactions/:id',
    name: 'transaction-detail',
    component: () => import('@/views/TransactionFormView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/reports',
    name: 'reports',
    component: () => import('@/views/PlaceholderView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('@/views/SettingsView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/settings/:section',
    name: 'settings-section',
    component: () => import('@/views/PlaceholderView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { guestOnly: true },
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('@/views/RegisterView.vue'),
    meta: { guestOnly: true },
  },
]

// Exported so the redirect logic can be unit-tested directly, without driving a
// full navigation. useAuthStore() is called here (navigation time), never at
// module load, so Pinia is already active.
export function authGuard(to: RouteLocationNormalized): true | RouteLocationRaw {
  const { isAuthenticated } = useAuthStore()
  if (to.meta.requiresAuth && !isAuthenticated) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.meta.guestOnly && isAuthenticated) {
    return { path: '/' }
  }
  return true
}

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

router.beforeEach(authGuard)

export default router
