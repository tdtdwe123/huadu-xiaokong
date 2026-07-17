#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对「跨小区错误」的重复坐标组做确定性去堆叠。

原因：projects.json 中很多 address 只写到街道/镇，地理编码退回街道质心，
导致同街道的不同小区共用一个坐标点。本脚本不改变街道级正确性，仅把
同一像素点上的多个不同小区散开成清晰的小簇（同小区紧聚、不同小区分离），
并标记 geo_approx=true，待高德精确 geocode 后可被覆盖。
"""
import json, re, math, shutil, os
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data.json")
PROJ = os.path.join(BASE, "projects.json")

R_SUB = 0.0013   # 不同小区相对中心点的偏移半径(约145m)
R_IN = 0.00035   # 同小区内楼栋的紧聚半径(约39m)


def devPrefix(name):
    if not name:
        return name
    n = name
    n = re.sub(r'[（(][^）)]*[）)]', '', n).strip()
    n = re.sub(r'自编号[:：][^\s]*', '', n).replace('自编', '')
    n = re.sub(r'住宅楼.*$', '', n).replace('住宅', '').replace('商业', '')
    n = re.sub(r'、.*$', '', n).strip()
    n = re.sub(r'\s*[0-9]+[栋号楼]*.*$', '', n).replace('[0-9]+号楼.*$', '').strip()
    n = re.sub(r'[\.\s]+$', '', n)
    return n or name


def main():
    d = json.load(open(DATA, encoding="utf-8"))
    pj = json.load(open(PROJ, encoding="utf-8"))
    pj_by_id = {p["id"]: p for p in pj}

    # 备份
    shutil.copy(DATA, DATA + ".bak")
    shutil.copy(PROJ, PROJ + ".bak")

    # 找出跨小区重复坐标组
    groups = defaultdict(list)
    for p in d["projects"]:
        groups[(round(p["lat"], 6), round(p["lng"], 6))].append(p)

    changed = 0
    for (lat0, lng0), members in groups.items():
        prefs = set(devPrefix(m["name"]) for m in members)
        if len(prefs) <= 1:
            continue  # 同小区多楼栋，保留原坐标
        # 按小区分组
        sub = defaultdict(list)
        for m in members:
            sub[devPrefix(m["name"])].append(m)
        keys = list(sub.keys())
        n = len(keys)
        for i, k in enumerate(keys):
            ang = 2 * math.pi * i / max(n, 1)
            clat = lat0 + R_SUB * math.sin(ang)
            clng = lng0 + R_SUB * math.cos(ang)
            ms = sub[k]
            m2 = len(ms)
            for j, m in enumerate(ms):
                if m2 == 1:
                    nlat, nlng = clat, clng
                else:
                    a2 = 2 * math.pi * j / m2
                    nlat = clat + R_IN * math.sin(a2)
                    nlng = clng + R_IN * math.cos(a2)
                m["lat"] = round(nlat, 6)
                m["lng"] = round(nlng, 6)
                m["geo_approx"] = True
                # 同步 projects.json（源头）
                src = pj_by_id.get(m["id"])
                if src:
                    src["lat"] = m["lat"]
                    src["lng"] = m["lng"]
                    src["geo_approx"] = True
                changed += 1

    json.dump(d, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    json.dump(pj, open(PROJ, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))

    # 统计
    distinct = len({(round(p["lat"], 6), round(p["lng"], 6)) for p in d["projects"]})
    print(f"去堆叠项目数: {changed}")
    print(f"独立坐标点: {distinct} / {len(d['projects'])}")
    print(f"geo_approx 标记: {sum(1 for p in d['projects'] if p.get('geo_approx'))}")


if __name__ == "__main__":
    main()
