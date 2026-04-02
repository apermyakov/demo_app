export const STEP_NAMES = [
  'preprocessing',
  'vocal_separation',
  'alignment',
  'stylization',
  'loop_generation',
  'composition',
  'upload',
] as const;

export type StepName = (typeof STEP_NAMES)[number];

export const STEP_PROGRESS: Record<string, { start: number; end: number }> = {
  preprocessing:    { start: 0,  end: 10 },
  vocal_separation: { start: 10, end: 20 },
  alignment:        { start: 20, end: 35 },
  stylization:      { start: 35, end: 50 },
  loop_generation:  { start: 50, end: 75 },
  composition:      { start: 75, end: 95 },
  upload:           { start: 95, end: 100 },
};

export const JOB_STATUSES = [
  'queued',
  'preprocessing',
  'separating_vocals',
  'aligning_lyrics',
  'stylizing_photo',
  'generating_loop',
  'composing_video',
  'uploading',
  'completed',
  'failed',
  'cancelled',
] as const;

export type JobStatus = (typeof JOB_STATUSES)[number];
