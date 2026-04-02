# Rendering & Cost Model

## Part 1: Final Video Rendering

### Technology Choice: FFmpeg (✅ RECOMMENDED)

**Why FFmpeg:**
- Industry standard, rock-solid reliability
- Handles all needed operations: loop, overlay, transitions, encoding
- Scripted via command-line, no runtime dependencies
- CPU-only (no GPU needed for composition)
- Deterministic output
- Extensive filter graph for effects

**Why NOT alternatives:**

| Alternative | Reason to skip |
|-------------|---------------|
| Remotion | Browser-based, complex setup, overkill for server-side |
| MoviePy | Python wrapper around FFmpeg, adds overhead/bugs without benefit |
| Custom OpenCV | Reinventing the wheel, slower than FFmpeg |
| After Effects | Not scriptable at scale, expensive license |

### FFmpeg Composition Pipeline

```bash
# 1. Create looped background (loop.mp4 repeated to fill song duration)
ffmpeg -stream_loop -1 -i loop.mp4 -t {song_duration} -c copy looped_bg.mp4

# 2. Apply camera motion per section (zoom/pan via filter_complex)
ffmpeg -i looped_bg.mp4 -filter_complex "
  [0:v]split=3[v1][v2][v3];
  [v1]trim=0:{verse_end},zoompan=z='min(zoom+0.0003,1.12)':d=1:s=1280x720[verse];
  [v2]trim={verse_end}:{chorus_end},zoompan=z='if(eq(on,1),1.12,max(zoom-0.0003,1.0))':d=1:s=1280x720[chorus];
  [v3]trim={chorus_end}:{total},zoompan=z='min(zoom+0.0002,1.08)':x='iw/2-(iw/zoom/2)+sin(on*0.01)*20':d=1:s=1280x720[bridge];
  [verse][chorus][bridge]concat=n=3:v=1:a=0[out]
" -map "[out]" motion_bg.mp4

# 3. Overlay particles
ffmpeg -i motion_bg.mp4 -i particles.mov -filter_complex "overlay=0:0:shortest=1" with_particles.mp4

# 4. Burn-in karaoke subtitles (ASS format for styled text)
ffmpeg -i with_particles.mp4 -vf "ass=karaoke.ass" with_karaoke.mp4

# 5. Merge audio
ffmpeg -i with_karaoke.mp4 -i song.mp3 -c:v copy -c:a aac -b:a 192k -shortest final.mp4
```

### Karaoke Rendering (ASS Subtitles)

**Why ASS (Advanced SubStation Alpha):**
- Rich styling: fonts, colors, outlines, shadows
- Karaoke timing tags (`\k`, `\kf`, `\ko`) for word-level highlight
- FFmpeg native support via `libass`
- No custom renderer needed

**ASS karaoke styling:**
```ass
[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720

[V4+ Styles]
Style: Karaoke,Arial,42,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,3,1,2,50,50,60,1
; Font: Arial 42pt, white text, cyan highlight, black outline (3px), shadow, bottom-center

[Events]
; Word-level karaoke with \kf (fill from left to right)
Dialogue: 0,0:00:12.34,0:00:15.67,Karaoke,,0,0,0,,{\kf16}С {\kf60}днём {\kf130}рождения {\kf127}тебя
```

**Two karaoke modes:**

1. **Word-level (primary):**
   - Each word highlights progressively (`\kf` tag)
   - Current word fills with highlight color left-to-right
   - Upcoming words are dimmed white
   - Sung words are fully highlighted

2. **Line-level (fallback):**
   - Current line is bright white
   - Next line is dimmed/grey
   - Line transitions at segment boundaries
   - Simpler but still looks good

**Karaoke display rules:**
- Always show 2 lines: current + next
- Safe margin: 60px from bottom
- Font: bold, with 3px black outline + 2px shadow for readability
- Current line: white → cyan/yellow fill as words are sung
- Next line: 50% opacity white
- Fade in/out between sections

### Output Specs

| Parameter | MVP Value | Premium |
|-----------|-----------|---------|
| Resolution | 1280×720 | 1920×1080 |
| Codec | H.264 (libx264) | H.264 |
| Pixel format | yuv420p | yuv420p |
| FPS | 30 | 30 |
| Bitrate | 3–4 Mbps | 6–8 Mbps |
| Audio codec | AAC | AAC |
| Audio bitrate | 192 kbps | 256 kbps |
| Container | mp4 (faststart) | mp4 (faststart) |
| File size (3 min) | ~70–90 MB | ~135–180 MB |

```bash
# Final encode command
ffmpeg -i composed.mp4 -i song.mp3 \
  -c:v libx264 -preset medium -crf 23 -profile:v high -level 4.1 \
  -pix_fmt yuv420p -r 30 \
  -c:a aac -b:a 192k -ar 44100 \
  -movflags +faststart \
  -t {duration} \
  final_clip.mp4
```

---

## Part 2: Cost Model

### Per-Clip Cost Breakdown (Recommended MVP — Variant 2)

