# Database Schema Draft

## RDBMS: PostgreSQL 16

---

## Tables

### 1. jobs

Main job tracking table.

```sql
CREATE TABLE jobs (
    id              VARCHAR(26) PRIMARY KEY,  -- ULID: clip_01HX7Y8Z9ABC
    user_id         VARCHAR(64) NOT NULL,
    song_id         VARCHAR(64) NOT NULL,
    title           VARCHAR(256),
    status          VARCHAR(32) NOT NULL DEFAULT 'queued',
    current_step    VARCHAR(32),
    progress_percent SMALLINT DEFAULT 0,
    
    -- Input references (S3 keys)
    audio_key       VARCHAR(512) NOT NULL,
    photo_key       VARCHAR(512) NOT NULL,
    lyrics_text     TEXT NOT NULL,
    
    -- Configuration
    style_hint      VARCHAR(64),
    output_resolution VARCHAR(16) DEFAULT '1280x720',
    
    -- Result
    output_clip_key VARCHAR(512),
    output_thumbnail_key VARCHAR(512),
    clip_duration_sec REAL,
    clip_file_size  BIGINT,
    
    -- Retry / idempotency
    idempotency_key VARCHAR(128) UNIQUE,
    retry_count     SMALLINT DEFAULT 0,
    max_retries     SMALLINT DEFAULT 3,
    retry_from_step VARCHAR(32),
    
    -- Error info
    error_code      VARCHAR(64),
    error_message   TEXT,
    error_step      VARCHAR(32),
    
    -- Cost tracking
    estimated_cost_usd NUMERIC(8,4),
    actual_cost_usd    NUMERIC(8,4),
    
    -- Timestamps
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    cancelled_at    TIMESTAMPTZ
);

CREATE INDEX idx_jobs_user_id ON jobs(user_id);
CREATE INDEX idx_jobs_song_id ON jobs(song_id);
CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_created_at ON jobs(created_at DESC);
```

**Status enum values:**
`queued`, `preprocessing`, `separating_vocals`, `aligning_lyrics`, `stylizing_photo`, `generating_loop`, `composing_video`, `uploading`, `completed`, `failed`, `cancelled`

---

### 2. job_steps

Individual step tracking within a job.

```sql
CREATE TABLE job_steps (
    id          BIGSERIAL PRIMARY KEY,
    job_id      VARCHAR(26) NOT NULL REFERENCES jobs(id),
    step_name   VARCHAR(32) NOT NULL,
    step_order  SMALLINT NOT NULL,
    status      VARCHAR(16) NOT NULL DEFAULT 'pending',
    
    -- Worker info
    worker_id   VARCHAR(64),
    queue_name  VARCHAR(64),
    
    -- Artifacts produced by this step (S3 keys)
    artifacts   JSONB DEFAULT '[]',
    
    -- Timing
    queued_at   TIMESTAMPTZ,
    started_at  TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    duration_sec REAL,
    
    -- Retry
    attempt     SMALLINT DEFAULT 1,
    error_code  VARCHAR(64),
    error_message TEXT,
    
    -- Cost
    cost_usd    NUMERIC(8,4),
    
    -- Cache
    cache_hit   BOOLEAN DEFAULT FALSE,
    cache_key   VARCHAR(256),
    
    UNIQUE(job_id, step_name, attempt)
);

CREATE INDEX idx_job_steps_job_id ON job_steps(job_id);
CREATE INDEX idx_job_steps_status ON job_steps(status);
```

**Step names:** `preprocessing`, `vocal_separation`, `alignment`, `stylization`, `loop_generation`, `composition`, `upload`

**Step statuses:** `pending`, `queued`, `running`, `completed`, `failed`, `skipped`

---

### 3. media_assets

Tracks all uploaded and generated media artifacts.

```sql
CREATE TABLE media_assets (
    id          BIGSERIAL PRIMARY KEY,
    job_id      VARCHAR(26) NOT NULL REFERENCES jobs(id),
    asset_type  VARCHAR(32) NOT NULL,    -- 'input_photo', 'input_audio', 'vocals', 'keyframe', 'loop', 'final_clip', etc.
    s3_key      VARCHAR(512) NOT NULL,
    s3_bucket   VARCHAR(128) NOT NULL DEFAULT 'brohit-clips',
    
    -- Metadata
    mime_type   VARCHAR(64),
    file_size   BIGINT,
    width       INT,
    height      INT,
    duration_sec REAL,
    
    -- Hash for cache dedup
    content_hash VARCHAR(64),
    
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at  TIMESTAMPTZ          -- for temporary artifacts
);

CREATE INDEX idx_media_assets_job_id ON media_assets(job_id);
CREATE INDEX idx_media_assets_type ON media_assets(asset_type);
CREATE INDEX idx_media_assets_hash ON media_assets(content_hash);
```

