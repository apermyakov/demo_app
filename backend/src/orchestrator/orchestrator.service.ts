import { Injectable, OnModuleInit } from '@nestjs/common';
import { Worker, Job } from 'bullmq';
import { config } from '../config';
import { db } from '../db/client';
import { workerQueues } from '../queues/clip.queue';
import { STEP_NAMES, STEP_PROGRESS } from '../../../shared/constants/steps';

interface ClipJobPayload {
  jobId: string;
  startFromStep?: string;
}

@Injectable()
export class OrchestratorService implements OnModuleInit {
  private worker!: Worker;

  onModuleInit() {
    const connection = {
      host: config.redis.host,
      port: config.redis.port,
      password: config.redis.password,
    };

    this.worker = new Worker(
      'clip:orchestrate',
      async (job: Job<ClipJobPayload>) => {
        await this.processClipJob(job.data);
      },
      { connection, concurrency: 5 },
    );

    this.worker.on('failed', (job, err) => {
      console.error(`Orchestrator job ${job?.id} failed:`, err.message);
    });

    console.log('Orchestrator worker started');
  }

  private async processClipJob(payload: ClipJobPayload) {
    const { jobId, startFromStep } = payload;

    // Load job from DB
    const jobResult = await db.query('SELECT * FROM jobs WHERE id = $1', [jobId]);
    const job = jobResult.rows[0];
    if (!job) throw new Error(`Job ${jobId} not found`);

    const startIndex = startFromStep ? STEP_NAMES.indexOf(startFromStep) : 0;

    for (let i = startIndex; i < STEP_NAMES.length; i++) {
      const stepName = STEP_NAMES[i];

      // Check if job was cancelled
      const currentJob = await db.query('SELECT status FROM jobs WHERE id = $1', [jobId]);
      if (currentJob.rows[0]?.status === 'cancelled') {
        console.log(`Job ${jobId} cancelled, stopping orchestration`);
        return;
      }

      // Check cache — if step already has artifacts, skip
      const stepResult = await db.query(
        'SELECT status, cache_key FROM job_steps WHERE job_id = $1 AND step_name = $2',
        [jobId, stepName],
      );
      if (stepResult.rows[0]?.status === 'completed') {
        console.log(`Step ${stepName} already completed for job ${jobId}, skipping`);
        continue;
      }

      // Update job status
      const statusMap: Record<string, string> = {
        preprocessing: 'preprocessing',
        vocal_separation: 'separating_vocals',
        alignment: 'aligning_lyrics',
        stylization: 'stylizing_photo',
        loop_generation: 'generating_loop',
        composition: 'composing_video',
        upload: 'uploading',
      };

      await db.query(
        `UPDATE jobs SET status = $2, current_step = $3, progress_percent = $4, updated_at = NOW()
         WHERE id = $1`,
        [jobId, statusMap[stepName] || stepName, stepName, STEP_PROGRESS[stepName]?.start || 0],
      );

      // Update step status
      await db.query(
        `UPDATE job_steps SET status = 'running', started_at = NOW() WHERE job_id = $1 AND step_name = $2`,
        [jobId, stepName],
      );

      // Dispatch to worker queue
      const queueMap: Record<string, keyof typeof workerQueues> = {
        preprocessing: 'preprocess',
        vocal_separation: 'preprocess', // same worker handles vocal separation
        alignment: 'alignment',
        stylization: 'stylization',
        loop_generation: 'animation',
        composition: 'composition',
        upload: 'composition', // same worker handles upload
      };

      const queue = workerQueues[queueMap[stepName]];
      const workerJob = await queue.add(stepName, { jobId, stepName }, {
        attempts: getMaxRetries(stepName),
        backoff: { type: 'exponential', delay: 10000 },
      });

      // Wait for worker to complete
      const result = await workerJob.waitUntilFinished(queue.events);

      // Update step as completed
      await db.query(
        `UPDATE job_steps SET status = 'completed', completed_at = NOW(),
         duration_sec = EXTRACT(EPOCH FROM (NOW() - started_at)),
         artifacts = $3
         WHERE job_id = $1 AND step_name = $2`,
        [jobId, stepName, JSON.stringify(result?.artifacts || [])],
      );
    }

    // Mark job as completed
    await db.query(
      `UPDATE jobs SET status = 'completed', progress_percent = 100, completed_at = NOW(), updated_at = NOW()
       WHERE id = $1`,
      [jobId],
    );
  }
}

function getMaxRetries(stepName: string): number {
  const retryMap: Record<string, number> = {
    preprocessing: 2,
    vocal_separation: 2,
    alignment: 2,
    stylization: 3,
    loop_generation: 3,
    composition: 2,
    upload: 3,
  };
  return retryMap[stepName] || 2;
}
