#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""高德 Web 服务地理编码/POI 检索模块（用于精确修正楼盘坐标）。

设计要点：
- 用楼盘的「完整备案地址」pjAddress 与「推广名/core」两种输入做解析。
- 解析优先级（在流水线中编排）：POI(推广名) → POI(备案名) → 地址地理编码。
- 地址先做清洗：去掉「社区居民委员会/社区/居民委员会」等行政虚词，避免被误匹配到
  外地同名居委会（曾出现花都地址被解析到南沙区）。
- 所有结果做花都区边界 sanity check；POI 结果额外做名称相关度校验，过滤外地误匹配。
- 限速 + 退避：高德免费 key 有 QPS 限制，命中 CUQPS 限制时退避重试。
- 支持 coord_overrides.json 手工覆盖（优先级最高）与本地缓存（避免重复请求）。
- 通过环境变量 AMAP_KEY 激活实时解析。
"""
import os, json, time, re, urllib.parse, urllib.request

HUADU_BBOX = dict(lat_min=23.10, lat_max=23.65, lng_min=112.80, lng_max=113.75)

CACHE_FILE = os.path.join(os.path.dirname(__file__), "geocode_cache.json")
OVERRIDE_FILE = os.path.join(os.path.dirname(__file__), "coord_overrides.json")

_cache = {}
_overrides = {}

# 行政虚词，地理编码时会干扰匹配，清洗掉
_ADMIN_NOISE = ["社区居民委员会", "居民委员会", "社区居委会", "社区", "居委会"]


def _load():
    global _cache, _overrides
    if not _cache and os.path.exists(CACHE_FILE):
        try:
            _cache = json.load(open(CACHE_FILE, encoding="utf-8"))
        except Exception:
            _cache = {}
    if not _overrides and os.path.exists(OVERRIDE_FILE):
        try:
            _overrides = json.load(open(OVERRIDE_FILE, encoding="utf-8"))
        except Exception:
            _overrides = {}


def save_cache():
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_cache, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def in_huadu(lat, lng):
    return (HUADU_BBOX["lat_min"] <= lat <= HUADU_BBOX["lat_max"] and
            HUADU_BBOX["lng_min"] <= lng <= HUADU_BBOX["lng_max"])


def clean_addr(addr):
    """去掉行政虚词与冗余门牌后缀，提升地理编码命中率。"""
    if not addr:
        return addr
    a = addr
    for w in _ADMIN_NOISE:
        a = a.replace(w, "")
    # 去掉「之一、之二」等子号后缀，仅保留主门牌号（避免过细导致无结果）
    a = re.sub(r"之[一二三四五六七八九十]+([、，])?", "", a)
    a = re.sub(r"\s+", "", a)
    return a


def _amap_get(url, key, retries=4):
    """带限速退避的 AMap GET；返回解析后的 dict，限流时退避重试。"""
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.loads(r.read().decode("utf-8"))
            if d.get("infocode") == "10000" or d.get("status") == "1":
                return d
            if d.get("infocode") in ("10044",) or "CUQPS" in str(d.get("info", "")):
                # QPS 超限：退避后重试
                time.sleep(2.0 * (i + 1))
                continue
            return d
        except Exception:
            time.sleep(1.2 * (i + 1))
    return {}


def geocode_amap(address, key, retries=3):
    """调用高德地理编码，返回 (lng, lat) 或 None（含边界校验）。"""
    addr = clean_addr(address)
    url = "https://restapi.amap.com/v3/geocode/geo?" + urllib.parse.urlencode({
        "key": key, "address": addr, "city": "广州市", "output": "json"})
    for i in range(retries):
        d = _amap_get(url, key)
        if d.get("status") == "1" and d.get("geocodes"):
            loc = d["geocodes"][0].get("location", "")
            if "," in loc:
                lng, lat = (float(x) for x in loc.split(","))
                if in_huadu(lat, lng):
                    return lng, lat
        time.sleep(1.0)
    return None


def poi_search(key, keyword, city="广州", retries=4):
    """高德 POI 文本检索，返回 [(name, lng, lat, address), ...]（花都边界内）。"""
    url = "https://restapi.amap.com/v3/place/text?" + urllib.parse.urlencode({
        "key": key, "keywords": keyword, "city": city,
        "citylimit": "true", "output": "json", "offset": "10"})
    d = _amap_get(url, key, retries=retries)
    out = []
    if d.get("status") == "1":
        for p in d.get("pois", []):
            loc = p.get("location", "")
            if "," in loc:
                lng, lat = (float(x) for x in loc.split(","))
                if in_huadu(lat, lng):
                    out.append((p.get("name", ""), lng, lat, p.get("address", "")))
    return out


def name_relevant(query, poi_name):
    """POI 名称与查询词是否相关（含子串或反之），过滤外地误匹配。"""
    if not query or not poi_name:
        return False
    q = query.replace(" ", "")
    n = poi_name.replace(" ", "")
    if q in n or n in q:
        return True
    # 取核心片段（去掉通用后缀）再比
    qc = re.sub(r"(花园|小区|住宅|广场|公馆|府|苑|城|庄|台|居|阁|座|栋|期|自编.*)$", "", q)
    nc = re.sub(r"(花园|小区|住宅|广场|公馆|府|苑|城|庄|台|居|阁|座|栋|期|自编.*)$", "", n)
    return bool(qc) and bool(nc) and (qc in nc or nc in qc)


def poi_keywords(core):
    """生成 POI 检索候选词：原词 + 去阶段/期数/括号后缀的基名。"""
    kws = []
    if core:
        kws.append(core)
        base = re.sub(r"[（(].*?[)）]", "", core)          # 去括号内容
        base = re.sub(r"\s*[一二三四五六七八九十\d]+区", "", base)  # 去「十一区」等
        base = re.sub(r"\d+期", "", base)                    # 去「X期」
        base = re.sub(r"(自编|住宅|商业|地下室|楼|栋).*$", "", base)  # 去后缀细节
        base = base.strip()
        if base and base not in kws:
            kws.append(base)
    return kws


def addr_fallbacks(address, core):
    """地址地理编码兜底：完整清洗地址 -> 街道/路级短地址。"""
    out = []
    if address:
        out.append(clean_addr(address))
        # 去掉「号…」之后的子号与过细巷弄，保留到街道/路
        short = re.sub(r"(路|街|大道|巷|号).*$", lambda m: m.group(1), clean_addr(address))
        if short and short != out[-1]:
            out.append(short)
    # 去重
    seen, res = set(), []
    for o in out:
        if o and o not in seen:
            seen.add(o); res.append(o)
    return res


def geocode(address, key=None, project_id=None, name=None, core=None):
    """综合解析一个地址/名称的坐标。优先级：手工覆盖 > 缓存 > 实时。
    返回 (lng, lat, source) 或 (None, None, None)。
    source ∈ {override, cache, amap_poi, amap_geo}。
    """
    _load()
    # 1) 手工覆盖
    for k in (project_id, name, core):
        if k and k in _overrides:
            lng, lat = _overrides[k]["lng"], _overrides[k]["lat"]
            return lng, lat, "override"
    if not key:
        return None, None, None
    # 2) POI 检索（推广名/核心名，多候选词兜底）
    seen_kw = set()
    for kw in poi_keywords(core) + poi_keywords(name):
        if not kw or kw in seen_kw:
            continue
        seen_kw.add(kw)
        hits = poi_search(key, kw)
        for n, lng, lat, ad in hits:
            if name_relevant(kw, n):
                _cache[("poi:" + kw)] = [lng, lat]
                return lng, lat, "amap_poi"
        time.sleep(0.5)
    # 3) 地址地理编码（仅当地址含路/门牌等可定位要素时尝试，避免纯街道地址空耗）
    if address and re.search(r"(路|街|大道|号|巷|里|弄)", address):
        for ad in addr_fallbacks(address, core or name):
            res = geocode_amap(ad, key)
            if res:
                _cache[clean_addr(address) or ad] = [res[0], res[1]]
                return res[0], res[1], "amap_geo"
            time.sleep(0.5)
    return None, None, None


if __name__ == "__main__":
    import sys
    key = os.environ.get("AMAP_KEY")
    arg = sys.argv[1] if len(sys.argv) > 1 else "花都区新雅街秀雅一路3号之八"
    lng, lat, src = geocode(arg, key=key, core="城芸花园")
    print(arg, "->", (lng, lat), src)
