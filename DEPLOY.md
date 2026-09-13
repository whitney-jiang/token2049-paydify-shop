# 部署到公网(展会用)· TOKEN2049 购物 Demo

把这个后端部署到云,得到一个**固定公网网址**。任何人(iPhone / 安卓 / 笔记本,不限系统)打开网址 →
购物页 → Buy now → 用真实 appId/appKey 建单 → **正式支付 0.10 USDT**。

密钥**只在服务器**(环境变量),绝不进网页。

---
## 先做两件事(重要)

1. **轮换 apiSecret**:当前这个密钥在对话里泄露过。公网上线前请在 Paydify 后台换新密钥,用新的。
2. 确认商户已开通你要展示的支付渠道(Binance 等)。

---
## 需要设置的环境变量(在云平台后台填)

| 变量 | 值 | 说明 |
|---|---|---|
| `PAYDIFY_KEY` | 你的 apiKey(AK…) | 必填 |
| `PAYDIFY_SECRET` | 轮换后的 apiSecret | 必填,**只填在后台,别写进代码/git** |
| `PAYDIFY_MERCHANT_ID` | `M524689056` | 可选(已有默认) |
| `PAYDIFY_APP_ID` | `A24689057` | 可选(已有默认) |

Docker 里已内置:`HOST=0.0.0.0`、`DEFAULT_PAGE=shop-demo.html`、`FIXED_AMOUNT=0.10`
(FIXED_AMOUNT=0.10 = 服务端把每笔都锁成 0.10,防止有人从公网构造大额订单。想放开就删掉这个变量。)

---
## 方式一:Render(推荐,免费,用 Docker)

1. 把本文件夹(server.py / shop-demo.html / TOKEN2049-Paydify-demo.html / Dockerfile / .dockerignore)推到一个 **GitHub 私有仓库**。
   - ⚠️ 确保仓库里**没有** `paydify.secret.json`(本部署包本来就不含它)。
2. 打开 https://render.com → New → **Web Service** → 连接你的 GitHub 仓库。
3. Render 检测到 Dockerfile,Runtime 选 **Docker**。
4. Instance Type 选 **Free**。
5. 在 **Environment** 里加两条:`PAYDIFY_KEY`、`PAYDIFY_SECRET`(新密钥)。
6. Create Web Service → 等构建完成 → 得到网址 `https://xxxx.onrender.com`。
7. 手机打开这个网址即可演示。

> 免费实例闲置会休眠,首次打开有 ~30 秒冷启动。展会怕这个的话,升级到最便宜的常驻实例即可。

---
## 方式二:Railway(也简单)

1. 同样把文件夹推到 GitHub 仓库(不含密钥)。
2. https://railway.app → New Project → Deploy from GitHub repo。
3. Railway 检测到 Dockerfile 自动构建。
4. 在 **Variables** 里加 `PAYDIFY_KEY`、`PAYDIFY_SECRET`。
5. 在 **Settings → Networking → Generate Domain** 生成公网网址。

---
## 方式三:本机先验一下(可选)

装了 Docker Desktop 的话,本地跑一遍:
```bash
docker build -t paydify-shop .
docker run -e PAYDIFY_KEY=AK... -e PAYDIFY_SECRET=你的新secret -p 8080:8080 paydify-shop
```
打开 http://localhost:8080/

---
## 上线后:做展台二维码

拿到公网网址后,把它做成二维码贴到展台。任何二维码工具都行;或把网址发给我,我给你生成一张验证过的高清 PNG/SVG。

---
## 页面说明
- `/`            → 购物页(4 商品,每个 0.10 USDT)
- `/TOKEN2049-Paydify-demo.html` → 之前的多场景 demo(如需)
- 支付流程:选币/钱包/链 → 实时下单出真码 → 扫码支付 → 轮询到 PAID 自动跳成功页

## 安全
- 密钥只在后台环境变量,不进 git、不进网页。
- `FIXED_AMOUNT=0.10` 已锁死金额,防止公网滥用。
- 建单接口在公网可被调用来创建**待支付**订单(未付=不产生费用);如需更严可加限流/口令,找我加。
