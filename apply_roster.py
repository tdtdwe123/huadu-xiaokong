#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用官网项目名册口径 (fdcxmxxlb.ashx -> houseSoldNum/houseUnsaleNum) 覆盖 data.json 的
已售/未售，使我们的销控表与阳光家缘官网列表页完全一致。

背景：原先 data.json 的已售/未售来自 fdcxmjbxx.ashx 的 pzystspzysmjxx 摘要
(totalSaleNum/totalNosoldNum)，该摘要对聚合/地下室/多证项目经常陈旧或不全，
与官网名册列表页 (houseSoldNum/houseUnsaleNum) 大面积不一致（抽样 54 个花都盘 41 个不符）。

本脚本：
  1) 以 /tmp/all_projects_full.json (名册快照) 为基线，给出全部 657 花都盘的
     houseSoldNum/houseUnsaleNum；
  2) 用实时拉取的 /tmp/roster_live*.json 覆盖其中能取到的盘（更新到当日）；
  3) 写出 roster_overlay.json（fetch_fast.py 在 Actions 上回退用的缓存）；
  4) 给 data.json 每个项目加 roster:{sold,unsold}，并统计变更量。
"""
import json, os

BASE = os.path.dirname(os.path.abspath(__file__))
PROJ_FILE = os.path.join(BASE, "projects.json")
DATA_FILE = os.path.join(BASE, "data.json")
OVERLAY_FILE = os.path.join(BASE, "roster_overlay.json")
MASTER = "/tmp/all_projects_full.json"


def load_master():
    try:
        return json.load(open(MASTER, encoding="utf-8"))
    except Exception:
        return []


def load_live():
    out = {}
    for fn in ("/tmp/roster_live2.json", "/tmp/roster_live.json"):
        try:
            for p in json.load(open(fn, encoding="utf-8")):
                out[p["projectId"]] = p
        except Exception:
            pass
    return out


def main():
    projects = json.load(open(PROJ_FILE, encoding="utf-8"))
    master = {p["projectId"]: p for p in load_master()}
    live = load_live()
    print(f"projects.json: {len(projects)} | master 名册: {len(master)} | 实时名册: {len(live)}")

    overlay = {}
    missing = 0
    for p in projects:
        pid = p["id"]
        src = live.get(pid) or master.get(pid)
        if not src:
            missing += 1
            continue
        try:
            sold = int(src.get("houseSoldNum") or 0)
        except Exception:
            sold = 0
        try:
            unsold = int(src.get("houseUnsaleNum") or 0)
        except Exception:
            unsold = 0
        overlay[pid] = {"sold": sold, "unsold": unsold}

    json.dump(overlay, open(OVERLAY_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    print(f"roster_overlay.json 写入 {len(overlay)} 条（master/live 均缺失: {missing}）")

    # 应用到 data.json
    data = json.load(open(DATA_FILE, encoding="utf-8"))
    changed = 0
    for p in data["projects"]:
        pid = p["id"]
        if pid in overlay:
            r = overlay[pid]
            old = p.get("roster") or {}
            if old.get("sold") != r["sold"] or old.get("unsold") != r["unsold"]:
                changed += 1
            p["roster"] = r
        # 缺失的盘：保留原 roster（若有）或置空，不强行填 0
    data["roster_updated"] = "official-roster(fdcxmxxlb)"
    json.dump(data, open(DATA_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    print(f"data.json 已写入 roster 字段，变更 {changed} 条，共 {len(data['projects'])} 盘")


if __name__ == "__main__":
    main()
