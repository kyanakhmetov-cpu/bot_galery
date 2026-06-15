#!/usr/bin/env python3
"""
Публикует случайную работу из открытой коллекции The Metropolitan Museum of Art
в Telegram-канал по шаблону:  Художник — Название (техника, год)

Запускается раз в день через GitHub Actions (см. .github/workflows/daily-art.yml).
Все картинки берутся из общественного достояния (CC0), поэтому их можно
свободно публиковать.
"""

import os
import sys
import random
import time

import requests

# ─────────────────────────────────────────────────────────────────────────────
# НАСТРОЙКИ (можно менять под себя)
# ─────────────────────────────────────────────────────────────────────────────

# Поисковые слова. Бот каждый раз берёт случайное и достаёт из него работу.
# Чем разнообразнее список — тем разнообразнее лента. Можно добавлять свои.
SEARCH_TERMS = [
    "painting", "portrait", "landscape", "still life", "flowers",
    "seascape", "garden", "river", "mountains", "sunset",
    "woman", "horse", "mythology", "angel", "winter",
    "impressionism", "watercolor", "drawing", "self-portrait", "street",
]

# Предпочитать «настенное» искусство (живопись, графику), чтобы лента
# выглядела как галерея. Если за все попытки ничего не нашлось — берётся
# любая подходящая работа. Поставь False, чтобы постить вообще любые
# экспонаты (скульптуру, керамику и т.д.).
PREFER_WALL_ART = True
PREFERRED_CLASSIFICATIONS = {
    "Paintings", "Drawings", "Prints", "Watercolors",
    "Pastels & Oil Sketches on Paper",
}

# Добавлять ли в конце поста ссылку на страницу работы на сайте музея.
ADD_SOURCE_LINK = True

# Сколько случайных работ перебрать на каждое поисковое слово, прежде чем
# перейти к следующему. Больше — надёжнее, но чуть медленнее.
OBJECTS_PER_TERM = 25

# Сколько постов публиковать за один запуск (т.е. за один день). Поставь 1 —
# будет один пост в день, как раньше.
POSTS_PER_RUN = 5

# Пауза между постами, в секундах. 5 секунд — безопасно для Telegram.
DELAY_BETWEEN_POSTS_SECONDS = 5

# ─────────────────────────────────────────────────────────────────────────────
# Дальше менять обычно не нужно
# ─────────────────────────────────────────────────────────────────────────────

MET_BASE = "https://collectionapi.metmuseum.org/public/collection/v1"
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendPhoto"
TELEGRAM_CAPTION_LIMIT = 1024
HTTP_HEADERS = {"User-Agent": "daily-art-bot/1.0 (+https://github.com)"}


def _get_json(url, params=None, attempts=3):
    """GET с несколькими попытками на случай сетевых сбоев."""
    for i in range(attempts):
        try:
            resp = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            if i == attempts - 1:
                print(f"  ! запрос не удался: {url} ({exc})", file=sys.stderr)
                return None
            time.sleep(2 * (i + 1))
    return None


def search_object_ids(term):
    """Вернуть список ID работ с картинками по поисковому слову."""
    data = _get_json(f"{MET_BASE}/search", params={"hasImages": "true", "q": term})
    if not data:
        return []
    return data.get("objectIDs") or []


def object_to_artwork(obj, require_preferred):
    """
    Проверить объект музея и, если он подходит, вернуть словарь с данными.
    Иначе вернуть None.
    """
    if not obj:
        return None
    # Только общественное достояние — такие изображения можно публиковать.
    if not obj.get("isPublicDomain"):
        return None
    image_url = obj.get("primaryImageSmall") or obj.get("primaryImage")
    if not image_url:
        return None
    title = (obj.get("title") or "").strip()
    if not title:
        return None
    if require_preferred:
        classification = (obj.get("classification") or "").strip()
        if classification not in PREFERRED_CLASSIFICATIONS:
            return None
    return {
        "id": obj.get("objectID"),
        "artist": (obj.get("artistDisplayName") or "").strip() or "Unknown artist",
        "title": title,
        "medium": (obj.get("medium") or "").strip(),
        "date": (obj.get("objectDate") or "").strip(),
        "image_url": image_url,
        "url": (obj.get("objectURL") or "").strip(),
    }


