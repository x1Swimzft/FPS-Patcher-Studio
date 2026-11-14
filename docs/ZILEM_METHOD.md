# X1T Zilem — container-only MP4 method

The default preset, `X1T 1080p`, uses the Zilem method in FPS Patcher Studio
2.3.0. It rewrites an MP4 container without touching a single encoded video or
audio sample. There is no FFmpeg call, no re-encode, and no quality loss.

The method reproduces the Zilem v1 container fingerprint: the reference file
generated with the method's original tag is matched byte-for-byte, except for
the reference's 71-byte trailing `free` box, which the production patcher does
not write.

## Accepted sources

A file must satisfy all of these conditions:

- Non-fragmented ISO-BMFF MP4 (`.mp4` or `.m4v`; a `.mov` file is also accepted
  when it uses the same box layout).
- Exactly one video track, using H.264 (`avc1` or `avc3`).
- Exactly one audio track, AAC (`mp4a`) with:
  - an AudioSpecificConfig whose first 13 bits describe AAC-LC, 48 kHz, stereo;
  - 2 channels and a 48,000 Hz sample rate in the sample entry;
  - a variable-size sample table (`stsz` with a per-sample size table).
- A 32-bit chunk-offset table (`stco`, not `co64`), and a final file size below
  4 GiB.

Fragmented MP4 (`moof`/`mvex`), multiple video or audio tracks, HEVC/AV1/VP9
video, non-AAC audio, 44.1 kHz audio, mono audio, and fixed-size audio sample
tables are rejected before any output is written. The rejection message names
the problem and, where relevant, tells you to convert the source to H.264 first.

## What the patch changes

The source bytes are copied unchanged. Only the following container structures
change:

1. **Old `moov` becomes `free`.** The four bytes at `moov_offset + 4` are
   rewritten from `moov` to `free`. The rest of the box, including its size and
   payload, stays byte-identical. Players therefore ignore the old metadata.
2. **Silent audio tail.** A new `mdat` box containing 17 six-byte AAC-LC silence
   frames (`21 10 04 60 8c 1c`) is appended: 110 bytes total. That is 17,408
   audio samples at 48 kHz, or about 0.3627 s.
3. **Extended audio track.** The original audio track's timing tables are
   extended by those 17 samples:
   - `stts`: `+17` samples at 1,024 samples per frame;
   - `stsz`: 17 additional sample sizes of 6 bytes;
   - `stsc`: two new chunk entries (9 frames, then 8 frames);
   - `stco`: two new chunk offsets pointing into the appended `mdat`;
   - `stbl` roll groups (`sgpd`/`sbgp`) extended to cover the new samples;
   - `mdhd`, `tkhd`, and `elst` durations extended by the same audio time.
4. **Duplicate audio track.** A second audio track is created with a new track
   ID (usually 4) and the next `next_track_ID`. It shares the same chunk
   offsets, so it adds no media bytes. Its sample description contains one
   entry, while the primary audio track carries the original entry plus an
   alternate sample entry.
5. **Neutral tag.** The video track gains `udta/meta/ilst/©too` with the UTF-8
   tag `X1T Zilem v1`. Existing per-track metadata is kept. The old
   movie-level `udta` is dropped.
6. **Movie header.** `mvhd` duration is set to the longest track duration and
   `next_track_ID` is advanced past the new track. If the source has the
   indeterminate duration `-1` (`0xFFFFFFFF` in version 0 or
   `0xFFFFFFFFFFFFFFFF` in version 1), that value is ignored and replaced with
   the longest finite video/audio track duration. Mobile players and upload
   services can otherwise reject a file whose movie duration never resolves.
7. **New `moov` at EOF.** The rebuilt movie box is written after the appended
   audio data. The top-level order becomes:

   ```
   ftyp, free(old moov), mdat(source), mdat(silence), moov(rebuilt)
   ```

The output is named `<stem>_zilem.mp4` unless a filename template is enabled.
The target FPS setting is ignored: no video timing table or timescale is
changed.

## What the preset skips

X1T Zilem deliberately bypasses the generic MP4 preflight and the colour and
metadata rewriter:

