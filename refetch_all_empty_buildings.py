#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全面补抓所有 buildings=[] 的盘的 detail（不限 presell 是否为空）。

fetch.yml 当前只跑 fetch_fast.py（只抓 summary），导致大部分盘的 detail.buildings 为空，
应用就显示"暂无楼栋销控数据"。本脚本遍历所有 buildings=空 的盘，调用 fetch_robust.fetch_project
重抓，写回 data.json。对 API 仍不返回的盘保持原样（已记录在 detail 字段，无需处理）。
"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_robust as FR

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data.json")


def main():
    d = json.load(open(DATA, encoding="utf-8"))
    projs = d["projects"]
    targets = [p for p in projs
               if not (p.get("detail") or {}).get("buildings")]
    print(f"待补抓 buildings=空 的盘: {len(targets)}")

    byid = {p["id"]: p for p in projs}
    ok = 0
    skipped = 0

    def save():
        d["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        d["count"] = len(projs)
        tmp = DATA + ".tmp"
        json.dump(d, open(tmp, "w", encoding="utf-8"),
                  ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, DATA)

    last_save = 0
    try:
        for i, p in enumerate(targets, 1):
            pid = p["id"]
            det = FR.fetch_project(pid)
            time.sleep(0.6)
            if det and det.get("buildings"):
                byid[pid]["detail"] = det
                ok += 1
                print(f"[{i}/{len(targets)}] {p['name'][:30]} -> {len(det['buildings'])} 栋", flush=True)
            else:
                skipped += 1
                print(f"[{i}/{len(targets)}] {p['name'][:30]} -> 仍无楼栋", flush=True)
            if (i - last_save) >= 25:
                save(); last_save = i
                print(f"[{i}/{len(targets)}] 已保存（成功 {ok}）", flush=True)
        save()
    except (KeyboardInterrupt, Exception) as e:
        save()
        print(f"⚠ 中断({type(e).__name__})，已保存进度: 成功 {ok}", flush=True)
        raise

    print(f"\n完成：成功填充 {ok}/{len(targets)}（{skipped} 个 API 仍无），已写回 {DATA}")


if __name__ == "__main__":
    main()