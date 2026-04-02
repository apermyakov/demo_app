# System Architecture: Clip Generation Service

## High-Level Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Client    │────▶│   Ingest API     │────▶│   Redis/BullMQ  │
│  (Бро.Хит)  │◀────│   (Node.js)      │     │   Job Queue     │
└─────────────┘     └──────────────────┘     └────────┬────────┘
                            │                          │
                    ┌───────▼────────┐                 │
                    │   PostgreSQL   │                 │
                    │   (Jobs, Meta) │                 │
                    └────────────────┘                 │
                                                       │
                    ┌──────────────────────────────────▼──────────┐
                    │              Orchestrator                    │
                    │         (Node.js BullMQ worker)             │
                    │                                              │
                    │  ┌─────────┐ ┌──────────┐ ┌──────────────┐ │
                    │  │ Step 1  │▶│ Step 2   │▶│   Step N     │ │
                    │  │Preproc  │ │Alignment │ │  Compose     │ │
                    │  └─────────┘ └──────────┘ └──────────────┘ │
                    └──────────────────────────────────────────────┘
                              │            │            │
                    ┌─────────▼──┐  ┌──────▼─────┐  ┌──▼──────────┐
                    │  Python    │  │  Python    │  │  Python     │
                    │  Workers   │  │  Workers   │  │  Workers    │
                    │ (GPU/CPU)  │  │ (GPU)      │  │ (CPU)       │
                    └────────────┘  └────────────┘  └─────────────┘
                              │            │            │
                    ┌─────────▼────────────▼────────────▼──────────┐
                    │              S3 Object Storage                │
                    │     (source files, artifacts, outputs)        │
                    └──────────────────────────────────────────────┘
