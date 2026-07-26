#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量校正花都区楼盘坐标（key 就绪）。

策略（与用户要求一致：用更精确的地址/推广名去匹配 POI 坐标）：
  1. 优先用「完整备案地址」pjAddress 地理编码（最精确，能定位到门牌）。
  2. 失败则回退用 core（推广/核心名）+「花都区」做 POI 检索。
  3. 结果做花都边界 sanity check；命中则写回 lng/lat，并置
     geo_approx=False, geo_src='amap_geo' (按地址) 或 'amap_poi' (按名)。

依赖 geocode.py（含高德 Web 服务接口、缓存、手工覆盖、边界校验）。
激活方式：环境变量 AMAP_KEY 提供高德 key；无 key 时仅做干跑统计。

用法：
  python3 geocode_pipeline.py            # 有 key 则执行校正，无 key 则干跑
  DRY=1 python3 geocode_pipeline.py      # 强制干跑
"""
import os, json, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(HERE, "data.json")
PROJECTS_FILE = os.path.join(HERE, "projects.json")

sys.path.insert(0, HERE)
import geocode as G


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(obj, path, compact=True):
    tmp = path + ".tmp"
    if compact:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    else:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def addr_of(p):
    return (p.get("detail") or {}).get("info", {}).get("pjAddress") or p.get("address") or ""


def core_of(p):
    return p.get("core") or p.get("name") or ""


def load_aliases():
    """aliases.json: 备案名前缀 -> {alias:推广名, filing:备案名}。返回 core->推广名 映射。"""
    path = os.path.join(HERE, "aliases.json")
    m = {}
    try:
        d = json.load(open(path, encoding="utf-8"))
        for k, v in d.items():
            if isinstance(v, dict):
                if v.get("alias"):
                    m[k] = v["alias"]
                if v.get("filing"):
                    m[v.get("filing")] = v.get("filing")
    except Exception:
        pass
    return m


def run(dry=True, key=None, limit=None):
    data = load(DATA_FILE)
    projects = data["projects"]
    approx = [p for p in projects if p.get("geo_approx")]
    alias_map = load_aliases()
    print(f"总项目 {len(projects)}，街道级近似 {len(approx)}")

    fixed = 0
    failed = []
    pending = 0  # 需要实时 key 才能解析
    for p in approx:
        pid = p.get("id")
        addr = addr_of(p)
        core = core_of(p)
        # 推广名优先（来自 aliases.json），否则用 core
        poi_kw = alias_map.get(core) or alias_map.get(p.get("group", "").split("|")[0]) or core
        # 综合解析：POI(推广名) -> POI(备案名) -> 地址地理编码（均在 geocode 内编排）
        lng, lat, src = G.geocode(addr, key=key, project_id=pid, name=core, core=poi_kw)
        if lng is None:
            pending += 1
            failed.append((p.get("name"), addr, core))
            continue
        # 边界复核
        if not G.in_huadu(lat, lng):
            failed.append((p.get("name"), addr, core))
            continue
        if dry:
            fixed += 1
            continue
        p["lng"] = round(lng, 6)
        p["lat"] = round(lat, 6)
        p["geo_approx"] = False
        p["geo_src"] = "amap_geo" if src == "amap_geo" else "amap_poi"
        fixed += 1
        if fixed % 25 == 0:
            print(f"[进度] 已修正 {fixed} 条，剩余近似 {len(approx)-fixed-pending} …", flush=True)
        if limit and fixed >= limit:
            break

    if not dry and fixed:
        save(data, DATA_FILE, compact=True)
        # 同步 projects.json（若结构一致）
        try:
            pj = load(PROJECTS_FILE)
            if isinstance(pj, list) and len(pj) == len(projects):
                by_id = {p["id"]: p for p in projects}
                changed = 0
                for q in pj:
                    srcp = by_id.get(q.get("id"))
                    if srcp and ("geo_approx" in q):
                        q["lng"] = srcp["lng"]; q["lat"] = srcp["lat"]
                        q["geo_approx"] = srcp["geo_approx"]; q["geo_src"] = srcp["geo_src"]
                        changed += 1
                if changed:
                    save(pj, PROJECTS_FILE)
                    print(f"已同步 projects.json：{changed} 条")
        except Exception as e:
            print("projects.json 同步跳过：", e)

    print(f"本批可校正 {fixed} 条" + ("（干跑，未写入）" if dry else "（已写入 data.json）"))
    if failed:
        print(f"未能解析 {len(failed)} 条：")
        for nm, ad, co in failed[:30]:
            print("  -", nm, "|", ad or co)
    if not dry:
        G.save_cache()
    return fixed


if __name__ == "__main__":
    key = os.environ.get("AMAP_KEY")
    apply_cache = os.environ.get("APPLYCACHE") == "1"
    # 有 key → 实时校正并写入；无 key 但 APPLYCACHE → 仅写入缓存/覆盖命中；否则纯干跑
    dry = (os.environ.get("DRY") == "1") or (key is None and not apply_cache)
    if key:
        print("（检测到 AMAP_KEY，执行实时校正）")
    elif apply_cache:
        print("（无 AMAP_KEY，仅应用缓存/手工覆盖命中）")
    else:
        print("（未检测到 AMAP_KEY，执行干跑）")
    limit = int(os.environ.get("LIMIT", "0")) or None
    run(dry=dry, key=key, limit=limit)
