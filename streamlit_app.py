import streamlit as st
import requests
import base64
import time
import mimetypes

st.set_page_config(page_title="Photo Animator — Veo 3.1", page_icon="🎬")

st.title("🎬 Оживи своё фото")
st.caption("Google Veo 3.1 via Replicate API")

api_token = st.secrets.get("REPLICATE_API_TOKEN", "")
if not api_token:
    api_token = st.text_input("Replicate API Token", type="password")

uploaded = st.file_uploader("Загрузите фото", type=["jpg", "jpeg", "png", "webp"])

prompt = st.text_area(
    "Промпт (опишите желаемое движение)",
    value=(
        "Two friends clinking beer glasses and smiling warmly at each other "
        "in a lively airport lounge, natural subtle movements, gentle laughter, "
        "ambient background activity, cinematic warm lighting"
    ),
)

col1, col2 = st.columns(2)
duration = col1.selectbox("Длительность (сек)", [4, 6, 8], index=2)
resolution = col2.selectbox("Разрешение", ["720p", "1080p"], index=0)

if uploaded:
    st.image(uploaded, caption="Исходное фото", use_container_width=True)

if st.button("🚀 Оживить!", type="primary", disabled=not (uploaded and api_token)):
    mime = mimetypes.guess_type(uploaded.name)[0] or "image/jpeg"
    b64 = base64.b64encode(uploaded.read()).decode()
    image_uri = f"data:{mime};base64,{b64}"

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    with st.spinner("Отправляю запрос на Replicate..."):
        resp = requests.post(
            "https://api.replicate.com/v1/predictions",
            json={
                "model": "google/veo-3.1",
                "input": {
                    "image": image_uri,
                    "prompt": prompt,
                    "duration": duration,
                    "resolution": resolution,
                },
            },
            headers=headers,
            timeout=60,
        )

        if resp.status_code != 201:
            st.error(f"Ошибка API: {resp.status_code} — {resp.text}")
            st.stop()

        prediction = resp.json()
        pred_url = prediction["urls"]["get"]
        pred_id = prediction["id"]

    st.info(f"Prediction ID: `{pred_id}`")
    progress = st.progress(0, text="Генерирую видео...")
    status_text = st.empty()

    elapsed = 0
    while True:
        r = requests.get(pred_url, headers={"Authorization": f"Bearer {api_token}"}, timeout=15)
        data = r.json()
        status = data.get("status", "unknown")
        status_text.text(f"Статус: {status} ({elapsed}с)")
        progress.progress(min(elapsed / 180, 0.95), text=f"Генерирую видео... ({status})")

        if status == "succeeded":
            progress.progress(1.0, text="Готово!")
            output = data.get("output")
            video_url = output if isinstance(output, str) else output[0]
            st.success("Видео готово!")
            st.video(video_url)
            st.markdown(f"[⬇️ Скачать видео]({video_url})")
            break
        elif status in ("failed", "canceled"):
            st.error(f"Ошибка: {data.get('error', 'Неизвестная ошибка')}")
            break

        time.sleep(10)
        elapsed += 10
