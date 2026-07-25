#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按"核心楼盘名 + 开发商"聚类，统一一个街道(板块)与坐标给整组。

修复同一个物理楼盘被多个预售证拆到不同板块的 bug（例如凤凰瑞景花园
被分到花城街/区府板块/空 area 三处）。
- 仅改 area/lng/lat/geo_approx/geo_src，不动 detail（保留真实房号）。
- 当地址里没有显式街道名时，按"组内多数非空街道"→"同开发商其它项目的
  最常见街道"→留空  顺序兜底，保证 凤凰瑞景 这种 4/5 写明花城街的组
  统一归到花城街。
"""
import json, os, re, sys, hashlib
from collections import defaultdict, Counter

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import build_projects as BP  # 复用 TOWN_CENTROID / detect_town / DEFAULT_CENTROID / jitter

TOWN_CENTROID = BP.TOWN_CENTROID
TOWN_TOKENS = BP.TOWN_TOKENS
detect_town = BP.detect_town
jitter = BP.jitter
DEFAULT_CENTROID = BP.DEFAULT_CENTROID


def py_base(name):
    """把 阳光家缘 返回的‘楼盘名+预售证/楼栋/期数/工程部位’剥离成物理楼盘核心名。"""
    n = name or ""
    # （...）／(...) 全部剥除（含跨括号的内容）
    n = re.sub(r"[（(][^）)]*[）)].*$", "", n)
    # 工程部位/业态作为名后缀去掉（"住宅楼"、"住宅"、"地下室"、"垃圾收集站"、"商业"等）
    n = re.sub(r"(住宅楼|住宅|公租房|公配|地下室|垃圾收集站|配电房|岗亭|商业)[（(（].*$", "", n)
    n = re.sub(r"(住宅楼|住宅|地下室|垃圾收集站|配电房|岗亭|商业)$", "", n)
    n = re.sub(r"及垃圾收集站.*$", "", n)
    n = re.sub(r"及商业.*$", "", n)
    n = re.sub(r"及地下室.*$", "", n)
    n = re.sub(r"、地下室.*$", "", n)
    n = re.sub(r"、.*$", "", n)
    # 自编号段
    n = re.sub(r"自编号.*$", "", n)
    # 数字+# 栋 号楼 等尾巴
    n = re.sub(r"[\s\-]*[\d]+[#栋号]?楼?.*$", "", n)
    n = re.sub(r"[A-Za-z]?\d.*$", "", n)
    n = re.sub(r"[。。.、，,\s]+$", "", n)
    return n.strip() or (name or "").strip()


def detect_town_safe(addr):
    """detect_town 兜底：若未匹配，重新去花都街道/镇 token 里再匹配一次。
    阳光家缘许多地址文本（比如"花都区X街Y社区Z号"）含街道 token 但前缀带"花都区"
    导致 detect_town 没匹配——其实街道名只要在文本里就该算上。"""
    t = detect_town(addr)
    if t:
        return t
    a = addr or ""
    # 优先 remap
    for k, v in BP.TOWN_REMAP.items():
        if k in a:
            return v
    for tok in TOWN_TOKENS:
        if tok in a:
            return tok
    return ""


def developer_area_hint(developer):
    """若 developer's projects 中大多数带某个街道/镇，作为该组的兜底街道。"""
    if not developer:
        return ""
    projs = json.load(open(os.path.join(BASE, "projects.json"), encoding="utf-8"))
    cnt = Counter()
    for p in projs:
        if (p.get("developer") or "").strip() == developer.strip():
            a = p.get("area") or ""
            if a:
                cnt[a] += 1
    if cnt:
        return cnt.most_common(1)[0][0]
    return ""


def group_key(p):
    return (py_base(p.get("name") or ""), (p.get("developer") or "").strip())


