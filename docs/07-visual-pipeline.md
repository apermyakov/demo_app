# Visual Pipeline: Photo → Stylized Scene → Animated Loop

## Overview

```
User Photo → Face Detection → Segmentation → Prompt Generation
                                                    ↓
                                            Stylized Keyframe (SDXL/Flux + IP-Adapter)
                                                    ↓
                                            Animated Loop (SVD / Kling API)
                                                    ↓
                                            Loop Masking & Variation
```

---

## Step 1: Face/Person Detection & Analysis

### Technology: MediaPipe Face Detection + RetinaFace

**Why both:**
- MediaPipe: fast, lightweight, good for initial detection
- RetinaFace: backup for edge cases (side profiles, small faces)

**Process:**
1. Detect all faces in photo
2. For each face extract:
   - Bounding box
   - Landmarks (5-point or 68-point)
   - Face size (relative to image)
   - Face position (centrality score)
   - Face quality score (sharpness, lighting)
   - Estimated age group (child/adult) — optional

3. Body/person detection via MediaPipe Pose or YOLO:
   - Full body bounding box
   - Pose keypoints
   - Person count validation

**Output:** `faces.json`
```json
{
  "total_faces": 2,
  "total_persons": 2,
  "faces": [
    {
      "id": 0,
      "bbox": [120, 50, 380, 310],
      "landmarks": [...],
      "size_relative": 0.35,
      "centrality": 0.85,
      "sharpness": 0.92,
      "is_primary": true,
      "age_group": "adult"
    },
    {
      "id": 1,
      "bbox": [400, 80, 600, 340],
      "size_relative": 0.22,
      "centrality": 0.60,
      "sharpness": 0.78,
      "is_primary": false,
      "age_group": "adult"
    }
  ]
}
```

---

## Step 2: Multi-Person Handling Policy

### Decision Matrix:

| Detected | Strategy | Scene Type |
|----------|----------|------------|
| 1 person | Solo scene, close-up or mid-shot | Portrait/bust |
| 2 persons | Duo scene, both prominent | Two-shot, side by side |
| 3 persons | Group scene or top-2 primary | Group with background blur |
| 4 persons | Group scene, ranked prominence | Wide group shot |
| 0 faces | Fallback: landscape/abstract scene with lyrics theme | No characters |
| Face too small (<64px) | Skip that face, use detectable ones | - |

### Primary Person Selection Algorithm:
```python
def rank_faces(faces):
    for face in faces:
        face.score = (
            face.size_relative * 0.4 +      # Bigger = more important
            face.centrality * 0.3 +          # Center = more important
            face.sharpness * 0.2 +           # Sharper = better quality
            (1.0 if face.age_group == 'adult' else 0.7) * 0.1  # Adults first
        )
    return sorted(faces, key=lambda f: f.score, reverse=True)
```

### Crop Strategy:
- **1 person:** Crop to upper body, center on face, add 30% padding
- **2 persons:** Crop to include both faces with 20% padding, horizontal composition
- **3–4 persons:** Wider crop, may zoom out to fit all, or use top-2 and mention others in prompt
- **Aspect ratio:** Always crop to 16:9 for consistency with output

---

## Step 3: Scene Prompt Generation

### Approach: Template-based + LLM enhancement

**Base template system:**
```python
STYLE_PREFIX = (
    "stylized 3D animated film look, cartoon cinematic, "
    "family-friendly 3D illustration, soft global illumination, "
    "expressive characters, non-photorealistic, Pixar-inspired quality, "
    "warm lighting, detailed textures"
)

SCENE_TEMPLATES = {
    "birthday": "birthday party scene with colorful decorations, cake, balloons, confetti",
    "love": "romantic garden scene with flowers, sunset, warm colors",
    "party": "lively celebration scene with disco lights, stage, music",
    "friendship": "cozy living room scene, friends together, warm atmosphere",
    "default": "beautiful scenic background, pleasant outdoor setting, warm daylight"
}
```

**Prompt assembly:**
```python
def build_prompt(faces_count, style_hint, primary_face_description):
    scene = SCENE_TEMPLATES.get(style_hint, SCENE_TEMPLATES["default"])
    
    if faces_count == 1:
        char_desc = f"one cartoon character, {primary_face_description}, mid-shot portrait"
    elif faces_count == 2:
        char_desc = "two cartoon characters together, friends or couple"
    else:
        char_desc = f"{faces_count} cartoon characters in a group"
    
    return f"{STYLE_PREFIX}, {char_desc}, {scene}"
```

**Optional LLM enhancement (Phase 2):**
- Use Claude/GPT to generate more creative scene descriptions based on lyrics themes
- Extract mood/theme from lyrics → map to scene type
- Cost: $0.001–$0.005 per call

---

## Step 4: Stylized Keyframe Generation

### Primary: SDXL + IP-Adapter

**Why:**
- IP-Adapter preserves facial identity without photorealism
- SDXL produces high-quality stylized images
- Well-supported, many fine-tuned models available
- Self-hosted cost: ~$0.03–$0.08 per image on A10

**Pipeline:**
```
Input: user_photo.jpg + scene_prompt
    → IP-Adapter face embedding extraction
    → SDXL generation with:
        - IP-Adapter (face reference, weight 0.5-0.7)
        - ControlNet OpenPose (optional, for body pose)
        - Positive prompt: style + scene + character description
        - Negative prompt: "photorealistic, photo, real face, uncanny valley, 
          deformed, ugly, blurry, low quality, nsfw"
    → Output: stylized_keyframe.png (1280x720)
```

