#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 examples/cases.json 跑三个示例，核对关键数字是否与文档一致。

用法：
    python3 scripts/check_examples.py

不依赖第三方库；任何一项不符就返回非 0，方便放进 CI。
"""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(ROOT, "scripts", "meal_planner.py")
CASES = os.path.join(ROOT, "examples", "cases.json")

GROUP_KEYS = ("budget", "nutrition", "taste")


def run_case(case):
    """把 input 转成命令行参数，跑引擎拿 JSON。"""
    inp = case["input"]
    argv = [sys.executable, ENGINE,
            "--budget", str(inp["budget"]),
            "--nutrition", inp["nutrition"],
            "--pickup", inp["pickup"],
            "--coupon", inp["coupon"],
            "--weekday", str(inp["weekday"]),
            "--json"]
    if inp["want"]:
        argv += ["--want", ",".join(inp["want"])]
    if inp["avoid"]:
        argv += ["--avoid", ",".join(inp["avoid"])]
    if inp.get("store", {}).get("delta"):
        argv += ["--store-delta", str(inp["store"]["delta"])]
    if inp.get("store", {}).get("soldout"):
        argv += ["--soldout", ",".join(inp["store"]["soldout"])]

    out = subprocess.run(argv, capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def check(case, data):
    exp = case["expect"]
    bad = []

    if data["feasible"] != exp["feasible"]:
        bad.append("feasible: 期望 %s，实际 %s" % (exp["feasible"], data["feasible"]))
    if "pool" in exp and data["poolSize"] != exp["pool"]:
        bad.append("poolSize: 期望 %s，实际 %s" % (exp["pool"], data["poolSize"]))
    if "inBudget" in exp and data["inBudget"] != exp["inBudget"]:
        bad.append("inBudget: 期望 %s，实际 %s" % (exp["inBudget"], data["inBudget"]))

    for key, want in (exp.get("groups") or {}).items():
        deck = data.get("decks", {}).get(key) or []
        if not deck:
            bad.append("组 %s 没有候选" % key)
            continue
        head = deck[0]
        for field in ("subtotal", "discount", "total", "kcal", "protein"):
            if field not in want:
                continue
            got = head.get(field)
            if abs(float(got) - float(want[field])) > 0.005:
                bad.append("%s.%s: 期望 %s，实际 %s" % (key, field, want[field], got))

    return bad


def main():
    with open(CASES, encoding="utf-8") as fh:
        cases = json.load(fh)["cases"]

    failed = 0
    for case in cases:
        data = run_case(case)
        bad = check(case, data)
        if bad:
            failed += 1
            print("FAIL  %s" % case["id"])
            for line in bad:
                print("      - " + line)
        else:
            print("ok    %s" % case["id"])

    print("\n%d/%d 通过" % (len(cases) - failed, len(cases)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
