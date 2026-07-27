#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""补抓单元标记字段（preSellStatus/backMove/useself/commonMatch/directly/divide/pactStatus）。

fetch_robust.py 旧版只保存了 5 个 unit 字段，导致官网销控表的 ★未纳入预售 等图例标记丢失。
本脚本对所有有 detail.buildings 的盘，单独调 xmxkbxx 拿单元数据，把新字段 merge 进现有 unit
（保留旧字段、补缺失字段），不重抓 info/summary/buildings 列表，节省 ~2/3 接口量。
"""
import json, os, sys, time, urllib.parse, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_robust as FR

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data.json")

NEW_FIELDS = ["preSellStatus", "backMove", "useself", "commonMatch", "directly", "divide", "pactStatus"]


def fetch_units_only(building_id, retries=3, timeout=20):
    """只取 unit 数据，绕过 fdcxmjbxx/xmldxx。"""
    url = FR.GOV_BASE + "/ysqgk/Api/WebApi/xmxkbxx.ashx?" + urllib.parse.urlencode({
        "buildingId": building_id, "houseFunctionId": "0", "unitType": "",
        "houseStatusId": "0", "totalAreaId": "0", "inAreaId": "0",
    })
    last = None
    for i in range(retries):
        try:
            r = subprocess.run(
                ["curl", "-s", "--compressed", "--max-time", str(timeout),
                 "-A", FR.HEADERS["User-Agent"],
                 "-e", FR.HEADERS["Referer"],
                 "-H", "X-Requested-With: XMLHttpRequest",
                 "-H", "Accept: application/json, text/plain, */*",
                 url],
                capture_output=True, text=True, timeout=timeout + 15)
            raw = (r.stdout or "").strip()
            if not raw:
                last = f"空 rc={r.returncode}"
                time.sleep(1.2 * (i + 1))
                continue
            d = json.loads(raw)
            if d.get("status") == 1 and isinstance(d.get("data"), list):
                return d["data"]
            last = f"status={d.get('status')}"
        except subprocess.TimeoutExpired:
            last = "超时"
        except Exception as e:
            last = str(e)
        time.sleep(1.2 * (i + 1))
    return None


def merge_units(old_floors, new_groups):
    """把 new_groups 的 NEW_FIELDS merge 到 old_floors 对应单元上。
    按 (floor, unitNum) 对齐。返回 (updated, missing)。
    """
    # new: floor -> {unitNum: {fields}}
    new_map = {}
    for grp in new_groups:
        fl = grp.get("group")
        for u in (grp.get("groupData") or []):
            un = u.get("unitNum")
            new_map.setdefault(fl, {})[un] = {f: u.get(f) for f in NEW_FIELDS}

    updated = 0
    missing = 0
    for f in old_floors:
        fl = f.get("floor")
        nm = new_map.get(fl, {})
        for u in f.get("units") or []:
            un = u.get("unitNum")
            nu = nm.get(un)
            if not nu:
                missing += 1
                continue
            for k, v in nu.items():
                u[k] = v
            updated += 1
    return updated, missing


def main():
    d = json.load(open(DATA, encoding="utf-8"))
    projs = d["projects"]
    targets = [p for p in projs
               if isinstance(p.get("detail"), dict) and p["detail"].get("buildings")]
    print(f"待补抓 unit 标记字段的盘: {len(targets)}")
    byid = {p["id"]: p for p in projs}
    total_blds = sum(len(p["detail"]["buildings"]) for p in targets)
    print(f"涉及楼栋: {total_blds}")

    ok_blds = 0
    fail_blds = 0
    fields_added = 0
    skipped = 0
    t0 = time.time()

    def save():
        tmp = DATA + ".tmp"
        json.dump(d, open(tmp, "w", encoding="utf-8"),
                  ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, DATA)

    last_save = 0
    try:
        for i, p in enumerate(targets, 1):
            pid = p["id"]
            blds = p["detail"]["buildings"]
            already = blds and blds[0].get("floors") and blds[0]["floors"] and \
                      blds[0]["floors"][0].get("units") and \
                      ("preSellStatus" in blds[0]["floors"][0]["units"][0])
            if already:
                skipped += 1
                continue
            for b in blds:
                bid = b["id"]
                groups = fetch_units_only(bid)
                if groups is None:
                    fail_blds += 1
                    continue
                upd, miss = merge_units(b["floors"], groups)
                fields_added += upd * len(NEW_FIELDS)
                ok_blds += 1
                if miss > 0:
                    print(f"  [{pid}/{bid}] 缺失 {miss}/{upd+miss} 单元", flush=True)
                time.sleep(0.4)
            # 每 25 个盘增量写回，防死锁/中断丢数据
            if (i - last_save) >= 25:
                save(); last_save = i
                print(f"[{i}/{len(targets)}] saved ok={ok_blds} skip={skipped} "
                      f"fail={fail_blds} f_added={fields_added} "
                      f"elapsed={time.time()-t0:.0f}s", flush=True)
        save()
    except (KeyboardInterrupt, Exception) as e:
        save()
        print(f"⚠ 中断({type(e).__name__})，已保存进度: ok={ok_blds} skip={skipped} "
              f"fail={fail_blds} f_added={fields_added}", flush=True)
        raise

    print(f"\n完成：ok_blds={ok_blds} skip={skipped} fail_blds={fail_blds} "
          f"fields_added={fields_added} elapsed={time.time()-t0:.0f}s")
    print(f"已写回 {DATA}")