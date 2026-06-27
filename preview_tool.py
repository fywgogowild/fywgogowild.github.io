import gradio as gr
from PIL import Image, ImageEnhance, ImageDraw, ImageFont
import subprocess, os, numpy as np, tempfile, shutil

state = {"img": None, "path": None}

# ── 工具函式 ──────────────────────────────────────────

def get_frame(path, ss="2"):
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        fp = f.name
    for t in [ss, "0"]:
        r = subprocess.run(["ffmpeg", "-i", path, "-ss", t, "-vframes", "1", "-q:v", "2", fp, "-y"], capture_output=True)
        if r.returncode == 0 and os.path.exists(fp):
            break
    if os.path.exists(fp):
        img = Image.open(fp).copy()
        os.unlink(fp)
        return img
    return None

def apply_color(img, contrast, saturation, warmth, vignette):
    img = ImageEnhance.Contrast(img).enhance(1 + contrast / 100)
    img = ImageEnhance.Color(img).enhance(1 + saturation / 100)
    if warmth != 0:
        arr = np.array(img, dtype=np.float32)
        if warmth > 0:
            arr[:,:,0] = np.clip(arr[:,:,0] + warmth * 0.5, 0, 255)
            arr[:,:,2] = np.clip(arr[:,:,2] - warmth * 0.3, 0, 255)
        else:
            arr[:,:,2] = np.clip(arr[:,:,2] - warmth * 0.5, 0, 255)
            arr[:,:,0] = np.clip(arr[:,:,0] + warmth * 0.3, 0, 255)
        img = Image.fromarray(arr.astype(np.uint8))
    if vignette > 0:
        w, h = img.size
        arr = np.array(img, dtype=np.float32)
        x, y = np.linspace(-1, 1, w), np.linspace(-1, 1, h)
        X, Y = np.meshgrid(x, y)
        mask = 1 - np.clip(np.sqrt(X**2 + Y**2) * (vignette / 60), 0, 1)
        arr *= np.stack([mask]*3, axis=-1)
        img = Image.fromarray(arr.astype(np.uint8))
    return img

