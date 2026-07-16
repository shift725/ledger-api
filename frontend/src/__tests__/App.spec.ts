import { describe, it, expect } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import App from '@/App.vue'
import { routes } from '@/router'

describe('App', () => {
  it('renders the guest layout on the login page', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes })
    await router.push('/login')
    const wrapper = mount(App, { global: { plugins: [createPinia(), router] } })
    await flushPromises()
    expect(wrapper.text()).toContain('晴空記帳')
  })
})
