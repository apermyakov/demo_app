# Roadmap & Risk Register

## Part 1: Roadmap

### Phase 1: Prototype (Weeks 1–2)

**Goal:** End-to-end pipeline working locally for 1 clip

**Deliverables:**
- [ ] Local Python script: photo → stylized keyframe (SDXL + IP-Adapter)
- [ ] Local script: keyframe → animated loop (SVD or Kling API)
- [ ] Whisper alignment script: mp3 + lyrics → alignment.json
- [ ] FFmpeg script: loop + audio + karaoke ASS → final mp4
- [ ] Manual quality assessment on 10 test clips
- [ ] Cost measurement per step

**Team:** 1 ML engineer + 1 backend engineer

**Risks:** 
- Quality of stylized keyframes may require prompt tuning
- Loop seamlessness may need iteration

**Exit criteria:** 
- One full clip generated end-to-end
- Subjective quality: "I'd share this with friends"
- Total cost under $1

---

### Phase 2: Internal MVP (Weeks 3–5)

**Goal:** API-driven pipeline, async processing, basic monitoring

**Deliverables:**
- [ ] Ingest API (NestJS): create job, get status, get result
- [ ] PostgreSQL schema deployed
- [ ] BullMQ orchestrator with step management
- [ ] Dockerized workers: preprocessing, alignment, stylization, animation, composition
- [ ] S3 storage integration
- [ ] Basic retry logic
- [ ] Artifact caching (skip completed steps on retry)
- [ ] 50 test clips with quality review
- [ ] Bull Board dashboard for queue monitoring
- [ ] Cost logging per job

**Team:** 1 ML engineer + 2 backend engineers

**Risks:**
- GPU worker stability under load
- Queue backlog management

**Exit criteria:**
- 20 clips/day processed reliably
- Average cost < $0.50/clip
- < 5% failure rate
- Latency < 5 minutes p95

---

### Phase 3: Production MVP (Weeks 6–8)

**Goal:** Production-ready, integrated with Бро.Хит, scalable to hundreds/day

**Deliverables:**
- [ ] Integration with Бро.Хит backend (auth, song data, webhook callbacks)
- [ ] Auto-scaling GPU workers (RunPod/Vast.ai or dedicated)
- [ ] Full retry policy with dead-letter handling
- [ ] Idempotency on job creation
- [ ] Progress reporting to client (polling API)
- [ ] Multi-person photo handling (1–4 people)
- [ ] Karaoke quality: word-level with line-level fallback
- [ ] Section-based visual variation (verse/chorus color grading, camera motion)
- [ ] Particle overlay library (5+ variants)
- [ ] Monitoring: Prometheus + Grafana dashboards
- [ ] Alerting: job failure rate, queue depth, cost anomalies
- [ ] Load testing: 100 concurrent jobs
- [ ] Photo moderation (NSFW filter)

**Team:** 1 ML engineer + 2 backend engineers + 0.5 DevOps

**Risks:**
- GPU availability at scale
- Cost spikes from retries
- User photo quality variance

**Exit criteria:**
- 300 clips/day sustained
- Average cost < $0.40/clip
- < 3% failure rate
- Latency < 4 minutes p95
- Positive user feedback on quality

---

### Phase 4: Premium Extensions (Weeks 9–16)

**Goal:** Upsell features, multiple styles, better quality

**Planned features (prioritized):**
1. **Multiple visual styles:** "Pixar", "Anime", "Watercolor", "Pop Art" — different SDXL checkpoints
2. **2–3 loops per clip:** Different scenes for verse/chorus/bridge
3. **Vertical format (9:16):** For TikTok/Reels/Shorts
4. **Beat-synced effects:** Light pulses, camera shake on beat drops
5. **Premium resolution:** 1080p output
6. **Style selection UI:** User picks visual style before generation
7. **Re-render without regeneration:** Change karaoke style without re-running expensive steps
8. **Section-based scene changes:** Different backgrounds for verse vs chorus
9. **Lip-sync (experimental):** Basic mouth animation synced to vocals
10. **Multi-language support:** Beyond Russian

**Pricing model:**
- Free/basic tier: Variant 1 (static image + motion design)
- Standard tier: Variant 2 (1 loop, current MVP)
- Premium tier: Variant 2+ (2–3 loops, style selection, 1080p)

---

## Part 2: Risk Register

