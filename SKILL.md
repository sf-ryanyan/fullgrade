---
name: fullgrade
description: Automatic light and colour correction for videos (auto colour grade, fix exposure, white balance, brightness, make clips match; 自动调色/调光影/统一颜色/白平衡/曝光). Fixes dark, yellow, blue, over-exposed, grey or flat clips, decodes LOG footage (DJI D-Log, Sony S-Log3, Panasonic V-Log, Apple Log) and iPhone HDR, grades each shot of a finished edit separately, applies a look preset (natural, real-estate, warm, vivid, cool-modern, cinematic) and reframes to 9:16 / 16:9 / 1:1 / 4:5 without stretching. One file or a whole folder; originals are never changed. Use for any request to colour-correct, grade, brighten, unify colours or change the aspect ratio of videos. Not for cutting/editing the story.
---

# Fullgrade

Automatic, gentle colour correction for video. Everything runs locally with ffmpeg + Python; no GPU, no cloud API, almost no tokens (the analysis is done by the script, not by looking at frames).

**Language:** reply in the user's language. If the user writes Chinese, pass `--lang zh` so the report and compare images are in Chinese; otherwise `--lang en`.

## 1. Environment (first run, or when something fails)

```bash
python3 <skill_dir>/scripts/fullgrade.py --check
```

If something is missing, tell the user the one command they need:

| Missing | macOS | Windows | Linux |
|---|---|---|---|
| ffmpeg | `brew install ffmpeg` | `winget install ffmpeg` | `sudo apt install ffmpeg` |
| numpy / Pillow | `python3 -m pip install numpy pillow` (add `--break-system-packages` if pip refuses) |||
| face-aware crop (optional) | `python3 -m pip install opencv-python-headless` |||

Run the script on the machine where the videos are. If the files were uploaded into a sandbox, run it there and send the outputs back.
On Windows use `python` instead of `python3` if `python3` is not found.

Optional: `python3 <skill_dir>/scripts/fullgrade.py --selftest` builds synthetic footage and checks every feature (about 2–3 minutes). Use it if the user asks "does it work on my computer?".

## 2. Turn the request into one command

```bash
python3 <skill_dir>/scripts/fullgrade.py <files-or-folders> [options] --lang <en|zh>
```

| The user says… | Option |
|---|---|
| nothing about style / "just fix it" / 自然 | `--preset natural` (default) |
| real estate, interior, bright & airy / 房产, 明亮通透 | `--preset real-estate` |
| warm, cozy, evening / 温暖, 温馨 | `--preset warm` |
| vivid, food, product / 鲜艳, 美食 | `--preset vivid` |
| clean, cool, modern, tech / 清冷, 现代 | `--preset cool-modern` |
| cinematic, film look, vlog / 电影感 | `--preset cinematic` |
| vertical, TikTok, Reels, Shorts, 抖音, 小红书 | `--ratio 9:16` |
| YouTube, landscape / 横屏 | `--ratio 16:9` |
| square / Instagram feed | `--ratio 1:1` or `--ratio 4:5` |
| fill the frame, no bars / 裁切 | `--fit crop` |
| keep the whole picture / 不要裁, 补边 | `--fit blur` |
| black / white bars | `--fit color --pad-color black` (or `white`) |
| drone / DJI D-Log | `--log dlog` |
| Sony S-Log3 · Panasonic V-Log · iPhone Apple Log | `--log slog3` · `--log vlog` · `--log applelog` |
| make everything match this clip / photo | `--match <file>` (`--match-method mkl` default; `reinhard`, `hist`) |
| make all clips match each other closely | `--match hero` |
| lighter touch / don't overdo it / 轻一点 | `--strength 0.6` |
| faster export | `--fast` (Apple / NVIDIA / Intel hardware encoder, auto fallback) |
| best quality | `--quality best` |
| include sub-folders | `--recursive` |
| only check, no export | `--analyze-only` |
| one grade for the whole file | `--no-split` |
| LUT files for Premiere / DaVinci / Final Cut / CapCut | point to `<skill_dir>/luts/` (or `--export-luts <folder>`) |

Defaults that are already right for most people: `--fit auto` (crop if it keeps ≥60% of the picture, otherwise blurred background — so 16:9 ↔ 9:16 uses blurred background unless the user asks to crop), `--dynamic auto`, `--denoise auto`.

Do not ask about the ratio unless the user mentions it — keep the original. Ask only when the request is truly unclear (for example they say "LOG" but not which camera).

## 3. What happens (explain briefly only if asked)

1. iPhone HDR → SDR automatically; LOG decoded when `--log` is given (the script warns when a clip *looks* like LOG).
2. A finished edit is split into shots (scene detection); every shot is graded on its own.
3. Per shot: white balance → black/white levels (highlights protected) → exposure into a comfort band → contrast → saturation → preset look → optional match. Baked into one 3D LUT per shot with safety limits, so it never overdoes it.
4. Brightness that drifts inside a shot (walking from a dark hall into a bright room) is smoothed (dynamic exposure). Strongly brightened shots get light denoise.
5. Reframing never stretches; smart crop follows faces (if OpenCV is installed) or the most detailed area.
6. A clip that already looks right is copied without re-encoding.

Speed: processing takes about 1–3× the video length for 1080p (4K takes longer). For long or many files, tell the user it is running and wait; do not cancel. Use `--fast` if they are in a hurry.

**Exit code:** `0` = all done · `2` = some files failed (others are fine — the end of the output lists `Done: X OK, Y failed` and the report shows why) · `1` = nothing could be processed. Always tell the user which files failed and why (common causes: not a video, damaged file, audio-only file).

## 4. Outputs

- Videos: `<input folder>/_graded/<name>_<preset>[_9x16].mp4` — never overwrites (adds `_v2`), originals untouched.
- `_graded/compare/*_compare.jpg` — before/after stills. **Always show at least one to the user.**
- `_graded/fullgrade_report.html` — before/after sliders, numbers and scopes for every shot. Offer it.
- `_graded/fullgrade_report.md` — the same numbers as text; read it to write your summary.

## 5. Reply

Short summary in the user's language: how many videos, which preset/ratio, where the files are, one or two sentences on what changed (from the report, e.g. "shot 2 was very yellow and is now neutral; the window highlights were protected"), the compare image(s), and one useful next step (another preset, a 9:16 version, `--strength` if they want it lighter).

## Honest limits

- Pure-white blown windows/skies cannot be recovered; the rest of the picture is still improved.
- Very dark footage shows noise when brightened (light denoise helps, it is not magic).
- Mixed light in one shot (orange lamp + blue daylight) is balanced as a compromise.
- Dissolves between two very different shots may show a small step at the cut.
- DJI **D-Log M** and other LOG curves not listed are not supported in V1 — grade them without `--log` and use `--strength`.
