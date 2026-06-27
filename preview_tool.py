import gradio as gr
from PIL import Image, ImageEnhance
import subprocess
import os
import numpy as np
import tempfile

original_image = None

def load_frame(video_path):
    global original_image
    if not video_path:
        return None, None, "請輸入影片路徑"
    path = os.path.expanduser(video_path.strip())
    if not os.path.exists(path):
        return None, None, f"❌ 找不到檔案：{path}"
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        frame_path = f.name
    r = subprocess.run(
        ["ffmpeg", "-i", path, "-ss", "2", "-vframes", "1", "-q:v", "2", frame_path, "-y"],
        capture_output=True
    )
    if r.returncode != 0 or not os.path.exists(frame_path):
        subprocess.run(
            ["ffmpeg", "-i", path, "-vframes", "1", "-q:v", "2", frame_path, "-y"],
            capture_output=True
        )
    if os.path.exists(frame_path):
        img = Image.open(frame_path).copy()
        os.unlink(frame_path)
        original_image = img
        return img, img, "✅ 載入成功，請調整下方滑桿"
    return None, None, "❌ 無法截取畫面"

def preview(contrast, saturation, warmth, vignette):
    if original_image is None:
        return None, "請先載入影片"
    img = original_image.copy()

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
        x = np.linspace(-1, 1, w)
        y = np.linspace(-1, 1, h)
        X, Y = np.meshgrid(x, y)
        mask = 1 - np.clip(np.sqrt(X**2 + Y**2) * (vignette / 60), 0, 1)
        arr *= np.stack([mask]*3, axis=-1)
        img = Image.fromarray(arr.astype(np.uint8))

    filters = []
    if contrast != 0 or saturation != 0:
        c = f"{1 + contrast/100:.2f}"
        s = f"{1 + saturation/100:.2f}"
        filters.append(f"eq=contrast={c}:saturation={s}")
    if warmth > 0:
        filters.append(f"colorchannelmixer=rr={1+warmth*0.005:.3f}:bb={1-warmth*0.003:.3f}")
    elif warmth < 0:
        filters.append(f"colorchannelmixer=rr={1+warmth*0.003:.3f}:bb={1-warmth*0.005:.3f}")
    if vignette > 0:
        filters.append(f"vignette=PI/{max(1, int(180/vignette))}")

    if filters:
        cmd = f'ffmpeg -i 你的影片.mp4 -vf "{",".join(filters)}" -c:a copy 輸出影片.mp4'
    else:
        cmd = "（尚未調整任何參數）"

    return img, cmd

def apply_to_video(video_path, contrast, saturation, warmth, vignette):
    if not video_path:
        return "請輸入影片路徑"
    path = os.path.expanduser(video_path.strip())
    if not os.path.exists(path):
        return f"❌ 找不到檔案：{path}"

    base = os.path.splitext(path)[0]
    output = base + "_graded.mp4"

    filters = []
    if contrast != 0 or saturation != 0:
        c = f"{1 + contrast/100:.2f}"
        s = f"{1 + saturation/100:.2f}"
        filters.append(f"eq=contrast={c}:saturation={s}")
    if warmth > 0:
        filters.append(f"colorchannelmixer=rr={1+warmth*0.005:.3f}:bb={1-warmth*0.003:.3f}")
    elif warmth < 0:
        filters.append(f"colorchannelmixer=rr={1+warmth*0.003:.3f}:bb={1-warmth*0.005:.3f}")
    if vignette > 0:
        filters.append(f"vignette=PI/{max(1, int(180/vignette))}")

    if not filters:
        return "⚠️ 請先調整至少一個參數"

    r = subprocess.run(
        ["ffmpeg", "-i", path, "-vf", ",".join(filters), "-c:a", "copy", output, "-y"],
        capture_output=True, text=True
    )
    if r.returncode == 0:
        return f"✅ 完成！\n輸出：{output}"
    return f"❌ 錯誤：{r.stderr[-300:]}"

with gr.Blocks(title="影片調色預覽器") as app:
    gr.Markdown("# 影片調色預覽器")

    with gr.Row():
        video_path = gr.Textbox(label="影片路徑", placeholder="~/Downloads/你的影片.mp4")
        load_btn = gr.Button("載入影片", variant="primary")

    status = gr.Textbox(label="狀態", interactive=False)

    with gr.Row():
        original_out = gr.Image(label="原始畫面")
        preview_out = gr.Image(label="調整後預覽")

    with gr.Row():
        with gr.Column():
            contrast = gr.Slider(-50, 50, value=0, step=1, label="對比度")
            saturation = gr.Slider(-50, 50, value=0, step=1, label="飽和度")
        with gr.Column():
            warmth = gr.Slider(-50, 50, value=0, step=1, label="色溫（負=冷藍 / 正=暖橘）")
            vignette = gr.Slider(0, 100, value=0, step=1, label="暗角強度")

    ffmpeg_cmd = gr.Textbox(label="對應 ffmpeg 指令（可複製）", interactive=False)
    apply_btn = gr.Button("套用到影片並輸出", variant="primary")
    apply_status = gr.Textbox(label="輸出狀態", interactive=False)

    load_btn.click(load_frame, inputs=video_path, outputs=[original_out, preview_out, status])

    for slider in [contrast, saturation, warmth, vignette]:
        slider.change(preview, inputs=[contrast, saturation, warmth, vignette],
                      outputs=[preview_out, ffmpeg_cmd])

    apply_btn.click(apply_to_video,
                    inputs=[video_path, contrast, saturation, warmth, vignette],
                    outputs=apply_status)

if __name__ == "__main__":
    app.launch(open_browser=True)
