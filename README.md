# youtube-summary-business

Pipeline harian untuk summarize episode podcast/video business & entrepreneurship dari 22 channel top dunia. Output ke Discord channel `#business-podcasts` dalam Bahasa Indonesia, format 4-section (Inti / Framework / Case Study / Actionable + rekomendasi 3-tier).

Target audience: founder/operator startup post-PMF (tim 20-50 orang), bukan pemula.

## Architecture

```
GitHub Actions (daily 8 AM WIB)
  └─> RSS feed scan per channel (lookback 7 hari)
      └─> Supadata API (metadata + transcript)
          └─> Claude Sonnet (4-section prompt)
              └─> Discord webhook (rich embed, per-channel color)
                  └─> state.json commit back to repo
```

Same architecture as `youtube-summary-ai` dan `youtube-mp3-downloader`, dengan prompt + filter yang disesuaikan untuk long-form business content.

## Setup

### 1. Create GitHub repo
```bash
gh repo create memorialindonesia/youtube-summary-business --private
cd youtube-summary-business
# copy semua file ini, commit, push
```

### 2. Create Discord channel & webhook
- Server > New Channel > `#business-podcasts`
- Channel settings > Integrations > Webhooks > New Webhook
- Copy webhook URL

### 3. Set GitHub secrets
Repository Settings > Secrets and variables > Actions > New secret:
- `SUPADATA_API_KEY` — same key as other pipelines
- `ANTHROPIC_API_KEY` — same key as other pipelines
- `DISCORD_WEBHOOK_URL` — new webhook untuk channel `#business-podcasts`

### 4. First run (soft launch)
Edit `config.yaml`: turunkan `initial_lookback_days: 7` menjadi `2` untuk first run agar tidak generate 100+ summaries sekaligus. Kembalikan ke `7` setelah state.json terisi.

Trigger manual run via Actions tab > "Run Business Podcast Summary" > Run workflow.

## Tuning

| Parameter | Default | Rationale |
|---|---|---|
| `initial_lookback_days` | 7 | Acquired upload bulanan, butuh window besar |
| `min_duration_seconds` | 600 | Skip clip/short (<10 min) |
| `max_videos_per_run` | 15 | Safety cap, ~$1.50/run di Claude API |
| `claude_model` | claude-sonnet-4-5 | Long context untuk transkrip 2-jam podcast |
| `supadata_lang` | auto | Mix English (mayoritas) + Bahasa Indonesia (Raymond, Felicia, Tom) |

## Review cadence

- **Week 1-2**: monitor mana yang Anda actually buka di Discord
- **Week 2**: drop channel dengan rasio skip-tier rekomendasi >70% (saya curigai: Helmy Yahya, Andika Sutoro berdasarkan content terbaru mereka)
- **Month 1**: review cost. Kalau lewat $100/bulan, kurangi `max_videos_per_run` atau drop Tier B (HBR, Stanford, Wharton — usually less actionable untuk operator)

## Budget estimate

22 channel × ~3 video/minggu × ~$0.05-0.10/summary = **$15-25/minggu = $60-100/bulan**

Plus Supadata Pro quota — kombinasi dengan 2 pipeline lain (saham 17 + AI 40 + business 22 = 79 channel) kemungkinan butuh upgrade ke tier lebih tinggi.

## Files

- `summarize.py` — main pipeline
- `config.yaml` — channels + settings
- `state.json` — auto-generated, tracks processed video IDs
- `.github/workflows/run.yml` — scheduler
- `requirements.txt` — Python deps

## Sister pipelines

- `youtube-summary-ai` — 40 channel AI/tools/automation, daily 9 AM WIB
- `youtube-mp3-downloader` — 17 channel saham Indonesia, 8 AM & 8 PM WIB
