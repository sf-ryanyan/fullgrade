"""Fullgrade self-test: builds synthetic room footage with typical problems,
runs the main features and checks the results. No real footage needed."""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fg_core as core  # noqa: E402

RNG = np.random.default_rng(7)


def _room(kind, W=1600, H=900):
    """Simple procedural interior: wall, wood floor, bright window, furniture."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    img = np.zeros((H, W, 3), np.float32)
    wall = {"living": (0.88, 0.85, 0.79), "bedroom": (0.84, 0.87, 0.89), "kitchen": (0.94, 0.94, 0.92)}[kind]
    horizon = int(H * 0.68)
    img[:horizon] = wall
    boards = ((xx[horizon:] + (yy[horizon:] - horizon) * (xx[horizon:] - W / 2) / H * 0.8) // 55).astype(int)
    tone = 0.85 + 0.25 * ((boards * 37) % 11) / 10
    img[horizon:] = np.stack([0.60 * tone, 0.42 * tone, 0.27 * tone], -1)
    wx, wy, ww, wh = int(W * 0.58), int(H * 0.12), int(W * 0.27), int(H * 0.42)
    img[wy:wy + wh, wx:wx + ww] = (0.98, 0.98, 0.98)
    img[wy + 12:wy + wh - 12, wx + 12:wx + ww - 12] = (0.78, 0.88, 0.97)
    img[wy + int(wh * 0.55):wy + wh - 12, wx + 12:wx + ww - 12] = (0.47, 0.65, 0.43)
    if kind == "kitchen":
        for k in range(4):
            x = 80 + k * 170
            img[int(H * .15):int(H * .38), x:x + 150] = (0.97, 0.97, 0.96)
            img[horizon - 210:horizon + 30, x:x + 150] = (0.95, 0.95, 0.94)
        img[horizon - 230:horizon - 205, 60:780] = (0.22, 0.22, 0.24)
    else:
        sofa = (0.47, 0.49, 0.51) if kind == "living" else (0.92, 0.91, 0.88)
        img[horizon - 170:horizon + 70, 120:800] = sofa
        img[horizon - 260:horizon - 150, 160:760] = sofa
        for k in range(3):
            img[horizon - 210:horizon - 130, 200 + k * 190:320 + k * 190] = (0.27, 0.43, 0.55)
        img[int(H * .18):int(H * .40), 280:640] = (0.15, 0.15, 0.15)
        img[int(H * .19):int(H * .39), 290:630] = (0.75, 0.63, 0.47)
        rug = ((xx - W * 0.75) / 300) ** 2 + ((yy - horizon - 90) / 90) ** 2 < 1
        img[rug] = (0.80, 0.76, 0.70)
    light = 0.75 + 0.35 * np.exp(-(((xx - wx - ww / 2) / 800) ** 2 + ((yy - H * 0.33) / 550) ** 2))
    img = img * light[..., None] + RNG.normal(0, 0.01, img.shape).astype(np.float32)
    return np.clip(img, 0, 1)


def _degrade(a, kind):
    if kind == "dark":
        return np.clip(np.power(a * 0.55, 1.35), 0, 1)
    if kind == "yellow":
        return np.clip(a * np.array([1.12, 0.98, 0.68]) * 0.85, 0, 1)
    if kind == "blown":
        return np.clip(0.18 + a * 1.25, 0, 1)
    if kind == "flat_cool":
        a = 0.16 + a * 0.62
        L = core.luma(a)[..., None]
        return np.clip((L + (a - L) * 0.6) * np.array([0.9, 0.98, 1.1]), 0, 1)
    return a


def _slog3_encode(img):
    """Display image -> linear -> S-Gamut3.Cine -> S-Log3 code -> tv-range RGB."""
    lin = np.power(img, 2.2) * 0.6
    M = np.linalg.inv(core._gamut_to_709("s-gamut3.cine"))
    lin = np.maximum(lin @ M.T, 0)
    code = np.where(lin >= 0.01125, (420 + np.log10((lin + 0.01) / 0.19) * 261.5) / 1023,
                    (lin * (171.2102946929 - 95) / 0.01125 + 95) / 1023)
    return np.clip((code * 1023 - 64) / 876, 0, 1)


def _write(path, frames_fn, size, n, fps=30, audio=False, extra=None):
    W, H = size
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(fps), "-i", "-"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=330:duration={n / fps}", "-c:a", "aac", "-shortest"]
    cmd += (extra or ["-c:v", "libx264", "-crf", "20", "-preset", "veryfast", "-pix_fmt", "yuv420p"]) + [str(path)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(n):
        p.stdin.write((frames_fn(i / max(n - 1, 1)) * 255).astype(np.uint8).tobytes())
    p.stdin.close()
    p.wait()


def _pan(img, size, zoom=1.12):
    from PIL import Image
    W, H = size
    Hs, Ws = img.shape[:2]
    s = max(W / Ws, H / Hs) * zoom
    big = np.asarray(Image.fromarray((img * 255).astype(np.uint8)).resize((int(Ws * s), int(Hs * s)))) / 255.0
    def fn(t):
        x = int((big.shape[1] - W) * (0.2 + 0.6 * t))
        y = (big.shape[0] - H) // 2
        return big[y:y + H, x:x + W]
    return fn


def make_footage(d):
    d = Path(d)
    living, bedroom, kitchen = _room("living"), _room("bedroom"), _room("kitchen")
    S = (1280, 720)
    _write(d / "living_dark.mp4", _pan(_degrade(living, "dark"), S), S, 90, audio=True)
    _write(d / "bedroom_yellow.mp4", _pan(_degrade(bedroom, "yellow"), S), S, 90)
    _write(d / "window_blown.mp4", _pan(_degrade(living, "blown"), S), S, 90)
    _write(d / "kitchen_vertical.mp4", _pan(_degrade(kitchen, "flat_cool"), (720, 1280)), (720, 1280), 90)
    # one "edited" file with three different shots
    parts = [_pan(_degrade(kitchen, "dark"), S), _pan(_degrade(bedroom, "yellow"), S), _pan(_degrade(living, "blown"), S)]
    _write(d / "edited_tour.mp4", lambda t: parts[min(int(t * 3), 2)]((t * 3) % 1.0), S, 270, audio=True)
    # brightness drifting inside one shot (walking from a dark hall into a bright room)
    base = _pan(living, S)
    _write(d / "walk_in.mp4", lambda t: np.clip(base(t) * (0.35 + 0.75 * t), 0, 1), S, 150)
    # LOG footage (S-Log3)
    (d / "log").mkdir(exist_ok=True)
    _write(d / "log" / "drone_slog3.mp4", _pan(_slog3_encode(living), S), S, 60)
    return d


def _probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format",
                        str(path)], stdout=subprocess.PIPE)
    return json.loads(r.stdout.decode())


def _dur(info):
    return float(info["format"]["duration"])


def _vstream(info):
    return next(s for s in info["streams"] if s["codec_type"] == "video")


def run(script, lang="en"):
    if not shutil.which("ffmpeg"):
        print("ffmpeg not found")
        return 1
    tmp = Path(tempfile.mkdtemp(prefix="fullgrade_selftest_"))
    print(f"Self-test folder: {tmp}")
    print("1/5 building synthetic footage…", flush=True)
    make_footage(tmp)
    py = sys.executable
    results = []

    def check(name, cond, detail=""):
        results.append((name, bool(cond), detail))
        print(f"   {'PASS' if cond else 'FAIL'}  {name} {detail}", flush=True)

    def go(*a):
        r = subprocess.run([py, str(script), *a, "--lang", lang], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return r.returncode, r.stdout.decode(errors="ignore")

    print("2/5 grading the folder (default preset)…", flush=True)
    code, outp = go(str(tmp))
    check("run finished", code == 0 and "❌" not in outp, "" if code == 0 else outp[-600:])
    g = tmp / "_graded"
    for src in sorted(tmp.glob("*.mp4")):
        out = g / f"{src.stem}_natural.mp4"
        alt = g / f"{src.stem}_natural.mp4"
        ok = out.exists() or alt.exists()
        check(f"output for {src.name}", ok)
        if ok:
            a, b = _probe(src), _probe(out)
            check(f"  same duration {src.name}", abs(_dur(a) - _dur(b)) < 0.15, f"{_dur(a):.2f}s vs {_dur(b):.2f}s")
            va, vb = _vstream(a), _vstream(b)
            check(f"  same size {src.name}", (va["width"], va["height"]) == (vb["width"], vb["height"]))
            has_a = any(s["codec_type"] == "audio" for s in a["streams"])
            check(f"  audio kept {src.name}", has_a == any(s["codec_type"] == "audio" for s in b["streams"]))
    rep_ok = (g / "fullgrade_report.html").exists() and (g / "fullgrade_report.md").exists()
    check("reports written", rep_ok)
    md = (g / "fullgrade_report.md").read_text(encoding="utf-8") if rep_ok else ""
    sec = {blk.split("\n", 1)[0].strip(): blk for blk in md.split("## ")[1:]}
    check("edited file split into 3 shots", re.search(r"(shots|镜头数): 3", sec.get("edited_tour.mp4", "")) is not None)
    check("dynamic exposure on walk_in", any(w in sec.get("walk_in.mp4", "") for w in ("dynamic", "动态")))
    import re as _re
    br = [float(x) for x in _re.findall(r"→ \*\*\D*?(\d+)", md)]
    check("all shots inside a comfortable brightness band", br and min(br) >= 40 and max(br) <= 72, f"{br}")

    print("3/5 aspect ratios…", flush=True)
    code, outp = go(str(tmp / "edited_tour.mp4"), "--ratio", "9:16", "--preset", "real-estate", "--out", str(tmp / "r916"))
    o = tmp / "r916" / "edited_tour_real-estate_9x16.mp4"
    check("9:16 blur-pad render", code == 0 and o.exists())
    if o.exists():
        v = _vstream(_probe(o))
        check("  1080x1920, square pixels", (v["width"], v["height"]) == (1080, 1920) and v.get("sample_aspect_ratio", "1:1") in ("1:1", "0:1"))
    code, outp = go(str(tmp / "kitchen_vertical.mp4"), "--ratio", "16:9", "--fit", "crop", "--out", str(tmp / "r169"))
    o = tmp / "r169" / "kitchen_vertical_natural_16x9.mp4"
    check("16:9 crop render", code == 0 and o.exists())
    if o.exists():
        v = _vstream(_probe(o))
        check("  1920x1080", (v["width"], v["height"]) == (1920, 1080))

    print("4/5 LOG footage (S-Log3) …", flush=True)
    code, outp = go(str(tmp / "log"), "--log", "slog3")
    o = tmp / "log" / "_graded" / "drone_slog3_natural.mp4"
    check("S-Log3 render", code == 0 and o.exists(), outp[-400:] if code else "")
    code2, outp2 = go(str(tmp / "log"), "--analyze-only")
    check("LOG hint shown when --log is missing", "LOG" in outp2)

    print("5/5 every preset + reference match…", flush=True)
    presets = [k for k in json.loads((HERE.parent / "presets.json").read_text(encoding="utf-8")) if not k.startswith("_")]
    for p in presets:
        code, outp = go(str(tmp / "bedroom_yellow.mp4"), "--preset", p, "--out", str(tmp / "presets"), "--no-report")
        check(f"preset {p}", code == 0 and (tmp / "presets" / f"bedroom_yellow_{p}.mp4").exists())
    code, outp = go(str(tmp / "living_dark.mp4"), "--match", str(tmp / "bedroom_yellow.mp4"), "--out", str(tmp / "match"), "--no-report")
    check("match to reference video", code == 0 and any((tmp / "match").glob("*.mp4")))
    code, outp = go(str(tmp), "--match", "hero", "--match-method", "reinhard", "--out", str(tmp / "hero"), "--no-report")
    check("hero match across folder", code == 0 and len(list((tmp / "hero").glob("*.mp4"))) >= 6)

    bad = [r for r in results if not r[1]]
    print(f"\nRESULT: {len(results) - len(bad)}/{len(results)} checks passed")
    if bad:
        print("Failed:", ", ".join(b[0] for b in bad))
    else:
        print(f"All good. Look at {g / 'fullgrade_report.html'} to see the before/after.")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(run(HERE / "fullgrade.py"))
