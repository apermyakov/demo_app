# API Specification

## Base URL
```
https://api.brohit.com/clips/v1
```

---

## Endpoints

### 1. Create Clip Job

**POST** `/jobs`

Creates a new clip generation job.

**Request (multipart/form-data):**
```
song_id:    string (required) — ID песни в Бро.Хит
user_id:    string (required) — ID пользователя
lyrics:     string (required) — полный текст песни (UTF-8)
audio:      file   (required) — mp3 файл (max 20MB, max 5 min)
photo:      file   (required) — фото пользователя (jpg/png, max 10MB, min 512×512)
title:      string (optional) — название песни
style_hint: string (optional) — подсказка стиля ("birthday", "love", "party", etc.)
```

**Response 201:**
```json
{
  "job_id": "clip_01HX7Y8Z9ABC",
  "status": "queued",
  "created_at": "2026-04-02T12:00:00Z",
  "estimated_duration_sec": 180,
  "estimated_completion_sec": 240,
  "status_url": "/jobs/clip_01HX7Y8Z9ABC"
}
```

**Errors:**
- `400` — invalid input (missing fields, bad format, photo too small)
- `413` — file too large
- `429` — rate limit exceeded
- `503` — service overloaded

---

### 2. Get Job Status

**GET** `/jobs/{job_id}`

**Response 200:**
```json
{
  "job_id": "clip_01HX7Y8Z9ABC",
  "status": "generating_loop",
  "progress_percent": 55,
  "current_step": "loop_generation",
  "steps": [
    {"name": "preprocessing", "status": "completed", "duration_sec": 8},
    {"name": "vocal_separation", "status": "completed", "duration_sec": 18},
    {"name": "alignment", "status": "completed", "duration_sec": 25},
    {"name": "stylization", "status": "completed", "duration_sec": 22},
    {"name": "loop_generation", "status": "in_progress", "duration_sec": null},
    {"name": "composition", "status": "pending", "duration_sec": null},
    {"name": "upload", "status": "pending", "duration_sec": null}
  ],
  "created_at": "2026-04-02T12:00:00Z",
  "updated_at": "2026-04-02T12:02:15Z",
  "error": null
}
```

**Job statuses:**
- `queued` — в очереди
- `preprocessing` — обработка входных данных
- `separating_vocals` — отделение вокала
- `aligning_lyrics` — синхронизация текста
- `stylizing_photo` — стилизация фото
- `generating_loop` — генерация анимации
- `composing_video` — сборка финального видео
- `uploading` — загрузка результата
- `completed` — готово
- `failed` — ошибка

---

### 3. Get Job Result / Artifacts

**GET** `/jobs/{job_id}/result`

**Response 200 (when completed):**
```json
{
  "job_id": "clip_01HX7Y8Z9ABC",
  "status": "completed",
  "clip_url": "https://cdn.brohit.com/clips/clip_01HX7Y8Z9ABC/final.mp4",
  "clip_url_expires_at": "2026-04-09T12:00:00Z",
  "thumbnail_url": "https://cdn.brohit.com/clips/clip_01HX7Y8Z9ABC/thumb.jpg",
  "duration_sec": 185.4,
  "resolution": "1280x720",
  "file_size_bytes": 28400000,
  "cost": {
    "total_usd": 0.42,
    "breakdown": {
      "preprocessing": 0.001,
      "vocal_separation": 0.01,
      "alignment": 0.02,
      "stylization": 0.05,
      "loop_generation": 0.28,
      "composition": 0.02,
      "storage": 0.01
    }
  },
  "completed_at": "2026-04-02T12:03:45Z",
  "total_processing_sec": 225
}
```

**Response 202 (when not yet completed):**
```json
{
  "job_id": "clip_01HX7Y8Z9ABC",
  "status": "generating_loop",
  "message": "Job is still in progress"
}
```

---

### 4. Retry Job

**POST** `/jobs/{job_id}/retry`

Retries a failed job, optionally from a specific step.

**Request body (optional):**
```json
{
  "from_step": "loop_generation"
}
```

If `from_step` is omitted, retries from the failed step. Reuses cached artifacts from prior steps.

**Response 200:**
```json
{
  "job_id": "clip_01HX7Y8Z9ABC",
  "status": "queued",
  "retry_from": "loop_generation",
  "retry_count": 1
}
```

**Errors:**
- `400` — job is not in `failed` state, or invalid step name
- `404` — job not found
- `429` — too many retries (max 3)

---

### 5. Cancel Job

**POST** `/jobs/{job_id}/cancel`

Cancels a job that is in progress or queued.

**Response 200:**
```json
{
  "job_id": "clip_01HX7Y8Z9ABC",
  "status": "cancelled",
  "cancelled_at": "2026-04-02T12:01:30Z"
}
```

**Errors:**
- `400` — job already completed or cancelled
- `404` — job not found

---

### 6. List Jobs (for admin/debugging)

**GET** `/jobs?user_id={user_id}&status={status}&limit=20&offset=0`

**Response 200:**
```json
{
  "jobs": [...],
  "total": 142,
  "limit": 20,
  "offset": 0
}
```

---

## Webhook Callback (optional)

When job completes or fails, POST to configured callback URL:

```json
{
  "event": "job.completed",
  "job_id": "clip_01HX7Y8Z9ABC",
  "status": "completed",
  "clip_url": "https://cdn.brohit.com/clips/...",
  "timestamp": "2026-04-02T12:03:45Z"
}
```

---

## Authentication

MVP: API key в header `X-API-Key`.
Production: JWT / OAuth2 от Бро.Хит backend.

---

## Rate Limits

- Per user: 5 concurrent jobs
- Per API key: 100 jobs/hour
- Global: configurable based on GPU capacity

---

## Idempotency

Header `Idempotency-Key` для POST `/jobs`:
- Если job с таким ключом уже существует — вернуть существующий job
- TTL идемпотентности: 24 часа
