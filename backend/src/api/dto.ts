import { IsString, IsOptional, MaxLength } from 'class-validator';

export class CreateJobDto {
  @IsString()
  song_id!: string;

  @IsString()
  user_id!: string;

  @IsString()
  @MaxLength(50000)
  lyrics!: string;

  @IsOptional()
  @IsString()
  @MaxLength(256)
  title?: string;

  @IsOptional()
  @IsString()
  style_hint?: string;

  @IsOptional()
  @IsString()
  idempotency_key?: string;
}

export class RetryJobDto {
  @IsOptional()
  @IsString()
  from_step?: string;
}

export interface JobResponse {
  job_id: string;
  status: string;
  progress_percent: number;
  current_step: string | null;
  steps: StepStatus[];
  created_at: string;
  updated_at: string;
  error: { code: string; message: string } | null;
}

export interface StepStatus {
  name: string;
  status: string;
  duration_sec: number | null;
}

export interface JobResultResponse {
  job_id: string;
  status: string;
  clip_url?: string;
  clip_url_expires_at?: string;
  thumbnail_url?: string;
  duration_sec?: number;
  resolution?: string;
  file_size_bytes?: number;
  cost?: {
    total_usd: number;
    breakdown: Record<string, number>;
  };
  completed_at?: string;
  total_processing_sec?: number;
}
