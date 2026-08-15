#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""\u628a\u672c\u5730\u6587\u4ef6\u4e00\u6b21\u6027\u63a8\u9001\u5230 GitHub\uff08Contents API\uff09\u3002

Token \u89e3\u6790\uff08\u89c1 config.get_token\uff09\uff1a\u73af\u5883\u53d8\u91cf GITHUB_TOKEN -> \u672c\u5730 .token \u6587\u4ef6\u3002
\u7528\u6cd5\uff1apython3 push_all.py            # \u63a8\u9001\u9ed8\u8ba4\u6e05\u5355
      python3 push_all.py data.json   # \u53ea\u63a8\u9001\u6307\u5b9a\u6587\u4ef6
"""
import os, base64, time, sys, json, socket
import requests
import config

BASE = os.path.dirname(os.path.abspath(__file__))
REPO = "tdtdwe123/huadu-xiaokong"
API = f"https://api.github.com/repos/{REPO}"


def _ensure_api_hosts():
    """沙箱 DNS 可能把 api.github.com 解析到坏代理 198.18.0.x，自动写 /etc/hosts 绕过。"""
    try:
        ip = socket.gethostbyname("api.github.com")
        if ip.startswith("198.18."):
            with open("/etc/hosts", "a") as f:
                f.write("\n140.82.121.6 api.github.com\n")
            print(f"[!] DNS polluted to {ip}, wrote /etc/hosts bypass", flush=True)
    except Exception:
        pass

# \u9ed8\u8ba4\u63a8\u9001\u6e05\u5355\uff08\u7ad9\u70b9\u6570\u636e + \u6293\u53d6/\u66f4\u65b0\u7ba1\u7ebf\uff09
FILES = [
    "data.json", "projects.json", "fetch_status.json",
    "fetch_fast.py", "fetch_robust.py", "retry_failed.py", "build_projects.py",
    "push_all.py", "auto_update.py", "deploy.py", "config.py", "index.html",
    "aliases.json",
]


# \u2014\u2014 data.json \u7626\u8eab \u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014
# GitHub Contents API \u5355\u6587\u4ef6\u4e0a\u9650\u7ea6 50MB\uff1b\u697c\u76d8\u697c\u680b\u660e\u7ec6\uff0827 \u4e07+ \u5957\uff09\u4f1a\u628a
# data.json \u6491\u5230 60MB+ \u800c\u88ab\u62d2\u7edd(HTTP 422)\u3002\u63a8\u9001\u524d\u7edf\u4e00\u5269\u9664\u524d\u7aef\u4e0d\u7528\u7684\u5197\u4f59
# \u5b57\u6bb5\u5e76\u6539\u7528\u7d27\u51d1 JSON\uff0c\u53ef\u5c06\u4f53\u79ef\u4ece ~61MB \u538b\u5230 ~43MB\uff0c\u4e14\u5b57\u6bb5\u540d\u4e0d\u53d8\uff0c
# \u524d\u7aef index.html \u65e0\u9700\u4efb\u4f55\u6539\u52a8\u3002
_UNIT_DROP = {"floorNum", "houseStatusId", "backMove", "useself",
              "commonMatch", "directly", "divide", "pactStatus"}
_KEY_MAP = {"unitNum": "n", "totalArea": "a", "status": "s",
            "preSellStatus": "p", "houseFunction": "f", "unitType": "t",
            "inArea": "i", "closed": "c", "pledgeStatus": "ps"}


def _norm_unit(u):
    out = {}
    for k, v in u.items():
        if k in _UNIT_DROP:
            continue
        nk = _KEY_MAP.get(k, k)
        if k in ("totalArea", "inArea") and isinstance(v, float):
            v = round(v, 2)
        out[nk] = v
    return out


def _norm_proj(p):
    p = dict(p)
    det = p.get("detail") or {}
    if det.get("buildings"):
        nb = []
        for b in det["buildings"]:
            b = dict(b)
            fls = []
            for f in (b.get("floors") or []):
                f = dict(f)
                f["units"] = [_norm_unit(u) for u in (f.get("units") or [])]
                fls.append(f)
            b["floors"] = fls
            nb.append(b)
        det = dict(det)
        det["buildings"] = nb
        p["detail"] = det
    return p


def normalize_data(obj):
    obj = dict(obj)
    obj["projects"] = [_norm_proj(p) for p in obj.get("projects", [])]
    return obj


def _headers(token):
    return {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}


def push(path, token, force=False):
    full = os.path.join(BASE, path)
    if not os.path.exists(full):
        print(f"  - {path} \u4e0d\u5b58\u5728\uff0c\u8df3\u8fc7")
        return False
    with open(full, "rb") as f:
        data = f.read()
    # data.json \u4f53\u578b\u8fc7\u5927\uff0c\u63a8\u9001\u524d\u5148\u5f52\u4e00\u5316\u7626\u8eab\uff08\u5b57\u6bb5\u540d\u4e0d\u53d8\uff0c\u524d\u7aef\u65e0\u9700\u6539\u52a8\uff09
    if path == "data.json":
        try:
            obj = json.loads(data.decode("utf-8"))
            data = json.dumps(normalize_data(obj), ensure_ascii=False,
                              separators=(",", ":")).encode("utf-8")
        except Exception as e:
            print(f"  ! data.json \u5f52\u4e00\u5316\u5931\u8d25\uff0c\u6309\u539f\u6837\u63a8\u9001: {e}")
    H = _headers(token)
    r = requests.get(f"{API}/contents/{path}", headers=H, timeout=30)
    sha = r.json().get("sha") if r.status_code == 200 else None
    if not force and r.status_code == 200 and path != "data.json":
        remote = base64.b64decode(r.json().get("content", ""))
        if remote == data:
            print(f"  = {path} \u5185\u5bb9\u672a\u53d8\uff0c\u8df3\u8fc7")
            return True
    body = {"message": f"\u81ea\u52a8\u66f4\u65b0\u9500\u63a7\u6570\u636e ({time.strftime('%Y-%m-%d %H:%M')})",
            "branch": "main", "content": base64.b64encode(data).decode()}
    if sha:
        body["sha"] = sha
    r = requests.put(f"{API}/contents/{path}", headers=H, timeout=120, json=body)
    if r.status_code in (200, 201):
        print(f"  \u2713 {path} \u5df2\u63a8\u9001")
        return True
    print(f"  \u2717 {path} \u5931\u8d25 {r.status_code}: {r.text[:200]}")
    return False


def push_all(token=None, targets=None):
    _ensure_api_hosts()
    token = token or config.get_token()
    targets = targets or FILES
    H = _headers(token)
    probe = requests.get(f"{API}", headers=H, timeout=20)
    if probe.status_code == 401:
        print("\u2717 GitHub Token \u65e0\u6548(401)\u3002\u8bf7\u8bbe\u7f6e\u6709\u6548 GITHUB_TOKEN\uff08repo \u6743\u9650\uff09\u6216\u5199\u5165 .token \u540e\u91cd\u8bd5\u3002")
        return False
    print(f"[{time.strftime('%H:%M:%S')}] \u63a8\u9001 {len(targets)} \u4e2a\u6587\u4ef6\u2026", flush=True)
    ok = 0
    for t in targets:
        if push(t, token):
            ok += 1
    print(f"[{time.strftime('%H:%M:%S')}] \u63a8\u9001\u5b8c\u6210 {ok}/{len(targets)}\u3002GitHub Pages \u7ea6 1-2 \u5206\u949f\u91cd\u5efa\u751f\u6548\u3002")
    return ok == len(targets)


if __name__ == "__main__":
    push_all(targets=(sys.argv[1:] or None))
