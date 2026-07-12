// 金額顯示格式化：契約 decimal 字串 → 千分位字串；不顯示幣別符號（契約無 currency 欄位）。
// 全程字串處理，不過 Number——金額精度紀律的顯示層落實。

export function formatAmount(value: string): string {
  const [head = '', frac] = value.split('.')
  const negative = head.startsWith('-')
  const digits = negative ? head.slice(1) : head
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return (negative ? '-' : '') + grouped + (frac !== undefined ? `.${frac}` : '')
}
