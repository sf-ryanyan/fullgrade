"""Fullgrade colour engine: measurement, correction model, LOG decoding,
reference matching and 3D LUT output. Pure numpy, no GPU."""
import numpy as np

LUMA = np.array([0.2126, 0.7152, 0.0722])

# Safety limits: gentle on purpose ("better under-corrected than over-done")
LIM = dict(gain=(0.76, 1.32), gamma=(0.60, 1.45), stretch=(1.0, 1.60),
           sat=(0.85, 1.30), contrast=(0.0, 0.22))


def luma(p):
    return p @ LUMA


# --------------------------------------------------------------------------
# Measurement
# --------------------------------------------------------------------------
def blown_mask(p):
    """Pixels blown out in the source. Nothing can bring them back, so they
    are excluded from the brightness measurement before AND after."""
    keep = luma(p) < 0.97
    return keep if keep.mean() > 0.3 else np.ones(len(p), bool)


def neutral_mask(p):
    L = luma(p)
    m = ((p.max(1) - p.min(1)) / np.maximum(L, 1e-3) < 0.25) & (L > 0.15) & (L < 0.95)
    return m if m.sum() > 200 else None


def describe(p, keep=None, cast_mask=None):
    """cast_mask lets before/after be measured on the SAME pixels."""
    L = luma(p)
    Lb = L[keep] if keep is not None else L
    bright = 0.5 * Lb.mean() + 0.5 * np.median(Lb)
    mx, mn = p.max(1), p.min(1)
    chroma = (mx - mn)[(L > 0.08) & (L < 0.95)]
    sat = float(chroma.mean()) if chroma.size else 0.0
    if cast_mask is None:
        cast_mask = neutral_mask(p)
    q = p[cast_mask] if cast_mask is not None else p
    cast = float((q[:, 0] - q[:, 2]).mean())  # >0 warm/yellow, <0 cool/blue
    return dict(bright=float(bright), sat=sat, cast=cast,
                black=float(np.percentile(L, 0.5)), white=float(np.percentile(L, 99.5)),
                std=float(L.std()))


def frame_brightness(frames):
    """Per-frame brightness (same metric as describe) for an (N,H,W,3) stack."""
    L = frames.reshape(len(frames), -1, 3) @ LUMA
    out = []
    for row in L:
        keep = row[row < 0.97] if (row < 0.97).mean() > 0.3 else row
        out.append(0.5 * keep.mean() + 0.5 * np.median(keep))
    return np.array(out)


def looks_like_log(d):
    """Flat, lifted, desaturated footage is often LOG (D-Log, S-Log, V-Log...)."""
    return d["black"] > 0.08 and d["white"] < 0.80 and d["std"] < 0.14 and d["sat"] < 0.10


# --------------------------------------------------------------------------
# LOG decoding (camera log -> scene linear -> Rec.709 display)
# --------------------------------------------------------------------------
def _rgb_to_xyz(prims, white=(0.3127, 0.3290)):
    xy = np.array(prims, dtype=np.float64)
    XYZ = np.stack([xy[:, 0] / xy[:, 1], np.ones(3), (1 - xy[:, 0] - xy[:, 1]) / xy[:, 1]])
    wx, wy = white
    W = np.array([wx / wy, 1.0, (1 - wx - wy) / wy])
    S = np.linalg.solve(XYZ, W)
    return XYZ * S


_P709 = [(0.64, 0.33), (0.30, 0.60), (0.15, 0.06)]
_GAMUTS = {
    "s-gamut3.cine": [(0.766, 0.275), (0.225, 0.800), (0.089, -0.087)],
    "v-gamut": [(0.730, 0.280), (0.165, 0.840), (0.100, -0.030)],
    "d-gamut": [(0.710, 0.310), (0.210, 0.880), (0.090, -0.080)],
    "rec2020": [(0.708, 0.292), (0.170, 0.797), (0.131, 0.046)],
}


