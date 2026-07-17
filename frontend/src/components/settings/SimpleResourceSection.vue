<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '@/api/client'
import type { components } from '@/api/schema'
import { useReferenceStore } from '@/stores/reference'
import { messagesFrom } from '@/lib/errors'
import { toast } from '@/lib/toast'

// 分類與標籤同形（{id, name, description}），只差端點路徑 → 一支泛用元件、resource 決定路徑。
type Category = components['schemas']['Category']
type Tag = components['schemas']['Tag']
type SimpleItem = Category | Tag
interface SimpleWrite {
  name: string
  description: string
}

const props = defineProps<{ resource: 'categories' | 'tags' }>()

const reference = useReferenceStore()
const items = computed<SimpleItem[]>(() =>
  props.resource === 'categories' ? reference.categories : reference.tags,
)

// openapi-fetch 需要字面路徑做型別推導 → 依 resource 分支呼叫（兩者同形，只差路徑）。
function createReq(body: SimpleWrite) {
  return props.resource === 'categories'
    ? api.POST('/api/ledger/categories/', { body: body as unknown as Category })
    : api.POST('/api/ledger/tags/', { body: body as unknown as Tag })
}
function updateReq(id: string, body: SimpleWrite) {
  return props.resource === 'categories'
    ? api.PATCH('/api/ledger/categories/{id}/', { params: { path: { id } }, body })
    : api.PATCH('/api/ledger/tags/{id}/', { params: { path: { id } }, body })
}
function removeReq(id: string) {
  return props.resource === 'categories'
    ? api.DELETE('/api/ledger/categories/{id}/', { params: { path: { id } } })
    : api.DELETE('/api/ledger/tags/{id}/', { params: { path: { id } } })
}

const dialog = ref<HTMLDialogElement | null>(null)
const deleteDialog = ref<HTMLDialogElement | null>(null)
const editingId = ref<string | null>(null)
const pendingDeleteId = ref<string | null>(null)
const formError = ref('')
const form = reactive<SimpleWrite>({ name: '', description: '' })

onMounted(() => reference.ensure())

function openCreate() {
  editingId.value = null
  Object.assign(form, { name: '', description: '' })
  formError.value = ''
  dialog.value?.showModal()
}

function openEdit(item: SimpleItem) {
  editingId.value = item.id
  Object.assign(form, { name: item.name, description: item.description ?? '' })
  formError.value = ''
  dialog.value?.showModal()
}

async function submit() {
  formError.value = ''
  const body = { ...form }
  const { error } = editingId.value ? await updateReq(editingId.value, body) : await createReq(body)
  if (error) {
    formError.value = messagesFrom(error) // 重名 400 逐欄如實顯示
    return
  }
  dialog.value?.close()
  await reference.refresh()
  toast('已儲存')
}

function askDelete(id: string) {
  pendingDeleteId.value = id
  deleteDialog.value?.showModal()
}

async function confirmDelete() {
  deleteDialog.value?.close()
  const id = pendingDeleteId.value
  if (!id) return
  const { error } = await removeReq(id)
  if (error) {
    toast(messagesFrom(error))
    return
  }
  await reference.refresh()
  toast('已刪除')
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <button
      type="button"
      data-test="res-new"
      class="bg-brand-fill self-start rounded-lg px-3 py-1.5 text-sm text-white"
      @click="openCreate"
    >
      新增
    </button>

    <p v-if="reference.loaded && items.length === 0" class="text-ink-2 py-6 text-center text-sm">
      尚無資料
    </p>

    <ul v-else class="flex flex-col gap-2">
      <li
        v-for="item in items"
        :key="item.id"
        data-test="res-row"
        class="bg-card rounded-card flex items-center justify-between gap-2 px-4 py-3"
      >
        <div class="min-w-0">
          <p class="text-ink truncate">{{ item.name }}</p>
          <p v-if="item.description" class="text-ink-2 truncate text-xs">{{ item.description }}</p>
        </div>
        <div class="flex shrink-0 items-center gap-3 text-xs">
          <button type="button" data-test="res-edit" class="text-ink-2" @click="openEdit(item)">
            編輯
          </button>
          <button
            type="button"
            data-test="res-delete"
            class="text-expense"
            @click="askDelete(item.id)"
          >
            刪除
          </button>
        </div>
      </li>
    </ul>

    <!-- 新增／編輯共用 dialog -->
    <dialog ref="dialog" class="rounded-card m-auto w-80 max-w-[90vw] p-5 backdrop:bg-black/30">
      <form class="flex flex-col gap-3" @submit.prevent="submit">
        <h2 class="font-medium">{{ editingId ? '編輯' : '新增' }}</h2>
        <label class="flex flex-col gap-1">
          <span class="text-ink-2 text-sm">名稱</span>
          <input
            v-model="form.name"
            data-test="res-name"
            class="border-hairline rounded-lg border px-3 py-2"
          />
        </label>
        <label class="flex flex-col gap-1">
          <span class="text-ink-2 text-sm">說明</span>
          <input
            v-model="form.description"
            data-test="res-desc"
            class="border-hairline rounded-lg border px-3 py-2"
          />
        </label>
        <p v-if="formError" data-test="res-error" class="text-expense text-sm">{{ formError }}</p>
        <div class="flex justify-end gap-2">
          <button type="button" class="text-ink-2 px-3 py-1.5 text-sm" @click="dialog?.close()">
            取消
          </button>
          <button
            type="submit"
            data-test="res-submit"
            class="bg-brand-fill rounded-lg px-3 py-1.5 text-sm text-white"
          >
            儲存
          </button>
        </div>
      </form>
    </dialog>

    <!-- 刪除確認 -->
    <dialog ref="deleteDialog" class="rounded-card m-auto p-5 backdrop:bg-black/30">
      <p class="mb-4">確定刪除？</p>
      <div class="flex justify-end gap-2">
        <button type="button" class="text-ink-2 px-3 py-1.5 text-sm" @click="deleteDialog?.close()">
          取消
        </button>
        <button
          type="button"
          data-test="res-confirm-delete"
          class="bg-expense dark:text-bg rounded-lg px-3 py-1.5 text-sm text-white"
          @click="confirmDelete"
        >
          刪除
        </button>
      </div>
    </dialog>
  </div>
</template>