def find_artwork(exclude_ids=None):
    """Найти подходящую работу. Сначала ищем «настенное» искусство, потом — любое.

    exclude_ids — множество ID, которые нужно пропустить, чтобы за один запуск
    не опубликовать одну и ту же работу дважды.
    """
    exclude_ids = exclude_ids or set()
    passes = [True, False] if PREFER_WALL_ART else [False]
    for require_preferred in passes:
        terms = SEARCH_TERMS[:]
        random.shuffle(terms)
        for term in terms:
            ids = search_object_ids(term)
            if not ids:
                continue
            random.shuffle(ids)
            for object_id in ids[:OBJECTS_PER_TERM]:
                if object_id in exclude_ids:
                    continue
                obj = _get_json(f"{MET_BASE}/objects/{object_id}")
                art = object_to_artwork(obj, require_preferred)
                if art:
                    return art
    return None


def build_caption(art):
    """Собрать подпись: Художник — Название (техника, год)."""
    inside = ", ".join(part for part in (art["medium"], art["date"]) if part)
    line = f"{art['artist']} — {art['title']}"
    if inside:
        line += f" ({inside})"

    parts = [line]
    if ADD_SOURCE_LINK and art["url"]:
        parts.append("")
        parts.append(f"🏛 {art['url']}")

    caption = "\n".join(parts)
    return caption[:TELEGRAM_CAPTION_LIMIT]


def post_to_telegram(art, token, channel):
    """Скачать картинку и опубликовать пост в канал."""
    image = requests.get(art["image_url"], headers=HTTP_HEADERS, timeout=120)
    image.raise_for_status()

    caption = build_caption(art)
    resp = requests.post(
        TELEGRAM_API.format(token=token),
        data={"chat_id": channel, "caption": caption},
        files={"photo": ("artwork.jpg", image.content)},
        timeout=120,
    )
    result = {}
    try:
        result = resp.json()
    except Exception:  # noqa: BLE001
        pass
    if not result.get("ok"):
        raise RuntimeError(f"Telegram вернул ошибку: HTTP {resp.status_code} — {result or resp.text}")
    return result


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    channel = os.environ.get("TELEGRAM_CHANNEL")
    if not token or not channel:
        print(
            "Не заданы переменные окружения TELEGRAM_BOT_TOKEN и/или TELEGRAM_CHANNEL.",
            file=sys.stderr,
        )
        sys.exit(1)

    seen_ids = set()
    posted = 0
    for i in range(1, POSTS_PER_RUN + 1):
        print(f"[{i}/{POSTS_PER_RUN}] Ищу подходящую работу в коллекции музея…")
        art = find_artwork(exclude_ids=seen_ids)
        if not art:
            print(f"[{i}/{POSTS_PER_RUN}] Не удалось найти работу, пропускаю.", file=sys.stderr)
            continue

        if art.get("id") is not None:
            seen_ids.add(art["id"])
        print(f"[{i}/{POSTS_PER_RUN}] Найдено: {art['artist']} — {art['title']} ({art['date']})")

        try:
            post_to_telegram(art, token, channel)
            posted += 1
            print(f"[{i}/{POSTS_PER_RUN}] Опубликовано ✅")
        except Exception as exc:  # noqa: BLE001
            print(f"[{i}/{POSTS_PER_RUN}] Ошибка публикации: {exc}", file=sys.stderr)

        # Пауза перед следующим постом (после последнего ждать не нужно).
        if i < POSTS_PER_RUN:
            time.sleep(DELAY_BETWEEN_POSTS_SECONDS)

    print(f"Итого опубликовано: {posted} из {POSTS_PER_RUN}.")
    if posted == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
