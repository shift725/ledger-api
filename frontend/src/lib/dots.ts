// 分類色點：範圍內出現序指派。
// 每個「渲染範圍 × 資源型別」建一個 assigner；依首次出現序發色盤，
// 同 id 再現拿同色 → 同資料同序在每台機器上必得同色（純函數、零儲存）。
// 鍵一律用 UUID（name 可編輯，不可作鍵）。

export const DOT_PALETTE: readonly string[] = Array.from(
  { length: 10 },
  (_, i) => `var(--dot-${i + 1})`,
)

// 第 11 個資源起以黃金角度取新色：hue 互異保證同 scope 不撞。
// 溢出色可能落入保留色域（紅/翠綠/青藍）——個人記帳單 scope >10 罕見，接受。
const GOLDEN_ANGLE = 137.508

export function createDotAssigner(): (id: string) => string {
  const assigned = new Map<string, string>()
  return (id) => {
    let color = assigned.get(id)
    if (color === undefined) {
      const rank = assigned.size
      color =
        DOT_PALETTE[rank] ?? `hsl(${((rank - DOT_PALETTE.length) * GOLDEN_ANGLE) % 360} 65% 45%)`
      assigned.set(id, color)
    }
    return color
  }
}
