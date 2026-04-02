"""Visual stylization worker: photo → cartoon/Pixar-like keyframe."""

import json
import os
import tempfile

import torch
from PIL import Image

from workers.shared.base_worker import BaseWorker


# Style prompt constants
STYLE_PREFIX = (
    "stylized 3D animated film look, cartoon cinematic, "
    "family-friendly 3D illustration, soft global illumination, "
    "expressive characters, non-photorealistic, high quality, "
    "warm lighting, detailed textures, vibrant colors"
)

NEGATIVE_PROMPT = (
    "photorealistic, photo, real face, uncanny valley, deformed, ugly, blurry, "
    "low quality, nsfw, nude, violent, dark, horror, scary, "
    "bad anatomy, bad proportions, extra limbs, mutated"
)

SCENE_TEMPLATES = {
    "birthday": "colorful birthday party scene, cake, balloons, confetti, festive decorations",
    "love": "romantic garden with flowers, sunset, warm golden light, dreamy atmosphere",
    "party": "lively celebration, disco lights, music stage, dynamic energy",
    "friendship": "cozy warm living room, friends together, soft lighting",
    "default": "beautiful scenic outdoor background, pleasant warm daylight, gentle landscape",
}


class StylizationWorker(BaseWorker):
    def __init__(self):
        super().__init__("clip:stylization")
        self.pipe = None

    def _load_pipeline(self):
        if self.pipe is not None:
            return

        print("Loading SDXL + IP-Adapter pipeline...")
        from diffusers import StableDiffusionXLPipeline

        # In production: use SDXL with IP-Adapter for face identity preservation
        # For skeleton, show the pipeline structure
        self.pipe = StableDiffusionXLPipeline.from_pretrained(
            "stabilityai/stable-diffusion-xl-base-1.0",
            torch_dtype=torch.float16,
            variant="fp16",
        )
        self.pipe.to("cuda")

        # TODO: Load IP-Adapter for face identity preservation
        # self.pipe.load_ip_adapter(
        #     "h94/IP-Adapter",
        #     subfolder="sdxl_models",
        #     weight_name="ip-adapter-plus-face_sdxl_vit-h.safetensors"
        # )
        # self.pipe.set_ip_adapter_scale(0.6)

        print("Pipeline loaded")

    def process(self, job_id: str, step_name: str, payload: dict) -> dict:
        self._load_pipeline()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Download photo and faces info
            photo_path = os.path.join(tmpdir, "photo.jpg")
            faces_path = os.path.join(tmpdir, "faces.json")
            self.download_from_s3(f"jobs/{job_id}/input/photo.jpg", photo_path)
            self.download_from_s3(f"jobs/{job_id}/artifacts/faces.json", faces_path)

            with open(faces_path) as f:
                faces_data = json.load(f)

            # Build prompt based on faces and style
            style_hint = payload.get("style_hint", "default")
            prompt = self._build_prompt(faces_data, style_hint)

            # Load reference image for IP-Adapter
            ref_image = Image.open(photo_path).convert("RGB")

            # Generate stylized keyframe
            result_image = self.pipe(
                prompt=prompt,
                negative_prompt=NEGATIVE_PROMPT,
                # ip_adapter_image=ref_image,  # Enable with IP-Adapter
                width=1280,
                height=720,
                num_inference_steps=35,
                guidance_scale=7.5,
                generator=torch.Generator("cuda").manual_seed(42),
            ).images[0]

            # Save and upload
            keyframe_path = os.path.join(tmpdir, "stylized_keyframe.png")
            result_image.save(keyframe_path, "PNG")

            keyframe_key = f"jobs/{job_id}/artifacts/stylized_keyframe.png"
            self.upload_to_s3(keyframe_path, keyframe_key)

            return {
                "artifacts": [keyframe_key],
                "faces_used": faces_data["total_faces"],
                "prompt": prompt,
            }

    def _build_prompt(self, faces_data: dict, style_hint: str) -> str:
        """Build generation prompt based on detected faces and style."""
        scene = SCENE_TEMPLATES.get(style_hint, SCENE_TEMPLATES["default"])
        face_count = faces_data.get("total_faces", 1)

        if face_count == 0:
            char_desc = "beautiful animated scene without people"
        elif face_count == 1:
            char_desc = "one expressive cartoon character, portrait composition, mid-shot"
        elif face_count == 2:
            char_desc = "two cartoon characters together, friendly composition, two-shot"
        else:
            char_desc = f"{face_count} cartoon characters in a group, group portrait"

        return f"{STYLE_PREFIX}, {char_desc}, {scene}"


if __name__ == "__main__":
    worker = StylizationWorker()
    worker.run()
