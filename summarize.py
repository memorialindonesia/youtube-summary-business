#!/usr/bin/env python3
"""
YouTube Business Podcast Summary Pipeline.

PATCHED untuk fix RSS bozo errors:
1. Fetch RSS via requests + User-Agent header (bukan feedparser.parse(url) langsung).
   feedparser tanpa header sering kena 404 dari YouTube datacenter IPs.
2. Add 1.5 detik delay antar channel untuk hindari rate limit.
3. Better error reporting: distinguish 404 (channel ID salah) vs throttling.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import feedparser
import requests
import yaml
from anthropic import Anthropic

# ---------- Config & Env ----------

CONFIG_PATH = "config.yaml"
STATE_PATH = "state.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
RSS_HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

settings = config["settings"]
channels = config["channels"]

SUPADATA_API_KEY = os.environ["SUPADATA_API_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]

claude = Anthropic(api_key=ANTHROPIC_API_KEY)

# ---------- State ----------

def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"processed_video_ids": []}

def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

state = load_state()
processed_ids = set(state["processed_video_ids"])

# ---------- Helpers ----------

def hex_to_int(hex_str: str) -> int:
    return int(hex_str.lstrip("#"), 16)


def fetch_rss(channel_id: str) -> feedparser.FeedParserDict | None:
    """
    Fetch YouTube RSS via requests + UA header, parse via feedparser.
    Return None kalau channel invalid atau RSS gagal.
    """
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        r = requests.get(url, headers=RSS_HEADERS, timeout=20)
    except Exception as e:
        print(f"    network error: {e}")
        return None

    if r.status_code == 404:
        print(f"    HTTP 404 — channel_id invalid atau YouTube Music podcast (no RSS)")
        return None
    if r.status_code != 200:
        print(f"    HTTP {r.status_code} — possibly throttled, will retry next run")
        return None

    feed = feedparser.parse(r.content)
    if feed.bozo:
        print(f"    feed parse error: {feed.bozo_exception}")
        return None
    return feed


def get_video_metadata(video_id: str) -> dict:
    url = "https://api.supadata.ai/v1/youtube/video"
    headers = {"x-api-key": SUPADATA_API_KEY}
    params = {"id": video_id}
    r = requests.get(url, headers=headers, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def get_transcript(video_id: str) -> str:
    url = "https://api.supadata.ai/v1/youtube/transcript"
    headers = {"x-api-key": SUPADATA_API_KEY}
    params = {"videoId": video_id, "text": "true"}
    r = requests.get(url, headers=headers, params=params, timeout=120)
    r.raise_for_status()
    data = r.json()
    return data.get("content", "")

# ---------- Prompt ----------

SYSTEM_PROMPT = """Anda adalah analis konten bisnis untuk founder/operator startup post-PMF (tim 20-50 orang).
Tugas: summarize episode podcast/video bisnis dalam 4 bagian terstruktur, dalam Bahasa Indonesia
(English jargon dipertahankan: CAC, LTV, runway, burn rate, hiring loop, GTM, dst).

Audience profile:
- Operator post-PMF, BUKAN pemula
- Bottleneck: prioritisasi strategis, hiring/firing decisions, accountability tim, energy management
- Sudah paham fundamental startup, finance, ops — skip definisi dasar
- Apresiasi: tradeoff eksplisit, mental model konkret, case study dengan angka

Format output WAJIB persis seperti ini:

🎯 **INTI EPISODE**
[2-3 kalimat: siapa guest, topik utama, hook yang membuat ini worth-listening]

🧠 **FRAMEWORK & MENTAL MODEL**
[2-4 framework/konsep konkret yang bisa diaplikasikan. Setiap point 1-2 kalimat.
Contoh BAIK: "Naval's 'specific knowledge' framework — skill yang tidak bisa di-train via kurikulum, hanya via apprenticeship/hands-on."
Contoh BURUK: "Pentingnya kerja keras dan disiplin."
Skip framework yang generic/motivational filler.]

📖 **CASE STUDY / WAR STORY**
[1-2 cerita konkret dengan: angka, nama perusahaan, periode, hasil.
Contoh: "Brian Chesky (Airbnb) — Q1 2009 pivot dari air mattresses ke seluruh apartment listing setelah revenue stagnan di $200/week selama 6 bulan."
Skip section ini jika episode hanya teori tanpa cerita konkret — tulis "—".]

⚡ **ACTIONABLE UNTUK OPERATOR**
[2-3 hal spesifik yang founder/operator bisa lakukan minggu ini.
Contextual untuk post-PMF startup. Bukan saran generic.
Contoh BAIK: "Audit hiring funnel: kalau time-to-close >45 hari untuk senior IC, masalahnya di compensation benchmark atau interview loop, bukan sourcing."
Contoh BURUK: "Hire orang yang tepat."]

