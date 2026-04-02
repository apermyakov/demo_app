import { Queue } from 'bullmq';
import { config } from '../config';

const connection = {
  host: config.redis.host,
  port: config.redis.port,
  password: config.redis.password,
};

export const clipQueue = new Queue('clip:orchestrate', { connection });

export const workerQueues = {
  preprocess: new Queue('clip:preprocess', { connection }),
  alignment: new Queue('clip:alignment', { connection }),
  stylization: new Queue('clip:stylization', { connection }),
  animation: new Queue('clip:animation', { connection }),
  composition: new Queue('clip:composition', { connection }),
};