```

---

## Service Breakdown

### A. Ingest API (Node.js / NestJS)

**Роль:** HTTP API, принимает запросы, валидирует, создаёт Job.

**Responsibilities:**
- REST endpoints для создания/управления клипами
- Валидация входных данных (формат фото, размер audio, наличие lyrics)
- Загрузка файлов в S3
- Создание записи Job в PostgreSQL
- Постановка задачи в BullMQ
- WebSocket/SSE для прогресса (опционально)

**Resource:** CPU only, 1–2 instances, stateless

### B. Orchestrator / Job Manager (Node.js BullMQ)

**Роль:** Управляет последовательностью шагов для каждого Job.

**Responsibilities:**
- Слушает BullMQ очередь `clip-jobs`
- Для каждого Job запускает шаги последовательно
- Отслеживает статус каждого шага
- Записывает progress в PostgreSQL
- При ошибке — retry logic или переход в failed
- Поддерживает rerun с конкретного шага
- Проверяет кэш артефактов перед запуском шага

**Sequence of Steps:**

```
1. PREPROCESSING     [CPU]  — валидация, нормализация audio, face detection
2. VOCAL_SEPARATION  [GPU]  — Demucs, отделение вокала
3. ALIGNMENT         [GPU]  — Whisper forced alignment
4. STYLIZATION       [GPU]  — photo → stylized cartoon keyframe
5. LOOP_GENERATION   [GPU]  — keyframe → animated loop 5-12 sec
6. COMPOSITION       [CPU]  — loop × N + karaoke + motion design → mp4
7. UPLOAD            [CPU]  — финальный mp4 → CDN
```

**CPU vs GPU breakdown:**

| Step | Type | Hardware | Latency | Cost |
|------|------|----------|---------|------|
| Preprocessing | CPU | 2 vCPU | 5–10 sec | ~$0.001 |
| Vocal Separation | GPU | T4/L4 | 15–20 sec | ~$0.01 |
| Alignment | GPU | T4/L4 | 20–30 sec | ~$0.02 |
| Stylization | GPU | A10/L40 | 15–30 sec | ~$0.05 |
| Loop Generation | GPU | A10/L40 | 30–90 sec | ~$0.15–$0.40 |
| Composition | CPU | 4 vCPU | 30–60 sec | ~$0.02 |
| Upload | CPU/Net | – | 5–10 sec | ~$0.01 |

**Total latency:** 2–4 минуты
**Total cost:** $0.25–$0.55

### C. Media Preprocessing Worker (Python, CPU)

**Functions:**
- Audio normalization (ffmpeg: loudnorm, sample rate 44.1kHz, mono for alignment)
- Audio duration extraction
- Photo validation (min resolution 512×512, face presence check)
- Face detection (MediaPipe / RetinaFace)
- Person segmentation (SAM / MediaPipe)
- Face ranking (by size, centrality, sharpness)
- Smart crop (center on faces, maintain aspect ratio)
- Waveform/energy extraction for motion design sync

**Output artifacts:**
- `normalized_audio.wav`
- `faces.json` — detected faces with bounding boxes and scores
- `cropped_photo.png` — reframed photo
- `audio_features.json` — BPM, energy curve, section boundaries

### D. Karaoke Alignment Worker (Python, GPU)

See [02-karaoke-alignment.md](./02-karaoke-alignment.md)

**Output:** `alignment.json`

### E. Visual Stylization Worker (Python, GPU)

**Functions:**
- Generate stylized cartoon keyframe from user photo
- Preserve identity at acceptable level (not photorealistic)
- Handle 1–4 people
- Generate scene prompt based on detected people and context

**Tech stack:**
- SDXL / Flux.1 with IP-Adapter for identity preservation
- ControlNet (openpose/depth) for composition
- Custom prompt engineering for consistent style

**Output:** `stylized_keyframe.png` (1280×720)

### F. Loop Animation Worker (Python, GPU)

**Functions:**
- Generate 5–12 second animated loop from keyframe
- Ensure seamless looping (or near-seamless with crossfade)
- Generate 1–3 variants if budget allows

**Tech stack:**
- Stable Video Diffusion (SVD) — self-hosted
- OR Kling API / MiniMax API — managed
- Post-processing: crossfade ends for seamless loop

**Output:** `loop_001.mp4`, `loop_002.mp4` (optional)

### G. Video Composition Worker (Python + FFmpeg, CPU)

**Functions:**
- Assemble full-length video from loops
- Apply section-based variations (zoom, pan, color grade)
- Render karaoke overlay (ASS/SRT → burn-in)
- Add motion design layers (particles, light, grain)
- Mix audio track
- Export final mp4

**Output:** `final_clip.mp4`

### H. Storage (S3-compatible)

**Layout:**
```
s3://brohit-clips/
├── jobs/{job_id}/
│   ├── input/
│   │   ├── original_photo.jpg
│   │   ├── audio.mp3
│   │   └── lyrics.txt
│   ├── artifacts/
│   │   ├── normalized_audio.wav
│   │   ├── vocals.wav
│   │   ├── faces.json
│   │   ├── audio_features.json
│   │   ├── alignment.json
│   │   ├── stylized_keyframe.png
│   │   ├── loop_001.mp4
│   │   └── loop_002.mp4
│   └── output/
│       ├── final_clip.mp4
│       ├── thumbnail.jpg
│       └── metadata.json
```

### I. Monitoring / Cost Control

**Stack:**
- Prometheus + Grafana для метрик
- Structured logging (JSON) → ELK или Loki
- Per-job cost tracking в PostgreSQL

**Ключевые метрики:**
- Cost per clip (разбивка по шагам)
- Job success rate
- Per-step latency (p50, p95, p99)
- GPU utilization
- Queue depth
- Error rate по шагам

---

## Communication Patterns

### Sync (API → Client):
- REST: create job, get status, get result
- Optional: WebSocket for real-time progress

### Async (Orchestrator → Workers):
- BullMQ queues per worker type:
  - `queue:preprocessing`
  - `queue:alignment`
  - `queue:stylization`
  - `queue:animation`
  - `queue:composition`
- Each worker pulls from its queue, processes, uploads artifacts to S3, reports completion

### Orchestrator flow:
```
Orchestrator receives job
→ check cache for each step
→ if artifact exists and is valid → skip step
→ else → enqueue step to worker queue
→ wait for worker completion (BullMQ job event)
→ update PostgreSQL status
→ proceed to next step
→ on all steps complete → mark job completed
```

---

## Deployment (MVP)

```
Docker Compose (dev/staging):
├── api          — Node.js, port 3000
├── orchestrator — Node.js, BullMQ worker
├── worker-preprocess  — Python, CPU
├── worker-alignment   — Python, GPU (T4)
├── worker-stylize     — Python, GPU (A10)
├── worker-animate     — Python, GPU (A10)
├── worker-compose     — Python + FFmpeg, CPU
├── postgres     — PostgreSQL 16
├── redis        — Redis 7
└── minio        — S3-compatible storage (dev only)
```

**Production:**
- API: 2 instances behind LB
- Orchestrator: 1–2 instances
- GPU workers: auto-scaling pool (RunPod / Vast.ai / self-hosted)
- CPU workers: 2–4 instances
- Managed PostgreSQL
- Managed Redis
- S3 / Selectel Object Storage
