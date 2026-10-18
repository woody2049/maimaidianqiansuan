# 麦当劳 MCP 集成说明

本文说明「麦麦点前算」怎么接麦当劳官方 MCP：为什么要服务端代理、怎么握手、五个业务接口的调用顺序、真实返回结构里的坑，以及核价口径。

> 本文只写方法与示例。**所有 Token 都从环境变量 `MCD_TOKEN` 读取，仓库里不含任何真实令牌。**

## 1. 为什么要服务端代理

浏览器直连 `https://mcp.mcd.cn` 会被 CORS 与 WAF 拦掉，所以 `app/server.js` 做了一层转发。前端只认两个本地接口：

```
POST /api/mcd/tools   { token? }              → { ok, tools: [{name, description}] }
POST /api/mcd/call    { token?, tool, args }  → { ok, tool, text, structured }
GET  /api/health                              → { ok, mcdConfigured, endpoint, ts }
```

`token` 字段是可选的：服务端配了环境变量 `MCD_TOKEN` 就只用环境变量里的值，客户端传什么都忽略。这样公开部署时，令牌不会出现在 HTML 或浏览器请求体里。

```
浏览器 ──POST /api/mcd/call──▶ server.js ──JSON-RPC over HTTPS──▶ mcp.mcd.cn
                                   │
                                   └─ 会话缓存（token 摘要 → Mcp-Session-Id，10 分钟）
```

## 2. 配置

```bash
export MCD_TOKEN=你的_MCP_Token      # 必填，从麦当劳开放平台控制台申请
export MCD_ENDPOINT=https://mcp.mcd.cn   # 可选
node app/server.js
```

Token 不落盘、不写日志、不下发浏览器。仓库里 `.env.example` 只有占位符：

```bash
MCD_TOKEN=your_mcd_mcp_token_here
```

自测连通性：

```bash
curl -s http://127.0.0.1:3000/api/health
# {"ok":true,"endpoint":"https://mcp.mcd.cn","mcdConfigured":true,...}

curl -s -X POST http://127.0.0.1:3000/api/mcd/call \
  -H 'Content-Type: application/json' \
  -d '{"tool":"query-nearby-stores","args":{"beType":1,"searchType":2,"city":"上海市","keyword":"人民广场"}}'
```

## 3. 传输层：握手与会话

这一步由 `server.js` 负责，调用方只关心工具名和参数。

1. `initialize`，`protocolVersion` 先试 `2025-06-18`，失败退 `2024-11-05`：

   ```json
   {"jsonrpc":"2.0","id":1,"method":"initialize",
    "params":{"protocolVersion":"2025-06-18","capabilities":{},
              "clientInfo":{"name":"maimai-order-calc","version":"1.0.0"}}}
   ```

2. 从响应头取 `Mcp-Session-Id`，再发一次 `notifications/initialized`。
3. 会话按「token 的 sha256 前 24 位」缓存 10 分钟；后续请求带 `Mcp-Session-Id` 与 `MCP-Protocol-Version`。
4. `tools/call` 失败且不是 401/403 时，丢弃会话、用新会话重试一次（会话过期是常态）。
5. 超时 20 秒；响应可能是 `text/event-stream`，取最后一条 `data:` 里的 JSON。
6. 优先读 `structuredContent`，不要解析给人看的 markdown 文本。

## 4. 业务调用顺序

### 第 1 步：找真实门店

```json
{"beType": 1, "searchType": 2, "city": "上海市", "keyword": "人民广场"}
```

- `beType`：`1` 到店自取，`5` 得来速。外送拿不到门店，因此不支持真实数据。
- `searchType: 2` 表示按城市 + 关键字搜，**一次最多 5 家，没有分页**。
- `city` 与 `keyword` 必须同时给，只给 `city` 会报「城市名或者关键词不能为空」。
- 返回里取 `storeCode / storeName / address / distance / beCode`。
- 关键字策略：先用示例门店名去掉「麦当劳」「城市名」「店」得到的词组，再退化成地标或城市名。

### 第 2 步：拉菜单

```json
{"storeCode": "1450713", "orderType": 1, "beType": 1}
```

- `orderType`：`1` 到店/得来速，`2` 外送；`beType` 同上。
- **得来速必须带 `beCode`**（`beType=2/5/6` 时官方会报「必传 beCode」），且得来速是另一批餐厅——原店可能根本没有得来速，要按 `beType=5` 重搜最近一家。
- **真实返回是码表结构**：

  ```text
  data.categories[].meals[].code      // 只有编码与 tags
  data.meals[code] = { name, currentPrice, originalPrice, image }
  ```

  必须按 `code` 拼装名称与价格。直接取「最大的对象数组」里的 `name/price`，拿到的是只有 `{code, tags}` 的记录，结果是 0 件。
