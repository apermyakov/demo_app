"""Karaoke alignment worker: lyrics + audio → word-level timestamps."""

import json
import os
import tempfile

import whisper

from workers.shared.base_worker import BaseWorker


class AlignmentWorker(BaseWorker):
    def __init__(self):
        super().__init__("clip:alignment")
        self.model = None

    def _load_model(self):
        if self.model is None:
            print("Loading Whisper large-v3...")
            self.model = whisper.load_model("large-v3")
            print("Whisper model loaded")

    def process(self, job_id: str, step_name: str, payload: dict) -> dict:
        self._load_model()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Download vocals (or normalized audio if vocals unavailable)
            vocals_key = f"jobs/{job_id}/artifacts/vocals.wav"
            vocals_path = os.path.join(tmpdir, "vocals.wav")
            try:
                self.download_from_s3(vocals_key, vocals_path)
            except Exception:
                # Fallback to normalized audio
                self.download_from_s3(
                    f"jobs/{job_id}/artifacts/normalized_audio.wav", vocals_path
                )

            # Get lyrics from Redis/payload (stored in job DB)
            lyrics = payload.get("lyrics", "")

            # Run Whisper with word-level timestamps
            result = self.model.transcribe(
                vocals_path,
                language="ru",
                word_timestamps=True,
                task="transcribe",
            )

            # Build alignment JSON
            alignment = self._build_alignment(result, lyrics, job_id)

            # Upload
            alignment_path = os.path.join(tmpdir, "alignment.json")
            with open(alignment_path, "w", encoding="utf-8") as f:
                json.dump(alignment, f, ensure_ascii=False, indent=2)

            alignment_key = f"jobs/{job_id}/artifacts/alignment.json"
            self.upload_to_s3(alignment_path, alignment_key)

            return {
                "artifacts": [alignment_key],
                "confidence": alignment["confidence"],
                "method": alignment["alignment_method"],
                "segment_count": len(alignment["segments"]),
            }

    def _build_alignment(self, whisper_result: dict, lyrics: str, song_id: str) -> dict:
        """Convert Whisper output to our alignment format."""
        segments = []
        overall_confidence = 0.0
        total_words = 0

        for seg in whisper_result.get("segments", []):
            words = []
            for w in seg.get("words", []):
                word_conf = w.get("probability", 0.5)
                words.append({
                    "word": w["word"].strip(),
                    "start": round(w["start"], 3),
                    "end": round(w["end"], 3),
                    "confidence": round(word_conf, 3),
                    "extended": (w["end"] - w["start"]) > 1.5,
                })
                overall_confidence += word_conf
                total_words += 1

            segment = {
                "index": len(segments),
                "line": seg.get("text", "").strip(),
                "start": round(seg["start"], 3),
                "end": round(seg["end"], 3),
                "confidence": round(
                    sum(w["confidence"] for w in words) / max(len(words), 1), 3
                ),
                "words": words,
            }

            # Mark instrumental gaps
            if not words:
                segment["is_instrumental"] = True

            segments.append(segment)

        # Fill gaps between segments as instrumental
        filled_segments = []
        for i, seg in enumerate(segments):
            if i > 0:
                prev_end = segments[i - 1]["end"]
                if seg["start"] - prev_end > 2.0:
                    filled_segments.append({
                        "index": len(filled_segments),
                        "line": "",
                        "start": round(prev_end, 3),
                        "end": round(seg["start"], 3),
                        "confidence": 1.0,
                        "is_instrumental": True,
                        "words": [],
                    })
            filled_segments.append({**seg, "index": len(filled_segments)})

        avg_confidence = overall_confidence / max(total_words, 1)

        # Determine method: if confidence too low, fallback info
        method = "whisper_word_level"
        if avg_confidence < 0.5:
            method = "whisper_line_level_fallback"

        return {
            "version": "1.0",
            "song_id": song_id,
            "duration": whisper_result.get("segments", [{}])[-1].get("end", 0) if whisper_result.get("segments") else 0,
            "language": "ru",
            "alignment_method": method,
            "confidence": round(avg_confidence, 3),
            "segments": filled_segments,
        }


if __name__ == "__main__":
    worker = AlignmentWorker()
    worker.run()
