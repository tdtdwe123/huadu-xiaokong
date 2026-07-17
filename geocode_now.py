#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键精确修正坐标（中国服务器上，设好 AMAP_KEY 后运行）。

用每个楼盘的「完整备案地址」pjAddress 调用高德地理编码，覆盖 projects.json
与 data.json 中的坐标。已精确的（geo_approx=false）会被保留；手工覆盖
（coord_overrides.json）优先级最高。
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geocode

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data.json")
PROJ = os.path.join(BASE, "projects.json")


def main():
    key = os.environ.get("AMAP_KEY")
    if not key:
        print("缺少环境变量 AMAP_KEY，无法精确 geocode。请先申请高德 Web 服务 key 并 export AMAP_KEY=xxx")
        return
    d = json.load(open(DATA, encoding="utf-8"))
    pj = json.load(open(PROJ, encoding="utf-8"))
    pj_by_id = {p["id"]: p for p in pj}

    # 同时修正断点续抓缓存（data_progress.json），否则服务器 hourly 循环会回退
    PROG = os.path.join(BASE, "data_progress.json")
    prog = json.load(open(PROG, encoding="utf-8")) if os.path.exists(PROG) else {}
    prog_by_id = prog if isinstance(prog, dict) else {}

    ok = skip = fail = 0
    for p in d["projects"]:
        addr = (p.get("detail") or {}).get("info", {}).get("pjAddress")
        if not addr:
            skip += 1
            continue
        lng, lat, src = geocode.geocode(addr, key=key, project_id=p["id"], name=p["name"])
        if lng is None:
            fail += 1
            print(f"  失败: {p['name']} ({addr})")
            continue
        p["lng"], p["lat"] = lng, lat
        p["geo_approx"] = False
        p["geo_src"] = src
        src0 = pj_by_id.get(p["id"])
        if src0:
            src0["lng"], src0["lat"] = lng, lat
            src0["geo_approx"] = False
            src0["geo_src"] = src
        pr = prog_by_id.get(p["id"])
        if pr:
            pr["lng"], pr["lat"] = lng, lat
            pr["geo_approx"] = False
            pr["geo_src"] = src
        ok += 1
        print(f"  OK: {p['name']} -> ({lat:.5f},{lng:.5f}) [{src}]")

    json.dump(d, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    json.dump(pj, open(PROJ, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    if prog_by_id:
        json.dump(prog, open(PROG, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    geocode.save_cache()
    print(f"\n完成：精确 {ok} / 跳过 {skip} / 失败 {fail}")


if __name__ == "__main__":
    main()