def main():
    proj_path = os.path.join(BASE, "projects.json")
    data_path = os.path.join(BASE, "data.json")
    projs = json.load(open(proj_path, encoding="utf-8"))
    data = json.load(open(data_path, encoding="utf-8"))
    data_projs = data.get("projects", [])
    by_id = {p["id"]: p for p in data_projs}

    groups = defaultdict(list)
    for p in projs:
        groups[group_key(p)].append(p)

    fixed_areas = 0
    fixed_coords = 0
    g_count = len(groups)
    multi = sum(1 for v in groups.values() if len(v) > 1)

    for key, members in list(groups.items()):
        base, dev = key
        # 候选街道 (a) 成员地址里抽 (b) 同开发商兜底
        towns = [detect_town_safe(m.get("address") or "") for m in members]
        town_candidates = [t for t in towns if t]
        hint = developer_area_hint(dev) if len(town_candidates) < len(members) else ""

        if town_candidates:
            town = Counter(town_candidates).most_common(1)[0][0]
        elif hint:
            town = hint
        else:
            town = ""
        clng, clat = TOWN_CENTROID.get(town, DEFAULT_CENTROID)
        gkey = base + "|" + dev
        jlng, jlat = jitter(gkey, clng, clat)

        # 是否包含有精确坐标的成员（保留此成员的 coords，其余仍然用组的近似）
        precise = [m for m in members if m.get("lng") and m.get("lat") and not m.get("geo_approx")]

        for m in members:
            if m.get("area") != town:
                fixed_areas += 1
            m["area"] = town
            # 若本成员已有精确坐标 → 保留；否则统一为组的近似坐标
            if m.get("lng") and m.get("lat") and not m.get("geo_approx"):
                continue
            m["lng"] = round(jlng, 6)
            m["lat"] = round(jlat, 6)
            m["geo_approx"] = True
            m["geo_src"] = "town_centroid_group"
            fixed_coords += 1

    # data.json 同步：area 永远同步；lng/lat/geo_* 只在不是精确坐标时同步
    synced = 0
    inserted = 0
    for p in projs:
        dp = by_id.get(p["id"])
        if not dp:
            data_projs.append({
                "id": p["id"], "name": p.get("name"),
                "developer": p.get("developer"),
                "presell": p.get("presell"),
                "address": p.get("address"),
                "area": p.get("area"),
                "lng": p.get("lng"), "lat": p.get("lat"),
                "geo_approx": p.get("geo_approx"),
                "geo_src": p.get("geo_src"),
                "summary": None, "detail": None,
            })
            inserted += 1
            continue
        if dp.get("area") != p.get("area"):
            dp["area"] = p.get("area"); synced += 1
        precise_dp = dp.get("lng") and dp.get("lat") and dp.get("geo_approx") is False
        if not precise_dp:
            if dp.get("lng") != p.get("lng") or dp.get("lat") != p.get("lat"):
                dp["lng"] = p.get("lng"); dp["lat"] = p.get("lat"); synced += 1
            if dp.get("geo_approx") != p.get("geo_approx"):
                dp["geo_approx"] = p.get("geo_approx"); synced += 1
            if dp.get("geo_src") != p.get("geo_src"):
                dp["geo_src"] = p.get("geo_src"); synced += 1

    json.dump(projs, open(proj_path, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    json.dump(data, open(data_path, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))

    print(f"共 {g_count} 组（其中多成员组 {multi} 个）")
    print(f"修正 area {fixed_areas} 处；统一近似坐标 {fixed_coords} 处；data.json 同步 {synced} 条；新增占位 {inserted} 条")

    # 报告关键案例
    print("\n=== 凤凰瑞景花园分组结果 ===")
    for (base, dev), members in groups.items():
        if "凤凰瑞景" in base:
            print(f"  组: base='{base}' dev='{dev}' 共 {len(members)} 条")
            for m in members:
                print(f"    {m['name']:42s} area={m.get('area'):8s} coord=({m.get('lng')},{m.get('lat')}) approx={m.get('geo_approx')}")

    print("\n=== 同开发商雄炜其它项目 area hint ===")
    print(f"  hint = {developer_area_hint('广州市雄炜房地产开发有限公司') or '(空)'}")

    # 数据校验
    fh = [p for p in projs if "凤凰瑞景" in (p.get("name") or "")]
    towns = set(p.get("area") for p in fh)
    print(f"\n凤凰瑞景现共 {len(fh)} 条，存在 area 取值 = {towns}")


if __name__ == "__main__":
    main()
