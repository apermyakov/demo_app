"""Preprocessing worker: audio normalization, face detection, photo analysis."""

import json
import os
import subprocess
import tempfile

import mediapipe as mp
import numpy as np
from PIL import Image

from workers.shared.base_worker import BaseWorker


class PreprocessingWorker(BaseWorker):
    def __init__(self):
        super().__init__("clip:preprocess")
        self.face_detector = mp.solutions.face_detection.FaceDetection(
            model_selection=1, min_detection_confidence=0.5
        )

    def process(self, job_id: str, step_name: str, payload: dict) -> dict:
        if step_name == "preprocessing":
            return self._preprocess(job_id, payload)
        elif step_name == "vocal_separation":
            return self._separate_vocals(job_id, payload)
        else:
            raise ValueError(f"Unknown step: {step_name}")

    def _preprocess(self, job_id: str, payload: dict) -> dict:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Download inputs
            audio_path = os.path.join(tmpdir, "audio.mp3")
            photo_path = os.path.join(tmpdir, "photo.jpg")
            self.download_from_s3(f"jobs/{job_id}/input/audio.mp3", audio_path)
            self.download_from_s3(f"jobs/{job_id}/input/photo.jpg", photo_path)

            # Normalize audio (loudnorm, mono, 44.1kHz WAV)
            norm_audio = os.path.join(tmpdir, "normalized.wav")
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", audio_path,
                    "-af", "loudnorm=I=-16:LRA=11:TP=-1.5",
                    "-ar", "44100", "-ac", "1",
                    norm_audio,
                ],
                check=True, capture_output=True,
            )

            # Get audio duration
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", audio_path],
                capture_output=True, text=True, check=True,
            )
            duration = float(probe.stdout.strip())

            # Face detection
            image = Image.open(photo_path)
            image_np = np.array(image)
            results = self.face_detector.process(image_np)

            faces = []
            if results.detections:
                h, w = image_np.shape[:2]
                for i, det in enumerate(results.detections):
                    bbox = det.location_data.relative_bounding_box
                    face = {
                        "id": i,
                        "bbox": [
                            int(bbox.xmin * w), int(bbox.ymin * h),
                            int((bbox.xmin + bbox.width) * w),
                            int((bbox.ymin + bbox.height) * h),
                        ],
                        "size_relative": bbox.width * bbox.height,
                        "centrality": 1.0 - abs(bbox.xmin + bbox.width / 2 - 0.5) * 2,
                        "sharpness": self._estimate_sharpness(image_np, bbox, w, h),
                        "is_primary": False,
                    }
                    faces.append(face)

                # Rank faces and mark primary
                faces.sort(
                    key=lambda f: f["size_relative"] * 0.4 + f["centrality"] * 0.3 + f["sharpness"] * 0.2,
                    reverse=True,
                )
                if faces:
                    faces[0]["is_primary"] = True

            faces_result = {"total_faces": len(faces), "total_persons": len(faces), "faces": faces}

            # Upload artifacts
            self.upload_to_s3(norm_audio, f"jobs/{job_id}/artifacts/normalized_audio.wav")
            faces_path = os.path.join(tmpdir, "faces.json")
            with open(faces_path, "w") as f:
                json.dump(faces_result, f)
            self.upload_to_s3(faces_path, f"jobs/{job_id}/artifacts/faces.json")

            return {
                "artifacts": [
                    f"jobs/{job_id}/artifacts/normalized_audio.wav",
                    f"jobs/{job_id}/artifacts/faces.json",
                ],
                "duration": duration,
                "faces_count": len(faces),
            }

    def _separate_vocals(self, job_id: str, payload: dict) -> dict:
        """Separate vocals using Demucs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = os.path.join(tmpdir, "audio.mp3")
            self.download_from_s3(f"jobs/{job_id}/input/audio.mp3", audio_path)

            # Run Demucs
            subprocess.run(
                ["python", "-m", "demucs", "-n", "htdemucs", "--two-stems", "vocals",
                 "-o", tmpdir, audio_path],
                check=True, capture_output=True,
            )

            vocals_path = os.path.join(tmpdir, "htdemucs", "audio", "vocals.wav")
            vocals_key = f"jobs/{job_id}/artifacts/vocals.wav"
            self.upload_to_s3(vocals_path, vocals_key)

            return {"artifacts": [vocals_key]}

    def _estimate_sharpness(self, image_np, bbox, w, h) -> float:
        """Estimate face sharpness using Laplacian variance."""
        x1 = max(0, int(bbox.xmin * w))
        y1 = max(0, int(bbox.ymin * h))
        x2 = min(w, int((bbox.xmin + bbox.width) * w))
        y2 = min(h, int((bbox.ymin + bbox.height) * h))
        face_crop = image_np[y1:y2, x1:x2]
        if face_crop.size == 0:
            return 0.0
        gray = np.mean(face_crop, axis=2)
        laplacian = np.abs(np.diff(gray, axis=0)) + np.abs(np.diff(gray, axis=1))
        return min(float(np.mean(laplacian)) / 50.0, 1.0)


if __name__ == "__main__":
    worker = PreprocessingWorker()
    worker.run()
