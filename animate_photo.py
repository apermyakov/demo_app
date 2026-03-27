#!/usr/bin/env python3
"""
Скрипт для оживления фото с помощью Google Veo 3.1 через Replicate API.
Превращает статичное изображение в видео.

Использование:
  export REPLICATE_API_TOKEN='ваш_токен'
  python3 animate_photo.py <путь_к_фото> [промпт]

Получить токен: https://replicate.com/account/api-tokens
"""

import os
import sys
import time
import requests

REPLICATE_API_URL = "https://api.replicate.com/v1/predictions"
MODEL_VERSION = "google/veo-3.1"

DEFAULT_PROMPT = (
    "Two friends clinking beer glasses together and smiling warmly at each other "
    "in a lively airport lounge, natural subtle movements, gentle laughter, "
    "ambient background activity, cinematic warm lighting"
)


def upload_image(image_path):
    """Читает изображение и возвращает data URI для Replicate."""
    import base64
    import mimetypes

    mime_type, _ = mimetypes.guess_type(image_path)
    if not mime_type:
        mime_type = "image/jpeg"

    with open(image_path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")

    return f"data:{mime_type};base64,{data}"


def create_prediction(api_token, image_data_uri, prompt):
    """Создаёт prediction на Replicate для генерации видео."""
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": MODEL_VERSION,
        "input": {
            "image": image_data_uri,
            "prompt": prompt,
            "duration": 8,
            "resolution": "720p",
        },
    }

    response = requests.post(REPLICATE_API_URL, json=payload, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def poll_prediction(api_token, prediction_url):
    """Ожидает завершения генерации видео."""
    headers = {"Authorization": f"Bearer {api_token}"}

    while True:
        response = requests.get(prediction_url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()

        status = data.get("status")
        print(f"  Статус: {status}")

        if status == "succeeded":
            return data.get("output")
        elif status in ("failed", "canceled"):
            error = data.get("error", "Неизвестная ошибка")
            raise RuntimeError(f"Генерация не удалась: {error}")

        time.sleep(10)


def download_video(url, output_path):
    """Скачивает сгенерированное видео."""
    response = requests.get(url, timeout=120, stream=True)
    response.raise_for_status()

    with open(output_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)


def main():
    # Проверка токена
    api_token = os.environ.get("REPLICATE_API_TOKEN", "")
    if not api_token:
        print("Ошибка: не задан REPLICATE_API_TOKEN")
        print("Получите токен: https://replicate.com/account/api-tokens")
        print("Затем: export REPLICATE_API_TOKEN='ваш_токен'")
        sys.exit(1)

    # Аргументы
    if len(sys.argv) < 2:
        print(f"Использование: python3 {sys.argv[0]} <путь_к_фото> [промпт]")
        print(f"\nПример:")
        print(f"  python3 {sys.argv[0]} photo.jpg")
        print(f'  python3 {sys.argv[0]} photo.jpg "People laughing and clinking glasses"')
        sys.exit(1)

    image_path = sys.argv[1]
    prompt = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PROMPT

    if not os.path.isfile(image_path):
        print(f"Ошибка: файл не найден: {image_path}")
        sys.exit(1)

    # Генерация
    print(f"Модель: {MODEL_VERSION}")
    print(f"Фото: {image_path}")
    print(f"Промпт: {prompt}")
    print()

    print("[1/4] Кодирую изображение...")
    image_data_uri = upload_image(image_path)

    print("[2/4] Отправляю запрос на Replicate...")
    prediction = create_prediction(api_token, image_data_uri, prompt)
    prediction_url = prediction.get("urls", {}).get("get")
    prediction_id = prediction.get("id", "unknown")
    print(f"  Prediction ID: {prediction_id}")

    print("[3/4] Ожидаю генерацию видео (может занять 1-3 минуты)...")
    output = poll_prediction(api_token, prediction_url)

    if not output:
        print("Ошибка: API не вернул результат.")
        sys.exit(1)

    # output может быть строкой (URL) или списком
    video_url = output if isinstance(output, str) else output[0]
    print(f"  Видео готово: {video_url}")

    output_path = os.path.splitext(image_path)[0] + "_animated.mp4"
    print(f"[4/4] Скачиваю видео в {output_path}...")
    download_video(video_url, output_path)

    print(f"\nГотово! Видео сохранено: {output_path}")


if __name__ == "__main__":
    main()
