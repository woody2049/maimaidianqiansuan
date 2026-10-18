<p align="center">
  <img src="app/brand-logo.png" width="96" alt="麦麦点前算">
</p>

<h1 align="center">麦麦点前算 · maimai-order-math</h1>

<p align="center">点麦当劳之前，先把「这一单怎么点」算清楚。</p>

<p align="center">
  <a href="https://maimai-order-calc.app.workbuddy.host/">在线体验</a> ·
  <a href="SKILL.md">Skill 说明</a> ·
  <a href="mcp-integration.md">MCP 集成</a> ·
  <a href="workbuddy-conversation.md">开发对话记录</a> ·
  <a href="examples/">使用示例</a>
</p>

---

## 这个项目是什么

一个**点单之前**用的决策工具：把预算、必吃/忌口、优惠券和营养目标一起算进去，摆出三组能直接照着下单的搭配，最后跳到麦当劳官方 App 自己下单。

它不代下单、不支付、不碰账号，只负责把「这顿饭怎么搭」算清楚。

三组方案不是三个价格档，而是三种取舍：

| 组 | 一句话 | 主排序 |
|---|---|---|
| 预算优先 | 尽量少花钱，同时吃得饱 | 实际应付升序 |
| 营养参考优先 | 贴着你设的热量与蛋白目标 | 营养贴合度降序 |
| 口味优先 | 想吃的都带上，吃得最满足 | 满足感降序 |

核心原则：**宁可判无解，也不拿超预算、不合营养、点不到的餐品凑数。**

## 缘起

每次在麦当劳点单前都要心算一遍：预算 40，想吃麦辣鸡腿堡加中薯条，怎么搭最省？券该用哪张？蛋白质够不够？——这些数字彼此牵制，人脑算不过来，于是有了这个工具。

它最初是想给自己省两分钟，做完发现真正的价值在**说清取舍**：同一笔预算，为什么这组便宜 5 块但少 10g 蛋白，为什么多花 4 块能正好凑到满减。所以结果页永远给三组，而不是一组「最优解」。

项目通过 WorkBuddy 的对话式开发完成：需求、改版、真机体验复查、上线发布、规则沉淀，全部在一次连续对话里推进，过程记录在 [workbuddy-conversation.md](workbuddy-conversation.md)。

## 功能

- **三组方案**：同一预算下的三种取舍，每组一叠最多 5 个候选，可「换一组方案」翻页。
- **金额三段拆解**：总价 / 优惠 / **实际应付**（外送含 ¥6 配送费，券后满 ¥39 免），应付最醒目。
- **营养四格**：千卡、蛋白质、脂肪、钠，并标出与目标的差距、占每日参考值的比例。
- **无解诊断**：候选池为空时不给方案，改为「卡在哪 + 差多少 + 六个可放开的条件」，每个条件都先试算确认有解才让点。
- **官方价格核验**：接麦当劳 MCP，拉真实门店菜单后逐组调 `calculate-price` 比对，差异超过 1 分就标注「以官方为准」。
- **全国城市/门店**：内地 31 个省级行政区 320 城、1100+ 家示例门店（含价格档与停售差异）。
- **本机优先**：不登录也能保存方案（localStorage，最多 50 条）；云同步是可选项，未配置就整站纯本机。
- **手机优先布局**：390px 宽下大字号大按钮，输入框 ≥16px（避免 iOS 聚焦缩放），首屏直出金额与营养。

## 快速开始

### 1. 网页应用（Node ≥ 18，零依赖）

```bash
git clone <this-repo> maimai-order-math
cd maimai-order-math/app

# 有 MCP Token 就这样起（Node ≥18，无依赖）
MCD_TOKEN=你的Token node server.js

# 没有 Token 也能跑，示例数据全流程可用
node server.js                 # http://localhost:3000
```

`server.js` 会读取环境变量后启动，只做两件事：托管 `index.html`、代理麦当劳 MCP（浏览器直连会被 CORS/WAF 拦）。

没有 Token 也能跑：示例菜单、示例门店、算法、结果页、保存方案全部可用，只有「搜索真实门店」不可用。

### 2. 规则引擎（Python 3.9+，无第三方依赖）

```bash
python3 scripts/meal_planner.py --budget 40 --nutrition any --pickup pickup \
    --want spicy,friesM --coupon prefer --weekday 1
```

输出与网页端逐分一致（示例 1 都是 `¥47 − ¥11.60 = ¥35.4`）。加 `--json` 给程序用，`--list-menu` 查餐品 id。

回归自检：`python3 scripts/check_examples.py` 会按 `examples/cases.json` 跑三个示例并核对关键数字。

### 3. 作为 Skill 使用

把仓库根目录放进技能目录即可（`SKILL.md` + `references/` + `scripts/` 是完整技能包）：

```bash
cp -r maimai-order-math ~/.workbuddy/skills/
```

之后在对话里说「预算 30 想吃麦辣鸡腿堡，帮我算怎么点最省」就会命中这个技能。详细说明见 [SKILL.md](SKILL.md)。

## 环境变量

所有密钥只从环境变量读，仓库里不含任何真实 Token。完整模板见 [`.env.example`](.env.example)：

| 变量 | 必填 | 说明 |
|---|---|---|
| `MCD_TOKEN` | 否 | 麦当劳 MCP Token。填了才能查真实门店/菜单/核价；服务端持有，不下发到浏览器 |
| `MCD_ENDPOINT` | 否 | 默认 `https://mcp.mcd.cn` |
| `PORT` | 否 | 默认 `3000` |
| `CLOUD_ENDPOINT` | 否 | 云同步服务地址（可选，留空=纯本机） |
| `CLOUD_RESOURCE_ID` | 否 | 云资源 id（可选） |
| `CLOUD_OAUTH_RELAY_URL` | 否 | 第三方登录中转地址（可选） |
| `CLOUD_PUBLISHABLE_KEY` | 否 | 云服务公开键（可选；这本身是客户端可见键，但请用自己的） |

