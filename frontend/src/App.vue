<script setup lang="ts">
import { RouterView } from 'vue-router'
</script>

<template>
  <div class="min-h-screen">
    <header class="mx-auto max-w-md px-4 py-3">
      <h1 class="text-brand-text text-xl font-medium">分類帳</h1>
    </header>
    <main class="mx-auto max-w-md px-4">
      <RouterView />
    </main>
  </div>
</template>
