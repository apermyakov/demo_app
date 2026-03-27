#!/usr/bin/env python3
"""
Скрипт для поиска актёра по имени "Степан" в сериале
"Улица разбитых фонарей" на Кинопоиске.

Использует несколько методов получения данных:
1. Неофициальный API Кинопоиска (kinopoiskapiunofficial.tech) — если есть токен
2. Прямой парсинг страницы Кинопоиска
3. Парсинг данных с Кино-Театр.ру
"""

import os
import sys
import requests
from bs4 import BeautifulSoup

# ID сериала "Улицы разбитых фонарей" на Кинопоиске
KINOPOISK_FILM_ID = 77052

# URL для прямого парсинга
KINOPOISK_CAST_URL = f"https://www.kinopoisk.ru/film/{KINOPOISK_FILM_ID}/cast/"
KINOTEATR_CAST_URL = "https://www.kino-teatr.ru/kino/movie/ros/82542/titr/"

# API endpoints
UNOFFICIAL_API_URL = f"https://kinopoiskapiunofficial.tech/api/v1/staff?filmId={KINOPOISK_FILM_ID}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

SEARCH_NAME = "Степан"


def fetch_via_unofficial_api(api_token):
    """Получает список актёров через неофициальный API Кинопоиска."""
    headers = {"X-API-KEY": api_token, "Content-Type": "application/json"}
    response = requests.get(UNOFFICIAL_API_URL, headers=headers, timeout=15)
    response.raise_for_status()

    data = response.json()
    actors = []
    for person in data:
        if person.get("professionKey") == "ACTOR":
            name_ru = person.get("nameRu", "")
            name_en = person.get("nameEn", "")
            role = person.get("description", "")
            if name_ru:
                actors.append({"name": name_ru, "name_en": name_en, "role": role})
    return actors


def fetch_page(url):
    """Загружает веб-страницу."""
    response = requests.get(url, headers=HEADERS, timeout=15)
    response.raise_for_status()
    return response.text


def parse_kinopoisk_actors(html):
    """Извлекает имена актёров из HTML страницы Кинопоиска."""
    soup = BeautifulSoup(html, "html.parser")
    actors = []

    # Разные варианты разметки Кинопоиска
    for tag in soup.select("div.actorInfo a.name, div.dub a.name"):
        name = tag.get_text(strip=True)
        if name:
            actors.append({"name": name, "name_en": "", "role": ""})

    if not actors:
        for tag in soup.select("a[data-tid] span"):
            name = tag.get_text(strip=True)
            if name:
                actors.append({"name": name, "name_en": "", "role": ""})

    if not actors:
        for tag in soup.find_all("a", href=True):
            if "/name/" in tag["href"]:
                name = tag.get_text(strip=True)
                if name:
                    actors.append({"name": name, "name_en": "", "role": ""})

    return actors


def parse_kinoteatr_actors(html):
    """Извлекает имена актёров из HTML страницы Кино-Театр.ру."""
    soup = BeautifulSoup(html, "html.parser")
    actors = []

    for tag in soup.find_all("a", href=True):
        if "/acter/" in tag["href"] or "/actor/" in tag["href"]:
            name = tag.get_text(strip=True)
            if name and len(name) > 2:
                actors.append({"name": name, "name_en": "", "role": ""})

    return actors


def search_actor(actors, search_name):
    """Ищет актёра по подстроке имени (без учёта регистра)."""
    found = []
    seen = set()
    for actor in actors:
        name = actor["name"]
        if search_name.lower() in name.lower() and name not in seen:
            found.append(actor)
            seen.add(name)
    return found


def deduplicate(actors):
    """Убирает дубликаты актёров по имени."""
    seen = set()
    unique = []
    for actor in actors:
        if actor["name"] not in seen:
            seen.add(actor["name"])
            unique.append(actor)
    return unique


def main():
    actors = []
    source = ""

    # Метод 1: Неофициальный API (если задан токен)
    api_token = os.environ.get("KINOPOISK_API_TOKEN", "")
    if api_token:
        print(f"[1] Пробую неофициальный API Кинопоиска...")
        try:
            actors = fetch_via_unofficial_api(api_token)
            source = "Kinopoisk Unofficial API"
            print(f"    Успех! Получено актёров: {len(actors)}")
        except requests.RequestException as e:
            print(f"    Ошибка API: {e}")

    # Метод 2: Прямой парсинг Кинопоиска
    if not actors:
        print(f"[2] Пробую парсинг страницы Кинопоиска: {KINOPOISK_CAST_URL}")
        try:
            html = fetch_page(KINOPOISK_CAST_URL)
            actors = parse_kinopoisk_actors(html)
            source = "Кинопоиск (парсинг HTML)"
            print(f"    Успех! Получено актёров: {len(actors)}")
        except requests.RequestException as e:
            print(f"    Ошибка: {e}")

    # Метод 3: Парсинг Кино-Театр.ру
    if not actors:
        print(f"[3] Пробую парсинг страницы Кино-Театр.ру: {KINOTEATR_CAST_URL}")
        try:
            html = fetch_page(KINOTEATR_CAST_URL)
            actors = parse_kinoteatr_actors(html)
            source = "Кино-Театр.ру (парсинг HTML)"
            print(f"    Успех! Получено актёров: {len(actors)}")
        except requests.RequestException as e:
            print(f"    Ошибка: {e}")

    if not actors:
        print("\nНе удалось получить список актёров ни одним из методов.")
        print("Попробуйте:")
        print("  1. Задать токен API: export KINOPOISK_API_TOKEN='ваш_токен'")
        print("     Получить токен: https://kinopoiskapiunofficial.tech/")
        print("  2. Запустить скрипт без прокси/VPN")
        sys.exit(1)

    actors = deduplicate(actors)
    print(f"\nИсточник данных: {source}")
    print(f"Всего уникальных актёров: {len(actors)}")

    # Поиск актёра с именем "Степан"
    results = search_actor(actors, SEARCH_NAME)

    print("\n" + "=" * 50)
    if results:
        print(f'РЕЗУЛЬТАТ: Актёр с именем "{SEARCH_NAME}" НАЙДЕН!')
        for actor in results:
            role_info = f' (роль: {actor["role"]})' if actor["role"] else ""
            print(f"  → {actor['name']}{role_info}")
    else:
        print(f'РЕЗУЛЬТАТ: Актёр с именем "{SEARCH_NAME}" НЕ найден среди актёров сериала.')
    print("=" * 50)

    # Вывод первых 30 актёров
    print(f"\nПервые {min(30, len(actors))} актёров из списка:")
    for i, actor in enumerate(actors[:30], 1):
        role_info = f' — {actor["role"]}' if actor["role"] else ""
        print(f"  {i:3d}. {actor['name']}{role_info}")

    if len(actors) > 30:
        print(f"  ... и ещё {len(actors) - 30} актёров")


if __name__ == "__main__":
    main()
