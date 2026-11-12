#!/usr/bin/env python3
"""
Fullgrade - automatic light & colour correction for video, as a Claude skill.

  probe -> HDR/LOG to SDR -> split into shots -> measure each shot ->
  one 3D LUT per shot (white balance, levels, exposure, contrast, saturation,
  look preset, optional reference match) -> optional dynamic exposure and
  denoise -> optional reframe (smart crop / blur pad / colour pad) ->
  single-pass ffmpeg render -> compare image + HTML report.

Originals are never modified. MIT License.
"""
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
for _s in (sys.stdout, sys.stderr):  # Windows consoles: never crash on Chinese / emoji
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import numpy as np
except ImportError:  # pragma: no cover
    sys.exit("numpy is missing. Run: python3 -m pip install numpy pillow\n"
             "缺少 numpy，请运行：python3 -m pip install numpy pillow")

import fg_core as core      # noqa: E402
import fg_report as rep     # noqa: E402

VERSION = "1.0.0"
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mts", ".m2ts", ".webm", ".3gp", ".mxf"}
RATIOS = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080),
          "4:5": (1080, 1350), "4:3": (1440, 1080), "3:4": (1080, 1440), "21:9": (2520, 1080)}

MSG = {
    "en": dict(
        start="Fullgrade {v} · preset: {p} · {n} video(s)",
        hdr="  · HDR detected (common on iPhone) -> converted to SDR",
        hdr_no="  · HDR detected but this ffmpeg has no zscale; colours may look grey",
        log="  · LOG profile: {p}",
        log_hint="  · This shot looks flat like LOG footage (D-Log / S-Log / V-Log / Apple Log). "
                 "If so, re-run with --log <camera>.",
        shots="  · {n} shot(s), {w}x{h}, {d:.1f}s",
        dynamic="  · shot {i}: brightness changes inside the shot -> dynamic exposure on",
        denoise="  · shot {i}: strong brightening -> light denoise on",
        face="  · shot {i}: face found -> crop follows the person",
        render="  · rendering…",
        copied="  ✅ already looked good -> copied without re-encoding: {o}",
        out="  ✅ output: {o}",
        cmp="  🖼  compare: {o}",
        fail="  ❌ failed: {e}",
        retry="  · retrying with safer settings…",
        report="\n📄 report: {o}",
        nofiles="No video files found.",
        nofound="Not found: {p}",
        badpreset="Unknown preset: {p}. Available: {a}",
        badratio="Unsupported ratio: {r}. Available: {a}",
        badlog="Unknown LOG profile: {p}. Available: slog3, vlog, dlog, applelog",
        noffmpeg="ffmpeg not found. Mac: brew install ffmpeg · Windows: winget install ffmpeg · Linux: sudo apt install ffmpeg",
        enc="  · encoder: {e}",
        summary="\nDone: {ok} OK, {bad} failed",
    ),
    "zh": dict(
        start="Fullgrade {v} · 预设：{p} · 共 {n} 个视频",
        hdr="  · 检测到 HDR（iPhone 常见），已自动转为 SDR",
        hdr_no="  · 检测到 HDR，但当前 ffmpeg 不支持 zscale，颜色可能发灰",
        log="  · LOG 素材：{p}",
        log_hint="  · 这段画面很灰很平，可能是 LOG 素材（D-Log / S-Log / V-Log / Apple Log）。"
                 "如果是，请加 --log <相机类型> 重新运行。",
        shots="  · {n} 个镜头，{w}x{h}，{d:.1f} 秒",
        dynamic="  · 镜头 {i}：镜头内亮度有变化 → 已开启动态亮度",
        denoise="  · 镜头 {i}：提亮较多 → 已开启轻度降噪",
        face="  · 镜头 {i}：检测到人脸 → 裁切跟随人物",
        render="  · 渲染中…",
        copied="  ✅ 素材本身已经不错 → 直接复制，未重新压缩：{o}",
        out="  ✅ 输出：{o}",
        cmp="  🖼  对比图：{o}",
        fail="  ❌ 失败：{e}",
        retry="  · 改用更稳妥的设置重试…",
        report="\n📄 报告：{o}",
        nofiles="没有找到视频文件。",
        nofound="找不到：{p}",
        badpreset="不认识的预设：{p}。可选：{a}",
        badratio="不支持的比例：{r}。可选：{a}",
        badlog="不认识的 LOG 类型：{p}。可选：slog3, vlog, dlog, applelog",
        noffmpeg="没有找到 ffmpeg。Mac：brew install ffmpeg · Windows：winget install ffmpeg · Linux：sudo apt install ffmpeg",
        enc="  · 编码器：{e}",
        summary="\n完成：成功 {ok} 个，失败 {bad} 个",
    ),
}
LANG = "en"


