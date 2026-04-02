import { Injectable, BadRequestException } from '@nestjs/common';
import { ulid } from 'ulid';
import { CreateJobDto, JobResponse, JobResultResponse } from './dto';
import { db } from '../db/client';
import { clipQueue } from '../queues/clip.queue';
import { STEP_NAMES, JOB_STATUSES } from '../../../shared/constants/steps';

@Injectable()
export class JobsService {
  async createJob(
    dto: CreateJobDto,
    audioFile: Express.Multer.File,
    photoFile: Express.Multer.File,
    idempotencyKey?: string,
  ) {
    // Check idempotency
    if (idempotencyKey) {
      const existing = await db.query(
        'SELECT id, status FROM jobs WHERE idempotency_key = $1',
        [idempotencyKey],
      );
      if (existing.rows[0]) {
        return { job_id: existing.rows[0].id, status: existing.rows[0].status, deduplicated: true };
      }
    }

    const jobId = `clip_${ulid()}`;

    // TODO: Upload files to S3 and get keys
    const audioKey = `jobs/${jobId}/input/audio.mp3`;
    const photoKey = `jobs/${jobId}/input/photo.jpg`;

    // Insert job record
    await db.query(
      `INSERT INTO jobs (id, user_id, song_id, title, status, audio_key, photo_key, lyrics_text, style_hint, idempotency_key)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)`,
      [jobId, dto.user_id, dto.song_id, dto.title, 'queued', audioKey, photoKey, dto.lyrics, dto.style_hint, idempotencyKey],
    );

    // Create step records
    for (let i = 0; i < STEP_NAMES.length; i++) {
      await db.query(
        `INSERT INTO job_steps (job_id, step_name, step_order, status)
         VALUES ($1, $2, $3, 'pending')`,
        [jobId, STEP_NAMES[i], i],
      );
    }

    // Enqueue to orchestrator
    await clipQueue.add('process-clip', { jobId }, { jobId });

    return {
      job_id: jobId,
      status: 'queued',
      created_at: new Date().toISOString(),
    };
  }

  async getJobStatus(jobId: string): Promise<JobResponse | null> {
    const jobResult = await db.query('SELECT * FROM jobs WHERE id = $1', [jobId]);
    if (!jobResult.rows[0]) return null;

    const job = jobResult.rows[0];
    const stepsResult = await db.query(
      'SELECT step_name, status, duration_sec FROM job_steps WHERE job_id = $1 ORDER BY step_order',
      [jobId],
    );

    return {
      job_id: job.id,
      status: job.status,
      progress_percent: job.progress_percent,
      current_step: job.current_step,
      steps: stepsResult.rows.map((s: any) => ({
        name: s.step_name,
        status: s.status,
        duration_sec: s.duration_sec,
      })),
      created_at: job.created_at,
      updated_at: job.updated_at,
      error: job.error_code
        ? { code: job.error_code, message: job.error_message }
        : null,
    };
  }

  async getJobResult(jobId: string): Promise<JobResultResponse | null> {
    const jobResult = await db.query('SELECT * FROM jobs WHERE id = $1', [jobId]);
    if (!jobResult.rows[0]) return null;

    const job = jobResult.rows[0];

    if (job.status !== 'completed') {
      return { job_id: job.id, status: job.status };
    }

    const costResult = await db.query(
      'SELECT step_name, total_cost_usd FROM cost_logs WHERE job_id = $1',
      [jobId],
    );
    const breakdown: Record<string, number> = {};
    let totalCost = 0;
    for (const row of costResult.rows) {
      breakdown[row.step_name] = parseFloat(row.total_cost_usd);
      totalCost += parseFloat(row.total_cost_usd);
    }

    return {
      job_id: job.id,
      status: 'completed',
      clip_url: job.output_clip_key, // TODO: generate presigned URL
      thumbnail_url: job.output_thumbnail_key,
      duration_sec: job.clip_duration_sec,
      resolution: job.output_resolution,
      file_size_bytes: job.clip_file_size,
      cost: { total_usd: totalCost, breakdown },
      completed_at: job.completed_at,
    };
  }

  async retryJob(jobId: string, fromStep?: string) {
    const jobResult = await db.query('SELECT * FROM jobs WHERE id = $1', [jobId]);
    if (!jobResult.rows[0]) return null;

    const job = jobResult.rows[0];
    if (!['failed', 'cancelled'].includes(job.status)) {
      throw new BadRequestException('Job must be in failed or cancelled state to retry');
    }
    if (job.retry_count >= job.max_retries) {
      throw new BadRequestException('Maximum retries exceeded');
    }

    const retryFrom = fromStep || job.error_step || STEP_NAMES[0];
    if (!STEP_NAMES.includes(retryFrom)) {
      throw new BadRequestException(`Invalid step name: ${retryFrom}`);
    }

    await db.query(
      `UPDATE jobs SET status = 'queued', retry_count = retry_count + 1,
       retry_from_step = $2, error_code = NULL, error_message = NULL, updated_at = NOW()
       WHERE id = $1`,
      [jobId, retryFrom],
    );

    // Reset steps from retryFrom onward
    const stepIndex = STEP_NAMES.indexOf(retryFrom);
    for (let i = stepIndex; i < STEP_NAMES.length; i++) {
      await db.query(
        `UPDATE job_steps SET status = 'pending', started_at = NULL, completed_at = NULL, duration_sec = NULL
         WHERE job_id = $1 AND step_name = $2`,
        [jobId, STEP_NAMES[i]],
      );
    }

    await clipQueue.add('process-clip', { jobId, startFromStep: retryFrom }, { jobId });

    return { job_id: jobId, status: 'queued', retry_from: retryFrom, retry_count: job.retry_count + 1 };
  }

  async cancelJob(jobId: string) {
    const jobResult = await db.query('SELECT status FROM jobs WHERE id = $1', [jobId]);
    if (!jobResult.rows[0]) return null;

    if (['completed', 'cancelled'].includes(jobResult.rows[0].status)) {
      throw new BadRequestException('Job already completed or cancelled');
    }

    await db.query(
      `UPDATE jobs SET status = 'cancelled', cancelled_at = NOW(), updated_at = NOW() WHERE id = $1`,
      [jobId],
    );

    return { job_id: jobId, status: 'cancelled', cancelled_at: new Date().toISOString() };
  }
}
