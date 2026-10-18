# 使用示例

三个场景覆盖了这套规则的三种结局：**有解**、**无解**、**有解但金额被运费改写**。

所有输出都是 `scripts/meal_planner.py` 的真实运行结果（同时归档在 [`output/`](output/)），不是手写的示意。示例 1 与线上应用默认场景完全一致：`¥47 − ¥11.60 = ¥35.4`。

| 示例 | 场景 | 候选池 | 结局 | 想看什么 |
|---|---|---|---|---|
| [01 预算优先](01-budget-first.md) | ¥40 / 不限 / 自取 / 必吃 2 项 | 16 | 三组方案 | 同价的两种取舍 |
| [02 无解诊断](02-no-solution.md) | ¥25 / 高蛋白 / 必吃双层吉士 | 0 | 无解 | 差多少、怎么放开 |
| [03 外送均衡](03-delivery-balanced.md) | ¥60 / 均衡 / 外送 / 忌口苹果片 | 45 | 三组方案 | 运费如何改写最优解 |

## 怎么复现

```bash
# 示例 1
python3 scripts/meal_planner.py --budget 40 --nutrition any --pickup pickup \
    --want spicy,friesM --coupon prefer --weekday 1

# 示例 2
python3 scripts/meal_planner.py --budget 25 --nutrition protein --pickup pickup \
    --want doublech --coupon normal --weekday 1

# 示例 3
python3 scripts/meal_planner.py --budget 60 --nutrition balanced --pickup delivery \
    --want bigmac --avoid apple --coupon prefer --weekday 2
```

`--weekday` 用 0–6 表示周日到周六（默认 1 = 周一；2 = 周二，触发会员日 88 折券）。机器可读的输入与预期值见 [`cases.json`](cases.json)，核对脚本：`python3 scripts/check_examples.py`。

## 餐品 id 对照（示例菜单）

| id | 餐品 | 价格 | 类目 |
|---|---|---|---|
| `spicy` | 麦辣鸡腿堡 | ¥21.5 | main |
| `doublech` | 双层吉士汉堡 | ¥19.5 | main |
| `bigmac` | 巨无霸 | ¥25.5 | main |
| `friesM` | 中薯条 | ¥12.5 | side |
| `apple` | 苹果片 | ¥8 | side |
| `nug5` | 麦乐鸡 5 块 | ¥14.5 | side |
| `corn` | 玉米杯 | ¥9.5 | side |
| `tea` | 柠檬茶 | ¥13 | drink |
| `cokezero` | 零度可乐（中） | ¥9.5 | drink |
| `coffee` | 鲜煮咖啡 | ¥12 | drink |
| `milk` | 纯牛奶 | ¥8 | drink |
| `cone` | 圆筒冰淇淋 | ¥6 | dessert |
| `pieT` | 香芋派 | ¥9 | dessert |

完整 30 件用 `python3 scripts/meal_planner.py --list-menu` 查看，原始数据在 [`../references/menu-data.json`](../references/menu-data.json)。

## 读输出的三个要点

1. **看实际应付，不看总价**：总价是货架价，券和运费之后才是你要付的钱。
2. **三组不是三档价格**：同一预算下的三种取舍，常常同价不同热量。
3. **无解也是结果**：说明条件互相打架，比给一个凑数的方案有用。
