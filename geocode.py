#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""高德 Web 服务地理编码模块（用于精确修正楼盘坐标）。

设计要点：
- 用楼盘的「完整备案地址」pjAddress（如「花都区新雅街合和社区秀雅一路3号之六」）
  而非 projects.json 里只写到街道/镇的 address 来 geocode，避免退回街道质心。
- 结果做花都区边界 sanity check，超出边界视为失败。
- 支持 coord_overrides.json 手工覆盖（优先级最高）与本地缓存（避免重复请求）。
- 在「中国服务器」上运行（能稳定访问高德），通过环境变量 AMAP_KEY 激活。
"""
import os, json, time, urllib.parse, urllib.request

# 花都区大致边界（含狮岭/花东/炭步/梯面等），用于结果校验
HUADU_BBOX = dict(lat_min=23.10, lat_max=23.65, lng_min=112.80, lng_max=113.75)

CACHE_FILE = os.path.join(os.path.dirname(__file__), "geocode_cache.json")
OVERRIDE_FILE = os.path.join(os.path.dirname(__file__), "coord_overrides.json")

_cache = {}
_overrides = {}


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


def geocode_amap(address, key, retries=3):
    """调用高德地理编码，返回 (lng, lat) 或 None。"""
    url = "https://restapi.amap.com/v3/geocode/geo?" + urllib.parse.urlencode({
        "key": key, "address": address, "city": "广州市", "output": "json"})
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.loads(r.read().decode("utf-8"))
            if d.get("status") == "1" and d.get("geocodes"):
                loc = d["geocodes"][0].get("location", "")
                if "," in loc:
                    lng, lat = (float(x) for x in loc.split(","))
                    if in_huadu(lat, lng):
                        return lng, lat
        except Exception:
            time.sleep(1.2 * (i + 1))
    return None


def geocode(address, key=None, project_id=None, name=None):
    """综合解析一个地址的坐标。优先级：手工覆盖 > 缓存 > 高德实时。
    返回 (lng, lat, source) 或 (None, None, None)。"""
    _load()
    # 1) 手工覆盖（按 project id 或 name）
    for k in (project_id, name):
        if k and k in _overrides:
            lng, lat = _overrides[k]["lng"], _overrides[k]["lat"]
            return lng, lat, "override"
    if not address:
        return None, None, None
    # 2) 缓存
    if address in _cache:
        lng, lat = _cache[address]
        return lng, lat, "cache"
    # 3) 高德实时（需 key）
    if key:
        res = geocode_amap(address, key)
        if res:
            _cache[address] = [res[0], res[1]]
            return res[0], res[1], "amap"
    return None, None, None


if __name__ == "__main__":
    import sys
    key = os.environ.get("AMAP_KEY")
    addr = sys.argv[1] if len(sys.argv) > 1 else "花都区新雅街合和社区秀雅一路3号之六"
    lng, lat, src = geocode(addr, key=key)
    print(addr, "->", (lng, lat), src)
