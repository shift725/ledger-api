# 貢獻指南（Contributing to ledger-api）

感謝你願意為 `ledger-api` 出一份力。本專案是一個以 **Django REST Framework + SimpleJWT** 打底的記帳 REST API；目前已完成帳號與認證核心，記帳（ledger）領域為進行中的下一階段。

這份文件說明：怎麼把開發環境跑起來、怎麼做出符合慣例的改動、以及一個 Pull Request 從開分支到 merge 的完整流程。動手前，建議先快速看過 [`README.md`](README.md)（怎麼把專案跑起來、API 端點、部署）。

---

## 1. 溝通慣例

- 有想法、疑問或要回報問題，請開 **Issue**；要提交改動，請開 **Pull Request**。
- 討論語言以**繁體中文**為主，技術名詞保留原文（如 `DecimalField`、`IsAuthenticated`）。
- 請保持友善、就事論事。（正式的 Code of Conduct 待補。）

---

## 2. 開發環境建置

兩條路徑，細節見 README，這裡只列骨架。

**Docker（主要路徑）** —— 見 [README · 快速開始](README.md#快速開始本機http)：

```bash
cp .env.example .env          # 然後填好 SECRET_KEY、POSTGRES_PASSWORD（見 README）
docker compose up -d --build
docker compose logs -f web    # 看 entrypoint → migrate → collectstatic → gunicorn
```

**本機 venv（不經 Docker）** —— 見 [README · 本機開發](README.md#本機開發不經-docker)：

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1            # Windows PowerShell；macOS/Linux：source .venv/bin/activate
pip install -r requirements-dev.txt   # runtime + 開發工具（ruff、coverage）
# 提供 DATABASE_URL 後：
python manage.py migrate
python manage.py runserver
```

> `ruff` 與 `coverage` 屬 `requirements-dev.txt`，**不在 runtime image 內**，請在本機 venv 執行。

---

## 3. 開發工作流程

整體一條線：

```
fork → 從最新 main 開分支 → 改動 → 本機自檢（lint + format + test）
  → commit（Conventional Commits）→ push → 開 PR → review → 通過後 merge
```

1. **Fork** 本 repo，clone 你的 fork 到本機。
2. **從最新 `main` 開分支**；`main` 受保護，**禁止直接 push**。分支命名見 [§5](#5-分支命名規則)。
3. **小步改動**，一個 commit 做一件事。
4. **本機自檢**（見 [§4](#4-提交前的本機自檢)）全綠再提交。
5. **commit**：遵循 [§6 Conventional Commits](#6-commit-規範conventional-commits)。
6. **push 並開 PR**，填好描述與 [§8 self-checklist](#8-pull-request-流程與檢查清單)。
7. **通過 review** 後才能 merge（自動化 CI 為 roadmap 目標，落地前以人工 review 為準）。

---

## 4. 提交前的本機自檢

提交前請在本機跑過以下三道（全綠再 commit）：

```bash
ruff check .                 # lint（規則集 E / F / I / UP）
ruff format --check .        # 確認格式（單引號風格）；要實際套用改 ruff format .
coverage run manage.py test  # 跑測試並蒐集覆蓋率（branch 模式，需 DATABASE_URL）
coverage report              # 覆蓋率報表（accounts、config；低於 fail_under=75 即非零結束）
```

容器內若只想跑測試（runtime image 不含覆蓋率工具，改用 Django 內建 runner）：

```bash
docker compose exec web python manage.py test accounts
```

> **現況 vs 目標**：目前自檢為**手動**執行。以 **pre-commit** 在每次 commit 前自動跑 lint/format、以及在 PR 上自動跑 lint + test 的 **CI**，都是 roadmap 上的目標、**尚未落地**；在那之前，請以上述手動自檢與人工 review 為準。

---

## 5. 分支命名規則

- 一律從**最新 `main`** 開分支。
- 格式：`<type>/<簡短-kebab-描述>`，可選帶 issue 編號：`<type>/<issue>-<簡短-kebab-描述>`。
- `<type>` 對齊 Conventional Commits 型別：`feat` / `fix` / `docs` / `refactor` / `test` / `chore` / `ci`。

範例：

```
feat/ledger-account-model
fix/login-stale-token
docs/contributing
chore/42-bump-ruff
```

---

## 6. Commit 規範（Conventional Commits）

格式：`<type>(<scope>): <subject>`，`scope` 可省略。

| type | 用途 | 範例 |
|---|---|---|
| `feat` | 新功能 | `feat(ledger): 新增 Account 模型` |
| `fix` | 修 bug | `fix(accounts): 登入避免讀到過期 token` |
| `docs` | 純文件 | `docs: 新增 CONTRIBUTING.md` |
| `style` | 格式／不影響邏輯 | `style: 套用 ruff format` |
| `refactor` | 重構 | `refactor(config): 抽出 settings 區塊` |
| `test` | 測試 | `test(ledger): 補 Transaction 聚合測試` |
| `chore` | 雜務／設定 | `chore: 導入 ruff/coverage 設定` |
| `ci` | CI 設定 | `ci: 加入 GitHub Actions lint+test` |

慣例：

- `scope` 建議用 app／領域名：`accounts`、`ledger`、`config`、`docker`、`docs`。
- subject 用**繁體中文、全形標點**，與既有 commit 風格一致。
- **一個 commit 做一件事**；避免把多個不相關改動塞進同一個 commit。
- 本專案 commit **不加 `Co-Authored-By` trailer**。

---

## 7. 程式風格與專案鐵則

**格式與 lint（Ruff）**

- 工具設定集中在 [`pyproject.toml`](pyproject.toml)：規則集 `E / F / I / UP`、`line-length = 100`、**單引號**風格、target `py312`；`migrations/`、`staticfiles` 已排除。
- **擴張規則集**（例如 `B` bugbear、`DJ` flake8-django）請**先在 issue／PR 討論**再改設定。

**核心鐵則（always do）**

- **DRF 權限**：DRF 預設 `AllowAny`，**需登入的端點必須明確指定 `IsAuthenticated`**；管理者操作用 `IsAdminUser`。
- **資料隔離**：業務資料**一律依 `request.user` 過濾**；寫入時把 `user` 設為當前登入者，**不信任 client 傳來的 `user_id`**。
- **金額**：一律用 `DecimalField`，**不用 `float`**；交易日 `date` 與建檔時間 `created_at` 分開。
- **新功能放新 app**：記帳等業務功能寫在獨立 app（如 `ledger/`），沿用 `accounts.UUIDv7Mixin`（UUIDv7 主鍵）、`APITestCase` 測試風格、既有 admin 註冊模式。
- **少改既有共用檔**：`INSTALLED_APPS`、`config/urls.py`、`accounts/`、Docker 骨架等共用基礎，非改不可時也讓改動**集中、最小**，並在 PR 說明原因。
- **機密**：走環境變數 / GitHub Secrets，**絕不進 repo**（不要把 `.env`、密碼、token 提交上來）。

---

## 8. Pull Request 流程與檢查清單

**PR 標題**用 Conventional Commits 格式（同 [§6](#6-commit-規範conventional-commits)），例如 `feat(ledger): 新增 Account 模型`。

**PR 描述**請包含：

- **動機**：解決什麼問題 / 為什麼要做。
- **做法**：主要改了什麼、有無取捨。
- **測試**：怎麼驗證的（哪些測試、手動步驟）。
- **關聯**：`Closes #<issue>`（若有）。

**送出前的 self-checklist：**

- [ ] 從最新 `main` 開的分支，分支名符合 [§5](#5-分支命名規則)。
- [ ] `ruff check .` 與 `ruff format --check .` 通過。
- [ ] `coverage run manage.py test` 全綠，且 `coverage report` 不低於 `fail_under`（目前 75）。
- [ ] 新端點 / 模型 / 序列化邏輯或 bug 修復**已附對應測試**（見 [§9](#9-測試要求)）。
- [ ] commit 訊息符合 Conventional Commits，且**未加 `Co-Authored-By` trailer**。
- [ ] 需登入端點已標權限類別；業務查詢／寫入皆依 `request.user`。
- [ ] 金額欄位用 `DecimalField`；無機密被提交進 repo。
- [ ] 若動到既有共用檔（`accounts/`、`config/` 等），已在 PR 說明原因與影響範圍。

**Merge 條件**：通過至少一位 reviewer 審查。`main` 受保護，不接受直接 push。（自動化 CI 為 roadmap 目標，落地前以本機自檢與人工 review 為準。）

---

## 9. 測試要求

- 測試 runner：Django 內建（**`manage.py test`**）。既有約 23 個測試集中在 [`accounts/tests.py`](accounts/tests.py)，採 DRF **`APITestCase`** 風格；新功能（如 `ledger`）比照此風格放各 app 的 `tests.py`。
- **必須附測試**：新增端點 / 模型 / 序列化邏輯時；修 bug 時請**先寫一個能重現問題的失敗測試，再修到綠**。純文件 / 純格式變更可豁免。
- 跑法：

  ```bash
  coverage run manage.py test                              # 本機 + 覆蓋率（branch 模式，需 DATABASE_URL）
  coverage report                                          # 文字報表；低於 fail_under=75 即非零結束
  coverage html                                            # htmlcov/index.html 逐行檢視
  coverage xml                                             # coverage.xml（CI / 工具用）
  python manage.py test                                    # 本機只跑測試
  docker compose exec web python manage.py test            # 容器內全部
  docker compose exec web python manage.py test accounts   # 容器內單一 app
  ```

- 覆蓋率：`coverage report` 觀察 `accounts` / `config`，已啟用 **branch 覆蓋**。已設防倒退地板 **`fail_under = 75`**（baseline≈77.34%）：`coverage report` 低於門檻即非零結束。在 PR 上自動跑覆蓋率的 CI（屬後續 CI pipeline 階段）落地前，請以本機 `coverage report` 自檢，PR **不應使覆蓋率低於門檻**。

---

## 10. 授權

本專案目前**尚未附 `LICENSE`**（授權待補）。在授權檔補上之前，提交 PR 即表示你同意你的貢獻將依專案日後採用的授權條款釋出。若你對授權有疑慮，請先開 issue 討論。