def _gamut_to_709(name):
    return np.linalg.inv(_rgb_to_xyz(_P709)) @ _rgb_to_xyz(_GAMUTS[name])


def _slog3(x):
    c = x * 1023.0
    return np.where(c >= 171.2102946929,
                    (10.0 ** ((c - 420.0) / 261.5)) * 0.19 - 0.01,
                    (c - 95.0) * 0.01125 / (171.2102946929 - 95.0))


def _vlog(x):
    return np.where(x < 0.181, (x - 0.125) / 5.6,
                    10.0 ** ((x - 0.598206) / 0.241514) - 0.00873)


def _dlog(x):
    return np.where(x <= 0.14, (x - 0.0929) / 6.025,
                    (10.0 ** (3.89616 * x - 2.27752) - 0.0108) / 0.9892)


def _applelog(x):
    R0, Rt, c, b, g, be = -0.05641088, 0.01, 47.28711236, 0.00964052, 0.08550479, 0.69336945
    Pt = c * (Rt - R0) ** 2
    return np.where(x >= Pt, 2.0 ** ((x - be) / g) - b,
                    np.where(x > 0, np.sqrt(np.maximum(x, 0) / c) + R0, R0))


LOG_PROFILES = {
    "slog3": (_slog3, "s-gamut3.cine", "Sony S-Log3"),
    "vlog": (_vlog, "v-gamut", "Panasonic V-Log"),
    "dlog": (_dlog, "d-gamut", "DJI D-Log"),
    "applelog": (_applelog, "rec2020", "Apple Log"),
}
LOG_ALIASES = {"slog3": "slog3", "s-log3": "slog3", "sony": "slog3",
               "vlog": "vlog", "v-log": "vlog", "panasonic": "vlog", "lumix": "vlog",
               "dlog": "dlog", "d-log": "dlog", "dji": "dlog", "drone": "dlog",
               "applelog": "applelog", "apple-log": "applelog", "apple": "applelog", "iphone-log": "applelog"}


def log_to_display(p, profile, tv_range=True):
    """Camera LOG RGB (as ffmpeg delivers it) -> Rec.709 display RGB 0..1."""
    curve, gamut, _ = LOG_PROFILES[profile]
    x = p.astype(np.float64)
    if tv_range:  # recover the camera code value (log curves are defined on code/1023)
        x = (x * 876.0 + 64.0) / 1023.0
    lin = curve(np.clip(x, 0, 1))
    lin = np.maximum(lin @ _gamut_to_709(gamut).T, 0.0)
    lin = lin * 1.5                              # put 18% grey near display mid-grey
    tm = lin * (1 + lin / 64.0) / (1 + lin)      # extended Reinhard, white = 8
    out = np.where(tm < 0.018, 4.5 * tm, 1.099 * np.power(np.maximum(tm, 0.018), 0.45) - 0.099)
    return np.clip(out, 0, 1)


# --------------------------------------------------------------------------
# Reference matching (MKL / Reinhard / histogram)
# --------------------------------------------------------------------------
_YCC = np.array([[0.2126, 0.7152, 0.0722],
                 [-0.1146, -0.3854, 0.5],
                 [0.5, -0.4542, -0.0458]])
_YCC_INV = np.linalg.inv(_YCC)


def _msqrt(A):
    w, V = np.linalg.eigh(A)
    return (V * np.sqrt(np.maximum(w, 1e-8))) @ V.T


