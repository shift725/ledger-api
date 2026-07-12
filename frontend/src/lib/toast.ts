import { ref } from 'vue'

// 極簡全域提示：module-level ref，任何地方 toast('訊息') 觸發、AppShell 顯示。
// 連續呼叫重置計時器，逾時自動清空（單一提示、後蓋前，夠用；佇列非需求）。
export const toastMessage = ref('')
let timer: ReturnType<typeof setTimeout> | undefined

export function toast(message: string, duration = 2500) {
  toastMessage.value = message
  clearTimeout(timer)
  timer = setTimeout(() => {
    toastMessage.value = ''
  }, duration)
}
