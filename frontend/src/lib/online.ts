import { computed, readonly, ref } from 'vue'

// 離線狀態源（module-level 單例，同 toast 前例）：navigator.onLine 給初值，
// online/offline 事件維護。消費端 watch(isOnline) 反應（banner、佇列重放）。
const state = ref(navigator.onLine)

window.addEventListener('online', () => {
  state.value = true
})
window.addEventListener('offline', () => {
  state.value = false
})

export const isOnline = readonly(state)

// 資料頁載入失敗的統一文案：離線時錯誤原因八成就是離線本身——
// 如實說「離線中」，別讓使用者誤以為服務壞了。全站錯誤態共用這一份。
export const loadErrorText = computed(() => (isOnline.value ? '載入失敗' : '離線中，暫無法載入'))