def build_title_card(title, subtitle, w, h, duration=2):
    img = Image.new("RGB", (w, h), "black")
    draw = ImageDraw.Draw(img)
    # Try system font, fallback to default
    try:
        font_title = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", size=int(h * 0.1))
        font_sub   = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", size=int(h * 0.05))
    except:
        font_title = ImageFont.load_default()
        font_sub   = ImageFont.load_default()
    # Draw title
    bbox = draw.textbbox((0,0), title, font=font_title)
    tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
    draw.text(((w-tw)//2, int(h*0.4)), title, font=font_title, fill="white")
    # Draw subtitle
    if subtitle:
        bbox2 = draw.textbbox((0,0), subtitle, font=font_sub)
        sw = bbox2[2]-bbox2[0]
        draw.text(((w-sw)//2, int(h*0.4)+th+20), subtitle, font=font_sub, fill="#cccccc")
    return img

# ── 回呼函式 ──────────────────────────────────────────

def load_video(video):
    if video is None:
        return None, None, "請上傳影片"
    path = video if isinstance(video, str) else video
    state["path"] = path
    img = get_frame(path)
    if img:
        state["img"] = img
        return img, img, f"✅ 載入成功：{os.path.basename(path)}"
    return None, None, "❌ 無法截取畫面"

def color_preview(contrast, saturation, warmth, vignette):
    if state["img"] is None:
        return None, "請先載入影片"
    out = apply_color(state["img"].copy(), contrast, saturation, warmth, vignette)
    filters = []
    if contrast != 0 or saturation != 0:
        filters.append(f"eq=contrast={1+contrast/100:.2f}:saturation={1+saturation/100:.2f}")
    if warmth > 0:
        filters.append(f"colorchannelmixer=rr={1+warmth*0.005:.3f}:bb={1-warmth*0.003:.3f}")
    elif warmth < 0:
        filters.append(f"colorchannelmixer=rr={1+warmth*0.003:.3f}:bb={1-warmth*0.005:.3f}")
    if vignette > 0:
        filters.append(f"vignette=PI/{max(1,int(180/vignette))}")
    cmd = f'ffmpeg -i 影片.mp4 -vf "{",".join(filters)}" -c:a copy 輸出.mp4' if filters else "（未調整）"
    return out, cmd

def title_preview(title, subtitle):
    if state["img"] is None:
        return None
    w, h = state["img"].size
    return build_title_card(title, subtitle, w, h)

def run_all(contrast, saturation, warmth, vignette,
            add_title, title_text, subtitle_text, title_dur,
            remove_silence, silence_thresh,
            zoom_enable, zoom_from, zoom_to,
            add_music, music_path, music_vol, ducking,
            output_name):

    if not state["path"]:
        return "❌ 請先載入影片"

    src = state["path"]
    base = os.path.splitext(src)[0]
    tmp_dir = tempfile.mkdtemp()
    current = src
    steps = []

    # 1. 去除靜音
    if remove_silence:
        out = os.path.join(tmp_dir, "step1_cut.mp4")
        r = subprocess.run(
            ["auto-editor", current, "-o", out, "--no-open",
             f"--edit", f"audio:threshold={silence_thresh}%"],
            capture_output=True, text=True
        )
        if r.returncode == 0:
            current = out
            steps.append("✅ 去除靜音")
        else:
            steps.append(f"⚠️ 去除靜音失敗（略過）")

    # 2. 調色 + 鏡頭推進
    color_filters = []
    if contrast != 0 or saturation != 0:
        color_filters.append(f"eq=contrast={1+contrast/100:.2f}:saturation={1+saturation/100:.2f}")
    if warmth > 0:
        color_filters.append(f"colorchannelmixer=rr={1+warmth*0.005:.3f}:bb={1-warmth*0.003:.3f}")
    elif warmth < 0:
        color_filters.append(f"colorchannelmixer=rr={1+warmth*0.003:.3f}:bb={1-warmth*0.005:.3f}")
    if vignette > 0:
        color_filters.append(f"vignette=PI/{max(1,int(180/vignette))}")
    if zoom_enable:
        # Get duration
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", current],
            capture_output=True, text=True
        )
        dur = float(probe.stdout.strip() or "30")
        color_filters.append(
            f"zoompan=z='min(zoom+{(zoom_to-zoom_from)/dur/25:.6f},{zoom_to})':d={int(dur*25)}:s=iw:ih:fps=25"
        )

    if color_filters:
        out = os.path.join(tmp_dir, "step2_color.mp4")
        r = subprocess.run(
            ["ffmpeg", "-i", current, "-vf", ",".join(color_filters),
             "-c:a", "copy", out, "-y"],
            capture_output=True, text=True
        )
        if r.returncode == 0:
            current = out
            steps.append("✅ 調色" + ("＋鏡頭推進" if zoom_enable else ""))
        else:
            steps.append("⚠️ 調色失敗（略過）")

    # 3. 加開場字卡
    if add_title and title_text:
        # Get video size
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=p=0", current],
            capture_output=True, text=True
        )
        try:
            ww, hh = map(int, probe.stdout.strip().split(","))
        except:
            ww, hh = 1080, 1920

        card_img = build_title_card(title_text, subtitle_text, ww, hh)
        card_path = os.path.join(tmp_dir, "title_card.png")
        card_img.save(card_path)

        card_video = os.path.join(tmp_dir, "title_video.mp4")
        subprocess.run([
            "ffmpeg", "-loop", "1", "-i", card_path,
            "-t", str(title_dur), "-r", "25",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-vf", f"scale={ww}:{hh}",
            card_video, "-y"
        ], capture_output=True)

        # Get audio sample rate from main video
        probe_a = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=sample_rate,channels",
             "-of", "csv=p=0", current],
            capture_output=True, text=True
        )
        try:
            sr, ch = probe_a.stdout.strip().split(",")
        except:
            sr, ch = "44100", "2"

        # Add silent audio to title card
        card_with_audio = os.path.join(tmp_dir, "title_audio.mp4")
        subprocess.run([
            "ffmpeg", "-i", card_video,
            "-f", "lavfi", "-i", f"anullsrc=r={sr}:cl={'stereo' if ch=='2' else 'mono'}",
            "-c:v", "copy", "-c:a", "aac", "-shortest",
            card_with_audio, "-y"
        ], capture_output=True)

        # Concat
        concat_list = os.path.join(tmp_dir, "concat.txt")
        with open(concat_list, "w") as f:
            f.write(f"file '{card_with_audio}'\nfile '{current}'\n")

        out = os.path.join(tmp_dir, "step3_title.mp4")
        r = subprocess.run([
            "ffmpeg", "-f", "concat", "-safe", "0",
            "-i", concat_list, "-c", "copy", out, "-y"
        ], capture_output=True, text=True)
        if r.returncode == 0:
            current = out
            steps.append(f"✅ 開場字卡「{title_text}」{title_dur}秒")
        else:
            steps.append("⚠️ 開場字卡失敗（略過）")

    # 4. 背景音樂 + ducking
    if add_music and music_path and os.path.exists(os.path.expanduser(music_path)):
        mp = os.path.expanduser(music_path)
        vol = music_vol / 100
        out = os.path.join(tmp_dir, "step4_music.mp4")
        if ducking:
            af = (f"[1:a]volume={vol}[bg];"
                  f"[0:a][bg]sidechaincompress=threshold=0.02:ratio=4:attack=200:release=1000[out]")
            r = subprocess.run([
                "ffmpeg", "-i", current, "-i", mp,
                "-filter_complex", af,
                "-map", "0:v", "-map", "[out]",
                "-c:v", "copy", "-c:a", "aac", "-shortest",
                out, "-y"
            ], capture_output=True, text=True)
        else:
            r = subprocess.run([
                "ffmpeg", "-i", current, "-i", mp,
                "-filter_complex",
                f"[1:a]volume={vol}[bg];[0:a][bg]amix=inputs=2:duration=first[out]",
                "-map", "0:v", "-map", "[out]",
                "-c:v", "copy", "-c:a", "aac",
                out, "-y"
            ], capture_output=True, text=True)
        if r.returncode == 0:
            current = out
            steps.append(f"✅ 背景音樂（音量{music_vol}%{'＋閃避' if ducking else ''}）")
        else:
            steps.append("⚠️ 背景音樂失敗（略過）")

    # 最終輸出
    out_dir = os.path.dirname(state["path"])
    final = os.path.join(out_dir, (output_name or "final_output") + ".mp4")
    shutil.copy2(current, final)
    shutil.rmtree(tmp_dir, ignore_errors=True)

    result = "\n".join(steps) + f"\n\n✅ 完成！\n輸出：{final}"
    return result

