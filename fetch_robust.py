#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""增量抓取：每抓一个就保存，支持断点续抓"""
import json, time, urllib.request, urllib.parse, os, re, sys, threading
from concurrent.futures import ThreadPoolExecutor, as_completed

GOV_BASE = "https://zfcj.gz.gov.cn"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://zfcj.gz.gov.cn/zfcj/fyxx/xkb/index.html",
    "X-Requested-With": "XMLHttpRequest",
}
BASE = "/workspace/huadu_map/github_pages"
PROJECTS_FILE = os.path.join(BASE, "projects.json")
OUTPUT_FILE = os.path.join(BASE, "data.json")
PROGRESS_FILE = os.path.join(BASE, "data_progress.json")


def gov_get(path, params, retries=2, timeout=12):
    url = GOV_BASE + path + "?" + urllib.parse.urlencode(params)
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8")
            d = json.loads(raw)
            if d.get("status") == 1:
                return d
            last = f"status={d.get('status')}"
        except Exception as e:
            last = str(e)
        time.sleep(1.5 * (i + 1))
    return None


def clean_build_name(n):
    if not n:
        return n
    n = n.replace("广州市花都区", "")
    n = re.sub(r"(\([^)]*(?:（[^）]*）[^)]*)*\))\1", r"\1", n)
    return n.strip()


def fetch_project(pid):
    d = gov_get("/ysqgk/Api/WebApi/fdcxmjbxx.ashx", {"sProjectId": pid})
    if not d:
        return None
    data = d.get("data") or {}
    x = data.get("xmldxxxgxx") or {}
    info = {
        "projectId": x.get("projectId"),
        "projectName": x.get("projectName"),
        "developer": x.get("developer"),
        "preSellNo": x.get("preSellNo"),
        "pjAddress": x.get("pjAddress"),
        "totalBuildingArea": x.get("totalBuildingArea"),
        "competencyNo": x.get("competencyNo"),
    }
    pz = data.get("pzystspzysmjxx") or {}
    summary = {
        "allowPresellNum": pz.get("allowPresellNum"),
        "totalSaleNum": pz.get("totalSaleNum"),
        "totalNosoldNum": pz.get("totalNosoldNum"),
    }
    bd = gov_get("/ysqgk/Api/WebApi/xmldxx.ashx", {"sProjectId": pid, "sPreSellNo": ""})
    buildings = []
    if bd and isinstance(bd.get("data"), list):
        for b in bd["data"]:
            bid = b.get("buildingId")
            bname = clean_build_name(b.get("buildName"))
            xk = gov_get("/ysqgk/Api/WebApi/xmxkbxx.ashx", {
                "buildingId": bid, "houseFunctionId": "0", "unitType": "",
                "houseStatusId": "0", "totalAreaId": "0", "inAreaId": "0",
            })
            units = []
            if xk and isinstance(xk.get("data"), list):
                for grp in xk["data"]:
                    floor = grp.get("group")
                    row = []
                    for u in grp.get("groupData") or []:
                        row.append({
                            "unitNum": u.get("unitNum"),
                            "houseFunction": u.get("houseFunction"),
                            "totalArea": u.get("totalArea"),
                            "inArea": u.get("inArea"),
                            "unitType": u.get("unitType"),
                            "pledgeStatus": u.get("pledgeStatus"),
                            "closed": u.get("closed"),
                            "floorNum": u.get("floorNum"),
                            "status": u.get("status"),
                            "houseStatusId": u.get("houseStatusId"),
                        })
                    units.append({"floor": floor, "units": row})
            buildings.append({"id": bid, "name": bname, "floors": units})
    return {"info": info, "summary": summary, "buildings": buildings}


