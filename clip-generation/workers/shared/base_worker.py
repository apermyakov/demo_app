"""Base worker class for all clip generation workers."""

import json
import os
import time
import redis
import boto3
from abc import ABC, abstractmethod


class BaseWorker(ABC):
    """Base class for BullMQ-compatible Python workers.

    Workers poll Redis for jobs from their queue, process them,
    and report results back via Redis.
    """

    def __init__(self, queue_name: str):
        self.queue_name = queue_name
        self.redis = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            password=os.getenv("REDIS_PASSWORD"),
            decode_responses=True,
        )
        self.s3 = boto3.client(
            "s3",
            endpoint_url=os.getenv("S3_ENDPOINT", "http://localhost:9000"),
            aws_access_key_id=os.getenv("S3_ACCESS_KEY", "minioadmin"),
            aws_secret_access_key=os.getenv("S3_SECRET_KEY", "minioadmin"),
        )
        self.bucket = os.getenv("S3_BUCKET", "brohit-clips")

    def download_from_s3(self, key: str, local_path: str):
        """Download file from S3 to local path."""
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        self.s3.download_file(self.bucket, key, local_path)

    def upload_to_s3(self, local_path: str, key: str) -> str:
        """Upload file to S3 and return the key."""
        self.s3.upload_file(local_path, self.bucket, key)
        return key

    @abstractmethod
    def process(self, job_id: str, step_name: str, payload: dict) -> dict:
        """Process a single job step. Must return dict with artifact keys."""
        ...

    def run(self):
        """Main loop: poll queue for jobs and process them."""
        print(f"Worker [{self.queue_name}] started, waiting for jobs...")
        while True:
            # Simplified polling — production would use BullMQ protocol
            job_data = self.redis.brpop(f"bull:{self.queue_name}:wait", timeout=5)
            if not job_data:
                continue

            try:
                payload = json.loads(job_data[1])
                job_id = payload.get("jobId", "unknown")
                step_name = payload.get("stepName", "unknown")
                print(f"Processing job={job_id} step={step_name}")

                start_time = time.time()
                result = self.process(job_id, step_name, payload)
                elapsed = time.time() - start_time

                print(f"Completed job={job_id} step={step_name} in {elapsed:.1f}s")
                # Report success back via Redis
                self.redis.publish(
                    f"bull:{self.queue_name}:completed",
                    json.dumps({"jobId": job_id, "result": result}),
                )
            except Exception as e:
                print(f"Error processing job: {e}")
                self.redis.publish(
                    f"bull:{self.queue_name}:failed",
                    json.dumps({"jobId": job_id, "error": str(e)}),
                )