def say(key, **kw):
    print(MSG[LANG][key].format(**kw), flush=True)


def run(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


_FILTERS = None


def have_filter(name):
    global _FILTERS
    if _FILTERS is None:
        _FILTERS = run(["ffmpeg", "-hide_banner", "-filters"]).stdout.decode(errors="ignore")
    return re.search(rf"\s{re.escape(name)}\s", _FILTERS) is not None


def encoder_works(name):
    r = run(["ffmpeg", "-hide_banner", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=256x256:d=0.2",
             "-frames:v", "3", "-c:v", name, "-f", "null", "-"])
    return r.returncode == 0


def pick_encoder(fast):
    if not fast:
        return "libx264"
    cands = ["h264_videotoolbox"] if platform.system() == "Darwin" else ["h264_nvenc", "h264_qsv"]
    for c in cands:
        if encoder_works(c):
            return c
    return "libx264"


# --------------------------------------------------------------------------
# Probe / decode
# --------------------------------------------------------------------------
def probe(path):
    r = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)])
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe cannot read {path}")
    info = json.loads(r.stdout.decode(errors="ignore"))
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"
              and not (s.get("disposition") or {}).get("attached_pic")), None)
    if v is None:
        raise RuntimeError(f"no video stream in {path}")
    a = next((s for s in info["streams"] if s.get("codec_type") == "audio"), None)
    w, h = int(v["width"]), int(v["height"])
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(float(sd["rotation"]))
    if "rotate" in (v.get("tags") or {}):
        rot = int(float(v["tags"]["rotate"]))
    if abs(rot) % 180 == 90:
        w, h = h, w
    dur = float(v.get("duration") or info.get("format", {}).get("duration") or 0)
    trc = v.get("color_transfer", "") or ""
    pix = v.get("pix_fmt", "") or ""
    cs = (v.get("color_space") or "").lower()
    matrix = "bt2020" if cs.startswith("bt2020") else ("bt601" if cs in ("smpte170m", "bt470bg") else "bt709")
    return dict(w=w, h=h, dur=dur, hdr=trc in ("smpte2084", "arib-std-b67"),
                audio=a["codec_name"] if a else None, codec=v.get("codec_name", ""),
                deep=bool(re.search(r"(10|12|16)", pix)), full=v.get("color_range") == "pc",
                matrix=matrix)


def pre_chain(info, zs):
    if info["hdr"] and zs:
        return ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
                "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p,")
    return ""


def in_matrix(info, zs):
    return "bt709" if (info["hdr"] and zs) else info["matrix"]


def even(x):
    return max(2, int(round(x / 2.0)) * 2)


def sample_frames(path, info, zs, max_frames=240):
    dur = max(info["dur"], 0.5)
    fps = min(4.0, max(0.5, max_frames / dur))
    if info["w"] >= info["h"]:
        sw, sh = 256, even(256 * info["h"] / info["w"])
    else:
        sh, sw = 256, even(256 * info["w"] / info["h"])
    vf = (pre_chain(info, zs) +
          f"fps={fps:.4f},scale={sw}:{sh}:in_color_matrix={in_matrix(info, zs)},format=rgb24")
    r = run(["ffmpeg", "-v", "error", "-i", str(path), "-an", "-vf", vf, "-f", "rawvideo", "-"])
    buf = np.frombuffer(r.stdout, dtype=np.uint8)
    n = buf.size // (sw * sh * 3)
    if n == 0:
        raise RuntimeError("could not decode frames: " + r.stderr.decode(errors="ignore")[-400:])
    frames = buf[: n * sw * sh * 3].reshape(n, sh, sw, 3).astype(np.float32) / 255.0
    return frames, np.arange(n) / fps


def detect_cuts(path, info, zs, threshold=0.30, min_len=1.0):
    dur = info["dur"]
    if dur < 3:
        return [(0.0, dur)]
    vf = pre_chain(info, zs) + f"scale=160:-2,select='gt(scene,{threshold})',showinfo"
    r = run(["ffmpeg", "-hide_banner", "-i", str(path), "-an", "-vf", vf, "-f", "null", "-"])
    cuts = sorted(float(x) for x in re.findall(r"pts_time:([\d.]+)", r.stderr.decode(errors="ignore")))
    bounds = [0.0]
    for c in cuts:
        if c - bounds[-1] >= min_len and dur - c >= min_len:
            bounds.append(c)
    while len(bounds) > 60:  # keep the render graph small
        gaps = [bounds[i + 1] - bounds[i] for i in range(len(bounds) - 1)]
        bounds.pop(int(np.argmin(gaps[1:])) + 1)
    bounds.append(dur)
    return [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]