def main():
    with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
        projects = json.load(f)
    total = len(projects)

    # 加载线上已有的坐标（保持已修正/已精确的坐标，避免被回退）
    live_coords = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            live = json.load(open(OUTPUT_FILE, encoding="utf-8"))
            for p in live.get("projects", []):
                if p.get("lng") and p.get("lat"):
                    live_coords[p["id"]] = (p["lng"], p["lat"], p.get("geo_approx"), p.get("geo_src"))
        except Exception:
            pass

    # 加载已有进度
    results = {}
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            results = json.load(f)
    done = len(results)
    print(f"共 {total} 个楼盘，已完成 {done} 个，剩余 {total - done} 个", flush=True)

    amap_key = os.environ.get("AMAP_KEY")

    lock = threading.Lock()
    save_counter = [0]

    def fetch_one(i, p):
        pid = p["id"]
        try:
            detail = fetch_project(pid)
        except Exception as e:
            detail = None
        r = {
            "id": pid, "name": p["name"], "developer": p.get("developer"),
            "presell": p.get("presell"), "address": p.get("address"),
            "area": p.get("area"),
            "lng": p.get("lng"), "lat": p.get("lat"),
            "geo_approx": p.get("geo_approx"), "geo_src": None,
            "detail": detail,
        }
        with lock:
            results[pid] = r
            save_counter[0] += 1
            ok = sum(1 for v in results.values() if v.get("detail"))
            print(f"[{i+1}/{total}] {p['name']} {'OK' if detail else 'FAIL'} (成功{ok})", flush=True)
            # 每完成 10 个或最后一个时保存进度，减少 IO
            if save_counter[0] % 10 == 0 or save_counter[0] == len(projects):
                with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
                    json.dump(results, f, ensure_ascii=False, separators=(",", ":"))
        return pid

    todo = [p for p in projects if p["id"] not in results]
    print(f"并发抓取 {len(todo)} 个楼盘（8 线程）…", flush=True)
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda args: fetch_one(*args), enumerate(todo)))

    # 最终保存一次进度
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, separators=(",", ":"))

    # 坐标修正优先级：高德实时 geocode > 线上已有坐标 > projects.json 原始坐标
    for p in projects:
        pid = p["id"]
        r = results.get(pid)
        if not r:
            continue
        final_lng, final_lat, approx, src = p.get("lng"), p.get("lat"), p.get("geo_approx"), None
        # 1) 高德精确 geocode（需 AMAP_KEY，且用完整备案地址）
        if amap_key and r.get("detail") and r["detail"].get("info", {}).get("pjAddress"):
            try:
                import geocode
                glng, glat, gsrc = geocode.geocode(
                    r["detail"]["info"]["pjAddress"], key=amap_key,
                    project_id=pid, name=p["name"])
                if glng:
                    final_lng, final_lat, approx, src = glng, glat, False, gsrc
            except Exception as e:
                print(f"  geocode {p['name']} 失败: {e}", flush=True)
        # 2) 否则保留线上已修正/精确坐标
        if src is None and pid in live_coords:
            final_lng, final_lat, approx, src = live_coords[pid]
        r["lng"], r["lat"] = final_lng, final_lat
        r["geo_approx"] = approx
        r["geo_src"] = src

    # 统计本次真正抓取成功的数量（未使用旧数据回填）
    fresh_ok = sum(1 for v in results.values() if v.get("detail") is not None)

    # 合并旧数据：本次抓取失败的项目保留 data.json 中的 detail，避免海外/不稳定网络把数据刷空
    old_details = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            old = json.load(open(OUTPUT_FILE, encoding="utf-8"))
            for op in old.get("projects", []):
                if op.get("detail"):
                    old_details[op["id"]] = op["detail"]
        except Exception:
            pass
    restored = 0
    for pid in results:
        if results[pid].get("detail") is None and pid in old_details:
            results[pid]["detail"] = old_details[pid]
            restored += 1

    # 生成最终 data.json
    out = {
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "count": total,
        "projects": [results[p["id"]] for p in projects if p["id"] in results],
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    # progress 只保留本次真正抓取成功的项目，失败项下次重试
    for pid in list(results.keys()):
        if results[pid].get("detail") is None:
            del results[pid]
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, separators=(",", ":"))

    # 写入状态文件，供 CI/Actions 判断是否提交
    status = {"fresh_ok": fresh_ok, "restored": restored, "total": total, "updated": out["updated"]}
    with open(os.path.join(BASE, "fetch_status.json"), "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False)

    print(f"\n完成：{fresh_ok}/{total} 本次新鲜抓取，{restored} 个从旧数据恢复，写入 {OUTPUT_FILE}", flush=True)


if __name__ == "__main__":
    main()