```bash
export MCD_TOKEN=你的麦当劳MCP_Token   # 只放在 shell / 容器环境里，不要提交
export PORT=3000
node app/server.js
```

> `server.js` 不读 `.env` 文件本身（保持零依赖），请用 `MCD_TOKEN=xxx node server.js`、`export` 或容器环境变量注入。

## 目录结构

```
.
├── README.md                  # 本文件：缘起、功能、用法、限制、参赛信息
├── SKILL.md                   # Skill 主文件：触发条件、输入 schema、工作流、规则速查
├── mcp-integration.md         # 麦当劳 MCP 集成：传输层、调用顺序、参数、错误处理
├── workbuddy-conversation.md  # 开发对话记录：需求如何一步步变成现在这样
├── .env.example               # 环境变量模板（不含真实密钥）
├── LICENSE                    # MIT
├── examples/
│   ├── README.md              # 三个示例的索引与餐品 id 对照
│   ├── 01-budget-first.md     # 有解：三种取舍
│   ├── 02-no-solution.md      # 无解：差多少、怎么放开
│   ├── 03-delivery-balanced.md# 外送：运费改写最优解
│   ├── cases.json             # 机器可读输入 + 预期数字
│   └── output/                # 引擎原始输出（txt / json）
├── references/
│   ├── rules.md               # 完整规则：公式、筛选、打分、无解诊断
│   └── menu-data.json         # 示例菜单 30 件 / 7 张券 / 4 档营养目标
├── scripts/
│   ├── meal_planner.py        # 规则引擎（与网页端算法 1:1）
│   └── check_examples.py      # 按 cases.json 核对数字的回归脚本
└── app/
    ├── index.html             # 单文件前端（无框架、无构建）
    ├── server.js              # 静态托管 + MCP 代理（零依赖）
    └── package.json
```

## 规则速览

```
总价 = Σ 餐品单价（含门店差价）
优惠 = 单张券的最大优惠（不叠加，且不超过总价）
应付 = 总价 − 优惠 + 配送费
配送费 = 外送时（券后 < 39 ? 6 : 0），自取/得来速为 0
```

营养是**硬门槛**不是加分项：低卡 ≤600 kcal、高蛋白 ≥42 g、均衡 450–900 kcal，达不到直接判无解。组合结构固定为「1 道主餐 + 至多各 1 份小食/饮品/甜品」，共 2–4 件；必吃先锁定、忌口先剔除、停售与渠道不售先筛。

完整公式、四维打分权重、去重与分位取门槛、无解六个方向的试算逻辑，见 [SKILL.md](SKILL.md) 与 [references/rules.md](references/rules.md)。

## 限制与数据说明

- **示例数据**：仓库里的菜单、价格、券、门店均为演示数据，不是麦当劳官方报价；真实价格必须走 MCP。
- **非官方项目**：与麦当劳中国无隶属或合作关系；「麦当劳」「麦辣鸡腿堡」等为权利人商标，仅作说明性使用。
- **不下单不支付**：只做计算与跳转，订单在官方 App 完成。
- **营养值为估算**：来自公开营养成分的近似值，仅作参考，不构成饮食或健康建议；文案不出现减重、降糖等功效表述。
- **真实数据仅支持自取与得来速**：外送接口需要收货地址 `addressId`，未开放，因此外送场景只用示例菜单估算。
- **门店数量受限**：`query-nearby-stores` 一次最多返回 5 家且无分页，关键字要具体到地标。
- **限流**：MCP 侧 600 次/分钟，超了只能等。
- **核价口径**：只比「原价合计」，因为页面上的示例券官方结算不叠加；比应付会系统性偏差。
- **部分门店拉不到菜单**：车站/候车室类门店常返回「门店可能已关闭或不在营业时间」，此时给「换一家」而不是重试。
- **单文件前端**：`index.html` 约 170 KB，图表/交互全部手写，没有构建步骤，也意味着不好做组件化拆分。

## 隐私

- 不收集姓名、电话、地址；真实门店列表刻意不显示门店地址，只给店名、距离、门店编号。
- 登录（可选）只用于云同步，手机号仅以 `138****8000` 形式回显。
- 未登录时方案只存在本机 `localStorage`，清缓存即消失。
- MCP Token 由服务端持有，不写进页面、不落盘、不记日志。

## 参赛信息

| 项 | 内容 |
|---|---|
| 赛事 | WorkBuddy 应用与 Skill 开发征集（赛事全称以官方提交页为准） |
| 赛道 | 开发 Skill（场景编号 #57） |
| 参赛作品 | 麦麦点前算 · `maimai-order-math` |
| 作品形态 | 可交互网页应用 + 可复用 Skill 包 + 规则引擎脚本 |
| 在线体验 | https://maimai-order-calc.app.workbuddy.host/ |
| 提交的 Skill | 本仓库根目录（`SKILL.md` + `references/` + `scripts/`） |
| 开发方式 | WorkBuddy Agent 模式，全程对话式开发（见 [workbuddy-conversation.md](workbuddy-conversation.md)） |
| 完成时间 | 2026-10-18 |

作品想验证的一件事：**Skill 不该只是提示词模板**。把可执行的规则、可复现的数据、可核对的示例一起打包，别人拿去就能跑出同样的数字，才算真的可复用。

## 许可

代码以 [MIT](LICENSE) 授权。示例菜单数据仅用于演示；麦当劳相关商标归权利人所有。
