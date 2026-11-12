"""Fullgrade reports: before/after compare image, scopes, HTML slider report."""
import base64
import html
import io
import os

import numpy as np

try:
    from PIL import Image, ImageDraw, ImageFont
    HAVE_PIL = True
except ImportError:  # pragma: no cover
    HAVE_PIL = False

TXT = {
    "en": dict(before="Before", after="After", title="Fullgrade Report", preset="Preset",
               ratio="Ratio", shots="shots", shot="Shot", output="Output", bright="Brightness",
               sat="Saturation", cast="Cast", warm="warm/yellow", cool="cool/blue",
               neutral="neutral", drag="Drag the slider to compare", scopes="Scopes (waveform + histogram)",
               notes="Notes", range_note="Brightness of all shots after grading",
               comfort="comfort band", shot_count="shots", copied="Already looked good - copied without re-encoding",
               orig="Originals are never modified."),
    "zh": dict(before="调整前", after="调整后", title="Fullgrade 调色报告", preset="预设",
               ratio="比例", shots="个镜头", shot="镜头", output="输出", bright="亮度",
               sat="饱和度", cast="色偏", warm="偏暖/黄", cool="偏冷/蓝", neutral="中性",
               drag="左右拖动滑块对比", scopes="示波器（波形图 + 直方图）", notes="说明",
               range_note="调整后所有镜头的亮度", comfort="舒适区间", shot_count="镜头数",
               copied="素材本身已经不错，直接复制，未重新压缩", orig="原文件不会被修改。"),
}


def t(lang, key):
    return TXT.get(lang, TXT["en"])[key]


