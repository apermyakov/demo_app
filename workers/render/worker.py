"""Composition/render worker: loop + karaoke + effects → final mp4."""

import json
import os
import subprocess
import tempfile

from workers.shared.base_worker import BaseWorker


class RenderWorker(BaseWorker):
    def __init__(self):
        super().__init__("clip:composition")

    def process(self, job_id: str, step_name: str, payload: dict) -> dict:
        if step_name == "composition":
            return self._compose(job_id, payload)
        elif step_name == "upload":
            return self._upload(job_id, payload)
        else:
            raise ValueError(f"Unknown step: {step_name}")

    def _compose(self, job_id: str, payload: dict) -> dict:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Download all artifacts
            loop_path = os.path.join(tmpdir, "loop.mp4")
            audio_path = os.path.join(tmpdir, "audio.mp3")
            alignment_path = os.path.join(tmpdir, "alignment.json")

            self.download_from_s3(f"jobs/{job_id}/artifacts/loop_001.mp4", loop_path)
            self.download_from_s3(f"jobs/{job_id}/input/audio.mp3", audio_path)
            self.download_from_s3(f"jobs/{job_id}/artifacts/alignment.json", alignment_path)

            # Get audio duration
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", audio_path],
                capture_output=True, text=True, check=True,
            )
            duration = float(probe.stdout.strip())

            with open(alignment_path, encoding="utf-8") as f:
                alignment = json.load(f)

            # Step 1: Loop video to fill song duration
            looped_path = os.path.join(tmpdir, "looped.mp4")
            subprocess.run(
                ["ffmpeg", "-y", "-stream_loop", "-1", "-i", loop_path,
                 "-t", str(duration), "-an",
                 "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                 "-pix_fmt", "yuv420p",
                 looped_path],
                check=True, capture_output=True,
            )

            # Step 2: Scale to 1280x720
            scaled_path = os.path.join(tmpdir, "scaled.mp4")
            subprocess.run(
                ["ffmpeg", "-y", "-i", looped_path,
                 "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2",
                 "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                 "-pix_fmt", "yuv420p",
                 scaled_path],
                check=True, capture_output=True,
            )

            # Step 3: Generate karaoke ASS subtitles
            ass_path = os.path.join(tmpdir, "karaoke.ass")
            self._generate_ass(alignment, ass_path)

            # Step 4: Burn-in karaoke subtitles
            with_karaoke_path = os.path.join(tmpdir, "with_karaoke.mp4")
            subprocess.run(
                ["ffmpeg", "-y", "-i", scaled_path,
                 "-vf", f"ass={ass_path}",
                 "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                 "-pix_fmt", "yuv420p",
                 with_karaoke_path],
                check=True, capture_output=True,
            )

            # Step 5: Merge audio
            final_path = os.path.join(tmpdir, "final_clip.mp4")
            subprocess.run(
                ["ffmpeg", "-y",
                 "-i", with_karaoke_path,
                 "-i", audio_path,
                 "-c:v", "copy",
                 "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
                 "-movflags", "+faststart",
                 "-shortest",
                 final_path],
                check=True, capture_output=True,
            )

            # Generate thumbnail
            thumb_path = os.path.join(tmpdir, "thumbnail.jpg")
            subprocess.run(
                ["ffmpeg", "-y", "-i", final_path, "-ss", "5",
                 "-vframes", "1", "-q:v", "3", thumb_path],
                check=True, capture_output=True,
            )

            # Upload
            final_key = f"jobs/{job_id}/output/final_clip.mp4"
            thumb_key = f"jobs/{job_id}/output/thumbnail.jpg"
            self.upload_to_s3(final_path, final_key)
            self.upload_to_s3(thumb_path, thumb_key)

            # Get file size
            file_size = os.path.getsize(final_path)

            return {
                "artifacts": [final_key, thumb_key],
                "duration": duration,
                "file_size": file_size,
                "resolution": "1280x720",
            }

    def _upload(self, job_id: str, payload: dict) -> dict:
        """Upload step — in MVP this is handled in composition. Placeholder for CDN push."""
        return {"artifacts": [], "cdn_pushed": True}

    def _generate_ass(self, alignment: dict, output_path: str):
        """Generate ASS subtitle file with karaoke timing from alignment JSON."""
        ass_header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,44,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,40,40,60,1
Style: Next,Arial,36,&H80FFFFFF,&H0000FFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,1,2,40,40,110,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        lines = [ass_header]

        segments = [s for s in alignment.get("segments", []) if not s.get("is_instrumental")]

        for i, seg in enumerate(segments):
            start = self._format_ass_time(seg["start"])
            end = self._format_ass_time(seg["end"])

            # Word-level karaoke if available
            if seg.get("words") and alignment.get("alignment_method") != "whisper_line_level_fallback":
                karaoke_text = ""
                for w in seg["words"]:
                    # Duration in centiseconds for \kf tag
                    word_dur = int((w["end"] - w["start"]) * 100)
                    karaoke_text += f"{{\\kf{word_dur}}}{w['word']} "
                lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{karaoke_text.strip()}")
            else:
                # Line-level fallback
                line_dur = int((seg["end"] - seg["start"]) * 100)
                lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{{\\kf{line_dur}}}{seg['line']}")

            # Show next line preview
            if i + 1 < len(segments):
                next_seg = segments[i + 1]
                next_start = self._format_ass_time(max(seg["start"], next_seg["start"] - 2))
                next_end = self._format_ass_time(next_seg["start"])
                lines.append(f"Dialogue: 1,{next_start},{next_end},Next,,0,0,0,,{next_seg['line']}")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _format_ass_time(self, seconds: float) -> str:
        """Format seconds to ASS time format H:MM:SS.CC"""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        cs = int((seconds % 1) * 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


if __name__ == "__main__":
    worker = RenderWorker()
    worker.run()
