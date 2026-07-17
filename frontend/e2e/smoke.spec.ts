import { test, expect } from '@playwright/test'

// 煙測打的是真容器棧：真瀏覽器 → nginx（服 SPA＋反代 /api）→ Django → PostgreSQL。
// 單元測試各自綠不保證接縫是通的，這裡保的就是「接起來」。
//
// 流程自包含：每次跑註冊一個時間戳新使用者（新使用者沒有帳戶，所以命脈必含
// 「建帳戶」），不依賴、不清理既有資料——同一份測試可以打本機容器、CI、
// 或部署後的正式站（換 E2E_BASE_URL 即可）。

const stamp = Date.now()
const username = `e2e_${stamp}`
const email = `e2e_${stamp}@example.com`
// 固定強密碼、刻意不含時間戳：Django 的相似度驗證會擋「跟使用者名稱太像」的密碼。
const password = 'Sunny-Ledger-42!'
const accountName = 'E2E 錢包'
const amount = '638'

test('未登入訪問首頁會被守衛導向登入頁', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/login/)
  await expect(page.getByRole('heading', { name: '登入' })).toBeVisible()
})

test('命脈：註冊 → 建帳戶 → 記一筆 → 列表見到 → 登出', async ({ page }) => {
  await test.step('註冊即登入，落地總覽', async () => {
    await page.goto('/register')
    await page.getByLabel('使用者名稱').fill(username)
    await page.getByLabel('Email').fill(email)
    // 「確認密碼」的文字包含「密碼」，需 exact 免撞 strict mode。
    await page.getByLabel('密碼', { exact: true }).fill(password)
    await page.getByLabel('確認密碼').fill(password)
    await page.getByRole('button', { name: '註冊' }).click()
    await expect(page).toHaveURL('/')
  })

  await test.step('建立第一個帳戶', async () => {
    await page.goto('/settings/accounts')
    await page.getByRole('button', { name: '新增帳戶' }).click()
    await page.getByLabel('名稱').fill(accountName)
    await page.getByRole('button', { name: '儲存' }).click()
    await expect(page.getByText(accountName)).toBeVisible()
  })

  await test.step('記一筆支出', async () => {
    await page.goto('/transactions/new')
    // selectOption 會等到選項存在才選——帳戶清單是進頁後才抓回來的。
    await page.getByLabel('帳戶').selectOption({ label: accountName })
    await page.getByLabel('金額').fill(amount)
    await page.getByRole('button', { name: '儲存' }).click()
    await expect(page).toHaveURL('/transactions')
  })

  await test.step('交易列表見到這筆', async () => {
    await expect(page.getByText(new RegExp(amount))).toBeVisible()
  })

  await test.step('登出後憑證確實失效', async () => {
    // 桌面視口：sidebar 的登出鈕（此頁唯一一顆）。
    await page.getByRole('button', { name: '登出' }).click()
    await expect(page).toHaveURL(/\/login/)
    // 再闖需登入頁，守衛仍擋＝token 真的清掉了，不是只換了畫面。
    await page.goto('/')
    await expect(page).toHaveURL(/\/login/)
  })
})