# --------------------------------------------------------------------------
# Reframing
# --------------------------------------------------------------------------
_CASCADE = None


def face_detector():
    global _CASCADE
    if _CASCADE is None:
        _CASCADE = False
        try:
            import cv2
            paths = [os.environ.get("FULLGRADE_FACE_CASCADE", "")]
            if getattr(cv2, "data", None) is not None:
                paths.append(os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml"))
            for p in paths:
                if p and os.path.exists(p):
                    c = cv2.CascadeClassifier(p)
                    if not c.empty():
                        _CASCADE = c
                        break
        except Exception:
            _CASCADE = False
    return _CASCADE or None


def face_center(frames, horizontal):
    det = face_detector()
    if det is None:
        return None
    import cv2
    hits = []
    idx = np.linspace(0, len(frames) - 1, min(len(frames), 10)).astype(int)
    for i in idx:
        g = (frames[i].mean(-1) * 255).astype(np.uint8)
        g = cv2.resize(g, (g.shape[1] * 2, g.shape[0] * 2))
        for (x, y, w, h) in det.detectMultiScale(g, 1.1, 5, minSize=(28, 28)):
            c = (x + w / 2) / g.shape[1] if horizontal else (y + h / 2) / g.shape[0]
            hits.append((c, w * h))
    if len(hits) < max(2, len(idx) // 3):
        return None
    c = np.array(hits)
    return float(np.average(c[:, 0], weights=c[:, 1]))


def crop_offset(frames, keep, horizontal):
    """0..1 position of the crop window: faces first, else detail energy + centre bias."""
    fc = face_center(frames, horizontal)
    if fc is not None:
        return float(np.clip((fc - keep / 2) / max(1 - keep, 1e-3), 0, 1)), True
    gray = frames.mean(-1)
    e = (np.abs(np.diff(gray, axis=2))[:, :-1, :] + np.abs(np.diff(gray, axis=1))[:, :, :-1]).mean(0)
    prof = e.mean(0) if horizontal else e.mean(1)
    n = len(prof)
    win = max(1, int(round(n * keep)))
    if win >= n:
        return 0.5, False
    cs = np.concatenate([[0], np.cumsum(prof)])
    scores = cs[win:] - cs[:-win]
    pos = np.arange(len(scores))
    centre = (len(scores) - 1) / 2
    prior = 1 - 0.35 * ((pos - centre) / max(centre, 1)) ** 2
    return int(np.argmax(scores * prior)) / max(len(scores) - 1, 1), False


def keep_fraction(info, target):
    W, H = target
    a, b = info["w"] / info["h"], W / H
    return min(a / b, b / a), a > b


def reframe_chain(info, target, mode, off, pad_color, i):
    W0, H0 = info["w"], info["h"]
    if target is None:
        return f"scale={even(W0)}:{even(H0)}"
    W, H = target
    src_ar, dst_ar = W0 / H0, W / H
    if abs(src_ar - dst_ar) < 0.01:
        return f"scale={W}:{H}"
    keep = min(src_ar / dst_ar, dst_ar / src_ar)
    if mode == "auto":
        mode = "crop" if keep >= 0.6 else "blur"
    if mode == "crop":
        if src_ar > dst_ar:
            cw = min(even(H0 * dst_ar), W0 - W0 % 2)
            return f"crop={cw}:{H0 - H0 % 2}:{int(round(off * (W0 - cw)))}:0,scale={W}:{H}"
        ch = min(even(W0 / dst_ar), H0 - H0 % 2)
        return f"crop={W0 - W0 % 2}:{ch}:0:{int(round(off * (H0 - ch)))},scale={W}:{H}"
    if mode == "color":
        return (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={pad_color}")
    sw, sh = even(W / 6), even(H / 6)
    return (f"split=2[bg{i}][fg{i}];"
            f"[bg{i}]scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh},"
            f"boxblur=8:2,scale={W}:{H},eq=brightness=-0.05:saturation=0.85[bgo{i}];"
            f"[fg{i}]scale={W}:{H}:force_original_aspect_ratio=decrease[fgo{i}];"
            f"[bgo{i}][fgo{i}]overlay=(W-w)/2:(H-h)/2")


# --------------------------------------------------------------------------
# Dynamic exposure (brightness that drifts inside one shot)
# --------------------------------------------------------------------------
def dynamic_plan(fr, ft, a, b, threshold=0.10):
    """Return [(t_rel, eq_gamma)] keyframes, or None if the shot is steady."""
    if b - a < 3 or len(fr) < 6:
        return None
    br = core.frame_brightness(fr)
    keys = np.arange(0, b - a + 1e-6, 1.0)
    vals = []
    for k in keys:
        sel = np.abs((ft - a) - k) <= 0.75
        vals.append(br[sel].mean() if sel.any() else np.nan)
    vals = np.array(vals)
    ok = ~np.isnan(vals)
    if ok.sum() < 3:
        return None
    vals = np.interp(keys, keys[ok], vals[ok])
    if vals.max() - vals.min() < threshold:
        return None
    med = float(np.median(vals))
    g = np.log(np.clip(vals, 0.03, 0.97)) / np.log(np.clip(med, 0.03, 0.97))
    g = np.clip(g ** 0.7, 0.70, 1.45)
    return list(zip(keys.tolist(), g.tolist()))


def dynamic_expr(plan):
    expr = f"{plan[-1][1]:.4f}"
    for (t0, g0), (t1, g1) in reversed(list(zip(plan[:-1], plan[1:]))):
        expr = f"if(lt(t,{t1:.3f}),{g0:.4f}+({g1 - g0:.4f})*(t-{t0:.3f})/{t1 - t0:.3f},{expr})"
    return f"eq=gamma='{expr}':eval=frame"


def apply_dynamic_to_frames(fr, ft, a, plan):
    keys = np.array([p[0] for p in plan])
    gs = np.array([p[1] for p in plan])
    g = np.interp(ft - a, keys, gs)
    return np.power(fr, 1.0 / g[:, None, None, None])


# --------------------------------------------------------------------------
# Render
# --------------------------------------------------------------------------
def build_graph(info, zs, shots, chains):
    n = len(shots)
    head = f"[0:v]{pre_chain(info, zs)}split={n}" + "".join(f"[s{i}]" for i in range(n))
    parts = [head]
    for i, ((a, b), ch) in enumerate(zip(shots, chains)):
        end = "" if i == n - 1 else f":end={b:.4f}"
        parts.append(f"[s{i}]trim=start={a:.4f}{end},setpts=PTS-STARTPTS,{ch},setsar=1[v{i}]")
    parts.append("".join(f"[v{i}]" for i in range(n)) +
                 f"concat=n={n}:v=1:a=0,scale=out_color_matrix=bt709:out_range=tv,format=yuv420p[vout]")
    return ";".join(parts)


def encode(path, out, info, graph, encoder, args, tmp):
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
           "-i", str(Path(path).resolve()), "-filter_complex", graph,
           "-map", "[vout]", "-map", "0:a:0?"]
    if encoder == "libx264":
        cmd += ["-c:v", "libx264", "-crf", str(args.crf),
                "-preset", "slow" if args.quality == "best" else "veryfast"]
    else:
        px = (RATIOS[args.ratio][0] * RATIOS[args.ratio][1]) if args.ratio else info["w"] * info["h"]
        cmd += ["-c:v", encoder, "-b:v", "16M" if px <= 2_100_000 else "45M"]
    cmd += ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]
    if info["audio"] in ("aac", "mp3", "alac"):
        cmd += ["-c:a", "copy"]
    elif info["audio"]:
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    cmd += ["-movflags", "+faststart", str(Path(out).resolve())]
    r = subprocess.run(cmd, cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return r.returncode == 0, r.stderr.decode(errors="ignore")[-1200:]


def grab(path, t, vf, dst):
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{max(t, 0):.3f}", "-i", str(path),
         "-frames:v", "1", "-vf", vf, str(dst)])
    if Path(dst).exists() and rep.HAVE_PIL:
        from PIL import Image
        return Image.open(dst).convert("RGB")
    return None


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def load_presets(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith("_")}