def build_match(src, ref, method="mkl", strength=0.5):
    """Return a match spec that moves the colour statistics of src toward ref."""
    src = src.astype(np.float64)
    ref = ref.astype(np.float64)
    if method == "hist":
        qs = np.linspace(0, 1, 257)
        maps = [(np.quantile(src[:, c], qs), np.quantile(ref[:, c], qs)) for c in range(3)]
        return ("hist", maps, strength)
    if method == "reinhard":
        s, r = src @ _YCC.T, ref @ _YCC.T
        scale = r.std(0) / np.maximum(s.std(0), 1e-4)
        scale = np.clip(scale, 0.5, 2.0)
        A = _YCC_INV @ np.diag(scale) @ _YCC
        b = ref.mean(0) - src.mean(0) @ A.T
        return ("affine", A, b, strength)
    # MKL: Monge-Kantorovich linear transfer (Pitie et al. 2007)
    mu_s, mu_r = src.mean(0), ref.mean(0)
    Cs = np.cov((src - mu_s).T) + np.eye(3) * 1e-5
    Cr = np.cov((ref - mu_r).T) + np.eye(3) * 1e-5
    Csh = _msqrt(Cs)
    Csih = np.linalg.inv(Csh)
    T = Csih @ _msqrt(Csh @ Cr @ Csh) @ Csih
    b = mu_r - mu_s @ T.T
    return ("affine", T, b, strength)


def _apply_match(x, spec):
    if spec[0] == "affine":
        _, A, b, k = spec
        y = x @ A.T + b
    else:
        _, maps, k = spec
        y = np.stack([np.interp(x[..., c], maps[c][0], maps[c][1]) for c in range(3)], -1)
    return x + k * (y - x)


# --------------------------------------------------------------------------
# Correction model. The SAME function measures progress and bakes the LUT.
# --------------------------------------------------------------------------
def soft_clip(y, knee):
    rng = 1.0 - knee
    return np.clip(np.where(y > knee, knee + rng * np.tanh((y - knee) / rng), y), 0.0, 1.0)


def identity_model(knee=1.0):
    return dict(log=None, tv=True, gains=np.ones(3), lo_in=0.0, lo_out=0.0, stretch=1.0,
                knee=knee, gamma=1.0, lift=0.0, contrast=0.0, sat=1.0, warmth=0.0,
                split=0.0, match=None)


def apply_model(p, m):
    x = p
    if m.get("log"):
        x = log_to_display(x, m["log"], m.get("tv", True))
    x = x * m["gains"]
    x = m["lo_out"] + (x - m["lo_in"]) * m["stretch"]
    if m["knee"] < 1.0:
        x = soft_clip(np.maximum(x, 0.0), m["knee"])
    x = np.power(np.clip(x, 0, 1), m["gamma"])
    if m["lift"]:
        x = x + m["lift"] * 4.0 * x * (1 - x) ** 3
    if m["contrast"]:
        x = x - (m["contrast"] / (2 * np.pi)) * np.sin(2 * np.pi * x)
    x = np.clip(x, 0, 1)
    L = luma(x)[..., None]
    s = 1 + (m["sat"] - 1) * (1 - L ** 4)
    x = L + (x - L) * s
    if m["warmth"]:
        mw = 4 * L * (1 - L)
        w = m["warmth"]
        x = x * np.concatenate([1 + w * mw, np.ones_like(mw), 1 - w * mw], axis=-1)
    if m["split"]:  # teal shadows / warm highlights
        k = m["split"]
        sh, hl = (1 - L) ** 2, L ** 2
        x = x + k * (hl * np.array([1.0, 0.25, -0.8]) + sh * np.array([-0.8, 0.1, 1.0]))
    if m.get("match") is not None:
        x = _apply_match(np.clip(x, 0, 1), m["match"])
    return np.clip(x, 0, 1)


def estimate_gains(p, strength):
    L = luma(p)
    ok = (L > 0.08) & (p.max(1) < 0.97)
    q = p[ok] if ok.sum() > 500 else p
    ill = np.power(np.mean(np.power(q, 6), axis=0), 1 / 6) + 1e-4   # shades of grey
    g = ill.mean() / ill
    for _ in range(2):                                              # refine on near-grey pixels
        c = q * g
        Lc = luma(c)
        neu = ((c.max(1) - c.min(1)) / np.maximum(Lc, 1e-3) < 0.18) & (Lc > 0.15)
        if neu.sum() < 0.03 * len(q):
            break
        mm = c[neu].mean(0) + 1e-4
        g = g * (mm.mean() / mm)
    g = np.clip(np.power(g, strength), *LIM["gain"])
    return g / float(g @ LUMA)