def find_font():
    cands = ["/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Medium.ttc",
             "/System/Library/Fonts/Hiragino Sans GB.ttc", "/Library/Fonts/Arial Unicode.ttf",
             "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
             "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
             "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    return next((c for c in cands if os.path.exists(c)), None)


def _font(size):
    fp = find_font()
    try:
        return ImageFont.truetype(fp, size) if fp else ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()


def stats_line(d, lang):
    cast = d["cast"] * 100
    tone = t(lang, "warm") if cast > 3 else (t(lang, "cool") if cast < -3 else t(lang, "neutral"))
    sep = " · "
    if lang == "zh":
        return f"{t(lang,'bright')} {d['bright']*100:.0f}{sep}{t(lang,'sat')} {d['sat']*100:.0f}{sep}{t(lang,'cast')} {cast:+.0f}（{tone}）"
    return f"{t(lang,'bright')} {d['bright']*100:.0f}{sep}{t(lang,'sat')} {d['sat']*100:.0f}{sep}{t(lang,'cast')} {cast:+.0f} ({tone})"


# --------------------------------------------------------------------------
def compare_image(rows, lang, preset_name, dst):
    """rows: list of (before PIL, after PIL)."""
    if not HAVE_PIL or not rows:
        return None
    portrait = any(im.height > im.width for r in rows for im in r)
    H = 560 if portrait else 360
    rows = [tuple(im.resize((max(1, round(im.width * H / im.height)), H)) for im in r) for r in rows]
    font, small = _font(26), _font(20)
    gap, top, foot = 16, 52, 40
    bw = max(r[0].width for r in rows)
    aw = max(r[1].width for r in rows)
    width = max(bw + aw + gap * 3, 420)
    canvas = Image.new("RGB", (width, top + len(rows) * (H + gap) + foot), (24, 24, 24))
    d = ImageDraw.Draw(canvas)
    x2 = gap * 2 + bw
    d.text((gap, 12), t(lang, "before"), fill=(220, 220, 220), font=font)
    d.text((x2, 12), t(lang, "after"), fill=(255, 210, 120), font=font)
    y = top
    for bimg, aimg in rows:
        canvas.paste(bimg, (gap, y))
        canvas.paste(aimg, (x2, y))
        y += H + gap
    d.text((gap, y + 4), f"Fullgrade · {preset_name}", fill=(160, 160, 160), font=small)
    canvas.save(dst, quality=90)
    return dst


# --------------------------------------------------------------------------
def _scope(arr):
    """Waveform (luma per column) + RGB histogram for one frame (H,W,3 uint8)."""
    im = Image.fromarray(arr).resize((256, max(2, round(256 * arr.shape[0] / arr.shape[1]))))
    a = np.asarray(im, dtype=np.float32) / 255.0
    L = a @ np.array([0.2126, 0.7152, 0.0722])
    wf = np.zeros((128, 256), np.float32)
    bins = np.clip((L * 127).astype(int), 0, 127)
    for x in range(256):
        wf[:, x] = np.bincount(bins[:, x], minlength=128)
    wf = np.sqrt(wf / max(wf.max(), 1)) * 255
    wave = np.zeros((128, 256, 3), np.uint8)
    wave[..., 1] = wf[::-1].astype(np.uint8)
    wave[..., 0] = (wf[::-1] * 0.6).astype(np.uint8)
    wave[..., 2] = (wf[::-1] * 0.6).astype(np.uint8)
    for lv in (0.1, 0.5, 0.9):                       # guide lines
        wave[int(127 - lv * 127), :, :] = 70
    hist = Image.new("RGB", (256, 128), (12, 12, 12))
    hd = ImageDraw.Draw(hist)
    q = (a * 255).astype(int).reshape(-1, 3)
    for c, col in enumerate([(230, 80, 80), (80, 210, 80), (90, 140, 255)]):
        h = np.bincount(q[:, c], minlength=256).astype(np.float32)
        h = h / max(np.percentile(h, 99.5), 1) * 120
        pts = [(x, 127 - min(127, h[x])) for x in range(256)]
        hd.line(pts, fill=col, width=1)
    out = Image.new("RGB", (520, 128), (12, 12, 12))
    out.paste(Image.fromarray(wave), (0, 0))
    out.paste(hist, (264, 0))
    return out


def scopes_image(before, after, lang):
    if not HAVE_PIL:
        return None
    f = _font(16)
    canvas = Image.new("RGB", (540, 128 * 2 + 3 * 24), (24, 24, 24))
    d = ImageDraw.Draw(canvas)
    d.text((10, 4), t(lang, "before"), fill=(200, 200, 200), font=f)
    canvas.paste(_scope(np.asarray(before)), (10, 26))
    d.text((10, 26 + 128 + 4), t(lang, "after"), fill=(255, 210, 120), font=f)
    canvas.paste(_scope(np.asarray(after)), (10, 26 + 128 + 26))
    return canvas


# --------------------------------------------------------------------------
def _b64(img, maxw=1100, quality=82):
    if img.width > maxw:
        img = img.resize((maxw, round(img.height * maxw / img.width)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


CSS = """
:root{--bg:#0f1012;--card:#17181b;--line:#2a2c31;--txt:#e9e7e2;--mute:#9a978f;--acc:#d9b26f}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);
font:15px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei","Segoe UI",sans-serif}
.wrap{max-width:1160px;margin:0 auto;padding:56px 28px 80px}
h1{font-size:40px;font-weight:600;letter-spacing:-.5px;margin:0 0 6px}
.sub{color:var(--mute);margin-bottom:40px}
.file{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:28px;margin:28px 0}
.file h2{font-size:22px;margin:0 0 4px;font-weight:600}.meta{color:var(--mute);font-size:13px;margin-bottom:18px}
.shot{margin:26px 0 8px}.shot h3{font-size:14px;color:var(--acc);margin:0 0 8px;font-weight:500;letter-spacing:.3px}
.cmp{position:relative;display:inline-block;max-width:100%;border-radius:10px;overflow:hidden;line-height:0;user-select:none}
.cmp img{display:block;max-width:100%;height:auto}
.cmp .after{position:absolute;inset:0;clip-path:inset(0 0 0 50%)}
.cmp .after img{width:100%;height:100%}
.cmp .bar{position:absolute;top:0;bottom:0;left:50%;width:2px;background:#fff;box-shadow:0 0 8px #0008;pointer-events:none}
.cmp input{position:absolute;inset:0;width:100%;height:100%;opacity:0;cursor:ew-resize;margin:0}
.tag{position:absolute;top:10px;padding:2px 10px;border-radius:20px;background:#000a;font-size:12px;line-height:20px}
.tag.l{left:10px}.tag.r{right:10px;color:var(--acc)}
.pair{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-start}.pair figure{margin:0}
.pair figcaption{font-size:12px;color:var(--mute);margin-top:4px}.pair img{max-height:520px;border-radius:10px;display:block}
.stats{font-size:13px;color:var(--mute);margin-top:8px}.stats b{color:var(--txt);font-weight:500}
details{margin-top:10px}summary{cursor:pointer;color:var(--mute);font-size:13px}
details img{margin-top:8px;border-radius:8px;max-width:100%}
.note{font-size:13px;color:var(--mute);margin:4px 0}.foot{color:var(--mute);font-size:12px;margin-top:40px}
"""

JS = """
document.querySelectorAll('.cmp input').forEach(function(r){r.addEventListener('input',function(){
var c=r.closest('.cmp');c.querySelector('.after').style.clipPath='inset(0 0 0 '+r.value+'%)';
c.querySelector('.bar').style.left=r.value+'%';});});
"""


def html_report(entries, dst, lang, preset_name, ratio_text, band, all_bright):
    if not HAVE_PIL:
        return None
    e = html.escape
    parts = [f"<!DOCTYPE html><html lang='{'zh-CN' if lang == 'zh' else 'en'}'><head><meta charset='utf-8'>"
             f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>{e(t(lang,'title'))}</title><style>{CSS}</style></head><body><div class='wrap'>"]
    sub = f"{t(lang,'preset')}: {e(preset_name)}"
    if ratio_text:
        sub += f" · {t(lang,'ratio')}: {e(ratio_text)}"
    if all_bright:
        sub += (f" · {t(lang,'range_note')}: {min(all_bright)*100:.0f}–{max(all_bright)*100:.0f}"
                f" ({t(lang,'comfort')} {band[0]*100:.0f}–{band[1]*100:.0f})")
    parts.append(f"<h1>{e(t(lang,'title'))}</h1><div class='sub'>{sub}<br>{e(t(lang,'orig'))}</div>")
    for ent in entries:
        parts.append(f"<div class='file'><h2>{e(ent['name'])}</h2>"
                     f"<div class='meta'>{t(lang,'output')}: {e(ent['out'])} · {len(ent['shots_all'])} {t(lang,'shots')}</div>")
        for n in ent.get("notes", []):
            parts.append(f"<div class='note'>• {e(n)}</div>")
        for s in ent["shots"]:
            parts.append(f"<div class='shot'><h3>{t(lang,'shot')} {s['idx']+1} · {s['a']:.1f}–{s['b']:.1f}s</h3>")
            bi, ai = s["before"], s["after"]
            if abs(bi.width / bi.height - ai.width / ai.height) < 0.02:
                ai2 = ai.resize(bi.size) if ai.size != bi.size else ai
                parts.append(
                    "<div class='cmp'>"
                    f"<img src='{_b64(bi)}' alt=''>"
                    f"<div class='after'><img src='{_b64(ai2)}' alt=''></div><div class='bar'></div>"
                    f"<span class='tag l'>{t(lang,'before')}</span><span class='tag r'>{t(lang,'after')}</span>"
                    "<input type='range' min='0' max='100' value='50' aria-label='compare'></div>"
                    f"<div class='note'>{t(lang,'drag')}</div>")
            else:
                parts.append(f"<div class='pair'><figure><img src='{_b64(bi, 900)}' alt=''><figcaption>{t(lang,'before')}</figcaption></figure>"
                             f"<figure><img src='{_b64(ai, 600)}' alt=''><figcaption>{t(lang,'after')}</figcaption></figure></div>")
            parts.append(f"<div class='stats'>{t(lang,'before')}: {e(stats_line(s['bs'], lang))}<br>"
                         f"<b>{t(lang,'after')}: {e(stats_line(s['as'], lang))}</b></div>")
            if s.get("scope") is not None:
                parts.append(f"<details><summary>{t(lang,'scopes')}</summary><img src='{_b64(s['scope'], 540, 88)}' alt=''></details>")
            parts.append("</div>")
        parts.append("</div>")
    parts.append(f"<div class='foot'>Fullgrade · MIT License</div></div><script>{JS}</script></body></html>")
    with open(dst, "w", encoding="utf-8") as f:
        f.write("".join(parts))
    return dst