- preflight audio normalisation, bitrate cap, VFR-to-CFR, codec fallback, and
  resolution caps are not run;
- `--tag-bt709` and `--scrub-metadata` are ignored with a clear
  `[COLOR] skipped` log line, because rewriting `colr`/`udta` would break the
  reproduced container fingerprint;
- target timescale, `--preset`, and `--timescale` do not alter the output.

If the source needs a preflight change, the source is incompatible with Zilem
by definition. Convert it to a compatible H.264/AAC-LC MP4 first; the hidden
`tiktok-ts` and `tiktok-ts-1080` presets remain available from the CLI for a
lossy re-encode.

## X1T 1080p (reference-exact Zilem)

`X1T 1080p` (`zilem-v3`, alias `x1t-zilem-v3`) is the default preset: the same
byte-preserving transform with the original reference tag and the reference
trailer restored. It is not the same preset as `X1T 1080p Re-encode`, which is
the hidden lossy letterbox path.

Differences from `X1T Zilem`:

1. The video track tag is
   `TikQuick Quality Method - https://tikquick.online/ - v25 - Orion`.
2. A `free` box is appended after the rebuilt `moov` with the payload
   `ZETA_OPTIMIZED/3 <YYYY-MM-DDTHH:MM:SS.mmmZ> <output filename>`.
   The timestamp is the UTC build time. The filename is the final output name,
   including a ` (n)` collision suffix. The box size follows the payload, so it
   is 71 bytes only when the output name is 21 characters.

The transform, preflight skips, source validation and output naming are
identical to `X1T Zilem`. Because the tag and trailer are part of the
fingerprint, the verifier checks the exact tag text and the exact trailer bytes,
and requires `moov` at `source size + 110` rather than as the last box.

## X1T 1080p Mobile (reference-exact single-audio-track Zilem)

`X1T 1080p Mobile` (`zilem-mobile`, alias `x1t-zilem-mobile`) reproduces a
second, incompatible reference build of the same method: one video track, **one**
audio track, no movie-level metadata, and a small filler `mdat` before the
rebuilt `moov`. It is not a variant of `X1T 1080p`; the two outputs differ in
size, audio track count and sample map.

The reference pair used for verification:

| item | value |
| --- | --- |
| source | `Deppart Prototype 1.mp4`, 258,100,994 bytes |
| reference | `Deppart Prototype 1_zilem.mp4`, 258,181,333 bytes |

Output layout:

