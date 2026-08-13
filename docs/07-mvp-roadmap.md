# MVP Roadmap — Parakeet Integration & Production Readiness

Status as of 2026-08-12. Written for the 2026-08-14 standup — treat as a
starting skeleton to adjust once DE-EN live testing results are in, not a
committed plan.

## Scope

**In scope for this MVP:**
- Finalize ASR engine choice (faster-whisper vs. Parakeet) from broader
  real-world testing, not just the initial spot-checks
- Model/DLL distribution and Windows installer packaging for whichever
  engine is chosen
- Config/UX for engine + device setup (currently requires hand-editing a
  YAML file in a hidden AppData folder)
- Broader QA across both directions (EN-DE, DE-EN), real speakers, real
  meeting conditions
- Explicit accept/fix decision on known ASR gaps (see "Known gaps" below)

**Explicitly out of scope — separate future projects, not MVP polish:**
- Streaming / rolling-decode architecture ("Part 2"). Latency headroom
  looks promising from testing so far, but it's a pipeline/concurrency
  rebuild, not a follow-on to the engine decision.
- Multi-participant capture and transcription. The app captures one local
  microphone only; capturing remote meeting audio too is a separate
  audio-pipeline project. Staying with the current one-speaker,
  one-direction-per-profile architecture as originally designed.

**Still undecided — needs an explicit yes/no, not a default:**
- Glossary / non-translatable-terms support. Real, scoped feature
  (placeholder-substitution approach sketched already) but not started.
  Decide in/out before anyone's estimate silently assumes either answer.

## Known gaps carried into MVP planning

- **Gibberish on hard/unfamiliar words:** confirmed both in structured
  testing (foreign proper nouns) and in today's live spot-check (a common
  compound word mangled differently across two takes). Compression-ratio
  and silence-rejection are shipped; per-word-confidence rejection was
  investigated and did not calibrate reliably on real data. Decide:
  ship as a documented known limitation, or invest in better calibration
  data first.
- **DE accuracy validated on a non-representative broadcast clip** — the
  natural-pause, meeting-style DE test is still outstanding.
- **Memory footprint** (~3.4-4.5x faster-whisper's, depending on
  quantization) — acceptable for target hardware or not, needs a decision
  tied to actual deployment targets, not just the raw number.

## Phased timeline (rough — adjust after Friday)

**Phase 1 — Decision & unblock — week of Aug 10, into Aug 17**
- Close out DE-EN live testing (in progress)
- Finalize engine choice
- Decide quantization level to ship (f16 vs. q8_0 — accuracy/memory
  tradeoff already measured)
- Model/DLL distribution — resolved this week (shared Drive)

**Phase 2 — Productionize — Aug 17 to Sep 6 (~3 weeks)**
- Fold DLL + model into the actual Windows installer/PyInstaller build —
  currently only wired at the source level, packaging untouched
- Config/UX for engine selection and setup
- Harden real-meeting failure modes (mic drop, model load failure —
  currently fatal per the architecture doc, worth an explicit call on
  whether that's MVP-acceptable)

**Phase 3 — QA & scope triage — Sep 7 to Sep 13 (~1 week)**
- Wider real-speaker test pool, both directions, real meeting conditions
- Explicit ship/fix decision on each "Known gap" above
- Glossary in/out decision, if not already made

**Phase 4 — Stabilize & ship — Sep 14 to Sep 20 (~1 week)**
- Bug fixing from QA
- User-facing docs (distinct from the dev setup doc in `docs/06`)
- Release sign-off

Target MVP: **week of Sep 21, 2026** (6 weeks from now). Tight if scope
quietly expands — worth reconfirming after Phase 1 closes.

## Workstream split (4 people, by workstream not headcount — adjust to skills)

1. **Packaging/distribution** — installer integration, owns the build
   pipeline, owned the shared-storage resolution
2. **ASR/accuracy** — finishes calibration testing, quantization decision,
   owns the confidence-gating ship/fix call
3. **Pipeline/reliability** — error handling, config/UX for engine +
   device setup, general hardening
4. **QA/test coordination** — runs the broader real-world test campaign,
   tracks go/no-go criteria, documents results

## Open decisions to close this week

- [ ] Engine choice: Parakeet or faster-whisper
- [ ] Quantization level to ship (if Parakeet)
- [ ] Glossary: in or out of MVP scope
- [ ] Mic-drop / model-load-failure handling: acceptable as-is (fatal) or
      needs hardening for MVP
