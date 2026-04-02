# Queue & Job Model Design

## Queue Technology: BullMQ (Redis-based)

**Why BullMQ:**
- Native Node.js — идеально для NestJS orchestrator
- Priority queues, delayed jobs, rate limiting
- Job events (progress, completed, failed)
- Built-in retry с backoff
- Dashboard (Bull Board) для мониторинга
- Battle-tested в production

**Why not RabbitMQ:**
- Overkill для MVP
- Нужен отдельный сервер
- BullMQ покрывает все потребности

---

## Queue Layout

```
Redis Queues:
├── clip:orchestrate       — main job queue (orchestrator listens)
├── clip:preprocess        — preprocessing worker
├── clip:alignment         — alignment worker (GPU)
├── clip:stylization       — stylization worker (GPU)
├── clip:animation         — animation worker (GPU)
├── clip:composition       — composition worker (CPU)
└── clip:notifications     — webhook/notification delivery
```

---

## Job State Machine

```
                    ┌──────────┐
                    │  queued   │
                    └─────┬────┘
                          │
                    ┌─────▼────────────┐
                    │  preprocessing   │
                    └─────┬────────────┘
                          │
                    ┌─────▼────────────┐
                    │ separating_vocals│
                    └─────┬────────────┘
                          │
                    ┌─────▼────────────┐
                    │ aligning_lyrics  │
                    └─────┬────────────┘
                          │
                    ┌─────▼────────────┐
                    │ stylizing_photo  │
                    └─────┬────────────┘
                          │
                    ┌─────▼────────────┐
                    │ generating_loop  │
                    └─────┬────────────┘
                          │
                    ┌─────▼────────────┐
                    │ composing_video  │
                    └─────┬────────────┘
                          │
                    ┌─────▼────────────┐
                    │   uploading      │
                    └─────┬────────────┘
                          │
                    ┌─────▼────────────┐
                    │   completed      │
                    └──────────────────┘

Any step can transition to:
  → failed (with error info)
  → cancelled (by user request)

From failed:
  → queued (retry from failed step)
```

**Note:** Steps 2+3 (vocal_separation + alignment) and step 4 (stylization) can run in **parallel** since they don't depend on each other:

```
preprocessing
    ├── vocal_separation → alignment  (audio branch)
    └── stylization                    (image branch)
         └── both complete → loop_generation → composition → upload
```

This saves ~30–40 sec latency.

---

## Job Data Model (BullMQ)

```typescript
interface ClipJobData {
  jobId: string;
  userId: string;
  songId: string;
  
  // S3 keys for inputs
  audioKey: string;
  photoKey: string;
  lyrics: string;
  
  // Options
  styleHint?: string;
  outputResolution: string;
  
  // For retry: which step to start from
  startFromStep?: StepName;
  
  // Cached artifact keys (populated during pipeline)
  artifacts: {
    normalizedAudio?: string;
    vocals?: string;
    facesJson?: string;
    audioFeatures?: string;
    alignmentJson?: string;
    stylizedKeyframe?: string;
    loopVideos?: string[];
    finalClip?: string;
    thumbnail?: string;
  };
}
```

---

## Retry Policy

### Per-step retry:

| Step | Max Retries | Backoff | Reason |
|------|-------------|---------|--------|
| preprocessing | 2 | fixed 5s | Transient I/O |
| vocal_separation | 2 | fixed 10s | GPU OOM |
| alignment | 2 | fixed 10s | Whisper timeout |
| stylization | 3 | exponential 10s, 30s, 60s | Generation quality |
| loop_generation | 3 | exponential 15s, 45s, 120s | Most failure-prone |
| composition | 2 | fixed 10s | FFmpeg errors |
| upload | 3 | exponential 5s, 15s, 45s | Network |

### Job-level retry:
- Max 3 retries per job
- User can trigger manual retry via API
- Manual retry can specify `from_step`

### Dead-letter handling:
- After all retries exhausted → job status = `failed`
- Job moves to `clip:dead-letter` queue for manual inspection
- Alert sent to monitoring (Slack/Telegram)
- Daily report of failed jobs

---

## Idempotency

### Request-level:
- `Idempotency-Key` header on POST `/jobs`
- Stored in `jobs.idempotency_key` (unique constraint)
- If duplicate key → return existing job (no re-creation)
- TTL: 24 hours (after which key can be reused)

### Step-level:
- Each step checks for existing artifacts before processing
- Cache key = `hash(input_artifacts + step_config)`
- If artifact exists in S3 and is valid → skip step, mark as `completed (cache_hit)`

### Worker-level:
- BullMQ job ID = `{jobId}:{stepName}:{attempt}`
- Prevents duplicate processing of same step

---

## Rerun from Specific Step

**Use case:** Loop generation produced bad quality → retry just loop + composition.

**Flow:**
1. User calls `POST /jobs/{id}/retry` with `{"from_step": "loop_generation"}`
2. Orchestrator:
   - Validates that all prior steps have completed artifacts
   - Resets steps from `loop_generation` onward to `pending`
   - Re-enqueues job starting from `loop_generation`
3. Prior artifacts (alignment, keyframe) are reused
4. Only GPU cost for loop_generation + CPU cost for composition is incurred

---

## Artifact Reuse / Caching

### Cross-job caching:

| Artifact | Cache Key | Reuse Scenario |
|----------|-----------|----------------|
| Alignment JSON | `hash(audio_mp3 + lyrics_text)` | Same song, different photo |
| Vocal separation | `hash(audio_mp3)` | Same song, different photo/lyrics |
| Stylized keyframe | `hash(photo + style_hint)` | Same photo, different song |

### Same-job caching:
- All artifacts stored in `s3://jobs/{job_id}/artifacts/`
- On retry, orchestrator checks artifact existence before re-running step
- `job_steps.cache_hit = true` when artifact reused

---

## Concurrency Control

```typescript
// BullMQ worker options per queue
const workerOptions = {
  'clip:preprocess':   { concurrency: 4 },   // CPU, lightweight
  'clip:alignment':    { concurrency: 2 },   // GPU, moderate
  'clip:stylization':  { concurrency: 2 },   // GPU, heavy
  'clip:animation':    { concurrency: 1 },   // GPU, very heavy
  'clip:composition':  { concurrency: 4 },   // CPU, moderate
};
```

### GPU scheduling:
- Animation worker gets priority on GPU
- Alignment and stylization share GPU with time-slicing
- If GPU queue depth > 10 → scale up worker instances

---

## Progress Reporting

Each worker reports progress to orchestrator:

```typescript
// Worker reports:
job.updateProgress({ step: 'alignment', percent: 60, message: 'Running Whisper...' });

// Orchestrator translates to overall progress:
// preprocessing: 0-10%
// vocal_separation: 10-20%
// alignment: 20-35%
// stylization: 35-50%
// loop_generation: 50-75%
// composition: 75-95%
// upload: 95-100%
```

Client polls `GET /jobs/{id}` for `progress_percent`.

---

## Monitoring Queues

**Bull Board** dashboard mounted at `/admin/queues`:
- View queue depth, processing rate, failed jobs
- Retry individual jobs
- Clean completed jobs

**Metrics exported to Prometheus:**
- `clip_queue_depth{queue="alignment"}` — jobs waiting
- `clip_job_duration_seconds{step="loop_generation"}` — processing time
- `clip_job_failures_total{step="stylization"}` — failure count
- `clip_jobs_completed_total` — total completed
