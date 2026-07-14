// 「更多」六個設定子頁的單一來源：AppShell 導覽、SettingsView 清單、SettingsSectionView
// 派發都讀這份，新增／改名／改順序一處生效，不必三地同步。
export interface SettingsSection {
  slug: string
  label: string
}

export const SETTINGS_SECTIONS: SettingsSection[] = [
  { slug: 'accounts', label: '帳戶' },
  { slug: 'categories', label: '分類' },
  { slug: 'tags', label: '標籤' },
  { slug: 'rules', label: '定期定額' },
  { slug: 'goals', label: '儲蓄目標' },
  { slug: 'profile', label: '個人資料' },
]