def resolve_preset(presets, name):
    n = name.strip().lower()
    for k, v in presets.items():
        if n == k.lower() or n in [a.lower() for a in v.get("aliases", [])]:
            return k
    return None


def collect_inputs(paths, recursive):
    files = []
    for p in paths:
        p = Path(p).expanduser()
        if p.is_dir():
            it = p.rglob("*") if recursive else p.iterdir()
            for f in sorted(it):
                if (f.is_file() and f.suffix.lower() in VIDEO_EXT and "_graded" not in f.parts
                        and not f.name.startswith(".")):
                    files.append((f, p))
        elif p.is_file():
            files.append((p, p.parent))
        else:
            say("nofound", p=p)
    return files


def unique(path):
    """Never overwrite: name.mp4 -> name_v2.mp4 -> name_v3.mp4 ..."""
    path = Path(path)
    base, i = path.stem, 2
    while path.exists():
        path = path.with_name(f"{base}_v{i}{path.suffix}")
        i += 1
    return path


def check_env():
    ok = True
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool):
            print(f"✅ {tool}")
        else:
            ok = False
            print(f"❌ {tool} — " + MSG[LANG]["noffmpeg"])
    print("✅ numpy")
    print("✅ Pillow (reports)" if rep.HAVE_PIL else "⚠️  Pillow missing — no compare images/report: python3 -m pip install pillow")
    if shutil.which("ffmpeg"):
        print("✅ HDR → SDR (zscale)" if have_filter("zscale") else "⚠️  ffmpeg without zscale: iPhone HDR may look grey")
        enc = pick_encoder(True)
        print(f"✅ hardware encoder: {enc}" if enc != "libx264" else "ℹ️  no hardware encoder (normal speed export)")
    try:
        import cv2  # noqa
        print("✅ OpenCV face-aware crop" if face_detector() else "ℹ️  OpenCV present, face model not found")
    except ImportError:
        print("ℹ️  OpenCV not installed (optional, for face-aware crop): python3 -m pip install opencv-python-headless")
    return ok


