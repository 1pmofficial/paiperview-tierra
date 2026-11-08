#!/usr/bin/env python3
"""
Fetch PPV streams from api.ppv.st, resolve each via Playwright batch,
write an M3U playlist with names, logos, and start/end times.

Usage:
    python3 fetch-streams.py [output.m3u]
"""
import sys
import os
import json
import re
import gzip
import time
import subprocess
import urllib.request
from datetime import datetime, timezone

API = "https://api.ppv.st/api/streams"
OUT = sys.argv[1] if len(sys.argv) > 1 else "ppv-streams.m3u"
RESOLVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resolve-island.py")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
)

CLIENT_HEADERS = {
    "User-Agent": UA,
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


# ---------- HTTP ----------

def http_text(url):
    req = urllib.request.Request(url, headers=CLIENT_HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        if (r.headers.get("Content-Encoding") or "").lower() == "gzip":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", "replace")


def http_json(url):
    return json.loads(http_text(url))


# ---------- Normalisation ----------

def normalise(data):
    """
    Response shape:
        { "streams": [ { "category": ..., "streams": [ <channel>, ... ] }, ... ] }
    """
    out = []
    for cat in data.get("streams", []):
        cat_name = cat.get("category") or cat.get("name") or "PPV"
        for s in cat.get("streams", []):
            out.append({
                "name":  s.get("name") or "Unknown",
                "logo":  s.get("poster") or "",
                "embed": s.get("iframe") or "",
                "code":  s.get("uri_name") or str(s.get("id") or ""),
                "group": s.get("category_name") or cat_name,
                "source_tag": s.get("source_tag") or "",
                "always_live": bool(s.get("always_live")),
                "starts_at": int(s.get("starts_at") or 0),
                "ends_at":   int(s.get("ends_at") or 0),
                "viewers": s.get("viewers") or "",
                "id": s.get("id"),
            })
    return out


# ---------- Batch resolve via Playwright ----------

def batch_resolve(channels):
    """Feed every embed URL to resolve-island.py in one shot, return list of m3u8s."""
    urls = [ch["embed"] for ch in channels if ch["embed"]]
    if not urls:
        return []
    print(f"  Spawning one browser for {len(urls)} channels ...")
    r = subprocess.run(
        [sys.executable, RESOLVER],
        input="\n".join(urls) + "\n",
        capture_output=True,
        text=True,
        timeout=60 + 40 * len(urls),   # generous
    )
    if r.returncode != 0:
        print("  resolver stderr:", r.stderr[-2000:], file=sys.stderr)
        return [f"ERROR: resolver exit {r.returncode}"] * len(channels)

    lines = r.stdout.strip().splitlines()
    if len(lines) != len(channels):
        # pad/truncate so indexes line up
        lines = (lines + ["ERROR: missing"] * len(channels))[:len(channels)]
    return lines


# ---------- Main ----------

def fmt_time(ts):
    if not ts:
        return "24/7"
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def main():
    print(f"Fetching {API} ...")
    data = http_json(API)
    channels = normalise(data)
    print(f"Resolving {len(channels)} channels ...")

    m3u8_list = batch_resolve(channels)

    lines = ["#EXTM3U"]
    ok = bad = 0
    for ch, m3u8 in zip(channels, m3u8_list):
        if m3u8.startswith("ERROR"):
            bad += 1
            print(f"  xx  {ch['name']}: {m3u8}")
            continue
        ok += 1
        print(f"  ok  {ch['name']}")
        when = fmt_time(ch["starts_at"]) if not ch["always_live"] \
               else "24/7"
        if not ch["always_live"] and ch["ends_at"]:
            when = f"{fmt_time(ch['starts_at'])} -> {fmt_time(ch['ends_at'])}"
        lines.append(f"# {ch['name']} | {when} | {ch['source_tag']} | viewers={ch['viewers']}")
        lines.append(
            f'#EXTINF:-1 tvg-id="{ch["code"]}" tvg-name="{ch["name"]}" '
            f'tvg-logo="{ch["logo"]}" group-title="{ch["group"]}",{ch["name"]}'
        )
        lines.append(m3u8)

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nWrote {OUT} — {ok} ok, {bad} failed.")


if __name__ == "__main__":
    main()