def solve_shot(p_raw, P, log=None, tv=True, match=None, strength=1.0):
    """Find model parameters for one shot. p_raw: (N,3) pixels as decoded."""
    m = identity_model(P["knee"])
    m.update(log=log, tv=tv, lift=P["lift"] * strength, warmth=P["warmth"], split=P["split"])
    p = log_to_display(p_raw, log, tv) if log else p_raw
    keep = blown_mask(p)
    # 1) white balance
    m["gains"] = estimate_gains(p, P["wb"] * strength)
    L = luma(p * m["gains"])
    # 2) levels: pull a milky black down, lift a dull white up (never compress highlights)
    lo, hi = np.percentile(L, 0.5), np.percentile(L, 99.5)
    lo_out = P["black"] + 0.3 * (lo - P["black"]) if lo > P["black"] else lo
    b_now = describe(p * m["gains"], keep)["bright"]
    # a dull white is lifted only when the shot is not already bright enough
    hi_out = hi if b_now >= P["ceil"] else max(hi, P["white"])
    stretch = (hi_out - lo_out) / max(hi - lo, 1e-3)
    stretch = 1 + (stretch - 1) * strength
    m.update(lo_in=float(lo), lo_out=float(lo + (lo_out - lo) * strength),
             stretch=float(np.clip(stretch, *LIM["stretch"])))
    # 3) contrast adapts to how flat the shot already is
    c = P["contrast"]
    std = float(L.std())
    c *= 0.4 if std > 0.28 else (1.6 if std < 0.16 else 1.0)
    m["contrast"] = float(np.clip(c * strength, *LIM["contrast"]))
    # 4) saturation toward the preset target
    d = describe(apply_model(p_raw, m), keep)
    s = P["sat_bias"] * ((P["sat_target"] / d["sat"]) ** 0.6 if d["sat"] > 0.03 else 1.0)
    s = 1 + (s - 1) * strength
    m["sat"] = float(np.clip(s, *LIM["sat"]))
    m["match"] = match
    # 5) exposure into the comfort band [target, ceil] - bright white rooms stay bright
    m["gamma"] = 1.0
    b0 = describe(apply_model(p_raw, m), keep)["bright"]
    want = float(np.clip(b0, P["target"], P["ceil"]))
    want = b0 + (want - b0) * strength
    lo_g, hi_g = LIM["gamma"]
    for _ in range(18):
        mid = 0.5 * (lo_g + hi_g)
        m["gamma"] = mid
        if describe(apply_model(p_raw, m), keep)["bright"] > want:
            lo_g = mid
        else:
            hi_g = mid
    m["gamma"] = float(0.5 * (lo_g + hi_g))
    return m


def look_model(P):
    m = identity_model(P["knee"])
    m.update(lift=P["lift"], contrast=P["contrast"], sat=P["sat_bias"],
             warmth=P["warmth"], split=P["split"])
    return m


def lut_grid(size):
    g = np.linspace(0, 1, size)
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")  # .cube: red changes fastest
    return np.stack([r, gg, b], axis=-1).reshape(-1, 3)


def lut_change(m, size=9):
    """How far the model moves colours (max abs difference vs identity)."""
    grid = lut_grid(size)
    return float(np.abs(apply_model(grid, m) - grid).max())


def write_cube(path, m, size=33, title="Fullgrade"):
    out = apply_model(lut_grid(size), m)
    with open(path, "w") as f:
        f.write(f'TITLE "{title}"\nLUT_3D_SIZE {size}\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n')
        np.savetxt(f, out, fmt="%.6f")


def brightening(before, after):
    """Ratio used to decide how much denoise a shot needs."""
    return after["bright"] / max(before["bright"], 1e-3)
