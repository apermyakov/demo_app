"""Loop animation worker: stylized keyframe → short animated loop."""

import os
import subprocess
import tempfile

import torch

from workers.shared.base_worker import BaseWorker


class AnimationWorker(BaseWorker):
    def __init__(self):
        super().__init__("clip:animation")
        self.pipe = None

    def _load_pipeline(self):
        if self.pipe is not None:
            return

        print("Loading Stable Video Diffusion pipeline...")
        from diffusers import StableVideoDiffusionPipeline

        self.pipe = StableVideoDiffusionPipeline.from_pretrained(
            "stabilityai/stable-video-diffusion-img2vid-xt",
            torch_dtype=torch.float16,
            variant="fp16",
        )
        self.pipe.to("cuda")
        print("SVD pipeline loaded")

    def process(self, job_id: str, step_name: str, payload: dict) -> dict:
        self._load_pipeline()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Download stylized keyframe
            keyframe_path = os.path.join(tmpdir, "keyframe.png")
            self.download_from_s3(
                f"jobs/{job_id}/artifacts/stylized_keyframe.png", keyframe_path
            )

            from PIL import Image
            image = Image.open(keyframe_path).convert("RGB").resize((1024, 576))

            # Generate video frames
            frames = self.pipe(
                image,
                decode_chunk_size=4,
                num_frames=75,  # ~5 sec at 15fps
                motion_bucket_id=140,
                noise_aug_strength=0.02,
                generator=torch.Generator("cuda").manual_seed(42),
            ).frames[0]

            # Save frames as video
            raw_path = os.path.join(tmpdir, "loop_raw.mp4")
            self._frames_to_video(frames, raw_path, fps=15)

            # Make seamless loop via crossfade
            loop_path = os.path.join(tmpdir, "loop_001.mp4")
            self._make_seamless_loop(raw_path, loop_path, crossfade_sec=0.5)

            # Upload
            loop_key = f"jobs/{job_id}/artifacts/loop_001.mp4"
            self.upload_to_s3(loop_path, loop_key)

            return {"artifacts": [loop_key], "loop_duration_sec": 5.0, "fps": 15}

    def _frames_to_video(self, frames: list, output_path: str, fps: int = 15):
        """Convert PIL frames to mp4 using FFmpeg."""
        frame_dir = os.path.join(os.path.dirname(output_path), "frames")
        os.makedirs(frame_dir, exist_ok=True)

        for i, frame in enumerate(frames):
            frame.save(os.path.join(frame_dir, f"{i:04d}.png"))

        subprocess.run(
            [
                "ffmpeg", "-y",
                "-framerate", str(fps),
                "-i", os.path.join(frame_dir, "%04d.png"),
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-pix_fmt", "yuv420p",
                output_path,
            ],
            check=True, capture_output=True,
        )

    def _make_seamless_loop(self, input_path: str, output_path: str, crossfade_sec: float = 0.5):
        """Create seamless loop by crossfading the end into the beginning."""
        # Get duration
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", input_path],
            capture_output=True, text=True, check=True,
        )
        duration = float(probe.stdout.strip())
        cf = crossfade_sec

        # FFmpeg xfade filter for seamless loop
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", input_path,
                "-filter_complex",
                f"[0:v]split[main][tail];"
                f"[tail]trim=start={duration - cf},setpts=PTS-STARTPTS[end];"
                f"[main]trim=end={cf},setpts=PTS-STARTPTS[start];"
                f"[end][start]blend=all_mode=average:all_opacity=0.5[blended];"
                f"[0:v]trim=start={cf}:end={duration - cf},setpts=PTS-STARTPTS[middle];"
                f"[blended][middle]concat=n=2:v=1:a=0[out]",
                "-map", "[out]",
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-pix_fmt", "yuv420p",
                output_path,
            ],
            check=True, capture_output=True,
        )


if __name__ == "__main__":
    worker = AnimationWorker()
    worker.run()
