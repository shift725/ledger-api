<script setup lang="ts">
import { RouterLink } from 'vue-router'

// 路由與資料層完全共用，手機/桌面只差版面。
const mainNav = [
  { label: '總覽', to: '/' },
  { label: '交易', to: '/transactions' },
  { label: '報表', to: '/reports' },
]
const settingsChildren = [
  { label: '帳戶', to: '/settings/accounts' },
  { label: '分類', to: '/settings/categories' },
  { label: '標籤', to: '/settings/tags' },
  { label: '定期定額', to: '/settings/rules' },
  { label: '儲蓄目標', to: '/settings/goals' },
  { label: '個人資料', to: '/settings/profile' },
]

const activeCls = 'text-brand-text font-medium'
</script>

<template>
  <div class="min-h-screen md:pl-56">
    <!-- 桌面：左 sidebar，「更多」子項展開直接可見 -->
    <aside
      data-test="sidebar"
      class="bg-card fixed inset-y-0 left-0 z-10 hidden w-56 flex-col gap-1 px-4 py-5 md:flex"
    >
      <p class="text-brand-text mb-4 text-xl font-medium">分類帳</p>
      <RouterLink
        v-for="item in mainNav"
        :key="item.to"
        :to="item.to"
        class="text-ink rounded-md px-2 py-1.5"
        :exact-active-class="activeCls"
      >
        {{ item.label }}
      </RouterLink>
      <p class="text-ink-2 mt-4 mb-1 px-2 text-xs">更多</p>
      <RouterLink
        v-for="item in settingsChildren"
        :key="item.to"
        :to="item.to"
        class="text-ink rounded-md px-2 py-1.5"
        :exact-active-class="activeCls"
      >
        {{ item.label }}
      </RouterLink>
    </aside>

    <!-- 桌面：右上常駐「+」 -->
    <RouterLink
      to="/transactions/new"
      aria-label="記一筆"
      class="bg-brand-fill fixed top-5 right-6 z-10 hidden h-11 w-11 items-center justify-center rounded-full text-2xl text-white md:flex"
    >
      +
    </RouterLink>

    <main class="mx-auto max-w-md px-4 pt-5 pb-28 md:max-w-2xl md:pt-8 md:pb-8">
      <slot />
    </main>

    <!-- 手機：fixed 底部 tabbar＋中央凸起 FAB -->
    <nav data-test="tabbar" class="fixed inset-x-0 bottom-0 z-10 md:hidden">
      <RouterLink
        to="/transactions/new"
        aria-label="記一筆"
        class="bg-brand-fill absolute -top-6 left-1/2 z-10 flex h-12 w-12 -translate-x-1/2 items-center justify-center rounded-full text-2xl text-white"
      >
        +
      </RouterLink>
      <div class="bg-card rounded-t-card text-ink-2 flex justify-around pt-3 pb-3 text-xs">
        <RouterLink to="/" :exact-active-class="activeCls">總覽</RouterLink>
        <RouterLink to="/transactions" :exact-active-class="activeCls">交易</RouterLink>
        <span class="w-12" aria-hidden="true"></span>
        <RouterLink to="/reports" :exact-active-class="activeCls">報表</RouterLink>
        <RouterLink to="/settings" :exact-active-class="activeCls">更多</RouterLink>
      </div>
    </nav>
  </div>
</template>