📊 **REKOMENDASI:** [pilih 1: 🔥 Tonton Sekarang / 📌 Bookmark / ⏭️ Skip]
[Satu kalimat alasan singkat. Jujur — kalau episode generic atau guest tidak deliver, kasih Skip.]

Aturan tambahan:
- TOTAL output maksimum 1800 karakter (constraint Discord embed)
- Jangan repeat judul episode atau nama guest di setiap section
- Tidak boleh hedging berlebihan ("mungkin", "bisa jadi", "tergantung")
- Jika konten clickbait atau tidak deliver value, kasih rekomendasi Skip dengan jujur"""


def summarize(channel_name: str, title: str, transcript: str) -> str:
    capped = transcript[:50000]
    msg = claude.messages.create(
        model=settings["claude_model"],
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Channel: {channel_name}\nJudul: {title}\n\nTranscript:\n{capped}"
        }]
    )
    return msg.content[0].text.strip()

# ---------- Discord ----------

def post_discord(channel: dict, video: dict, summary: str):
    embed = {
        "title": video["title"][:256],
        "url": video["link"],
        "description": summary[:4096],
        "color": hex_to_int(channel["color"]),
        "author": {"name": channel["name"]},
        "thumbnail": {"url": f"https://i.ytimg.com/vi/{video['video_id']}/hqdefault.jpg"},
        "footer": {"text": f"Published {video['published_str']} • duration {video.get('duration_min', '?')} min"}
    }
    payload = {"embeds": [embed]}
    r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=30)
    r.raise_for_status()

# ---------- Main ----------

def main():
    lookback = timedelta(days=settings["initial_lookback_days"])
    cutoff = datetime.now(timezone.utc) - lookback
    candidates = []
    rss_failed = []

    print(f"Lookback cutoff: {cutoff.isoformat()}")
    print(f"Channels: {len(channels)}\n")

    # Pass 1: discover candidates from RSS
    for channel in channels:
        print(f"  {channel['name']}")
        feed = fetch_rss(channel["id"])
        if feed is None:
            rss_failed.append(channel["name"])
            time.sleep(1.5)
            continue

        new_count = 0
        for entry in feed.entries:
            try:
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            except Exception:
                continue
            if published < cutoff:
                continue
            video_id = entry.yt_videoid
            if video_id in processed_ids:
                continue
            candidates.append({
                "channel": channel,
                "video_id": video_id,
                "title": entry.title,
                "link": entry.link,
                "published": published,
                "published_str": published.strftime("%Y-%m-%d"),
            })
            new_count += 1
        print(f"    → {new_count} new candidates")
        time.sleep(1.5)  # gentle delay antar channel

    if rss_failed:
        print(f"\n⚠ RSS failed for {len(rss_failed)} channels: {', '.join(rss_failed)}")
        print(f"  Run `python verify_channels.py` untuk diagnostik per-channel.\n")

    candidates.sort(key=lambda v: v["published"])

    cap = settings["max_videos_per_run"]
    if len(candidates) > cap:
        print(f"Total candidates: {len(candidates)} — capping at {cap} (oldest first)")
        candidates = candidates[:cap]
    else:
        print(f"Total candidates: {len(candidates)}")

    min_dur = settings["min_duration_seconds"]
    success = 0
    skipped_short = 0
    failed = 0

    for v in candidates:
        try:
            try:
                meta = get_video_metadata(v["video_id"])
                duration = meta.get("duration", 0)
            except Exception as e:
                print(f"  meta fail {v['video_id']}: {e} — proceeding without duration check")
                duration = None

            if duration and duration < min_dur:
                print(f"  ⏭ short ({duration}s): {v['title'][:60]}")
                processed_ids.add(v["video_id"])
                skipped_short += 1
                continue

            v["duration_min"] = duration // 60 if duration else "?"

            transcript = get_transcript(v["video_id"])
            if not transcript or len(transcript) < 500:
                print(f"  ⏭ no transcript: {v['title'][:60]}")
                processed_ids.add(v["video_id"])
                continue

            summary = summarize(v["channel"]["name"], v["title"], transcript)
            post_discord(v["channel"], v, summary)
            processed_ids.add(v["video_id"])
            success += 1
            print(f"  ✓ {v['channel']['name']}: {v['title'][:60]}")
            time.sleep(2)

        except Exception as e:
            failed += 1
            print(f"  ✗ {v['video_id']} failed: {e}")

    print(f"\nDone: {success} posted, {skipped_short} short-skipped, {failed} failed")

    state["processed_video_ids"] = sorted(processed_ids)
    save_state(state)

if __name__ == "__main__":
    main()
