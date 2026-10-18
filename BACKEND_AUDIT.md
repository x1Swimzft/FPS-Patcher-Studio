# Backend Audit — FPS Patcher Studio

Updated: 2026-10-09

## Summary

The project has four distinct strategy paths. Routing and FFmpeg capability separation are covered by automated tests. This audit intentionally separates verified local behavior from hypotheses about platform ingestion.

## Findings and changes in this implementation pass

### Fixed: hash-unavailable false PASS

**Finding:** the forensic result exposed `match = not changed`. If both hashes were empty/unavailable, that expression incorrectly reported MATCH.

**Change:** `ForensicDiffResult` now includes `mdat_hash_verified`, `video_payload_verified`, and `audio_payload_verified`. Match properties require both a completed hash comparison and equality. JSON exports include verification flags. UI and `verify_payload_integrity` present unavailable hashes as `UNKNOWN` / `CHECK` rather than PASS.

### Fixed: incomplete track payload hashing

**Finding:** old track hashing could hash a partial set of sample slices, accept samples merely within file bounds, and ignore unsupported/incomplete mappings.

**Change:** analyzer checks complete sample mapping, sample/chunk counts, complete sample extents, and containment within one declared `mdat` payload range. Adds `stz2` support for 4-, 8-, and 16-bit compact sample sizes. Returns empty hash when complete verification is impossible.

### Fixed: multiple `mdat` boxes

**Finding:** analyzer kept only the final `mdat` hash, which could miss changes in earlier `mdat` payloads.

**Change:** all top-level `mdat` payload segments are fed to one SHA-256 hash in file order. A regression test proves changing the first of two `mdat` payloads changes the result.

### Fixed: strict V4 post-patch gate

**Finding:** V4 previously skipped sample payload comparisons when hashes were unavailable and did not enforce structural/sample-table/offset validation before success.

**Change:** strict V4 now requires `VALID` top-level atom structure, valid chunk offsets/extents, valid static sample tables, available `mdat` hash, available video sample hash, available audio sample hash when an audio track exists, and expected target timescale. On strict verification failure, the generated output is removed (the source is untouched). Non-strict mode labels its reduced validation clearly.

### Fixed: BXD input truncation and unsafe output replacement

**Finding:** BXD reconstructed only `ftyp`/`moov`/first `mdat`, silently discarded unsupported root atoms, and wrote directly to the destination before validation. Input/output could also resolve to the same path.

**Change:** BXD now refuses same-path operation, malformed/trailing input bytes, unsupported root atoms, duplicate required boxes, and multiple `mdat` boxes. It preserves legal root `free` boxes emitted by FFmpeg, validates a staged temporary output, and replaces the destination only after hard checks pass. Tests confirm source preservation and that existing output is not clobbered on rejected input.

### Fixed: unsupported BXD marketing claims

**Finding:** docstrings implied a guaranteed TikTok 1080p bypass and universal losslessness, while the algorithm can append unboxed trailing bytes.

**Change:** BXD is labelled experimental/non-standard. Output log explicitly says structure and receiver behavior remain unverified. No platform-resolution guarantee is made.

## Current architecture

- `src/fps_patcher/core/strategies.py`: strategy identifiers and aliases.
- `src/fps_patcher/core/patcher.py`: strategy dispatch.
- `src/fps_patcher/core/prober.py`: external probe plus direct fallback.
- `src/fps_patcher/core/atom_patcher.py`: direct atom operations.
- `src/fps_patcher/core/v4_patcher.py`: strict V4 patch pipeline.
- `src/fps_patcher/core/bxd_patcher.py`: experimental/non-standard transformation.
- `src/fps_patcher/core/forensic_analyzer.py`: atom tree, semantic/binary diff, hashes.
- `src/fps_patcher/core/verifier.py`: structure/table/offset/payload integrity validators.
- `src/fps_patcher/ui/theme.py`: theme tokens and Windows backdrop integration.
- `src/fps_patcher/ui/forensic_window.py`: forensic comparison UI; hash-unavailable statuses are not treated as matches.

## Test evidence

- `PYTHONPATH='/mnt/data/test-deps:src' python -m pytest -q` — **81 passed**.
- `python -m compileall -q src tests` — passed.
- Ruff and mypy — not run in the current sandbox; executable dependencies were not installed and network install was unavailable.
- Windows UI screenshot/manual QA — not performed in this environment.

## Outstanding risks / limitations

1. BXD output may include unboxed trailing bytes and must remain opt-in/experimental. It is not guaranteed to be valid for every player or platform.
2. V4 rejects fragmented MP4. The verifier is not a full ISO-BMFF conformance implementation.
3. V4 reads the whole file into memory, which can be costly for large source files.
4. The basic `direct-atom` strategy does not automatically inherit V4 strict validation.
5. Glass blur depends on Windows/DWM; cross-platform appearance is a fallback, not identical native transparency.
6. No evidence in this repository proves that any method affects TikTok's server-side output resolution. That behavior remains not verified.

## Recommended next actions

See `NEXT_STEPS.md` and use `AI_NEXT_REVIEW_PROMPT.md` for the next independent review.
