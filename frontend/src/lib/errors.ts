// 後端 400/409 訊息攤平成人話（DRF 回 {欄位:[訊息]} 或 {detail:訊息}）。
// 契約鐵則：信後端人話（409 detail／400 逐欄如實顯示）；呼叫端只在此之上補場景文案
// （如跨用戶 404 顯示「找不到」、藏存在性）。交易表單與設定面各資源共用同一份。
export function messagesFrom(err: unknown): string {
  if (!err || typeof err !== 'object') return '操作失敗，請稍後再試'
  const parts: string[] = []
  for (const v of Object.values(err as Record<string, unknown>)) {
    if (Array.isArray(v)) parts.push(...v.map(String))
    else if (typeof v === 'string') parts.push(v)
  }
  return parts.join('；') || '操作失敗，請稍後再試'
}
