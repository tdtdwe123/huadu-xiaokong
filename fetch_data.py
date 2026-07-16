#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_data.py — 抓取花都区新楼盘实时销控数据，生成 data.json
在 GitHub Actions runner 上运行（服务器端请求，无 CORS 限制）。

数据来源：广州市住房和城乡建设局「阳光家缘」 https://zfcj.gz.gov.cn
"""
import json, time, urllib.request, urllib.parse, os, sys

GOV_BASE = "https://zfcj.gz.gov.cn"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://zfcj.gz.gov.cn/zfcj/fyxx/xkb/index.html",
    "X-Requested-With": "XMLHttpRequest",
}

# 读取项目清单（id/name/developer/presell/address/area）
PROJECTS_FILE = os.path.join(os.path.dirname(__file__), "projects.json")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "data.json")


def gov_get(path, params, retries=1, timeout=12):
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
        time.sleep(0.8 * (i + 1))
    return None


def clean_build_name(n):
    if not n:
        return n
    n = n.replace("广州市花都区", "")
    import re
    n = re.sub(r"(\([^)]*(?:（[^）]*）[^)]*)*\))\1", r"\1", n)
    return n.strip()


def fetch_project(pid):
    """返回 {info, buildings:[{id,name,units:[[status,...]],summary}]} 或 None"""
    d = gov_get("/ysqgk/Api/WebApi/fdcxmjbxx.ashx", {"sProjectId": pid})
    if not d:
        return None
    info = {}
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
    # 销售概览
    pz = data.get("pzystspzysmjxx") or {}
    summary = {
        "allowPresellNum": pz.get("allowPresellNum"),
        "totalSaleNum": pz.get("totalSaleNum"),
        "totalNosoldNum": pz.get("totalNosoldNum"),
    }

    # 楼栋列表
    bd = gov_get("/ysqgk/Api/WebApi/xmldxx.ashx", {"sProjectId": pid, "sPreSellNo": ""})
    buildings = []
    if bd and isinstance(bd.get("data"), list):
        for b in bd["data"]:
            bid = b.get("buildingId")
            bname = clean_build_name(b.get("buildName"))
            # 销控表（参数名是 buildingId，不是 sBuildingId）
            xk = gov_get("/ysqgk/Api/WebApi/xmxkbxx.ashx", {
                "buildingId": bid,
                "houseFunctionId": "0",
                "unitType": "",
                "houseStatusId": "0",
                "totalAreaId": "0",
                "inAreaId": "0",
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
                            # status 字段可能不存在，用 pledgeStatus/closed 推断
                            "status": u.get("status"),
                            "houseStatusId": u.get("houseStatusId"),
                        })
                    units.append({"floor": floor, "units": row})
            buildings.append({"id": bid, "name": bname, "floors": units})
    return {"info": info, "summary": summary, "buildings": buildings}


def main():
    with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
        projects = json.load(f)
    print(f"共 {len(projects)} 个楼盘", flush=True)

    ok = 0
    out_projects = []
    for i, p in enumerate(projects):
        pid = p["id"]
        try:
            detail = fetch_project(pid)
        except Exception as e:
            print(f"[{i+1}/{len(projects)}] {p['name']} 失败: {e}", flush=True)
            detail = None
        if detail:
            slim = {
                "id": pid,
                "name": p["name"],
                "developer": p.get("developer"),
                "presell": p.get("presell"),
                "address": p.get("address"),
                "area": p.get("area"),
                "lng": p.get("lng"),
                "lat": p.get("lat"),
                "detail": detail,
            }
            out_projects.append(slim)
            ok += 1
        print(f"[{i+1}/{len(projects)}] {p['name']} {'OK' if detail else 'SKIP'}", flush=True)
        time.sleep(0.4)

    print(f"\n成功 {ok}/{len(projects)}", flush=True)
    # 保护机制：如果成功数太少（多为接口不可达），不覆盖已有数据，避免清空页面
    if ok < 200:
        print(f"成功数 {ok} 过少，疑似接口不可达，跳过写入 data.json", flush=True)
        return

    out = {
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "count": ok,
        "projects": out_projects,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"已写入 {OUTPUT_FILE}（{ok} 个楼盘）", flush=True)


if __name__ == "__main__":
    main()
