#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性补抓 presell=None 且当前楼栋明细为空的盘（多为聚合/地下室记录，如凤凰瑞景13-14-15#），
用 fdcxmjbxx->xmldxx->xmxkbxx 重新拉取并写回 data.json 的 detail。
注意：名册口径(roster)不在此处理，由 apply_roster / fetch_fast 负责。"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_robust as FR

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data.json")


def main():
    d = json.load(open(DATA, encoding="utf-8"))
    targets = [p for p in d["projects"]
               if not p.get("presell") and not (p.get("detail") or {}).get("buildings")]
    print(f"待补抓 presell=None 空楼栋盘: {len(targets)}")
    byid = {p["id"]: p for p in d["projects"]}
    ok = 0
    for i, p in enumerate(targets, 1):
        pid = p["id"]
        det = FR.fetch_project(pid)
        time.sleep(0.8)
        if det and det.get("buildings"):
            byid[pid]["detail"] = det
            ok += 1
            print(f"[{i}/{len(targets)}] {p['name'][:28]} -> {len(det['buildings'])} 栋", flush=True)
        else:
            print(f"[{i}/{len(targets)}] {p['name'][:28]} -> 仍无楼栋(官方亦无)", flush=True)
    json.dump(d, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"完成：成功填充 {ok}/{len(targets)} 个盘的楼栋明细，已写回 {DATA}")


if __name__ == "__main__":
    main()
