#!/usr/bin/env python3
"""
verify_channels.py

Standalone verifier — pastikan setiap channel_id di config.yaml masih
return RSS feed yang valid. Run via:
  python verify_channels.py

Atau via GitHub Actions (lihat .github/workflows/verify.yml).

Output: tabel status per channel + saran fix.
"""

import sys
import time
import yaml
import requests
import feedparser

CONFIG_PATH = "config.yaml"

# Pakai User-Agent browser supaya YouTube tidak treat sebagai bot
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}


def check_channel(name: str, cid: str) -> dict:
    """Return status dict per channel."""
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
    except Exception as e:
        return {"name": name, "id": cid, "status": "NETERR", "detail": str(e), "entries": 0}

    if r.status_code == 404:
        return {
            "name": name, "id": cid, "status": "404",
            "detail": "Channel ID tidak exist atau ini YouTube Music podcast channel (tidak ada RSS)",
            "entries": 0,
        }
    if r.status_code != 200:
        return {
            "name": name, "id": cid, "status": f"HTTP {r.status_code}",
            "detail": "Transient — coba retry, atau YouTube throttling",
            "entries": 0,
        }

    feed = feedparser.parse(r.content)
    if feed.bozo:
        return {
            "name": name, "id": cid, "status": "BOZO",
            "detail": str(feed.bozo_exception)[:80],
            "entries": 0,
        }

    # Ambil channel title dari feed untuk verify identitas
    actual_title = feed.feed.get("title", "?")
    return {
        "name": name, "id": cid, "status": "OK",
        "detail": f"title='{actual_title}'",
        "entries": len(feed.entries),
    }


def main():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    channels = cfg.get("channels", [])
    if not channels:
        print("No channels in config")
        sys.exit(1)

    print(f"\nVerifying {len(channels)} channels...\n")
    print(f"{'STATUS':10} {'ENTRIES':8} {'NAME':40} {'ID':28} DETAIL")
    print("-" * 130)

    results = []
    for ch in channels:
        result = check_channel(ch["name"], ch["id"])
        results.append(result)
        icon = "✓" if result["status"] == "OK" else "✗"
        print(f"{icon} {result['status']:8} {result['entries']:<8} {ch['name'][:38]:40} {ch['id']:28} {result['detail'][:50]}")
        time.sleep(1.5)  # gentle, hindari rate limit

    print()
    ok = sum(1 for r in results if r["status"] == "OK")
    fail = len(results) - ok
    print(f"Result: {ok} OK, {fail} fail")

    if fail > 0:
        print("\n=== ACTION ITEMS ===")
        for r in results:
            if r["status"] != "OK":
                print(f"  [{r['status']}] {r['name']} ({r['id']})")
                print(f"           → buka https://www.youtube.com/channel/{r['id']}")
                print(f"           → atau cari handle yang benar di YouTube, View Source, ambil channelId")
        sys.exit(1)


if __name__ == "__main__":
    main()
