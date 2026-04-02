export const config = {
  port: parseInt(process.env.PORT || '3000', 10),

  postgres: {
    host: process.env.PG_HOST || 'localhost',
    port: parseInt(process.env.PG_PORT || '5432', 10),
    database: process.env.PG_DATABASE || 'clip_generation',
    user: process.env.PG_USER || 'clips',
    password: process.env.PG_PASSWORD || '',
  },

  redis: {
    host: process.env.REDIS_HOST || 'localhost',
    port: parseInt(process.env.REDIS_PORT || '6379', 10),
    password: process.env.REDIS_PASSWORD || undefined,
  },

  s3: {
    endpoint: process.env.S3_ENDPOINT || 'http://localhost:9000',
    bucket: process.env.S3_BUCKET || 'brohit-clips',
    accessKey: process.env.S3_ACCESS_KEY || 'minioadmin',
    secretKey: process.env.S3_SECRET_KEY || 'minioadmin',
    region: process.env.S3_REGION || 'us-east-1',
  },

  jobs: {
    maxRetries: 3,
    maxConcurrentPerUser: 5,
    rateLimit: { max: 100, duration: 3600 }, // 100 jobs/hour
    idempotencyTtlSec: 86400, // 24h
  },

  webhookUrl: process.env.WEBHOOK_URL || '',
  apiKey: process.env.API_KEY || 'dev-api-key',
};
