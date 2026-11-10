# X1T Zilem — container-only MP4 method

X1T Zilem is the default preset in FPS Patcher Studio 2.1.1. It rewrites an
MP4 container without touching a single encoded video or audio sample. There is
no FFmpeg call, no re-encode, and no quality loss.

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
the problem and, where relevant, points to `X1T 1080p` for a lossy re-encode.

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
by definition. Use `X1T 1080p` or `X1T 60fps` for a lossy re-encode, or remux
the source to AAC-LC 48 kHz stereo MP4 first.

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
- the rebuilt movie has two audio tracks, the expected durations, and the
  expected tag;
- the movie duration is finite and matches the longest video/audio track.

A failure raises `VerifyError`; the partial output is removed and the source is
never modified.

## Reference provenance and the golden test

The method was derived from a real reference pair:

- source: an H.264 1080p60 MP4 with AAC-LC 48 kHz stereo;
- reference: the same media after the Zilem v1 transform.

The reference was built with the original tag
`TikQuick Quality Method - https://tikquick.online/ - v25 - Orion`, plus a
71-byte `free` trailer. Production builds use only the neutral
`X1T Zilem v1` tag and omit the trailer.

The 161 MB reference media is not committed. To run the golden test locally:

```powershell
$env:FPS_ZILEM_SOURCE = "E:\path\to\source.mp4"
$env:FPS_ZILEM_REFERENCE = "E:\path\to\reference.mp4"
uv run pytest tests/test_zilem_patcher.py::test_golden_fixture_matches_reference -q
```

The test is skipped when either variable is unset or the file is missing.
With the fixtures present it asserts that the patcher output equals the
reference minus its 71-byte trailer, byte for byte.

## Limits

- X1T Zilem preserves the source video bitstream exactly, so it cannot improve
  resolution, frame rate, codec, or bitrate.
- It does not claim that TikTok or any other platform will skip transcoding.
  Matching a container fingerprint is not proof of upload behaviour.
- It cannot process fragmented MP4 or more than one video/audio track.
- It does not write the reference's 71-byte trailer and does not use the
  original reference tag or any TikQuick/ZETA branding.
