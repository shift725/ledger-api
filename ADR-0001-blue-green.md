# 0001. 部署停機窗與 blue-green 部署

- **狀態**：已接受（2026-07-21）——**決定暫不實作**，設計備查。
- **脈絡**：2026-07-21 對線上站實測部署停機窗之後。

## 脈絡（Context）

現行部署以「就地重建」更新 web 容器：`docker compose pull && up -d` 讓舊 web 停 → 新 web 起 → entrypoint 依序跑 `migrate → collectstatic → ensure_superuser → gunicorn`。這段期間 web 的 `:8000` 沒人聽，前端 nginx 對它的反代回 **502**。

實測一次受控 web 重建，停機窗 **8.2 秒**（公網探針，±1s 採樣），組成：

| entrypoint 步驟 | 耗時 | 性質 |
|---|---|---|
| migrate（無遷移可套用） | ~3.0s | 純 Django 啟動開銷（import apps＋連 DB＋查遷移狀態） |
| collectstatic | ~2.6s | 157 檔複製、453 post-process（whitenoise 雜湊） |
| ensure_superuser | ~1.8s | 冪等、無變更（又一次 Django 啟動） |
| gunicorn boot | ~0.6s | 開始 listening |

三個關鍵觀察：

1. 停機**全是 502**（有人接、上游死），**無連線被拒**——TLS 邊界（edge nginx）不隨部署重建、始終在。
2. 前端靜態頁（SPA）在 web 重建期間**仍可存取**（前端 nginx 服自己的靜態檔、不經 web）；純前端重建的停機 **< 0.3s**，可忽略。
3. 「一次部署的使用者可見停機」≈ **web 那 8 秒**，其中**約七成來自 migrate＋collectstatic**——兩者都得先把整個 Django boot 起來。

## 決策（Decision）

**暫不實作 zero-downtime 部署**，維持現行單容器就地重建。

本站有真實使用（作者本人日常記帳），但**使用者就只有作者一人**：8 秒窗的期望撞擊次數極低，且撞到時的後果是「操作失敗、重試即可」，不是資料遺失——502 表示請求根本沒被伺服器處理。blue-green 的實作與長期維護成本（見下）買不回這點改善。設計先想清楚，日後有他人依賴時照此升級、不返工。

**一個容易誤會的邊界**：前端的離線佇列**接不住這 8 秒**。它只在 `fetch` 直接 throw（網路不通）時把新增交易入隊，而部署期的 502 是一個合法的 HTTP 回應、不會 throw，所以使用者看到的是明確的錯誤訊息而非靜默入隊。就本站而言這個界線是對的：502 代表伺服器還在、只是這一刻沒人接，把它當成離線而靜默吞下去，反而會讓使用者以為已經記到帳。

## 設計（若要實作 blue-green，本專案的具體形）

**切換點＝路由到 web 的那層 nginx 的 upstream。** web 是唯一有意義停機的層（8s），且它藏在前端 nginx 後面；前端本身重啟 <0.3s、不需雙色。故雙色只做 web：

1. 兩個 web 容器 `web-blue`／`web-green`，同接**單一共用 Postgres**；同一時刻只有一色收流量。
2. 前端 nginx 對 web 的反代目標改成可切變數（把前端 nginx 也 templatize，如 edge nginx 現行作法：`envsubst` 一個 `WEB_UPSTREAM`）。
3. 部署序列（假設現役＝blue）：
   1. `up -d web-green`（拉新 image）→ green 在**背景**跑那 8 秒 entrypoint，**blue 照常服流量**、使用者無感。
   2. 等 green healthy（healthcheck 過）。
   3. 前端 upstream 切到 green，`nginx -s reload`（graceful、drain 舊連線，<1s）。
   4. 停 blue。
   5. 下次部署 green↔blue 互換。
4. **rollback**＝upstream 切回 blue（舊 image sha 不可變、容器還在或秒級重起），比重新部署快。

**硬前提：migration 必須 expand-contract。** blue 與 green 共用同一個 DB schema，切換期間**新舊碼同時對同一 schema 讀寫**。所以 schema 變更不能就地改（就地 rename 欄位會讓另一色炸），要拆兩段部署：

- **expand**（本次部署）：只加不改——加 nullable 欄、加表、`CREATE INDEX CONCURRENTLY`；舊碼忽略新欄、新碼用新欄。green 起來時這 migration 對還在跑的 blue 仍相容。
- 切流量 blue→green。
- **contract**（下次部署、確定無舊碼在跑後）：刪掉不再用的舊欄／約束。

一次「改欄位」＝兩次部署（先加＋雙寫＋讀新，後刪舊），永不就地 rename。

**範圍：只雙色 web。** worker/beat（Celery）停機不產生使用者可見 502（任務排在 Redis、worker 回來再消化）；beat 更**必須全系統唯一**（雙色會重複排程）。故 worker/beat 照常就地重啟即可，不進雙色。

## 後果（Consequences）

- **接受**：每次部署 web 有 ~8s 的 502 窗（唯一使用者是作者本人，實害趨近於零）。
- **觸發重議**：**使用者不只作者一人**（開放註冊、有他人依賴）時，回到本設計實作。
- **若採用的代價**：deploy 流程變**有狀態**（要記得/推得出「現役是哪色」）；compose 多一組 web 服務；**每次 schema 變更都要按 expand-contract 拆兩段部署＝開發紀律稅**（solo 專案這稅不小）。估 1–2 天實作＋持續的 migration 紀律成本。

## 考慮過的替代（Alternatives）

- **rolling update**（多 web replica 逐台換）：單機 compose 無真正的負載平衡器（前端 nginx 頂多 round-robin 多 replica），滾動期同樣要 expand-contract、還多「同時多版本」的變數；blue-green 的「兩色明確、一次切」更貼單機。compose 原生也不做滾動（那是 Swarm/k8s 的事）。
- **不上雙色、只縮短那 8s**（更便宜的中間解）：把 collectstatic 移到 image build 期（靜態檔本就烤進 image、跑 runtime 是浪費）可省 ~2.6s；減少 entrypoint 裡「把 Django boot 起來」的次數可再省。這能把 8s 砍到 ~3–4s、成本遠低於 blue-green，但**不消除**停機。本次一併不做（非一行級、要動核心 Dockerfile/entrypoint），列為比 blue-green 更早該考慮的一步。
- **維持現狀（選定）**：單一使用者，8s 無實害；設計備查即可。
