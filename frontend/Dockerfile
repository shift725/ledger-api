# syntax=docker/dockerfile:1.7

# multi-stage：Node 只在 build 階段存在，最終 image 只有 nginx＋編譯好的靜態檔。
# node_modules（數百 MB）與 Node runtime 都不會進到成品——體積小，攻擊面也小。

# ---------- Stage 1: build ----------
FROM node:24-alpine AS build

WORKDIR /app

# 先只複製依賴宣告，讓 npm ci 自成一層：改原始碼時這層命中快取，不必重裝依賴。
# .npmrc 必須一起帶（legacy-peer-deps），否則 npm ci 會卡在 openapi-typescript 的 peer 範圍。
COPY package.json package-lock.json .npmrc ./
RUN npm ci

COPY . .

# 與 CI／本機同一個指令（type-check + vite build），不另開一條建置路徑。
RUN npm run build


# ---------- Stage 2: serve ----------
FROM nginx:1.27-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
