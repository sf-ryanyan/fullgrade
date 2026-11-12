<div align="center">

# 🎨 Fullgrade

**Automatic light & colour correction for video — as a Claude skill.**
**视频自动调光调色 Claude 技能**

Drop in a clip or a whole folder. Get back footage that is evenly exposed, correctly white-balanced, consistent from shot to shot, and ready for any aspect ratio.

`MIT License` · `ffmpeg + Python` · `No GPU` · `No cloud API` · `macOS · Windows · Linux`

🔗 **[github.com/sf-ryanyan/fullgrade](https://github.com/sf-ryanyan/fullgrade)** · 📦 **[Download the latest release · 下载最新版](https://github.com/sf-ryanyan/fullgrade/releases/latest)**

[English](#-english) · [中文](#-中文)

</div>

---

## 🇺🇸 English

### 😩 The problem

Most video looks "almost right" — and that is what makes it look cheap:

- 🌑 One clip is too dark, the next one is blown out.
- 🟡 Indoor lamps turn every white wall yellow; shade turns it blue.
- 🎞️ A finished edit jumps in colour from shot to shot.
- 📱 iPhone HDR clips look grey once uploaded; drone LOG footage looks flat and washed out.
- ↕️ A 16:9 video needs a 9:16 version for Reels/TikTok/Shorts — and simple cropping cuts off the subject or stretches the picture.

Fixing this by hand means learning a colour-grading app and doing it clip by clip.

### ✅ How Fullgrade solves it

| Pain point | What Fullgrade does |
|---|---|
| Too dark / too bright | Measures every shot and brings it into a **comfortable brightness band**. Naturally bright rooms are *not* darkened; blown highlights are protected. |
| Yellow / blue cast | Robust automatic white balance (shades-of-grey + near-neutral refinement), limited so warm wood or warm walls are not turned grey. |
| Shots don't match | Every shot is graded toward the same targets; optional matching to a reference clip/photo or to the best shot in the folder. |
| Finished edits | Scene detection splits the edit into shots and grades **each shot separately** in one pass. |
| Exposure drifting inside one shot | **Dynamic exposure** smooths brightness over time (e.g. walking from a dark hall into a bright room). |
| Noise after brightening | Light denoise switches on only when a shot is brightened a lot. |
| iPhone HDR / camera LOG | HDR → SDR automatically. LOG decoding for **DJI D-Log, Sony S-Log3, Panasonic V-Log, Apple Log**; flat-looking clips trigger a LOG hint. |
| Wrong aspect ratio | 9:16 · 16:9 · 1:1 · 4:5 · 4:3 · 3:4 · 21:9. Never stretches: **smart crop** (follows faces, or the most detailed area) or **blurred-background pad**. |
| "Did it actually help?" | Before/after compare image + an **HTML report with drag sliders**, numbers and scopes (waveform + histogram) for every shot. |
| Fear of overdoing it | Every adjustment has hard limits; `--strength` makes it gentler; clips that already look right are copied without re-encoding. |

Originals are **never modified**. Output goes to a `_graded` folder next to your videos.

### 🎛️ Look presets

| Preset | For |
|---|---|
| **natural** *(default)* | Fix problems only, no added style |
| **real-estate** | Bright & airy interiors, clean whites |
| **warm** | Cozy interiors, evening, restaurants |
| **vivid** | Food, products, travel |
| **cool-modern** | Tech, offices, architecture |
| **cinematic** | Vlogs and brand films (soft contrast, teal-and-warm split tone) |

Each preset is also shipped as a `.cube` LUT in `luts/` for Premiere Pro, DaVinci Resolve, Final Cut Pro and CapCut. Add your own preset by copying a block in `presets.json`.

### 🚀 How to use

1. **Install the skill** — download `fullgrade.zip` from the [latest release](https://github.com/sf-ryanyan/fullgrade/releases/latest) and upload it on the Skills page of Claude's settings, or unzip it into `~/.claude/skills/` for Claude Code.
2. **Install ffmpeg** (once):
   - macOS: `brew install ffmpeg`
   - Windows: `winget install ffmpeg`
   - Linux: `sudo apt install ffmpeg`
   - then: `python3 -m pip install numpy pillow` (optional, for face-aware crop: `opencv-python-headless`)
3. **Ask Claude in plain words:**
   - "Colour-correct all videos in this folder."
   - "Use the real-estate preset and make a 9:16 version for Reels."
   - "This is DJI D-Log drone footage, make it look natural."
   - "Make every clip match this photo."
   - "Lighter touch, please."

Want to be sure it works on your machine? Ask Claude to run the **self-test**, or run it yourself:

```bash
python3 scripts/fullgrade.py --check
python3 scripts/fullgrade.py --selftest
```

The self-test builds synthetic footage (dark, yellow, blown-out, flat, an edited multi-shot file, a drifting-exposure shot, S-Log3) and verifies every feature.

### 🔧 Command line (optional)

```bash
python3 scripts/fullgrade.py <files-or-folders> [--preset real-estate] [--ratio 9:16] [--fit auto|crop|blur|color]
        [--log dlog|slog3|vlog|applelog] [--match <file>|hero] [--strength 0.6] [--fast] [--lang en|zh]
```

`python3 scripts/fullgrade.py --help` lists every option.

### ⚠️ Honest limits

- Pure-white blown windows or skies cannot be recovered.
- Very dark footage will show some noise when brightened.
- Mixed lighting in one shot is balanced as a compromise.
- DJI D-Log **M** and LOG curves not listed above are not supported in this version.

### 🙏 Acknowledgements

Fullgrade is an original implementation. It was shaped by ideas from these projects and papers (no code was copied):

- [browser-use/video-use](https://github.com/browser-use/video-use) — measured, bounded per-clip auto-grade
- [perbhat/agentic-color-grader](https://github.com/perbhat/agentic-color-grader) — numeric analysis, scopes, hero-clip matching with tolerances
- [hahnec/color-matcher](https://github.com/hahnec/color-matcher) — reference colour transfer (MKL / Reinhard / histogram)
- [Google AutoFlip](https://research.google/blog/autoflip-an-open-source-framework-for-intelligent-video-reframing/) — content-aware reframing
- [JosiahSiegel/claude-plugin-marketplace](https://github.com/JosiahSiegel/claude-plugin-marketplace) — ffmpeg colour filter reference
- F. Pitié et al., *The linear Monge-Kantorovitch colour mapping* (2007); E. Reinhard et al., *Color Transfer between Images* (2001)
- Published LOG and gamut specifications from DJI, Sony, Panasonic and Apple
- [FFmpeg](https://ffmpeg.org) — does all the heavy lifting

### 📄 Disclaimer

Fullgrade changes only copies of your files, never the originals. Automatic grading is a strong starting point, not a replacement for a colourist on critical work — always review the result before publishing. Camera and brand names are trademarks of their owners and are used only to describe compatibility.

---

## 🇨🇳 中文

### 😩 痛点

大多数视频"差一点就好看"，正是这一点让它显得不专业：

- 🌑 这一段太暗，下一段又过曝；
- 🟡 室内灯光把白墙照得发黄，阴天又发蓝；
- 🎞️ 剪好的成片，镜头之间颜色跳来跳去；
- 📱 iPhone 的 HDR 视频一上传就发灰；无人机 LOG 素材灰蒙蒙的；
- ↕️ 横屏视频要出竖屏版本，一裁就把人裁掉，或者画面被拉变形。

手动解决，需要学调色软件，还要一段一段地调。

### ✅ Fullgrade 怎么解决

| 痛点 | Fullgrade 的做法 |
|---|---|
| 太暗 / 太亮 | 测量每个镜头，把亮度调到**舒适区间**；本来就亮的白色房间不会被压暗，窗户高光会被保护 |
| 偏黄 / 偏蓝 | 稳健的自动白平衡，并限制力度，木地板、暖色墙不会被修成发灰的冷色 |
| 镜头颜色不统一 | 所有镜头对齐同一组目标值；还可以按一张参考图、一段参考视频，或文件夹里最好的那一段来统一 |
| 剪好的成片 | 自动识别镜头切换，**每个镜头单独调色**，一次输出 |
| 一个镜头内亮度在变 | **动态亮度**：比如从暗走廊走进明亮房间，亮度会平滑过渡 |
| 提亮后噪点多 | 只在提亮幅度大时，自动开启轻度降噪 |
| iPhone HDR / 相机 LOG | HDR 自动转 SDR；支持 **DJI D-Log、Sony S-Log3、Panasonic V-Log、Apple Log**；画面像 LOG 时会主动提醒 |
| 比例不对 | 9:16 · 16:9 · 1:1 · 4:5 · 4:3 · 3:4 · 21:9；绝不拉伸变形：**智能裁切**（跟随人脸，或画面最丰富的区域）或**模糊背景补边** |
| "到底有没有变好？" | 每个视频都有调整前后对比图，外加一份 **HTML 报告**：可拖动的前后对比滑块、数值和示波器 |
| 怕调过头 | 每一项调整都有上下限；可以用 `--strength` 调轻；本来就好的素材直接复制，不重新压缩 |

**原文件永远不会被修改**，新文件放在视频旁边的 `_graded` 文件夹里。

### 🎛️ 风格预设

| 预设 | 适合 |
|---|---|
| **natural 自然校正**（默认） | 只修问题，不加风格 |
| **real-estate 房产明亮通透** | 室内、房产，明亮干净 |
| **warm 温暖室内** | 温馨氛围、夜景、餐厅 |
| **vivid 鲜艳** | 美食、产品、旅行 |
| **cool-modern 清冷现代** | 科技、办公、建筑 |
| **cinematic 电影感** | Vlog、品牌片 |

每个预设在 `luts/` 文件夹里都有对应的 `.cube` 文件，Premiere、达芬奇、Final Cut、剪映都能导入。复制 `presets.json` 里的一段，就能添加自己的风格。

### 🚀 使用方法

1. **安装技能**：从 [最新版本页面](https://github.com/sf-ryanyan/fullgrade/releases/latest) 下载 `fullgrade.zip`，在 Claude 设置的技能（Skills）页面上传；Claude Code 用户解压到 `~/.claude/skills/`。
2. **安装 ffmpeg**（只需一次）：
   - Mac：`brew install ffmpeg`
   - Windows：`winget install ffmpeg`
   - Linux：`sudo apt install ffmpeg`
   - 然后：`python3 -m pip install numpy pillow`（可选：人脸跟随裁切需要 `opencv-python-headless`）
3. **直接用中文告诉 Claude：**
   - "把这个文件夹的视频都调一下色"
   - "用房产预设，再出一个 9:16 竖屏版"
   - "这是大疆 D-Log 航拍素材，调成自然的样子"
   - "所有视频都按这张图的色调统一"
   - "调得轻一点"

想确认在自己电脑上能不能用？让 Claude 运行**自检**，或者自己运行：

```bash
python3 scripts/fullgrade.py --check
python3 scripts/fullgrade.py --selftest
```

自检会自动生成测试素材（偏暗、偏黄、过曝、灰平、多镜头成片、亮度变化的镜头、S-Log3），逐项检查所有功能。

### ⚠️ 已知限制

- 完全过曝成纯白的窗户或天空，细节无法找回；
- 很暗的素材提亮后会有一些噪点；
- 同一画面里有混合光源时，只能取折中；
- 这一版暂不支持 DJI D-Log **M**，以及上面没有列出的 LOG 曲线。

### 🙏 致谢

Fullgrade 是独立实现的代码，设计思路参考了以下项目和论文（没有复制它们的代码）：browser-use/video-use、perbhat/agentic-color-grader、hahnec/color-matcher、Google AutoFlip、JosiahSiegel/claude-plugin-marketplace、Pitié 等人的 MKL 论文、Reinhard 等人的颜色迁移论文，以及 DJI、Sony、Panasonic、Apple 公开的 LOG 规范。所有视频处理都由 FFmpeg 完成。链接见上方英文部分。

### 📄 免责声明

Fullgrade 只处理文件副本，不会修改原文件。自动调色是很好的起点，但重要项目仍建议发布前人工检查。文中相机和品牌名称归各自所有者，仅用于说明兼容性。

---

## 👤 About the author · 关于作者

Built by **Ryan Yan, a data analyst.** Issues and suggestions are welcome on [GitHub Issues](https://github.com/sf-ryanyan/fullgrade/issues).
由 **Ryan Yan（数据分析师）** 开发。欢迎在 [GitHub Issues](https://github.com/sf-ryanyan/fullgrade/issues) 提问题和建议。

## ©️ Copyright & License · 版权与许可

© 2026 Ryan Yan. Released under the [MIT License](LICENSE) — free to use, modify and share, including commercially, as long as the copyright notice is kept.

© 2026 Ryan Yan。基于 [MIT 许可证](LICENSE) 开源：可以免费使用、修改、分发和商用，只需保留版权声明。
