#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦麦点前算 · 规则引擎（与 index.html 核心算法 1:1 对应）

用法示例：
  python3 meal_planner.py --budget 40 --nutrition any --pickup pickup \
      --want spicy,friesM --coupon prefer

输出：三组方案（预算优先 / 营养参考优先 / 口味优先）+ 逐项金额与营养；
条件冲突时输出「无解诊断 + 六个可放开的条件」。

数据来源：references/menu-data.json（示例菜单 / 示例券 / 营养目标）。
"""

import argparse
import json
import os
import re
import sys
from itertools import product

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(HERE, "..", "references", "menu-data.json")

DELIVERY_FEE = 6
FREE_DELIVERY_LINE = 39

CATS = ["main", "side", "drink", "dessert"]

# 取餐方式按名称兜底筛选（官方菜单也走这一层）
CHANNEL_RESTRICT = {
    "pickup": None,
    "delivery": re.compile(r"(冰淇淋|麦旋风|新地|圆筒|沙拉)"),
    "drivethru": re.compile(r"(冰淇淋|麦旋风|新地|圆筒)"),
}

PICKUP_LABEL = {"pickup": "到店自取", "delivery": "外送", "drivethru": "得来速"}

# 营养硬条件：达不到即无解，不硬凑
NUTRITION_RULES = {
    "any": lambda ev: True,
    "low": lambda ev: ev["kcal"] <= 600,
    "protein": lambda ev: ev["protein"] >= 42,
    "balanced": lambda ev: 450 <= ev["kcal"] <= 900,
}
NUTRITION_RELAX = {
    "protein": ["balanced", "any"],
    "low": ["any"],
    "balanced": ["any"],
    "any": [],
}

GROUPS = [
    {"key": "budget", "name": "预算优先", "w": {"fit": .18, "value": .48, "disc": .24, "sat": .10},
     "sort": "price", "gate": .55},
    {"key": "nutrition", "name": "营养参考优先", "w": {"fit": .60, "value": .16, "disc": .12, "sat": .12},
     "sort": "fit", "gate": .50},
    {"key": "taste", "name": "口味优先", "w": {"fit": .14, "value": .14, "disc": .12, "sat": .60},
     "sort": "sat", "gate": .50},
]


def load_data():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


DATA = load_data()
MENU = DATA["menu"]
COUPONS = DATA["coupons"]
TARGETS = DATA["targets"]
BY_ID = {i["id"]: i for i in MENU}


def round2(n):
    return round(n + 1e-9, 2)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def money(n):
    v = round2(n)
    if abs(v - round(v)) < 1e-9:
        return "¥%d" % round(v)
    if abs(v * 10 - round(v * 10)) < 1e-9:
        return "¥%.1f" % v
    return "¥%.2f" % v


def item_price(item, delta):
    return round2(item["price"] + delta)


def channel_blocked(item, pickup):
    rule = CHANNEL_RESTRICT.get(pickup)
    return bool(rule and rule.search(item.get("name", "")))


def build_menu(delta=0.0, soldout=(), pickup="pickup"):
    sold = set(soldout)
    avail, sold_names, chan_names = [], [], []
    for i in MENU:
        if i["id"] in sold:
            sold_names.append(i["name"])
            continue
        if channel_blocked(i, pickup):
            chan_names.append(i["name"])
            continue
        avail.append(dict(i, price=item_price(i, delta)))
    return {"items": avail, "soldout": sold_names, "channel": chan_names}


def coupon_discount(c, items, subtotal):
    t = c["type"]
    if t == "pair":
        pool = sorted([i for i in items if i.get("pair")], key=lambda x: -x["price"])
        if len(pool) < 2:
            return 0.0
        return round2(max(0.0, round2(pool[0]["price"] + pool[1]["price"]) - c["price"]))
    if t == "combo":
        have = {i["cat"] for i in items}
        return float(c["off"]) if all(cat in have for cat in c["cats"]) else 0.0
    if t == "threshold":
        return float(c["off"]) if subtotal >= c["min"] else 0.0
    if t == "item":
        return float(c["off"]) if any(i["id"] == c["item"] for i in items) else 0.0
    if t == "flat":
        return float(c["off"])
    if t == "rate":
        return round2(subtotal * c["rate"])
    return 0.0


def available_coupons(weekday):
    return [c for c in COUPONS if c.get("onlyWeekday") is None or c["onlyWeekday"] == weekday]


def evaluate(items, coupons, pickup):
    subtotal = round2(sum(i["price"] for i in items))
    best, best_d = None, 0.0
    for c in coupons:
        d = round2(coupon_discount(c, items, subtotal))
        d = min(d, subtotal)
        if d > best_d + 1e-9:
            best_d, best = d, c
    after = round2(subtotal - best_d)
    fee = 0.0
    if pickup == "delivery":
        fee = 0.0 if after >= FREE_DELIVERY_LINE else float(DELIVERY_FEE)
    return {
        "items": items,
        "subtotal": subtotal,
        "discount": best_d,
        "coupon": best["name"] if best else None,
        "deliveryFee": fee,
        "total": round2(after + fee),
        "kcal": sum(i["kcal"] for i in items),
        "protein": sum(i["p"] for i in items),
        "fat": sum(i["f"] for i in items),
        "na": sum(i["na"] for i in items),
        "sat": sum(i["sat"] for i in items),
    }


def enumerate_plans(opts, menu_items):
    blocked = set(opts["avoid"])
    pool = [i for i in menu_items if i["id"] not in blocked]
    want = opts["want"]
    forced = [i for i in pool if i["id"] in want]
    forced_ids = {i["id"] for i in forced}
    cnt = lambda cat: sum(1 for i in forced if i["cat"] == cat)
    rest = [i for i in pool if i["id"] not in forced_ids]

    main_opts = [None] if cnt("main") else [i for i in rest if i["cat"] == "main"]
    side_opts = [None] if cnt("side") else [None] + [i for i in rest if i["cat"] == "side"]
    drink_opts = [None] if cnt("drink") else [None] + [i for i in rest if i["cat"] == "drink"]
    des_opts = [None] if cnt("dessert") else [None] + [i for i in rest if i["cat"] == "dessert"]

    out, seen = [], set()
    for m, s, d, ds in product(main_opts, side_opts, drink_opts, des_opts):
        items = forced + [x for x in (m, s, d, ds) if x]
        if not (2 <= len(items) <= 4):
            continue
        if not any(i["cat"] == "main" for i in items):
            continue
        sig = "|".join(sorted(i["id"] for i in items))
        if sig in seen:
            continue
        seen.add(sig)
        out.append(items)
    return out


def scan(opts, delta=0.0, soldout=(), weekday=1):
    report = build_menu(delta, soldout, opts["pickup"])
    avail_ids = {i["id"] for i in report["items"]}
    want_blocked = [w for w in opts["want"] if w not in avail_ids]
    coupons = [] if opts["coupon"] == "none" else available_coupons(weekday)
    combos = []
    for items in enumerate_plans(opts, report["items"]):
        ev = evaluate(items, coupons, opts["pickup"])
        combos.append({"items": items, "ev": ev,
                       "sig": "|".join(sorted(i["id"] for i in items))})
    rule = NUTRITION_RULES.get(opts["nutrition"], NUTRITION_RULES["any"])
    in_budget = [p for p in combos if p["ev"]["total"] <= opts["budget"] + 1e-6]
    pass_budget = [p for p in in_budget if rule(p["ev"])]
    pass_any = [p for p in combos if rule(p["ev"])]
    feasible = [] if want_blocked else pass_budget

    def mn(arr, f):
        return min((f(p) for p in arr), default=0)

    def mx(arr, f):
        return max((f(p) for p in arr), default=0)

    return {
        "report": report, "combos": combos, "inBudget": in_budget,
        "passBudget": pass_budget, "pass": feasible, "passAny": pass_any,
        "wantBlocked": want_blocked, "coupons": coupons,
        "cheapest": mn(combos, lambda p: p["ev"]["total"]),
        "cheapestPass": mn(pass_any, lambda p: p["ev"]["total"]),
        "proteinMaxInBudget": mx(in_budget, lambda p: p["ev"]["protein"]),
        "kcalMinInBudget": mn(in_budget, lambda p: p["ev"]["kcal"]),
        "kcalMaxInBudget": mx(in_budget, lambda p: p["ev"]["kcal"]),
        "feasible": bool(feasible),
    }


def score_plan(ev, weights, nutr_key, budget, coupon_first):
    t = TARGETS[nutr_key]
    kcal_fit = clamp(1 - abs(ev["kcal"] - t["kcal"]) / (t["kcal"] * 0.62), 0, 1)
    pro_fit = clamp(ev["protein"] / t["protein"], 0, 1)
    fit = 0.6 * kcal_fit + 0.4 * pro_fit
    value = clamp((ev["kcal"] / max(ev["total"], 1)) / 32, 0, 1)
    disc = clamp((ev["discount"] / ev["subtotal"]) / 0.36, 0, 1) if ev["subtotal"] else 0
    sat = clamp((ev["sat"] - 3) / 7, 0, 1)
    complete = (0.5 if any(i["cat"] == "side" for i in ev["items"]) else 0) + \
               (0.5 if any(i["cat"] == "drink" for i in ev["items"]) else 0)
    w = {
        "fit": weights["fit"] * (1 if nutr_key == "any" else 1.15),
        "value": weights["value"],
        "disc": weights["disc"] * (1 if coupon_first else 0.2),
        "sat": weights["sat"],
    }
    s = w["fit"] * fit + w["value"] * value + w["disc"] * disc + w["sat"] * sat + complete * 0.03
    over = ev["total"] - budget
    if over > 0:
        s -= 0.4 + (over / max(budget, 1)) * 1.1
    return {"score": s, "fit": fit, "value": value, "disc": disc, "sat": sat}


def main_id_of(ev):
    for i in ev["items"]:
        if i["cat"] == "main":
            return i["id"]
    return ""


def extras_of(ev, forced):
    return [i["id"] for i in ev["items"] if i["cat"] != "main" and i["id"] not in forced]


def too_similar(a, b, forced):
    ea, eb = extras_of(a, forced), extras_of(b, forced)
    ma, mb = main_id_of(a), main_id_of(b)
    if ma == mb and ma not in forced:
        if not ea or not eb:
            return True
        if len(ea) >= 2 and len(eb) >= 2:
            return True
        return any(x in eb for x in ea)
    if not ea or not eb:
        return len(ea) == len(eb)
    shared = len([x for x in eb if x in ea])
    return shared >= min(len(ea), len(eb))


def build_decks(opts, delta=0.0, soldout=(), weekday=1):
    sc = scan(opts, delta, soldout, weekday)
    pool = sc["pass"]
    forced = set(opts["want"])
    decks, used = {}, set()
    for g in GROUPS:
        if not pool:
            decks[g["key"]] = []
            continue
        scored = [{"ev": p["ev"], "sig": p["sig"],
                   "s": score_plan(p["ev"], g["w"], opts["nutrition"], opts["budget"],
                                   opts["coupon"] == "prefer")} for p in pool]
        mx = max(x["s"]["score"] for x in scored)
        mn = min(x["s"]["score"] for x in scored)
        spread = max(1e-6, mx - mn)
        gate = mx - spread * (1 - g["gate"])
        lst = [x for x in scored if x["s"]["score"] >= gate] or scored[:]
        if g["sort"] == "price":
            lst.sort(key=lambda x: (x["ev"]["total"], -x["s"]["score"]))
        elif g["sort"] == "fit":
            lst.sort(key=lambda x: (-x["s"]["fit"], -x["s"]["score"]))
        else:
            lst.sort(key=lambda x: (-x["ev"]["sat"], x["ev"]["total"]))

        deck = []

        def fill(arr):
            for c in arr:
                if len(deck) >= 5:
                    break
                if any(d["sig"] == c["sig"] for d in deck):
                    continue
                if any(too_similar(d["ev"], c["ev"], forced) for d in deck):
                    continue
                deck.append(c)

        fill(lst)
        if deck and deck[0]["sig"] in used:
            fill(scored)
        at = next((i for i, d in enumerate(deck) if d["sig"] not in used), -1)
        if at > 0:
            deck = deck[at:] + deck[:at]
        if deck:
            used.add(deck[0]["sig"])
        decks[g["key"]] = deck
    return {"decks": decks, "feasible": bool(pool), "scan": sc,
            "totalPlans": len(sc["combos"]), "inBudget": len(sc["inBudget"]),
            "poolSize": len(pool)}


def diagnose(opts, sc):
    t = TARGETS[opts["nutrition"]]
    conflicts = []
    for wid in sc["wantBlocked"]:
        item = BY_ID.get(wid, {})
        no_chan = channel_blocked(item, opts["pickup"])
        conflicts.append({
            "tag": "餐品",
            "title": "「%s」%s" % (item.get("name", wid),
                                 ("%s不售" % PICKUP_LABEL[opts["pickup"]]) if no_chan else "这家门店停售"),
            "detail": "该餐品在当前渠道点不到，换个取餐方式或换同类餐品。" if no_chan
                      else "当前门店没有这道，换门店或换同类餐品。",
        })
    avoid = set(opts["avoid"])
    avail_mains = [i for i in sc["report"]["items"] if i["cat"] == "main" and i["id"] not in avoid]
    blocked_mains = [i for i in sc["report"]["items"] if i["cat"] == "main" and i["id"] in avoid]
    if not avail_mains:
        conflicts.append({
            "tag": "餐品",
            "title": "主餐被忌口排光了" if blocked_mains else "这家店没有可售主餐",
            "detail": ("一个套餐至少要 1 道主餐，而你忌口了 %d 道主餐。" % len(blocked_mains))
                      if blocked_mains else "换门店或换城市。",
        })
    elif not sc["combos"] and not sc["wantBlocked"]:
        conflicts.append({
            "tag": "组合",
            "title": "按现在的必吃项凑不出套餐",
            "detail": "套餐是「1 主餐 + 最多 3 件配餐」，必吃项已占满 4 件。",
        })
    if sc["combos"] and not sc["inBudget"]:
        conflicts.append({
            "tag": "预算",
            "title": "预算 %s 装不下任何组合" % money(opts["budget"]),
            "detail": "当前门店最便宜的组合要 %s，差 %s。%s" % (
                money(sc["cheapest"]), money(sc["cheapest"] - opts["budget"]),
                ("同时满足「%s」最低要 %s。" % (t["label"], money(sc["cheapestPass"])))
                if sc["cheapestPass"] > sc["cheapest"] else ""),
        })
    if sc["inBudget"] and not sc["passBudget"]:
        if opts["nutrition"] == "protein":
            d = "预算内蛋白质最高 %dg，离目标 %dg 差 %dg。" % (
                sc["proteinMaxInBudget"], t["protein"], max(0, t["protein"] - sc["proteinMaxInBudget"]))
        elif opts["nutrition"] == "low":
            d = "预算内热量最低也有 %d 千卡，超过低卡上限 600 千卡。" % sc["kcalMinInBudget"]
        else:
            d = "预算内热量在 %d–%d 千卡，落在均衡区间 450–900 之外。" % (
                sc["kcalMinInBudget"], sc["kcalMaxInBudget"])
        if sc["cheapestPass"] > opts["budget"]:
            d += " 达标最便宜的组合要 %s。" % money(sc["cheapestPass"])
        conflicts.append({"tag": "营养", "title": "「%s」和预算互相打架" % t["label"], "detail": d})
    if not conflicts and not sc["feasible"]:
        conflicts.append({"tag": "条件", "title": "这几项条件凑不到一起",
                          "detail": "预算、必吃、忌口、取餐方式与营养参考没有交集。"})
    return conflicts


def fix_one(opts, patch, delta, soldout, weekday, allow_budget=True):
    def run(p):
        nxt = dict(opts)
        nxt.update(p)
        nxt["want"] = list(nxt.get("want") or [])
        nxt["avoid"] = list(nxt.get("avoid") or [])
        s = scan(nxt, delta, soldout, weekday)
        return (p, s) if s["feasible"] else None

    r = run(patch)
    if r:
        return {"patch": r[0], "scan": r[1], "extra": []}
    for alt in NUTRITION_RELAX.get(opts["nutrition"], []):
        r = run(dict(patch, nutrition=alt))
        if r:
            return {"patch": r[0], "scan": r[1], "extra": ["营养放宽到" + TARGETS[alt]["label"]]}
    if not allow_budget:
        return None
    p2 = dict(patch, nutrition="any")
    s0 = scan(dict(opts, **p2), delta, soldout, weekday)
    if not s0["combos"]:
        return None
    need = int(-(-s0["cheapest"] // 1))
    budget = max(opts["budget"], p2.get("budget") or 0, need)
    if budget > 80 or budget == opts["budget"]:
        return None
    r = run(dict(p2, budget=budget))
    if r:
        return {"patch": r[0], "scan": r[1], "extra": ["营养放宽到不限", "预算提到" + money(budget)]}
    return None


def actions(opts, sc, delta, soldout, weekday):
    acts = []
    blocked = bool(sc["wantBlocked"])
    avoid = set(opts["avoid"])
    no_main = not any(i["cat"] == "main" and i["id"] not in avoid for i in sc["report"]["items"])

    # 1 增加预算
    targets = sorted({int(-(-v // 1)) for v in (sc["cheapestPass"], sc["cheapest"])
                      if opts["budget"] < v <= 80})
    fix = None
    for v in targets:
        r = fix_one(opts, {"budget": v}, delta, soldout, weekday)
        if not r:
            continue
        fix = fix if (fix and not r["extra"]) else r
        if not r["extra"]:
            fix = r
            break
    if fix:
        acts.append({"key": "budget", "label": "增加预算", "ok": True,
                     "detail": "%s → %s%s" % (money(opts["budget"]), money(fix["patch"]["budget"]),
                                              ("，" + "，".join(fix["extra"])) if fix["extra"] else "，能满足全部条件")})
    else:
        why = ("这道餐品现在点不到，加预算也没用" if blocked else
               "主餐全被排掉，加预算也没用" if no_main else
               "没有可组合的套餐，加预算也没用" if not sc["combos"] else
               "至少要 %s，超过 ¥80 上限" % money(sc["cheapest"]) if sc["cheapest"] > 80 else
               "预算不是这里的卡点")
        acts.append({"key": "budget", "label": "增加预算", "ok": False, "detail": why})

    # 2 放宽营养参考
    alts = NUTRITION_RELAX.get(opts["nutrition"], [])
    if not alts:
        acts.append({"key": "nutrition", "label": "放宽营养参考", "ok": False, "detail": "已经是不限"})
    elif blocked or no_main:
        acts.append({"key": "nutrition", "label": "放宽营养参考", "ok": False,
                     "detail": "卡点不在营养，是餐品点不到" if blocked else "先放开一道主餐"})
    else:
        r = None
        for alt in alts:
            r = fix_one(opts, {"nutrition": alt}, delta, soldout, weekday)
            if r:
                break
        if r:
            acts.append({"key": "nutrition", "label": "放宽营养参考", "ok": True,
                         "detail": "%s → %s%s" % (TARGETS[opts["nutrition"]]["label"],
                                                  TARGETS[r["patch"]["nutrition"]]["label"],
                                                  ("，" + "，".join(x for x in r["extra"] if not x.startswith("营养放宽"))) if r["extra"] else "")})
        else:
            acts.append({"key": "nutrition", "label": "放宽营养参考", "ok": False,
                         "detail": "放宽到「不限」也凑不出来"})

    # 3 替换餐品
    if not opts["want"]:
        acts.append({"key": "swap", "label": "替换餐品", "ok": False, "detail": "没勾必吃项，没有可替换目标"})
    else:
        fix = None
        for wid in opts["want"]:
            old = BY_ID.get(wid)
            if not old:
                continue
            cands = sorted([x for x in sc["report"]["items"]
                            if x["cat"] == old["cat"] and x["id"] != wid
                            and x["id"] not in opts["want"] and x["id"] not in avoid],
                           key=lambda x: (x["price"], x["kcal"]))[:12]
            for c in cands:
                nxt = [c["id"] if x == wid else x for x in opts["want"]]
                r = fix_one(opts, {"want": nxt}, delta, soldout, weekday)
                if not r:
                    continue
                if not fix or (fix[2]["extra"] and not r["extra"]):
                    fix = (wid, c, r)
                if not r["extra"]:
                    break
            if fix and not fix[2]["extra"]:
                break
        if fix:
            wid, c, r = fix
            acts.append({"key": "swap", "label": "替换餐品", "ok": True,
                         "detail": "把「%s」换成「%s」（%s）%s" % (
                             BY_ID[wid]["name"], c["name"], money(c["price"]),
                             ("，" + "，".join(r["extra"])) if r["extra"] else "")})
        else:
            acts.append({"key": "swap", "label": "替换餐品", "ok": False, "detail": "同类里换哪道都凑不齐"})

    # 4 去掉一个餐品
    fix = None
    for wid in sorted(opts["want"], key=lambda x: -(BY_ID.get(x, {}).get("price", 0))):
        r = fix_one(opts, {"want": [x for x in opts["want"] if x != wid]}, delta, soldout, weekday)
        if r:
            fix = (wid, r)
            if not r["extra"]:
                break
    if fix:
        acts.append({"key": "drop", "label": "去掉一个餐品", "ok": True,
                     "detail": "去掉「%s」%s" % (BY_ID[fix[0]]["name"],
                                               ("，" + "，".join(fix[1]["extra"])) if fix[1]["extra"] else "")})
    else:
        acts.append({"key": "drop", "label": "去掉一个餐品", "ok": False, "detail": "去掉任何一项都还差条件"})

    # 5 更换取餐方式
    fix = None
    for mode in ("pickup", "drivethru", "delivery"):
        if mode == opts["pickup"]:
            continue
        s = scan(dict(opts, pickup=mode), delta, soldout, weekday)
        if s["feasible"]:
            fix = mode
            break
    if fix:
        acts.append({"key": "pickup", "label": "更换取餐方式", "ok": True,
                     "detail": "%s → %s" % (PICKUP_LABEL[opts["pickup"]], PICKUP_LABEL[fix])})
    else:
        acts.append({"key": "pickup", "label": "更换取餐方式", "ok": False, "detail": "另外两种方式也凑不出来"})

    # 6 更换门店（脚本只调整门店差价/停售这两个维度）
    fix = None
    for d in (delta - 1, delta - 0.5, delta + 0.5, delta + 1, 0):
        s = scan(opts, d, (), weekday)
        if s["feasible"]:
            fix = d
            break
    if fix is not None:
        acts.append({"key": "store", "label": "更换门店", "ok": True,
                     "detail": "换到价格档 %+.1f、无停售的门店（%s）" % (fix, PICKUP_LABEL[opts["pickup"]])})
    else:
        acts.append({"key": "store", "label": "更换门店", "ok": False, "detail": "换门店也解决不了"})
    return acts


def render(opts, res, delta, soldout, weekday):
    sc = res["scan"]
    out = []
    out.append("## 条件")
    out.append("- 预算：%s｜营养参考：%s｜取餐方式：%s" % (
        money(opts["budget"]), TARGETS[opts["nutrition"]]["label"], PICKUP_LABEL[opts["pickup"]]))
    out.append("- 必吃：%s｜忌口：%s｜券偏好：%s" % (
        "、".join(BY_ID[x]["name"] for x in opts["want"] if x in BY_ID) or "无",
        "、".join(BY_ID[x]["name"] for x in opts["avoid"] if x in BY_ID) or "无",
        {"prefer": "优先用券", "normal": "顺其自然", "none": "不用券"}[opts["coupon"]]))
    out.append("- 门店：差价 %+.1f｜停售：%s｜可选 %d 件" % (
        delta, "、".join(sc["report"]["soldout"]) or "无", len(sc["report"]["items"])))
    out.append("")
    out.append("## 筛选过程")
    out.append("穷举 %d 种组合 → 预算内 %d 种 → 同时达到营养参考 %d 种（候选池）%s" % (
        res["totalPlans"], res["inBudget"], res["poolSize"],
        "；必吃项点不到，判定无解" if sc["wantBlocked"] else ""))

    if not res["feasible"]:
        out.append("")
        out.append("## 无解诊断")
        for c in diagnose(opts, sc):
            out.append("- **【%s】%s**：%s" % (c["tag"], c["title"], c["detail"]))
        out.append("")
        out.append("## 可放开的条件（每个都先试算确认有解）")
        for a in actions(opts, sc, delta, soldout, weekday):
            out.append("- %s：%s" % (a["label"], a["detail"]))
        return "\n".join(out)

    out.append("")
    for g in GROUPS:
        deck = res["decks"][g["key"]]
        out.append("## %s%s" % (g["name"], "" if deck else "（收敛到别的组）"))
        if not deck:
            out.append("_这组没有更合适的搭配，可用「换一组方案」或调整条件。_\n")
            continue
        pick = deck[0]
        ev = pick["ev"]
        out.append("- 总价 %s｜优惠 %s｜**实际应付 %s**" % (
            money(ev["subtotal"]),
            ("−" + money(ev["discount"])) if ev["discount"] > 0 else "¥0.00",
            money(ev["total"])))
        if ev["coupon"]:
            out.append("- 用券：%s（单张最优，不叠加）" % ev["coupon"])
        if ev["deliveryFee"] > 0:
            out.append("- 配送费：%s（券后未满 %s）" % (money(ev["deliveryFee"]), money(FREE_DELIVERY_LINE)))
        out.append("- 餐品：%s" % "、".join("%s %s" % (i["name"], money(i["price"])) for i in ev["items"]))
        out.append("- 营养：%d 千卡 / 蛋白质 %dg / 脂肪 %dg / 钠 %dmg" % (
            ev["kcal"], ev["protein"], ev["fat"], ev["na"]))
        out.append("- 该组候选 %d 个（换一组方案可翻页）" % len(deck))
        out.append("")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="麦麦点前算 · 规则引擎")
    ap.add_argument("--budget", type=float, default=40, help="预算上限（12–80）")
    ap.add_argument("--nutrition", choices=list(TARGETS), default="any")
    ap.add_argument("--pickup", choices=list(PICKUP_LABEL), default="pickup")
    ap.add_argument("--want", default="", help="必吃餐品 id，逗号分隔，最多 3 个")
    ap.add_argument("--avoid", default="", help="忌口餐品 id，逗号分隔")
    ap.add_argument("--coupon", choices=["prefer", "normal", "none"], default="prefer")
    ap.add_argument("--store-delta", type=float, default=0.0, help="门店价格档差价")
    ap.add_argument("--soldout", default="", help="门店停售餐品 id，逗号分隔")
    ap.add_argument("--weekday", type=int, default=1, help="0=周日 … 6=周六，影响周二 88 折券")
    ap.add_argument("--list-menu", action="store_true", help="打印餐品 id 与价格")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    if args.list_menu:
        for cat in CATS:
            print("[%s]" % cat)
            for i in MENU:
                if i["cat"] == cat:
                    print("  %-10s %-16s %6.1f  %4d kcal  P%dg" % (
                        i["id"], i["name"], i["price"], i["kcal"], i["p"]))
        return

    opts = {
        "budget": clamp(args.budget, 12, 80),
        "nutrition": args.nutrition,
        "pickup": args.pickup,
        "want": [x.strip() for x in args.want.split(",") if x.strip()][:3],
        "avoid": [x.strip() for x in args.avoid.split(",") if x.strip()],
        "coupon": args.coupon,
    }
    bad = [x for x in opts["want"] + opts["avoid"] if x not in BY_ID]
    if bad:
        sys.exit("未知餐品 id：%s（用 --list-menu 查看）" % ", ".join(bad))
    delta = args.store_delta
    soldout = [x.strip() for x in args.soldout.split(",") if x.strip()]
    known = [x for x in soldout if x not in BY_ID]
    if known:
        sys.exit("未知餐品 id：%s" % ", ".join(known))

    res = build_decks(opts, delta, soldout, args.weekday)
    if args.json:
        payload = {
            "opts": opts, "feasible": res["feasible"],
            "totalPlans": res["totalPlans"], "inBudget": res["inBudget"], "poolSize": res["poolSize"],
            "decks": {k: [{"sig": p["sig"], "total": p["ev"]["total"],
                           "subtotal": p["ev"]["subtotal"], "discount": p["ev"]["discount"],
                           "coupon": p["ev"]["coupon"],
                           "items": [i["id"] for i in p["ev"]["items"]],
                           "kcal": p["ev"]["kcal"], "protein": p["ev"]["protein"]}
                          for p in v] for k, v in res["decks"].items()},
        }
        if not res["feasible"]:
            payload["conflicts"] = diagnose(opts, res["scan"])
            payload["actions"] = actions(opts, res["scan"], delta, soldout, args.weekday)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print(render(opts, res, delta, soldout, args.weekday))


if __name__ == "__main__":
    main()