| offset | box | size |
| --- | --- | --- |
| 0 | `ftyp` (isom/iso2/avc1/mp41) | 32 |
| 32 | `free` (the old `moov`, type bytes rewritten) | 80,132 |
| 80,164 | `free` (the source's own padding box) | 8 |
| 80,172 | `mdat` (source media, payload byte-identical) | 258,020,822 |
| 258,100,994 | `mdat` filler: four 15-byte samples | 68 |
| 258,101,062 | rebuilt `moov` | 80,192 |
| 258,181,254 | `free` `ZETA_OPTIMIZED/3 <stamp> <filename>` | 79 |

The filler sample is a fixed 15-byte constant of that build:
`a0 98 00 40 01 28 00 64 00 00 03 50 00 00 38` (`TAIL_FRAME` in
`src/fps_patcher/core/zilem_patcher.py`).

Every leaf box is byte-identical to the source except these four changes:

1. `moov/udta` is removed (the source's movie-level `©too`).
2. The video track gains a 150-byte `udta/meta/ilst/©too` holding the reference
   tag; every other video byte is unchanged.
3. Audio `stsz` keeps its sample count and its leading sample sizes, but the last
   four sizes become `15, 15, 15, 15`.
4. Audio `stsc` and `stco` gain one chunk at the end: `stsc` becomes
   `(1,24,1), (192,20,1), (193,4,1)` and `stco` appends the offset
   `source size + 8`, the payload of the filler `mdat`.

`mvhd`, the audio `tkhd`/`mdhd` durations, `stsd`, `stts`, `sgpd` and `sbgp` are
copied untouched, so the movie duration and the media duration are unchanged.
The audio track is **not** duplicated and no silence is appended.

The four original AAC frames that the replaced `stsz` entries used to describe
(about 85 ms) are dropped from the sample map and stay in the source `mdat` as
unreferenced bytes. That is a property of the method and is reproduced, not
fixed: a player decodes the four filler samples instead, which is inaudible at
the end of the track.

**Matching this container byte-for-byte does not prove that TikTok or any other
service skips transcoding.** Only the container transform is reproducible
offline; server-side behaviour is unverifiable and not claimed.

Output naming, source validation, preflight skips and the output filename in the
trailer are the same as `X1T 1080p`. `verify_zilem_tail_output()` is the
matching verifier: it requires one video and one audio track, no movie-level
`udta`, the exact filler `mdat`, unchanged `mvhd`/audio timing payloads, the
rebuilt chunk map and the exact trailer bytes.


## Verification

`verify_zilem_output()` checks the produced file against the source before the
temporary output is promoted:

- output size equals source size + 110-byte silence `mdat` + rebuilt `moov`;
- the file ends with the rebuilt `moov` and has no trailing bytes;
- `ftyp` is unchanged;
- the old `moov` is now a `free` box with the same size and an unchanged
  payload;
- every source `mdat` payload hash is unchanged;
- the appended `mdat` contains exactly the 17 expected silence frames;
- the rebuilt movie has two audio tracks (the original extended track plus the
  chunk-sharing duplicate), the expected durations, and the expected tag;
- the movie duration is finite and matches the longest video/audio track.

`verify_zilem_tail_output()` is the verifier for `X1T 1080p Mobile`; it is
listed in that preset's section above.

A failure raises `VerifyError`; the partial output is removed and the source is
never modified.

## Reference provenance and the golden test

The method was derived from a real reference pair:

- source: an H.264 1080p60 MP4 with AAC-LC 48 kHz stereo;
- reference: the same media after the Zilem v1 transform.

The reference was built with the original tag
`TikQuick Quality Method - https://tikquick.online/ - v25 - Orion`, plus a
71-byte `free` trailer. The hidden `zilem` preset writes the neutral
`X1T Zilem v1` tag and omits the trailer; the default `X1T 1080p` reproduces
the original tag and trailer exactly.

The 161 MB reference media is not committed. To run the v1 golden test locally:

```powershell
$env:FPS_ZILEM_SOURCE = "E:\path\to\source.mp4"
$env:FPS_ZILEM_REFERENCE = "E:\path\to\reference.mp4"
uv run pytest tests/test_zilem_patcher.py::test_golden_fixture_matches_reference -q
```

For the reference-exact V3 output:

```powershell
$env:FPS_ZILEM_V3_SOURCE = "E:\path\to\source.mp4"
$env:FPS_ZILEM_V3_REFERENCE = "E:\path\to\reference.mp4"
uv run pytest tests/test_zilem_patcher.py::test_golden_v3_fixture_matches_reference -q
```

For the single-audio-track mobile output:

```powershell
$env:FPS_ZILEM_MOBILE_SOURCE = "E:\path\to\source.mp4"
$env:FPS_ZILEM_MOBILE_REFERENCE = "E:\path\to\reference.mp4"
uv run pytest tests/test_zilem_patcher.py::test_golden_mobile_fixture_matches_reference -q
```

All three tests skip when their variables are unset or the files are missing.
The v1 test compares the patcher output with the reference minus its trailer.
The V3 and mobile tests read the timestamp and filename from the reference
trailer, build with those exact values, and assert full byte equality.

## Limits

- X1T Zilem preserves the source video bitstream exactly, so it cannot improve
  resolution, frame rate, codec, or bitrate.
- It does not claim that TikTok or any other platform will skip transcoding.
  Matching a container fingerprint is not proof of upload behaviour.
- It cannot process fragmented MP4 or more than one video/audio track.
- The hidden `zilem` preset does not write the reference trailer and does not
  use the original reference tag. Only the default `X1T 1080p` does, to
  reproduce the reference fingerprint exactly.
