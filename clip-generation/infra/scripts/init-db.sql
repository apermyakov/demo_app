-- Clip Generation Service: Database Schema
-- PostgreSQL 16

-- ─── Jobs ──────────────────────────────────────────────────

CREATE TABLE jobs (
    id              VARCHAR(26) PRIMARY KEY,
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

-- ─── Job Steps ─────────────────────────────────────────────

CREATE TABLE job_steps (
    id          BIGSERIAL PRIMARY KEY,
    job_id      VARCHAR(26) NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    step_name   VARCHAR(32) NOT NULL,
    step_order  SMALLINT NOT NULL,
    status      VARCHAR(16) NOT NULL DEFAULT 'pending',

    worker_id   VARCHAR(64),
    queue_name  VARCHAR(64),

    artifacts   JSONB DEFAULT '[]',

    queued_at   TIMESTAMPTZ,
    started_at  TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    duration_sec REAL,

    attempt     SMALLINT DEFAULT 1,
    error_code  VARCHAR(64),
    error_message TEXT,

    cost_usd    NUMERIC(8,4),

    cache_hit   BOOLEAN DEFAULT FALSE,
    cache_key   VARCHAR(256),

    UNIQUE(job_id, step_name, attempt)
);

CREATE INDEX idx_job_steps_job_id ON job_steps(job_id);
CREATE INDEX idx_job_steps_status ON job_steps(status);

-- ─── Media Assets ──────────────────────────────────────────

CREATE TABLE media_assets (
    id          BIGSERIAL PRIMARY KEY,
    job_id      VARCHAR(26) NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    asset_type  VARCHAR(32) NOT NULL,
    s3_key      VARCHAR(512) NOT NULL,
    s3_bucket   VARCHAR(128) NOT NULL DEFAULT 'brohit-clips',

    mime_type   VARCHAR(64),
    file_size   BIGINT,
    width       INT,
    height      INT,
    duration_sec REAL,

    content_hash VARCHAR(64),

    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at  TIMESTAMPTZ
);

CREATE INDEX idx_media_assets_job_id ON media_assets(job_id);
CREATE INDEX idx_media_assets_type ON media_assets(asset_type);
CREATE INDEX idx_media_assets_hash ON media_assets(content_hash);

-- ─── Karaoke Alignments ───────────────────────────────────

CREATE TABLE karaoke_alignments (
    id              BIGSERIAL PRIMARY KEY,
    job_id          VARCHAR(26) NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    song_id         VARCHAR(64) NOT NULL,

    alignment_method VARCHAR(32) NOT NULL,
    confidence      REAL,

    alignment_json  JSONB NOT NULL,

    audio_hash      VARCHAR(64),
    lyrics_hash     VARCHAR(64),

    word_count      INT,
    segment_count   INT,
    language        VARCHAR(8) DEFAULT 'ru',

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_karaoke_song_id ON karaoke_alignments(song_id);
CREATE UNIQUE INDEX idx_karaoke_cache ON karaoke_alignments(audio_hash, lyrics_hash);

-- ─── Render Outputs ───────────────────────────────────────

CREATE TABLE render_outputs (
    id              BIGSERIAL PRIMARY KEY,
    job_id          VARCHAR(26) NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,

    resolution      VARCHAR(16) NOT NULL,
    codec           VARCHAR(16) DEFAULT 'h264',
    bitrate_kbps    INT,
    fps             SMALLINT DEFAULT 30,
    format          VARCHAR(8) DEFAULT 'mp4',

    clip_s3_key     VARCHAR(512) NOT NULL,
    thumbnail_s3_key VARCHAR(512),

    duration_sec    REAL NOT NULL,
    file_size       BIGINT NOT NULL,
    render_time_sec REAL,

    loop_count      SMALLINT,
    loop_duration_sec REAL,
    karaoke_mode    VARCHAR(16),

    cdn_url         VARCHAR(512),
    cdn_url_expires_at TIMESTAMPTZ,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_render_outputs_job_id ON render_outputs(job_id);

-- ─── Cost Logs ────────────────────────────────────────────

CREATE TABLE cost_logs (
    id          BIGSERIAL PRIMARY KEY,
    job_id      VARCHAR(26) NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    step_name   VARCHAR(32) NOT NULL,

    gpu_type    VARCHAR(32),
    gpu_seconds REAL,
    cpu_seconds REAL,

    api_provider VARCHAR(32),
    api_cost_usd NUMERIC(8,4),

    compute_cost_usd NUMERIC(8,4),
    storage_cost_usd NUMERIC(8,4),
    total_cost_usd   NUMERIC(8,4),

    bytes_downloaded BIGINT DEFAULT 0,
    bytes_uploaded   BIGINT DEFAULT 0,

    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_cost_logs_job_id ON cost_logs(job_id);
CREATE INDEX idx_cost_logs_step ON cost_logs(step_name);
CREATE INDEX idx_cost_logs_date ON cost_logs(created_at);

-- ─── Monitoring Views ─────────────────────────────────────

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

CREATE VIEW v_step_failure_rate AS
SELECT
    step_name,
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE status = 'failed') AS failed,
    ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'failed') / NULLIF(COUNT(*), 0), 1) AS fail_pct
FROM job_steps
WHERE queued_at > NOW() - INTERVAL '24 hours'
GROUP BY step_name;