- 解析出的餐品少于 8 件时判定解析失败，回落到示例菜单并在界面说明，不要拿半份菜单继续算。

### 第 3 步：营养表（可选）

```json
{}
```

- 返回的 `data` 是 TOON 文本（`[N]{fields}:` 行格式），需要专门解析。
- 拿不到不影响价格；按餐品名匹配，匹配不上就保留示例估算值。

### 第 4 步：门店券（可选）

```json
{"storeCode": "1450713", "orderType": 1, "beType": 1}
```

只做展示与参考，**不参与本地优惠计算**——官方结算不会与页面上的示例券叠加。账号券 `query-my-coupons` 同理，当前流程不调用。

### 第 5 步：价格核验

```json
{
  "storeCode": "1450713", "orderType": 1, "beType": 1, "needTableware": false,
  "items": [{"productCode": "1000123", "quantity": 1}]
}
```

- 每件餐品都要能映射到 `productCode`；映射不到就报「某餐品没有官方商品编码」，不要猜编码。
- 返回取 `price`（应付）、`originalPrice`（原价）、`discount`，单位是分，需要 ÷100。
- 本地用**原价合计**与 `originalPrice` 比，不要用应付比——示例券不参与官方结算，比应付会系统性偏低。
- 差值 `< 0.01` 记一致，否则记差异并在界面标明「以官方结果为准」。
- 同一方案 10 分钟内复用结果；换门店、换取餐方式后缓存失效。

## 5. 一次完整同步的时序

```
用户搜门店
  └─ query-nearby-stores(beType, searchType=2, city, keyword) → 候选（≤5 家）
用户点选一家
  ├─ query-meals                → 餐品与价格（按 code 码表拼装）
  ├─ list-nutrition-foods       → 营养（失败可忽略）
  ├─ query-store-coupons        → 门店券（失败可忽略）
  └─ buildMenu                  → 生成可售清单（<8 件则回落示例菜单）

用户点「开始计算」
  ├─ 本地穷举 + 打分（不调 MCP）
  └─ 对每张展示方案调 calculate-price（10 分钟缓存、同方案去重）

用户换门店 / 换取餐方式
  └─ 清空真实菜单 → 重走 query-meals 链路
  └─ 得来速若原店不支持 → query-nearby-stores(beType=5) 换最近一家
```

调用次数估算：一次「搜店 + 同步 + 三组核价」约 6–8 次；连续刷方案不会重复核价（命中缓存）。按 600 次/分钟限流算，够 70+ 次完整同步。

## 6. 错误映射

| HTTP / 现象 | 含义 | 页面处理 |
|---|---|---|
| 401 | Token 无效或过期 | 提示检查 `MCD_TOKEN`，不重试 |
| 403 | 权限不足 / WAF 拦截 | 提示 Token 或权限问题，不重试 |
| 429 | 超过 600 次/分钟 | 提示稍后再试，不自动重试 |
| 5xx / 超时（20s） | 上游异常 | 提示稍后重试，保留本地估算结果 |
| `isError: true` | 工具级错误（如门店已关闭） | 透出官方原话 + 给「换一家」入口 |
| 餐品只解析出几件 | 码表没拼对 | 回落示例菜单并说明 |
| 核价金额有差异 | 门店调价 / 券不适用 | 标注差异，以官方为准 |
| 外送选真实门店 | 官方要 `addressId` | 只允许自取与得来速 |

## 7. 三个容易踩的坑

1. **拿 `text` 当数据**：工具返回的 `text` 是「字段说明 markdown + ## Original Response {json}」，`JSON.parse` 和 TOON 都解析不了。必须先看 `structuredContent`。
2. **把菜单当扁平数组**：真实菜单是 `categories + meals 码表` 两级结构，套餐/拼盘/单人餐/随心配类目还要跳过。
3. **`storeCode` 和 `beCode` 不是一回事**：自取用 `storeCode`，得来速除了 `storeCode` 还要 `beCode`（来自 `query-nearby-stores` 的返回）。

## 8. 拿不到 Token 怎么办

项目不是必须连 MCP：

- 示例菜单 30 件、7 张券、320 城 1100+ 门店足够跑通全部计算与交互。
- 结果页会标「示例数据」，核价区显示「金额为本地估算」。
- 真实门店按钮在未配置 Token 时返回明确提示，不会静默失败。

这样任何人都能 `git clone` 后直接看到完整效果，不必先申请令牌。