### Quality Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Stylized keyframe doesn't look like the person | Medium | High | Tune IP-Adapter weight, offer re-generation. Accept cartoon-level similarity, not photorealistic. |
| Animated loop has artifacts (distorted faces, flickering) | Medium | High | Quality check after generation (CLIP score vs keyframe). Auto-retry with different seed. Fallback to Ken Burns. |
| Karaoke timing is off by >500ms | Low | Medium | Vocal separation improves Whisper accuracy. Line-level fallback always works. Manual correction for popular songs. |
| Loop repetition is obviously visible | Medium | Medium | Camera motion, color grading, particles mask repetition. Carousel of 3 overlay sets. Karaoke text draws attention away. |
| Multi-person photos produce bad results | High | Medium | Limit to 1–2 primary faces with IP-Adapter. Others from prompt only. Set expectations in UI. |
| Uncanny valley effect | Low | High | Strict prompt engineering: NO photorealistic terms. Strong cartoon style. Negative prompts. |

### Privacy Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| User photos stored insecurely | Low | Critical | Encrypt at rest (S3 SSE). Delete input photos after 30 days. Access logging. |
| Generated clips contain inappropriate content | Low | High | NSFW filter on input photo. Style prompts exclude inappropriate content. Post-generation NSFW check. |
| Face data used for training without consent | Low | Critical | Never use user photos for model training. Document in privacy policy. Photos only processed, not stored in datasets. |
| Minor's face in photo | Medium | High | Age estimation in preprocessing. If child detected, apply extra privacy safeguards. Parental consent note in ToS. |

### Moderation / Content Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Offensive lyrics in karaoke | Medium | Medium | Lyrics come from Бро.Хит (already moderated). Additional keyword filter on clip generation side. |
| Generated scene inappropriate for content | Low | Medium | Constrained style prompts. No violence/sexual content in templates. NSFW classifier on output. |
| Deepfake concerns | Low | High | Cartoon style (not photorealistic) significantly reduces deepfake risk. Add watermark/metadata. |

### Scaling Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| GPU shortage during peak hours | Medium | High | Queue-based architecture handles bursts. Priority queue for paying users. Pre-warm GPU pool. Multi-provider strategy. |
| Queue backlog grows uncontrollably | Low | Medium | Rate limiting on API. Queue depth monitoring + alerting. Auto-scaling workers. |
| S3 storage costs grow unexpectedly | Low | Low | TTL on intermediate artifacts (7 days). Lifecycle policies. Monitor storage growth. |
| Single GPU failure blocks all jobs | Medium | High | Multiple GPU workers. Health checks. Auto-replacement. |

### Cost Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Loop generation API price increases | Medium | High | Abstract behind interface. Have self-hosted SVD ready as fallback. Multi-provider strategy. |
| Retry storms inflate costs | Low | Medium | Max 3 retries per job. Dead-letter after exhaustion. Alert on retry rate > 10%. |
| GPU utilization too low (paying for idle) | Medium | Medium | Spot/preemptible instances. Shared GPU pool across steps. Auto-scaling to zero during off-peak. |
| Cost per clip exceeds $1 target | Low | High | Per-job cost tracking. Alert on jobs exceeding threshold. Fallback to cheaper pipeline (Variant 1). |

### Technical Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Whisper model update breaks alignment | Low | Medium | Pin model version. Regression tests on 50 reference tracks. |
| SDXL/Flux model deprecated | Low | Medium | Abstract model behind interface. Keep fallback models ready. |
| FFmpeg filter compatibility issues | Low | Low | Pin FFmpeg version in Docker. Integration tests for all filter chains. |
| Redis data loss | Low | High | Redis persistence (RDB + AOF). Job state also in PostgreSQL (source of truth). |

---

## Monitoring & Alerting Summary

### Key Alerts (PagerDuty/Telegram):

| Alert | Condition | Severity |
|-------|-----------|----------|
| High failure rate | > 10% jobs failed in last hour | P1 |
| Queue depth critical | > 50 jobs waiting > 10 min | P2 |
| Cost anomaly | Single job cost > $2 | P2 |
| GPU worker down | Health check failed 3× | P1 |
| Storage usage high | > 80% of budget | P3 |
| Latency spike | p95 > 10 minutes | P2 |

### Dashboards (Grafana):

1. **Operations:** Jobs/hour, success rate, queue depth, latency distribution
2. **Cost:** Cost per clip trend, cost breakdown by step, daily/weekly spend
3. **Quality:** Retry rate by step, cache hit rate, alignment confidence distribution
4. **Infrastructure:** GPU utilization, CPU usage, memory, S3 operations
