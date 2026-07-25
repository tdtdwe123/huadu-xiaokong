#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重建 projects.json：补齐阳光家缘全部花都区项目，使 app 与官网一致。

- 现有 projects.json 的 254 条（含精确坐标）原样保留。
- 从 /tmp/all_projects_full.json（阳光家缘全量列表）中筛出全部「花都」项目，
  缺失的补入；新项目无坐标来源（官方接口不含坐标、Nominatim 被墙、无 AMAP_KEY），
  用「街道/镇级质心 + 确定性抖动」给出近似坐标，geo_approx=true，便于地图展示。
  后续若提供 AMAP_KEY 并运行 geocode_now.py 即可升级为精确坐标。
"""
import json, os, hashlib

BASE = os.path.dirname(os.path.abspath(__file__))
PROJ_FILE = os.path.join(BASE, "projects.json")
FULL_FILE = "/tmp/all_projects_full.json"

# 花都各街道/镇质心（近似），用于在无精确坐标时散点展示
TOWN_CENTROID = {
    "新华街": (113.225, 23.405),
    "花城街": (113.238, 23.416),
    "秀全街": (113.205, 23.393),
    "新雅街": (113.215, 23.372),
    "狮岭镇": (113.132, 23.452),
    "花东镇": (113.350, 23.382),
    "花山镇": (113.272, 23.430),
    "炭步镇": (113.052, 23.322),
    "赤坭镇": (112.982, 23.382),
    "梯面镇": (113.252, 23.552),
    "雅瑶镇": (113.272, 23.362),
}
TOWN_TOKENS = list(TOWN_CENTROID.keys())
DEFAULT_CENTROID = (113.220, 23.404)  # 花都中心兜底


def is_huadu(x):
    t = (x.get("projectName", "") + x.get("projectAddress", ""))
    return "花都" in t


# 旧地名 / 地标 → 现街道（用于更准的近似落点）
TOWN_REMAP = {
    "新华镇": "新华街",   # 新华镇已撤并入新华街
    "北兴": "花东镇",     # 北兴镇现属花东镇
    "北兴镇": "花东镇",
    "芙蓉": "狮岭镇",     # 芙蓉度假区/芙蓉嶂在狮岭西北
    "山前大道": "狮岭镇",
    "度假区": "狮岭镇",
    "御水山庄": "狮岭镇",
    "金碧御水": "狮岭镇",
}


def detect_town(addr):
    a = addr or ""
    # 先匹配旧地名/地标
    for k, v in TOWN_REMAP.items():
        if k in a:
            return v
    for tok in TOWN_TOKENS:
        if tok in a:
            return tok
    return ""


def jitter(idstr, base_lng, base_lat):
    """确定性抖动：同一 id 永远得到相同偏移，避免 pin 完全重叠。"""
    h = hashlib.md5(idstr.encode("utf-8")).hexdigest()
    a = int(h[0:8], 16) / 0xFFFFFFFF
    b = int(h[8:16], 16) / 0xFFFFFFFF
    dlng = (a - 0.5) * 0.024   # ±0.012 度 ≈ ±1.2km
    dlat = (b - 0.5) * 0.020   # ±0.010 度 ≈ ±1.1km
    return base_lng + dlng, base_lat + dlat


def main():
    existing = json.load(open(PROJ_FILE, encoding="utf-8"))
    full = json.load(open(FULL_FILE, encoding="utf-8"))
    have_ids = {p["id"] for p in existing}

    huadu = [x for x in full if is_huadu(x)]
    print(f"阳光家缘全量列表：{len(full)} 条；花都项目：{len(huadu)} 条")

    # 现有顺序优先（保留用户已校准坐标），再追加缺失的新项目
    merged = list(existing)
    added = 0
    for x in huadu:
        pid = x["projectId"]
        if pid in have_ids:
            continue
        addr = x.get("projectAddress") or ""
        town = detect_town(addr)
        clng, clat = TOWN_CENTROID.get(town, DEFAULT_CENTROID)
        lng, lat = jitter(pid, clng, clat)
        entry = {
            "id": pid,
            "name": x.get("projectName"),
            "developer": x.get("developer"),
            "presell": x.get("presell") or "",
            "address": addr,
            "area": town,
            "lng": round(lng, 6),
            "lat": round(lat, 6),
            "geo_approx": True,
            "geo_src": "town_centroid",
        }
        merged.append(entry)
        have_ids.add(pid)
        added += 1

    # 兜底：万一有 projects.json 中 id 不在花都全量列表里，也保留（不丢弃）
    extra = [p for p in existing if p["id"] not in {x["projectId"] for x in huadu}]
    print(f"保留原 254 条；新增 {added} 条；原列表不在花都全量中的 {len(extra)} 条（一并保留）")

    # 重算近似条目（geo_src=town_centroid）的街道与坐标：兼容旧地名/地标，
    # 并纠正上一轮遗留的空 area。幂等，重复运行只会更准。
    fixed = 0
    for p in merged:
        if p.get("geo_src") != "town_centroid":
            continue
        town = detect_town(p.get("address") or "")
        if town and (not p.get("area") or p["area"] != town):
            clng, clat = TOWN_CENTROID.get(town, DEFAULT_CENTROID)
            lng, lat = jitter(p["id"], clng, clat)
            p["area"] = town
            p["lng"] = round(lng, 6)
            p["lat"] = round(lat, 6)
            fixed += 1
    if fixed:
        print(f"重算并修正近似条目坐标：{fixed} 条")

    json.dump(merged, open(PROJ_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    print(f"写入 projects.json：共 {len(merged)} 条")

    # 校验凤凰瑞景完整性
    fh = [p for p in merged if "凤凰瑞景" in p["name"]]
    print(f"凤凰瑞景条数（应与官网一致=5）：{len(fh)}")
    for p in fh:
        print("   ", p["id"], p["name"], "| presell", p.get("presell"),
              "| coord", (p["lng"], p["lat"]), "| approx", p.get("geo_approx"))


if __name__ == "__main__":
    main()