**Key parameters:**
- IP-Adapter weight: 0.5–0.7 (lower = more stylized, higher = more similar)
- CFG scale: 7–9
- Steps: 30–40
- Sampler: DPM++ 2M Karras
- Resolution: 1280×720 (native 16:9)

### Alternative: Flux.1 + IP-Adapter
- Higher quality but slightly more expensive
- Better prompt following
- Consider for Phase 2

### Identity Preservation Level:
- NOT photorealistic face swap
- Goal: "this cartoon character clearly resembles the person in the photo"
- Hair color, general face shape, skin tone, glasses → preserved
- Exact facial features → stylized/simplified
- This is a feature, not a bug: cartoon look is the product

### Multi-person handling in generation:
- **1 person:** Single IP-Adapter reference, straightforward
- **2 persons:** Two IP-Adapter references (one per face). Some models support multi-reference.
  Fallback: generate separately and composite
- **3–4 persons:** Primary 1–2 get IP-Adapter references, others generated from prompt description only
- Quality trade-off: more faces = less individual accuracy. This is acceptable for MVP.

---

## Step 5: Loop Animation Generation

### Primary Option: Stable Video Diffusion (SVD) — Self-hosted

**Pipeline:**
```
stylized_keyframe.png → SVD img2vid
    → Parameters:
        - fps: 12-15
        - frames: 60-150 (5-12 sec)
        - motion_bucket_id: 100-180
        - noise_aug_strength: 0.02
    → Raw video: loop_raw.mp4
    → Post-processing: crossfade for seamless loop
    → Output: loop_001.mp4
```

**Cost:** ~$0.10–$0.20 per loop (self-hosted A10, ~30-60 sec inference)

### Alternative: Kling API / MiniMax Hailuo
- Managed API, no infra needed
- Higher quality motion
- Cost: $0.05–$0.30 per 5-sec clip
- Risk: API availability, rate limits, pricing changes

### Alternative: AnimateDiff
- Lighter weight than SVD
- Lower quality but faster
- Good for budget tier

### Recommendation for MVP:
1. **Start with Kling/MiniMax API** — fastest to market, good quality
2. **Migrate to self-hosted SVD** — when volume justifies dedicated GPU
3. **Keep AnimateDiff** as ultra-cheap fallback

---

## Step 6: Loop Masking & Variation

### Problem: 5-12 sec loop repeated 10-20 times = obvious repetition

### Solution Toolkit:

#### 1. Seamless Loop Processing
```python
def make_seamless_loop(video, crossfade_frames=15):
    """Crossfade end into beginning for seamless repetition."""
    total = len(video)
    blend_region = video[-crossfade_frames:]
    start_region = video[:crossfade_frames]
    
    for i in range(crossfade_frames):
        alpha = i / crossfade_frames
        blend_region[i] = blend_region[i] * (1 - alpha) + start_region[i] * alpha
    
    video[-crossfade_frames:] = blend_region
    return video
```

#### 2. Camera Motion Variations (FFmpeg)
Apply different camera movements per section:
- **Verse:** Slow zoom in (1.0x → 1.15x over 30 sec)
- **Chorus:** Slow zoom out (1.15x → 1.0x) + slight pan
- **Bridge:** Pan left-to-right
- **Outro:** Slow pull back

```bash
# Example: slow zoom with FFmpeg
ffmpeg -i loop.mp4 -vf "zoompan=z='min(zoom+0.0005,1.15)':d=1:s=1280x720" output.mp4
```

#### 3. Color/Mood Variations per Section
```python
SECTION_COLOR_GRADES = {
    "verse": {"brightness": 1.0, "saturation": 1.0, "hue_shift": 0},
    "chorus": {"brightness": 1.1, "saturation": 1.2, "hue_shift": 10},
    "bridge": {"brightness": 0.9, "saturation": 0.8, "hue_shift": -15},
    "outro": {"brightness": 0.85, "saturation": 0.9, "hue_shift": -5}
}
```

#### 4. Particle/Light Overlays
Pre-rendered transparent overlay loops:
- Bokeh lights (warm/cool variants)
- Floating particles (dust, sparkles, snow)
- Light rays / lens flares
- Subtle film grain

These are cheap (pre-rendered), add visual variety per section.

#### 5. Ping-Pong (Forward + Reverse)
- Doubles effective loop length (5 sec → 10 sec)
- Works well for subtle motion (breathing, background movement)
- May look odd for directional motion (walking)

#### 6. Multiple Loops for Sections
If budget allows ($0.30–$0.60 extra):
- Loop A: verse scene (calm, close-up)
- Loop B: chorus scene (energetic, wider shot)
- Transition between them with crossfade/wipe at section boundaries

### Recommended MVP Strategy:
1. Generate **1 loop** (5–8 sec)
2. Make it **seamless** via crossfade
3. Apply **different camera motions** per section (verse/chorus/bridge)
4. Add **2–3 particle overlay** variants
5. Apply **color grading** per section
6. This combination makes the loop feel like 3–4 different shots while using only 1 generation

### Phase 2 Enhancement:
- Generate 2–3 loops for verse/chorus/bridge
- Use audio energy curve to drive camera motion intensity
- Beat-synced light pulses
- More sophisticated section transitions (dissolve, wipe, zoom-through)

---

## Fallback Chain

1. **Normal:** Stylized keyframe → animated loop → full pipeline
2. **Loop generation fails:** Stylized keyframe → Ken Burns effect + particles (Variant 1)
3. **Stylization fails:** Original photo with cartoon filter (OpenCV/Pillow) → Ken Burns
4. **Face detection fails:** Generate abstract/landscape scene from lyrics theme → animate
5. **Everything fails:** Static colored background + karaoke text only (emergency fallback)

Each fallback is progressively cheaper and more reliable.
