#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestFlight Data Export via App Store Connect API

Pulls the full picture of your TestFlight beta program that the ASC web UI
won't let you export:

  testers.csv       all beta testers: name, email, state, invite type, groups
  builds.csv        build versions with upload/expiration dates and state
  crashes.json      crash feedback submissions (raw JSON)
  screenshots.json  screenshot feedback submissions (raw JSON)
  summary.txt       human-readable funnel & stats summary

Why: App Store Connect has no bulk export for beta testers. If you want to
analyze activation, conversion, or feedback volume for a beta program,
you have to click through the API yourself. This script does it in one run.

Usage:
    python asc_fetch.py \
        --key AuthKey_XXXXXX.p8 \
        --key-id XXXXXXXXXX \
        --issuer-id xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx \
        --app-id 1234567890

Setup (one time):
    1. Go to https://appstoreconnect.apple.com/access/integrations/api
    2. Create an API key with "App Manager" role (or "Developer")
    3. Download the .p8 key file, note the Key ID and Issuer ID
    4. Pass all three to this script. Nothing is stored anywhere.

Requirements:
    pip install -r requirements.txt
"""

import argparse
import csv
import json
import os
import sys
import time
from collections import Counter

try:
    import jwt
    import requests
except ImportError:
    sys.exit("Missing dependencies. Run: pip install -r requirements.txt")

BASE = "https://api.appstoreconnect.apple.com"


def make_token(key_path, key_id, issuer_id):
    with open(key_path, "r", encoding="utf-8") as f:
        private_key = f.read()
    now = int(time.time())
    payload = {
        "iss": issuer_id,
        "iat": now,
        "exp": now + 900,          # 15 min, ASC accepts up to 20 min
        "aud": "appstoreconnect-v1",
    }
    return jwt.encode(payload, private_key, algorithm="ES256",
                      headers={"kid": key_id, "typ": "JWT"})


class Client:
    def __init__(self, token):
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {token}"})

    def get(self, path, params=None):
        url = path if path.startswith("http") else BASE + path
        for attempt in range(4):
            r = self.s.get(url, params=params, timeout=30)
            if r.status_code == 429:
                time.sleep(2 ** attempt * 3)
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code} {url}\n{r.text[:500]}")
            return r.json()
        raise RuntimeError(f"Rate-limited after 4 retries: {url}")

    def paged(self, path, params=None):
        """Auto-paginate, return the merged data list."""
        out = []
        params = dict(params or {})
        params.setdefault("limit", 200)
        data = self.get(path, params)
        out.extend(data.get("data", []))
        while True:
            nxt = data.get("links", {}).get("next")
            if not nxt:
                break
            data = self.get(nxt)
            out.extend(data.get("data", []))
            print(f"    {len(out)} records fetched...", end="\r")
        if out:
            print(" " * 40, end="\r")
        return out


def main():
    ap = argparse.ArgumentParser(
        description="Export TestFlight testers, builds and feedback via the App Store Connect API.")
    ap.add_argument("--key", required=True, help="Path to AuthKey_XXXXXX.p8")
    ap.add_argument("--key-id", required=True, help="10-character API Key ID")
    ap.add_argument("--issuer-id", required=True, help="Issuer ID (UUID)")
    ap.add_argument("--app-id", required=True, help="Apple App ID (numeric)")
    ap.add_argument("--out", default="asc_data", help="Output directory (default: ./asc_data)")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    c = Client(make_token(args.key, args.key_id, args.issuer_id))

    # ---------- 1. Beta groups ----------
    print("[1/5] Fetching beta groups...")
    groups = c.paged("/v1/betaGroups",
                     {"filter[app]": args.app_id,
                      "fields[betaGroups]": "name,isInternalGroup,publicLinkEnabled,publicLinkLimit,createdDate"})
    gname = {g["id"]: g["attributes"]["name"] for g in groups}
    print(f"      {len(groups)} group(s): {', '.join(gname.values())}")

    # ---------- 2. Testers ----------
    print("[2/5] Fetching testers (state, invite type, groups)...")
    testers = c.paged("/v1/betaTesters", {
        "filter[apps]": args.app_id,
        "fields[betaTesters]": "firstName,lastName,email,inviteType,state",
        "include": "betaGroups",
        "limit": 200,
    })
    print(f"      API returned {len(testers)} testers")

    rows = []
    for t in testers:
        a = t["attributes"]
        grp_ids = [g["id"] for g in
                   (t.get("relationships", {}).get("betaGroups", {}).get("data") or [])]
        rows.append({
            "name": f"{a.get('firstName') or ''} {a.get('lastName') or ''}".strip(),
            "email": a.get("email") or "(anonymous/public link)",
            "state": a.get("state") or "",
            "invite_type": a.get("inviteType") or "",
            "groups": " | ".join(gname.get(i, i) for i in grp_ids),
            "tester_id": t["id"],
        })

    with open(os.path.join(args.out, "testers.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["name"])
        w.writeheader()
        w.writerows(rows)

    # ---------- 3. Builds ----------
    print("[3/5] Fetching builds...")
    builds = c.paged("/v1/builds", {
        "filter[app]": args.app_id,
        "fields[builds]": "version,uploadedDate,expirationDate,expired,processingState",
        "limit": 200,
    })
    with open(os.path.join(args.out, "builds.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["build", "uploaded_date", "expiration_date", "expired", "processing_state"])
        for b in builds:
            a = b["attributes"]
            w.writerow([a.get("version"), (a.get("uploadedDate") or "")[:10],
                        (a.get("expirationDate") or "")[:10],
                        a.get("expired"), a.get("processingState")])
    print(f"      {len(builds)} build(s)")

    # ---------- 4. Crash feedback ----------
    print("[4/5] Fetching crash feedback...")
    try:
        crashes = c.paged("/v1/betaFeedbackCrashSubmissions", {
            "filter[app]": args.app_id,
            "limit": 200,
        })
    except Exception as e:
        crashes = []
        print(f"      WARNING: crash feedback fetch failed: {e}")
    with open(os.path.join(args.out, "crashes.json"), "w", encoding="utf-8") as f:
        json.dump(crashes, f, ensure_ascii=False, indent=2)
    print(f"      {len(crashes)} crash submission(s)")

    # ---------- 5. Screenshot feedback ----------
    print("[5/5] Fetching screenshot feedback...")
    try:
        shots = c.paged("/v1/betaFeedbackScreenshotSubmissions", {
            "filter[app]": args.app_id,
            "limit": 200,
        })
    except Exception as e:
        shots = []
        print(f"      WARNING: screenshot feedback fetch failed: {e}")
    with open(os.path.join(args.out, "screenshots.json"), "w", encoding="utf-8") as f:
        json.dump(shots, f, ensure_ascii=False, indent=2)
    print(f"      {len(shots)} screenshot submission(s)")

    # ---------- Summary ----------
    lines = []
    lines.append("=" * 46)
    lines.append("TestFlight Beta Summary")
    lines.append("=" * 46)
    lines.append(f"Total testers          : {len(rows)}")

    st = Counter(r["state"] for r in rows)
    lines.append("")
    lines.append("By state:")
    for k, v in st.most_common():
        lines.append(f"  {k or '(empty)'}: {v}")

    it = Counter(r["invite_type"] for r in rows)
    lines.append("")
    lines.append("By invite type:")
    for k, v in it.most_common():
        lines.append(f"  {k or '(empty)'}: {v}")

    anon = sum(1 for r in rows if "anonymous" in r["email"])
    named = len(rows) - anon
    lines.append("")
    lines.append(f"Identifiable testers   : {named}")
    lines.append(f"Anonymous/public link  : {anon}")
    if rows:
        lines.append(f"Identifiable ratio     : {named / len(rows) * 100:.1f}%")

    inst = sum(1 for r in rows if r["state"] == "INSTALLED")
    acc = sum(1 for r in rows if r["state"] == "ACCEPTED")
    inv = sum(1 for r in rows if r["state"] == "INVITED")
    if named:
        lines.append("")
        lines.append("Identifiable tester funnel:")
        lines.append(f"  invited, not accepted : {inv}")
        lines.append(f"  accepted, not installed: {acc}")
        lines.append(f"  installed             : {inst}")
        lines.append(f"  install conversion    : {inst / named * 100:.1f}%")

    lines.append("")
    lines.append(f"Crash submissions      : {len(crashes)}")
    lines.append(f"Screenshot submissions : {len(shots)}")
    lines.append(f"Builds                 : {len(builds)}")

    txt = "\n".join(lines)
    with open(os.path.join(args.out, "summary.txt"), "w", encoding="utf-8") as f:
        f.write(txt)
    print()
    print(txt)
    print()
    print(f"All files saved to: {os.path.abspath(args.out)}")


if __name__ == "__main__":
    main()