# ── UI ────────────────────────────────────────────────

with gr.Blocks(title="影片剪輯工作室", theme=gr.themes.Soft()) as app:
    gr.Markdown("# 影片剪輯工作室")

    with gr.Row():
        video_input = gr.Video(label="拖曳影片到這裡（或點擊上傳）")
        with gr.Column():
            status = gr.Textbox(label="狀態", interactive=False, lines=2)
            load_btn = gr.Button("載入影片", variant="primary", size="lg")

    with gr.Row():
        orig_img = gr.Image(label="原始畫面")
        prev_img = gr.Image(label="預覽")

    with gr.Tabs():

        # ── Tab 1: 調色 ──
        with gr.Tab("🎨 調色"):
            with gr.Row():
                contrast  = gr.Slider(-50, 50, 0, step=1, label="對比度")
                saturation = gr.Slider(-50, 50, 0, step=1, label="飽和度")
            with gr.Row():
                warmth   = gr.Slider(-50, 50, 0, step=1, label="色溫（負=冷藍 / 正=暖橘）")
                vignette = gr.Slider(0, 100, 0, step=1, label="暗角強度")
            color_cmd = gr.Textbox(label="對應 ffmpeg 指令", interactive=False)

        # ── Tab 2: 開場字卡 ──
        with gr.Tab("📝 開場字卡"):
            add_title    = gr.Checkbox(label="加入開場字卡", value=False)
            title_text   = gr.Textbox(label="主標題", placeholder="追憶華語樂壇")
            subtitle_text = gr.Textbox(label="副標題（可留空）", placeholder="那些年的聲音")
            title_dur    = gr.Slider(1, 5, 2, step=0.5, label="字卡時長（秒）")
            title_prev   = gr.Image(label="字卡預覽")
            prev_btn     = gr.Button("預覽字卡")

        # ── Tab 3: 剪輯 ──
        with gr.Tab("✂️ 自動去靜音"):
            remove_silence = gr.Checkbox(label="啟用自動去除靜音", value=False)
            silence_thresh = gr.Slider(1, 20, 4, step=1, label="靜音門檻（%，越小去越多）")

        # ── Tab 4: 鏡頭推進 ──
        with gr.Tab("🎬 鏡頭推進"):
            zoom_enable = gr.Checkbox(label="啟用鏡頭緩慢推進", value=False)
            with gr.Row():
                zoom_from = gr.Slider(1.0, 1.5, 1.0, step=0.05, label="起始縮放")
                zoom_to   = gr.Slider(1.0, 1.5, 1.2, step=0.05, label="結束縮放")

        # ── Tab 5: 音樂 ──
        with gr.Tab("🎵 背景音樂"):
            add_music  = gr.Checkbox(label="加入背景音樂", value=False)
            music_path = gr.Textbox(label="音樂路徑", placeholder="~/Downloads/bgm.mp3")
            music_vol  = gr.Slider(5, 100, 30, step=5, label="音樂音量（%）")
            ducking    = gr.Checkbox(label="人聲時自動降低音樂（ducking）", value=True)

    # ── 輸出 ──
    gr.Markdown("---")
    with gr.Row():
        output_name = gr.Textbox(label="輸出檔名（不含副檔名）", value="final_output", scale=2)
        apply_btn   = gr.Button("🚀 套用全部並輸出", variant="primary", scale=1)
    apply_status = gr.Textbox(label="執行結果", interactive=False, lines=8)

    # ── 事件綁定 ──
    load_btn.click(load_video, inputs=video_input, outputs=[orig_img, prev_img, status])

    for sl in [contrast, saturation, warmth, vignette]:
        sl.change(color_preview, inputs=[contrast, saturation, warmth, vignette],
                  outputs=[prev_img, color_cmd])

    prev_btn.click(title_preview, inputs=[title_text, subtitle_text], outputs=title_prev)

    apply_btn.click(
        run_all,
        inputs=[contrast, saturation, warmth, vignette,
                add_title, title_text, subtitle_text, title_dur,
                remove_silence, silence_thresh,
                zoom_enable, zoom_from, zoom_to,
                add_music, music_path, music_vol, ducking,
                output_name],
        outputs=apply_status
    )

if __name__ == "__main__":
    app.launch(inbrowser=True)
