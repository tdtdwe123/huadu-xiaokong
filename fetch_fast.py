#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""差分快速抓取：先轻量拿「在售/未售」摘要，只对有变动或尚无数据的楼盘做完整抓取。

设计目标（对比原 fetch_robust 每轮全量重抓 657×3 次接口）：
  1) 快：每轮只对全部楼盘发 1 次轻量摘要请求（~657 次），完整抓取仅作用于
     「摘要变化的盘」+「还没有 detail 的盘」（通常几十个），接口量从 ~1971 降到 ~657+少量。
  2) 稳：摘要请求轻量、并发耐受更好；完整抓取走耐心单/双线程重试，专治瞬断。
  3) 完整：任何抓取失败都回退到旧 data.json 的已有 detail，绝不把数据刷空。

差分指纹 = (allowPresellNum, totalSaleNum, totalNosoldNum, preSellNo)
  有房源售出 → totalSaleNum↑ / totalNosoldNum↓ → 触发该盘重新拉取房号明细。

返回：写入 data.json / fetch_status.json；并通过 fetch_status.json 的 changed 标志
      供 auto_update 判断是否「主动推送」。
"""
import json, time, os, sys, threading, hashlib
import urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_robust as FR

BASE = os.path.dirname(os.path.abspath(__file__))
PROJECTS_FILE = os.path.join(BASE, "projects.json")
OUTPUT_FILE = os.path.join(BASE, "data.json")
STATUS_FILE = os.path.join(BASE, "fetch_status.json")

# 并发策略
SUMMARY_WORKERS = 4      # 轻量摘要请求，可稍高并发
SUMMARY_RETRIES = 2
SUMMARY_TIMEOUT = 12
FULL_WORKERS = 2         # 完整抓取（每盘数十次子请求），低并发更稳
FULL_RETRIES = 2         # 真失败快速放弃，避免长尾
FULL_TIMEOUT = 30
RETRY_PASS_CAP = 150     # Phase A 缺失摘要重试上限（避免数百个缺失全重试拖爆）


def gov_get(path, params, retries=SUMMARY_RETRIES, timeout=SUMMARY_TIMEOUT):
    url = FR.GOV_BASE + path + "?" + urllib.parse.urlencode(params)
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=FR.HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8")
            d = json.loads(raw)
            if d.get("status") == 1:
                return d
            last = f"status={d.get('status')}"
        except Exception as e:
            last = str(e)
        time.sleep(1.0 * (i + 1))
    return None


def fetch_summary(pid):
    """单次轻量请求：返回 (info, summary) 或 None。"""
    d = gov_get("/ysqgk/Api/WebApi/fdcxmjbxx.ashx", {"sProjectId": pid})
    if not d:
        return None
    data = d.get("data") or {}
    x = data.get("xmldxxxgxx") or {}
    pz = data.get("pzystspzysmjxx") or {}
    info = {
        "projectId": x.get("projectId"),
        "projectName": x.get("projectName"),
        "developer": x.get("developer"),
        "preSellNo": x.get("preSellNo"),
        "pjAddress": x.get("pjAddress"),
        "totalBuildingArea": x.get("totalBuildingArea"),
        "competencyNo": x.get("competencyNo"),
    }
    summary = {
        "allowPresellNum": pz.get("allowPresellNum"),
        "totalSaleNum": pz.get("totalSaleNum"),
        "totalNosoldNum": pz.get("totalNosoldNum"),
    }
    return info, summary


def fingerprint(summ, presell):
    if not summ:
        return None
    return (summ.get("allowPresellNum"), summ.get("totalSaleNum"),
            summ.get("totalNosoldNum"), presell)


def _compact_sig(p):
    """用于变化检测的轻量签名：摘要 + 是否有明细（兼容旧记录：摘要藏在 detail.summary）。"""
    s = p.get("summary") or (p.get("detail") or {}).get("summary") or {}
    return (s.get("allowPresellNum"), s.get("totalSaleNum"),
            s.get("totalNosoldNum"), bool(p.get("detail")))


def main():
    t0 = time.time()
    with open(PROJECTS_FILE, encoding="utf-8") as f:
        projects = json.load(f)
    total = len(projects)

    # 旧数据：保留已有 detail / summary / 坐标
    old = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            live = json.load(open(OUTPUT_FILE, encoding="utf-8"))
            for p in live.get("projects", []):
                old[p["id"]] = p
        except Exception:
            pass

    # ---- Phase A：轻量摘要（全量） ----
    print(f"Phase A 摘要请求 {total} 个（{SUMMARY_WORKERS} 线程）…", flush=True)
    summaries = {}     # pid -> (info, summary)
    info_only = {}     # pid -> info（用于回填基本信息）
    lock = threading.Lock()
    ok = [0]

    def do_summary(p):
        pid = p["id"]
        res = fetch_summary(pid)
        with lock:
            if res:
                info, summ = res
                summaries[pid] = summ
                info_only[pid] = info
                ok[0] += 1
        return pid

    with ThreadPoolExecutor(max_workers=SUMMARY_WORKERS) as ex:
        list(ex.map(do_summary, projects))

    # 失败摘要重试 pass：对没拿到摘要的盘，降到 2 线程再补一次（设上限，避免拖爆）
    missing = [p for p in projects if p["id"] not in summaries][:RETRY_PASS_CAP]
    if missing:
        print(f"  摘要缺失 {len(missing)} 个（上限{RETRY_PASS_CAP}），2 线程重试…", flush=True)
        with ThreadPoolExecutor(max_workers=2) as ex:
            list(ex.map(do_summary, missing))
    print(f"  摘要成功 {ok[0]}/{total}", flush=True)

    # ---- 决定哪些需要完整抓取 ----
    need_full = []
    for p in projects:
        pid = p["id"]
        o = old.get(pid)
        new_fp = fingerprint(summaries.get(pid), (info_only.get(pid) or {}).get("preSellNo"))
        if not o or not o.get("detail"):
            need_full.append(p)                      # 尚无明细 → 必抓
        else:
            # 旧指纹：优先顶层 summary，回退到 detail.summary（fetch_robust 旧结构）
            old_summ = o.get("summary") or (o.get("detail") or {}).get("summary")
            old_presell = o.get("presell") or (o.get("detail") or {}).get("info", {}).get("preSellNo")
            old_fp = fingerprint(old_summ, old_presell)
            if new_fp is not None and old_fp != new_fp:
                need_full.append(p)                  # 摘要变动 → 重抓明细
    print(f"Phase B 需完整抓取 {len(need_full)} 个（{FULL_WORKERS} 线程，耐心重试）…", flush=True)

    fresh_detail = {}   # pid -> detail（本轮成功抓到）
    with ThreadPoolExecutor(max_workers=FULL_WORKERS) as ex:
        futs = {ex.submit(FR.fetch_project, p["id"], FULL_RETRIES, FULL_TIMEOUT): p for p in need_full}
        done = [0]
        for fut in as_completed(futs):
            p = futs[fut]
            det = fut.result()
            with lock:
                if det:
                    fresh_detail[p["id"]] = det
                done[0] += 1
                if done[0] % 10 == 0 or done[0] == len(need_full):
                    print(f"  完整抓取 {done[0]}/{len(need_full)}（成功 {len(fresh_detail)}）", flush=True)

    # ---- 合并输出 ----
    out_projects = []
    restored = 0
    for p in projects:
        pid = p["id"]
        rec = {
            "id": pid, "name": p["name"], "developer": p.get("developer"),
            "presell": p.get("presell"), "address": p.get("address"),
            "area": p.get("area"),
            "lng": p.get("lng"), "lat": p.get("lat"),
            "geo_approx": p.get("geo_approx"), "geo_src": p.get("geo_src"),
            "summary": summaries.get(pid), "detail": None,
        }
        # 坐标优先级：旧 data 已有坐标 > projects.json 原始坐标（保留精确/已修正坐标）
        o = old.get(pid)
        if o and o.get("lng") and o.get("lat"):
            rec["lng"], rec["lat"] = o["lng"], o["lat"]
            rec["geo_approx"] = o.get("geo_approx")
            rec["geo_src"] = o.get("geo_src")
        # 明细优先级：本轮新鲜抓取 > 旧 detail > 无
        if pid in fresh_detail:
            rec["detail"] = fresh_detail[pid]
            # 用新基本信息覆盖（开发者/地址可能更新）
            ni = info_only.get(pid)
            if ni:
                rec["developer"] = ni.get("developer") or rec["developer"]
                rec["address"] = ni.get("pjAddress") or rec["address"]
                rec["presell"] = ni.get("preSellNo") or rec["presell"]
        elif o and o.get("detail"):
            rec["detail"] = o["detail"]
            restored += 1
        out_projects.append(rec)

    out = {
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "count": total,
        "projects": out_projects,
    }
    pre_sig = hashlib.sha256(json.dumps([_compact_sig(o) for o in (old.get(p["id"], {}) for p in projects)], separators=(",", ":")).encode()).hexdigest() if old else ""
    json.dump(out, open(OUTPUT_FILE, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    post_sig = hashlib.sha256(json.dumps([_compact_sig(p) for p in out_projects], separators=(",", ":")).encode()).hexdigest()
    changed = (pre_sig != post_sig)

    status = {
        "updated": out["updated"], "total": total,
        "summary_ok": ok[0], "full_fetched": len(need_full),
        "full_ok": len(fresh_detail), "restored": restored,
        "changed": changed,
        "elapsed_sec": round(time.time() - t0, 1),
    }
    json.dump(status, open(STATUS_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    has_detail = sum(1 for p in out_projects if p.get("detail"))
    print(f"\n完成：摘要{ok[0]}/{total}，完整抓取{len(need_full)}个（成功{len(fresh_detail)}），"
          f"回退{restored}个，最终有明细{has_detail}/{total}。耗时{status['elapsed_sec']}s，changed={changed}", flush=True)
    return status


if __name__ == "__main__":
    main()
