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
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_robust as FR

BASE = os.path.dirname(os.path.abspath(__file__))
PROJECTS_FILE = os.path.join(BASE, "projects.json")
OUTPUT_FILE = os.path.join(BASE, "data.json")
STATUS_FILE = os.path.join(BASE, "fetch_status.json")

# 并发策略（阳光家缘 WAF 对并发极敏感：并发越高越易被秒拒；单线程+礼貌间隔+耐心重试最稳）
SUMMARY_WORKERS = 1      # 摘要改为单线程，避免触发限流
SUMMARY_RETRIES = 3      # 耐心重试，救回瞬断
SUMMARY_TIMEOUT = 15
SUMMARY_GAP = 0.8        # 两次摘要请求之间的礼貌间隔（秒），给令牌桶喘息
FULL_WORKERS = 1         # 完整抓取单线程，最稳
FULL_RETRIES = 3         # 耐心重试
FULL_TIMEOUT = 40
FULL_GAP = 1.0           # 两次完整抓取之间的间隔
RETRY_PASS_CAP = 120     # Phase A 缺失摘要重试上限（避免数百个缺失全重试拖爆）


def fetch_summary(pid):
    """单次轻量请求：返回 (info, summary) 或 None。（HTTP 层统一走 fetch_robust.gov_get / curl）"""
    d = FR.gov_get("/ysqgk/Api/WebApi/fdcxmjbxx.ashx", {"sProjectId": pid},
                   retries=SUMMARY_RETRIES, timeout=SUMMARY_TIMEOUT)
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
        time.sleep(SUMMARY_GAP)   # 礼貌间隔，降低触发 WAF 限流概率
        return pid

    with ThreadPoolExecutor(max_workers=SUMMARY_WORKERS) as ex:
        list(ex.map(do_summary, projects))

    # 失败摘要重试 pass：对没拿到摘要的盘，单线程耐心补一次（设上限，避免拖爆）
    missing = [p for p in projects if p["id"] not in summaries][:RETRY_PASS_CAP]
    if missing:
        print(f"  摘要缺失 {len(missing)} 个（上限{RETRY_PASS_CAP}），单线程重试…", flush=True)
        with ThreadPoolExecutor(max_workers=1) as ex:
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
    def do_full(p):
        det = FR.fetch_project(p["id"], FULL_RETRIES, FULL_TIMEOUT)
        time.sleep(FULL_GAP)   # 礼貌间隔
        return p, det
    with ThreadPoolExecutor(max_workers=FULL_WORKERS) as ex:
        futs = {ex.submit(do_full, p): p for p in need_full}
        done = [0]
        for fut in as_completed(futs):
            p = futs[fut]
            _, det = fut.result()
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
            # 摘要优先用本轮新鲜值；若本轮未拿到（瞬断）则保留旧摘要，绝不降级
            "summary": summaries.get(pid) if summaries.get(pid) is not None else (o or {}).get("summary"),
            "detail": None,
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