| Step | Technology | GPU/CPU | Latency | Cost per clip | Notes |
|------|-----------|---------|---------|---------------|-------|
| Preprocessing | MediaPipe, FFmpeg | CPU | 5–10 sec | **$0.002** | Face detection, audio norm |
| Vocal Separation | Demucs v4 | GPU T4 | 15–20 sec | **$0.010** | Self-hosted |
| Alignment | Whisper large-v3 | GPU T4 | 20–30 sec | **$0.020** | Self-hosted |
| Stylization | SDXL + IP-Adapter | GPU A10 | 15–30 sec | **$0.050** | Self-hosted |
| Loop Generation (1 loop) | Kling API | API | 30–60 sec | **$0.200** | Managed API |
| Loop Generation (1 loop) | SVD self-hosted | GPU A10 | 30–90 sec | **$0.100** | Alternative |
| Composition | FFmpeg | CPU | 30–60 sec | **$0.020** | CPU rendering |
| Storage | S3 | — | — | **$0.010** | ~100MB per job |
| Transfer | CDN | — | — | **$0.005** | ~90MB output |
| **TOTAL (API loop)** | | | **2–4 min** | **$0.32** | |
| **TOTAL (self-hosted loop)** | | | **2–4 min** | **$0.22** | |

### With 2–3 loops (verse + chorus):

| Variant | Loops | Total Cost |
|---------|-------|-----------|
| Minimum (1 loop, API) | 1 | **$0.32** |
| Recommended (1 loop, self-hosted) | 1 | **$0.22** |
| Enhanced (2 loops, API) | 2 | **$0.52** |
| Enhanced (2 loops, self-hosted) | 2 | **$0.32** |
| Premium (3 loops, API) | 3 | **$0.72** |

### Monthly Cost at Scale

Assumption: 300 clips/day, 30 days/month = 9,000 clips/month

| Component | Per Clip | Monthly (9K clips) |
|-----------|---------|-------------------|
| GPU compute (self-hosted) | $0.18 | **$1,620** |
| GPU compute (API-based) | $0.28 | **$2,520** |
| CPU compute | $0.02 | **$180** |
| Storage (S3) | $0.01 | **$90** |
| CDN/Transfer | $0.005 | **$45** |
| PostgreSQL (managed) | — | **$50** |
| Redis (managed) | — | **$30** |
| Monitoring | — | **$30** |
| **Total (self-hosted GPU)** | **$0.22** | **$2,045** |
| **Total (API GPU)** | **$0.32** | **$2,945** |

### Infrastructure Cost (if self-hosted GPU)

| Resource | Spec | Monthly Cost |
|----------|------|-------------|
| GPU Server 1 (alignment+stylization) | 1× A10 24GB | $400–$600 |
| GPU Server 2 (animation) | 1× A10 24GB | $400–$600 |
| API Server | 4 vCPU, 8GB RAM | $40–$60 |
| CPU Workers | 8 vCPU, 16GB RAM | $60–$100 |
| PostgreSQL | 2 vCPU, 4GB RAM | $40–$60 |
| Redis | 2GB | $20–$30 |
| S3 Storage (1TB) | — | $20–$30 |
| **Total infra** | | **$980–$1,480/mo** |

At 9,000 clips/month, infra cost per clip ≈ $0.11–$0.16.
Plus per-clip compute ≈ $0.07–$0.10 (GPU time).
**Total: $0.18–$0.26 per clip with self-hosted.**

### What Drives Cost Most

```
Loop Generation:  ████████████████████████  55-65% of total
Stylization:      ███████                   12-18%
Alignment:        █████                     6-10%
Vocal Separation: ███                       3-5%
Composition:      ████                      5-8%
Storage/Transfer: ██                        3-5%
Preprocessing:    █                         1%
```

**Key insight:** Loop generation is >50% of cost. Optimizing this single step has the most impact:
- Fewer frames (5 sec vs 12 sec) → ~40% savings
- Lower resolution generation → upscale in post → ~30% savings
- Batch processing on dedicated GPU → better utilization → ~20% savings
- Self-hosted vs API → ~40% savings

---

## Ultra-Cheap Variant (Variant 1) Cost

| Step | Cost |
|------|------|
| Preprocessing | $0.002 |
| Alignment | $0.020 |
| Stylization | $0.050 |
| **NO loop generation** | $0.000 |
| Composition (Ken Burns + particles) | $0.015 |
| Storage + Transfer | $0.015 |
| **TOTAL** | **$0.10** |

Monthly at 9K clips: **$900 + infra ~$600 = $1,500/mo**

---

## Premium Variant (Variant 3) Cost

| Step | Cost |
|------|------|
| Scene planning (LLM) | $0.010 |
| Multiple keyframes (4–6) | $0.200 |
| Multiple video generations (4–6) | $1.500 |
| Editing/transitions | $0.050 |
| Composition | $0.030 |
| Storage + Transfer | $0.030 |
| **TOTAL** | **$1.82** |
| With retries (30% failure rate) | **$2.50–$4.00** |

Monthly at 9K clips: **$22,500–$36,000/mo** — clearly not MVP.