def main(argv=None):
    global LANG
    presets_path = HERE.parent / "presets.json"
    ap = argparse.ArgumentParser(prog="fullgrade", description="Fullgrade: automatic light & colour correction for video")
    ap.add_argument("inputs", nargs="*", help="video files and/or folders")
    ap.add_argument("--preset", default="natural", help="natural | real-estate | warm | vivid | cool-modern | cinematic (or alias)")
    ap.add_argument("--presets-file", default=str(presets_path))
    ap.add_argument("--ratio", default=None, help="9:16 16:9 1:1 4:5 4:3 3:4 21:9 (default: keep)")
    ap.add_argument("--fit", default="auto", choices=["auto", "crop", "blur", "color"])
    ap.add_argument("--pad-color", default="black")
    ap.add_argument("--strength", type=float, default=1.0, help="0-1 overall correction strength")
    ap.add_argument("--log", default=None, help="camera LOG: slog3 | vlog | dlog | applelog")
    ap.add_argument("--match", default=None, help="reference video/image, or 'hero' to match the best shot")
    ap.add_argument("--match-method", default="mkl", choices=["mkl", "reinhard", "hist"])
    ap.add_argument("--match-strength", type=float, default=0.5)
    ap.add_argument("--dynamic", default="auto", choices=["auto", "on", "off"])
    ap.add_argument("--denoise", default="auto", choices=["auto", "on", "off"])
    ap.add_argument("--no-split", action="store_true", help="treat each file as one shot")
    ap.add_argument("--no-sharpen", action="store_true")
    ap.add_argument("--recursive", action="store_true")
    ap.add_argument("--out", default=None, help="output folder (default: <input folder>/_graded)")
    ap.add_argument("--fast", action="store_true", help="hardware encoder if available")
    ap.add_argument("--quality", default="normal", choices=["normal", "best"])
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--lang", default="en", choices=["en", "zh"])
    ap.add_argument("--analyze-only", action="store_true")
    ap.add_argument("--no-report", action="store_true")
    ap.add_argument("--export-luts", default=None, help="write each preset look as .cube into this folder")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--version", action="version", version=f"Fullgrade {VERSION}")
    args = ap.parse_args(argv)
    LANG = args.lang

    if args.check:
        return 0 if check_env() else 1
    if args.selftest:
        import fg_selftest
        return fg_selftest.run(HERE / "fullgrade.py", args.lang)
    presets = load_presets(args.presets_file)
    if args.export_luts:
        os.makedirs(args.export_luts, exist_ok=True)
        for k, P in presets.items():
            core.write_cube(Path(args.export_luts) / f"fullgrade_{k}.cube", core.look_model(P),
                            title=f"Fullgrade {P['name']['en']}")
        print(f"LUTs -> {args.export_luts}")
        return 0
    if not args.inputs:
        ap.print_help()
        return 1
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        say("noffmpeg")
        return 1

    key = resolve_preset(presets, args.preset)
    if key is None:
        say("badpreset", p=args.preset, a=", ".join(presets))
        return 1
    P = presets[key]
    pname = P["name"].get(LANG, P["name"]["en"])
    target = None
    if args.ratio:
        r = args.ratio.replace("x", ":").replace("：", ":").replace("/", ":")
        if r not in RATIOS:
            say("badratio", r=args.ratio, a=" ".join(RATIOS))
            return 1
        args.ratio = r
        target = RATIOS[r]
    log = None
    if args.log:
        log = core.LOG_ALIASES.get(args.log.strip().lower())
        if log is None:
            say("badlog", p=args.log)
            return 1
    strength = float(np.clip(args.strength, 0.0, 1.0))
    zs = have_filter("zscale")
    encoder = pick_encoder(args.fast)
    files = collect_inputs(args.inputs, args.recursive)
    if not files:
        say("nofiles")
        return 1
    say("start", v=VERSION, p=pname, n=len(files))
    if encoder != "libx264":
        say("enc", e=encoder)

    ref_px = None
    if args.match and args.match.lower() != "hero":
        mp = Path(args.match).expanduser()
        if not mp.is_file():
            say("nofound", p=mp)
            return 1
        if mp.suffix.lower() not in VIDEO_EXT and not rep.HAVE_PIL:
            print("Pillow is needed for an image reference: python3 -m pip install pillow")
            return 1
        if mp.suffix.lower() in VIDEO_EXT:
            mi = probe(mp)
            fr, _ = sample_frames(mp, mi, zs, max_frames=40)
            ref_px = fr.reshape(-1, 3)
        else:
            from PIL import Image
            im = Image.open(mp).convert("RGB")
            im.thumbnail((320, 320))
            ref_px = np.asarray(im, dtype=np.float32).reshape(-1, 3) / 255.0
        ref_px = ref_px[:: max(1, len(ref_px) // 150000)]

    # ---------- pass 1: analyse every file and solve every shot ----------
    jobs, failed, md = [], [], []
    for f, root in files:
        try:
            info = probe(f)
            if log:
                info["hdr"] = False  # LOG decoding replaces the HDR tone-map
            frames, times = sample_frames(f, info, zs)
            shots = [(0.0, info["dur"])] if args.no_split else detect_cuts(f, info, zs)
            job = dict(f=f, root=root, info=info, frames=frames, times=times, shots=shots, items=[])
            for i, (a, b) in enumerate(shots):
                sel = (times >= a - 1e-3) & (times < b)
                if not sel.any():
                    sel = np.zeros(len(times), bool)
                    sel[int(np.argmin(np.abs(times - (a + b) / 2)))] = True
                fr, ft = frames[sel], times[sel]
                plan = None
                if args.dynamic != "off" and not log:
                    plan = dynamic_plan(fr, ft, a, b, 0.04 if args.dynamic == "on" else 0.10)
                fr_eff = apply_dynamic_to_frames(fr, ft, a, plan) if plan else fr
                step = max(1, fr.shape[0] * fr.shape[1] * fr.shape[2] // 120000)
                px = fr_eff.reshape(-1, 3)[::step]
                job["items"].append(dict(a=a, b=b, fr=fr, px=px, px_raw=fr.reshape(-1, 3)[::step], plan=plan))
            jobs.append(job)
        except Exception as e:
            print(f"\n{f.name}")
            say("fail", e=e)
            failed.append(f.name)
            md.append(f"## {f.name}\n- ❌ {e}")

    def solve_all(match_for):
        for job in list(jobs):
            try:
                for it in job["items"]:
                    it["m"] = core.solve_shot(it["px"], P, log=log, tv=not job["info"]["full"],
                                              match=match_for(it), strength=strength)
            except Exception as e:  # one bad file must not stop the batch
                print(f"\n{job['f'].name}")
                say("fail", e=e)
                failed.append(job["f"].name)
                md.append(f"## {job['f'].name}\n- ❌ {e}")
                jobs.remove(job)

    solve_all(lambda it: None)
    if args.match:
        if args.match.lower() == "hero":
            allit = [it for j in jobs for it in j["items"]]
            def score(it):
                d = core.describe(core.apply_model(it["px"], it["m"]))
                return abs(d["bright"] - P["target"]) + abs(d["cast"]) + (it["b"] - it["a"] < 1.5) * 0.2
            if len(allit) > 1:
                hero = min(allit, key=score)
                hero_px = core.apply_model(hero["px"], hero["m"])
                solve_all(lambda it: None if it is hero else core.build_match(
                    core.apply_model(it["px"], it["m"]), hero_px, args.match_method, args.match_strength))
        elif ref_px is not None:
            solve_all(lambda it: core.build_match(core.apply_model(it["px"], it["m"]), ref_px,
                                                  args.match_method, args.match_strength))

    # ---------- pass 2: render ----------
    entries, all_bright, done = [], [], 0
    for idx, job in enumerate(jobs, 1):
        f, info, items = job["f"], job["info"], job["items"]
        print(f"\n[{idx}/{len(jobs)}] {f.name}", flush=True)
        tmp = None
        try:
            if info["hdr"]:
                say("hdr" if zs else "hdr_no")
            if log:
                say("log", p=core.LOG_PROFILES[log][2])
            say("shots", n=len(items), w=info["w"], h=info["h"], d=info["dur"])
            out_dir = Path(args.out).expanduser() if args.out else job["root"] / "_graded"
            try:
                rel = f.parent.relative_to(job["root"])
            except ValueError:
                rel = Path()
            out_dir = out_dir / rel
            out_dir.mkdir(parents=True, exist_ok=True)
            tmp = tempfile.mkdtemp(prefix="fullgrade_")
            chains, notes, changed = [], [], False
            for i, it in enumerate(items):
                raw = it["px_raw"]
                p_disp = core.log_to_display(raw, log, not info["full"]) if log else raw
                after = core.apply_model(it["px"], it["m"])
                cm = core.neutral_mask(after)  # pixels that end up neutral: measure cast on these
                it["bs"] = core.describe(p_disp, core.blown_mask(p_disp), cm)
                it["as"] = core.describe(after, core.blown_mask(
                    core.log_to_display(it["px"], log, not info["full"]) if log else it["px"]), cm)
                all_bright.append(it["as"]["bright"])
                if not log and i == 0 and core.looks_like_log(it["bs"]):
                    say("log_hint")
                    notes.append(MSG[LANG]["log_hint"].strip().lstrip("· "))
                cube = f"shot{i:03d}.cube"
                core.write_cube(Path(tmp) / cube, it["m"])
                change = core.lut_change(it["m"])
                changed |= change > 0.02 or bool(it["plan"])
                ch = []
                if it["plan"]:
                    ch.append(dynamic_expr(it["plan"]))
                    say("dynamic", i=i + 1)
                    notes.append(MSG[LANG]["dynamic"].format(i=i + 1).strip().lstrip("· "))
                ratio_b = core.brightening(it["bs"], it["as"])
                if args.denoise == "on" or (args.denoise == "auto" and ratio_b > 1.45):
                    ch.append("hqdn3d=3:2.5:4:4" if ratio_b > 2.0 or args.denoise == "on" else "hqdn3d=1.5:1.5:3:3")
                    if args.denoise == "auto":
                        say("denoise", i=i + 1)
                        notes.append(MSG[LANG]["denoise"].format(i=i + 1).strip().lstrip("· "))
                fmt = "gbrp16le" if info["deep"] else "gbrp"
                ch.append(f"scale=in_color_matrix={in_matrix(info, zs)},format={fmt},"
                          f"lut3d=file={cube}:interp=tetrahedral")
                off = 0.5
                if target:
                    k, horiz = keep_fraction(info, target)
                    off, face = crop_offset(it["fr"], k, horiz)
                    mode = args.fit if args.fit != "auto" else ("crop" if k >= 0.6 else "blur")
                    if face and mode == "crop":
                        say("face", i=i + 1)
                        notes.append(MSG[LANG]["face"].format(i=i + 1).strip().lstrip("· "))
                ch.append(reframe_chain(info, target, args.fit, off, args.pad_color, i))
                if P["sharpen"] and not args.no_sharpen:
                    ch.append(f"unsharp=5:5:{P['sharpen'] * strength:.3f}:5:5:0")
                chains.append(",".join(ch))

            if args.analyze_only:
                for i, it in enumerate(items):
                    print(f"  {it['a']:6.1f}-{it['b']:6.1f}s  {rep.t(LANG,'before')}: {rep.stats_line(it['bs'], LANG)}")
                    print(f"  {'':15}{rep.t(LANG,'after')}: {rep.stats_line(it['as'], LANG)}")
                done += 1
                continue

            suffix = f"_{key}" + (f"_{args.ratio.replace(':', 'x')}" if target else "")
            copied = (not changed and target is None and not info["hdr"] and not log)
            if copied:
                out = unique(out_dir / f"{f.stem}{suffix}{f.suffix.lower()}")
                shutil.copy2(f, out)
                say("copied", o=out)
            else:
                out = unique(out_dir / f"{f.stem}{suffix}.mp4")
                say("render")
                graph = build_graph(info, zs, job["shots"], chains)
                ok, err = encode(f, out, info, graph, encoder, args, tmp)
                if not ok:  # safety net: software encoder, no dynamic / denoise
                    say("retry")
                    if out.exists():
                        out.unlink()
                    safe = [re.sub(r"^eq=gamma='.*?':eval=frame,", "", c) for c in chains]
                    safe = [re.sub(r"hqdn3d=[\d.:]+,", "", c) for c in safe]
                    ok, err = encode(f, out, info, build_graph(info, zs, job["shots"], safe), "libx264", args, tmp)
                if not ok:
                    raise RuntimeError(err)
                say("out", o=out)

            # ---------- reports ----------
            entry = dict(name=f.name, out=out.name, shots_all=items, shots=[], notes=notes)
            if rep.HAVE_PIL and not args.no_report:
                # beginning, middle and end of the video (skip very short shots when possible)
                cand = [i for i in range(len(items)) if items[i]["b"] - items[i]["a"] >= 1.0] or list(range(len(items)))
                order = sorted({cand[int(round(x))] for x in np.linspace(0, len(cand) - 1, min(3, len(cand)))})
                rows = []
                for k_, i in enumerate(order):
                    it = items[i]
                    tm = it["a"] + (it["b"] - it["a"]) * 0.5
                    bimg = grab(f, tm, pre_chain(info, zs) + f"scale=-2:720:in_color_matrix={in_matrix(info, zs)}", Path(tmp) / f"b{k_}.png")
                    aimg = grab(out, tm, "scale=-2:720", Path(tmp) / f"a{k_}.png")
                    if bimg is None or aimg is None:
                        continue
                    rows.append((bimg, aimg))
                    entry["shots"].append(dict(idx=i, a=it["a"], b=it["b"], before=bimg, after=aimg,
                                               bs=it["bs"], as_=it["as"], scope=rep.scopes_image(bimg, aimg, LANG)))
                for s in entry["shots"]:
                    s["as"] = s.pop("as_")
                cdir = out_dir / "compare"
                cdir.mkdir(exist_ok=True)
                cpath = rep.compare_image(rows, LANG, pname, cdir / f"{out.stem}_compare.jpg")
                if cpath:
                    say("cmp", o=cpath)
            entries.append(entry)
            md.append(f"## {f.name}\n- {rep.t(LANG, 'output')}: `{out.name}`"
                      + (f" ({rep.t(LANG, 'copied')})" if copied else "")
                      + f"\n- {rep.t(LANG, 'shot_count')}: {len(items)}" + "".join(f"\n- {n}" for n in notes))
            for it in items:
                md.append(f"- {it['a']:.1f}–{it['b']:.1f}s: {rep.stats_line(it['bs'], LANG)} → **{rep.stats_line(it['as'], LANG)}**")
            done += 1
        except Exception as e:
            say("fail", e=e)
            failed.append(f.name)
            md.append(f"## {f.name}\n- ❌ {e}")
        finally:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)

    say("summary", ok=done, bad=len(failed))
    code = 0 if not failed else (2 if done else 1)
    if args.analyze_only or not md:
        return code
    rdir = Path(args.out).expanduser() if args.out else files[0][1] / "_graded"
    rdir.mkdir(parents=True, exist_ok=True)
    head = [f"# {rep.t(LANG,'title')}\n\n{rep.t(LANG,'preset')}: **{pname}**"
            + (f" · {rep.t(LANG,'ratio')}: {args.ratio} ({args.fit})" if target else "")]
    if all_bright:
        head.append(f"\n{rep.t(LANG,'range_note')}: {min(all_bright)*100:.0f}–{max(all_bright)*100:.0f} "
                    f"({rep.t(LANG,'comfort')} {P['target']*100:.0f}–{P['ceil']*100:.0f})\n")
    (rdir / "fullgrade_report.md").write_text("\n".join(head + md) + "\n", encoding="utf-8")
    if entries and rep.HAVE_PIL and not args.no_report:
        h = rep.html_report(entries, rdir / "fullgrade_report.html", LANG, pname,
                            f"{args.ratio} ({args.fit})" if target else "", (P["target"], P["ceil"]), all_bright)
        say("report", o=h)
    else:
        say("report", o=rdir / "fullgrade_report.md")
    return code


if __name__ == "__main__":
    t0 = time.time()
    code = main()
    sys.exit(code)
