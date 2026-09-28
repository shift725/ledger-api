import type { components } from '@/api/schema'

// 金額顯示格式化：契約 decimal 字串 → 千分位字串；不顯示幣別符號（契約無 currency 欄位）。
// 全程字串處理，不過 Number——金額精度紀律的顯示層落實。

export function formatAmount(value: string): string {
  const [head = '', frac] = value.split('.')
  const negative = head.startsWith('-')
  const digits = negative ? head.slice(1) : head
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  // 全零小數部省略（後端 decimal 固定送兩位）：整數金額為大宗，.00 是視覺噪音。
  const showFrac = frac !== undefined && !/^0+$/.test(frac)
  return (negative ? '-' : '') + grouped + (showFrac ? `.${frac}` : '')
}

// 帳戶類型 enum → 顯示標籤（契約 AccountTypeEnum 的四值）。
const ACCOUNT_TYPE_LABELS: Record<string, string> = {
  cash: '現金',
  bank: '銀行',
  credit_card: '信用卡',
  e_wallet: '電子錢包',
}
export function accountTypeLabel(type: string): string {
  return ACCOUNT_TYPE_LABELS[type] ?? type
}

// Date → <input type="datetime-local"> 值（YYYY-MM-DDTHH:mm，當地時間、無秒無時區）。
export function toDatetimeLocal(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
}

// 交易顯示名稱：名字 → 標籤（以「, 」串接）→ 分類 → 未命名。空標籤 join 成 ''，自然落到下一層。
// 只用於顯示：表單預填與送出一律用原始 name，否則 fallback 文字會被存成名字。
export function txnDisplayName(
  txn: Pick<components['schemas']['Transaction'], 'name' | 'tag_names' | 'category_name'>,
): string {
  return txn.name || txn.tag_names.join(', ') || txn.category_name || '未命名'
}