---

### 4. karaoke_alignments

Stores alignment data separately for reuse.

```sql
CREATE TABLE karaoke_alignments (
    id              BIGSERIAL PRIMARY KEY,
    job_id          VARCHAR(26) NOT NULL REFERENCES jobs(id),
    song_id         VARCHAR(64) NOT NULL,
    
    -- Method used
    alignment_method VARCHAR(32) NOT NULL,  -- 'whisper_forced', 'line_level', 'even_split'
    confidence      REAL,
    
    -- The actual alignment data
    alignment_json  JSONB NOT NULL,
    
    -- Source info for caching
    audio_hash      VARCHAR(64),       -- hash of normalized audio
    lyrics_hash     VARCHAR(64),       -- hash of lyrics text
    
    -- Stats
    word_count      INT,
    segment_count   INT,
    language        VARCHAR(8) DEFAULT 'ru',
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_karaoke_song_id ON karaoke_alignments(song_id);
CREATE UNIQUE INDEX idx_karaoke_cache ON karaoke_alignments(audio_hash, lyrics_hash);
```

---

### 5. render_outputs

Final rendered clips with metadata.

```sql
CREATE TABLE render_outputs (
    id              BIGSERIAL PRIMARY KEY,
    job_id          VARCHAR(26) NOT NULL REFERENCES jobs(id),
    
    -- Output specs
    resolution      VARCHAR(16) NOT NULL,  -- '1280x720'
    codec           VARCHAR(16) DEFAULT 'h264',
    bitrate_kbps    INT,
    fps             SMALLINT DEFAULT 30,
    format          VARCHAR(8) DEFAULT 'mp4',
    
    -- Files
    clip_s3_key     VARCHAR(512) NOT NULL,
    thumbnail_s3_key VARCHAR(512),
    
    -- Stats
    duration_sec    REAL NOT NULL,
    file_size       BIGINT NOT NULL,
    render_time_sec REAL,
    
    -- Composition details
    loop_count      SMALLINT,         -- how many loops used
    loop_duration_sec REAL,           -- duration of single loop
    karaoke_mode    VARCHAR(16),      -- 'word_level', 'line_level'
    
    -- CDN
    cdn_url         VARCHAR(512),
    cdn_url_expires_at TIMESTAMPTZ,
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_render_outputs_job_id ON render_outputs(job_id);
```

---

### 6. cost_logs

Per-step cost tracking for monitoring and optimization.

```sql
CREATE TABLE cost_logs (
    id          BIGSERIAL PRIMARY KEY,
    job_id      VARCHAR(26) NOT NULL REFERENCES jobs(id),
    step_name   VARCHAR(32) NOT NULL,
    
    -- Resource usage
    gpu_type    VARCHAR(32),          -- 'T4', 'A10', 'L40', null for CPU
    gpu_seconds REAL,
    cpu_seconds REAL,
    
    -- External API costs
    api_provider VARCHAR(32),         -- 'kling', 'runway', 'replicate', null
    api_cost_usd NUMERIC(8,4),
    
    -- Computed cost
    compute_cost_usd NUMERIC(8,4),
    storage_cost_usd NUMERIC(8,4),
    total_cost_usd   NUMERIC(8,4),
    
    -- Network
    bytes_downloaded BIGINT DEFAULT 0,
    bytes_uploaded   BIGINT DEFAULT 0,
    
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_cost_logs_job_id ON cost_logs(job_id);
CREATE INDEX idx_cost_logs_step ON cost_logs(step_name);
CREATE INDEX idx_cost_logs_date ON cost_logs(created_at);
```

---

## Views (useful for monitoring)

```sql
-- Average cost per clip over last 24h
CREATE VIEW v_avg_clip_cost AS
SELECT 
    DATE_TRUNC('hour', j.created_at) AS hour,
    COUNT(*) AS clips,
    AVG(j.actual_cost_usd) AS avg_cost,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY j.actual_cost_usd) AS p95_cost
FROM jobs j
WHERE j.status = 'completed' 
  AND j.created_at > NOW() - INTERVAL '24 hours'
GROUP BY 1;

-- Step failure rates
CREATE VIEW v_step_failure_rate AS
SELECT 
    step_name,
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE status = 'failed') AS failed,
    ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'failed') / COUNT(*), 1) AS fail_pct
FROM job_steps
WHERE queued_at > NOW() - INTERVAL '24 hours'
GROUP BY step_name;
```

---

## Migrations

Use **node-pg-migrate** or **Prisma** for schema migrations.

Migration files should be stored in:
```
backend/src/db/migrations/
├── 001_create_jobs.sql
├── 002_create_job_steps.sql
├── 003_create_media_assets.sql
├── 004_create_karaoke_alignments.sql
├── 005_create_render_outputs.sql
└── 006_create_cost_logs.sql
```
