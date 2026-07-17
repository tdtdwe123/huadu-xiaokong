#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用高德 POI 校准「位置不确定」的楼盘坐标（限定花都区，严格校验）。

策略（对每个 geo_approx 项目）：
  1) 用推广名 / 小区核心名 在【花都区】搜高德 POI；
  2) 名称须相关（去后缀核心词子串匹配），且 adname 必须为花都区；
  3) POI 无可靠匹配则退回按完整备案地址 pjAddress 做高德 geocode；
  4) 仍失败则保留原近似坐标（不破坏现有数据）。
结果写回 data.json / projects.json / data_progress.json，标记 geo_approx=false, geo_src=amap_poi/amap_geo。
"""
import os, sys, re, json, time, urllib.parse, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geocode

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data.json")
PROJ = os.path.join(BASE, "projects.json")
PROG = os.path.join(BASE, "data_progress.json")
ALIAS = os.path.join(BASE, "aliases.json")

SUFFIX = re.compile(r"(花园|花苑|苑|府|庄|阁|园|城|公馆|小区|公寓|广场|中心|营销中心|展示中心|售楼部|住宅|社区)$")


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


def core_name(prefix):
    n = prefix or ""
    n = re.sub(r'[（(][^）)]*[）)]', '', n)
    n = re.sub(r'(第?[一二三四五六七八九十\d]+期)', '', n)
    n = re.sub(r'[东西南北]+(区|侧|苑|园|阁)?', '', n)
    n = re.sub(r'[0-9]+', '', n)
    n = re.sub(r'(区|栋|幢|号|之.*)$', '', n).strip()
    return n or prefix


def match_key(s):
    """去后缀/标点，取用于匹配的核心词。"""
    s = re.sub(r'[\s·•.\-（）()、，,/]', '', s or '')
    s = SUFFIX.sub('', s)
    return s


def name_related(q, poi_name):
    a, b = match_key(q), match_key(poi_name)
    if not a or not b:
        return False
    return a in b or b in a


def poi_search(key, *queries):
    """对多个候选名依次在【花都区】搜高德 POI，返回首个通过校验的 (lng,lat,name)。"""
    for q in queries:
        if not q:
            continue
        url = "https://restapi.amap.com/v3/place/text?" + urllib.parse.urlencode({
            "key": key, "keywords": q, "city": "440114",
            "citylimit": "true", "offset": "10", "page": "1",
        })
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    d = json.loads(r.read().decode("utf-8"))
                if d.get("status") == "1":
                    for poi in d.get("pois", []):
                        if poi.get("adname") != "花都区":
                            continue
                        loc = poi.get("location", "")
                        if "," not in loc:
                            continue
                        lng, lat = (float(x) for x in loc.split(","))
                        if not geocode.in_huadu(lat, lng):
                            continue
                        if name_related(q, poi.get("name", "")):
                            return lng, lat, poi.get("name", q)
                break
            except Exception:
                time.sleep(1.0 * (attempt + 1))
        time.sleep(0.15)
    return None


def main():
    key = os.environ.get("AMAP_KEY") or (sys.argv[1] if len(sys.argv) > 1 else None)
    if not key:
        print("缺少高德 Web 服务 key：请 export AMAP_KEY=xxx 或在命令行传入。")
        return
    aliases = json.load(open(ALIAS, encoding="utf-8")) if os.path.exists(ALIAS) else {}
    d = json.load(open(DATA, encoding="utf-8"))
    pj = json.load(open(PROJ, encoding="utf-8"))
    pj_by_id = {p["id"]: p for p in pj}
    prog = json.load(open(PROG, encoding="utf-8")) if os.path.exists(PROG) else {}
    prog_by_id = prog if isinstance(prog, dict) else {}

    ok = skip = fail = 0
    for p in d["projects"]:
        # 全量校准：对所有楼盘尝试高德 POI/geocode；无可靠结果则保留原坐标
        name = p["name"]
        al = aliases.get(name, {}).get("alias")
        prefix = devPrefix(name)
        core = core_name(prefix)
        queries = [al, core, prefix, re.sub(r'[（(][^）)]*[）)]', '', name).strip()]
        addr = (p.get("detail") or {}).get("info", {}).get("pjAddress")

        res = poi_search(key, *queries)
        src = "amap_poi"
        if not res and addr:
            lng, lat, g = geocode.geocode(addr, key=key, project_id=p["id"], name=name)
            if lng:
                res = (lng, lat, name); src = "amap_geo"
        if not res:
            fail += 1
            print(f"  跳过(无结果): {name}  (查询: {queries[0] or queries[1]})")
            continue

        lng, lat, found = res
        p["lng"], p["lat"] = lng, lat
        p["geo_approx"] = False
        p["geo_src"] = src
        s0 = pj_by_id.get(p["id"])
        if s0:
            s0["lng"], s0["lat"] = lng, lat; s0["geo_approx"] = False; s0["geo_src"] = src
        pr = prog_by_id.get(p["id"])
        if pr:
            pr["lng"], pr["lat"] = lng, lat; pr["geo_approx"] = False; pr["geo_src"] = src
        ok += 1
        print(f"  OK: {name} -> ({lat:.5f},{lng:.5f}) [{src}] 匹配「{found}」")

    json.dump(d, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    json.dump(pj, open(PROJ, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    if prog_by_id:
        json.dump(prog, open(PROG, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    geocode.save_cache()
    print(f"\n完成：POI校准 {ok} / 原近似 {ok+fail+skip} (跳过无结果 {fail})")


if __name__ == "__main__":
    main()
