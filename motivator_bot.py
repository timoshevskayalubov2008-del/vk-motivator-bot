# -*- coding: utf-8 -*-
"""
Чат-бот-мотиватор для проекта "Gamification для водителей-дальнобойщиков"
Бот поздравляет водителя с новым уровнем / достижением через сообщения ВК.

Как это работает:
- VK сообщество отправляет Callback-запросы на наш URL при новом сообщении
- Flask-приложение принимает запрос, обрабатывает текст, отвечает водителю
- Уровни и баллы храним в простом JSON-файле (без базы данных — для простоты)
- Водитель управляет ботом через кнопки (клавиатуру), а не вводом текста
- При нажатии кнопки действия бот сначала отвечает "отправлено на проверку",
  затем через несколько секунд присылает результат — это имитация модерации
  (в реальном проекте здесь было бы подтверждение диспетчера/системы).
"""

import json
import os
import random
import threading
import time

import requests
from flask import Flask, request

app = Flask(__name__)

# ===================== НАСТРОЙКИ =====================
# Токен и код подтверждения берутся из переменных окружения Amvera (раздел Переменные),
# а не хранятся в коде — так безопаснее, особенно если репозиторий на GitHub публичный.
VK_TOKEN = os.environ.get("VK_TOKEN", "ВСТАВЬ_СЮДА_НОВЫЙ_ТОКЕН")

# Строка подтверждения сервера (Управление -> Работа с API -> Callback API -> вкладка "Подтверждение")
CONFIRMATION_CODE = os.environ.get("CONFIRMATION_CODE", "ВСТАВЬ_СЮДА_СТРОКУ_ПОДТВЕРЖДЕНИЯ")

# Секретный ключ (необязательно, но рекомендуется для защиты от чужих запросов)
SECRET_KEY = os.environ.get("SECRET_KEY", "")  # можно оставить пустым, если не настраивал

VK_API_VERSION = "5.199"
# Используем постоянное хранилище /data в Amvera, чтобы баллы не сбрасывались при пересборке.
# Если запускаем не в Amvera (например, локально), используем обычную папку рядом со скриптом.
if os.path.isdir("/data"):
    DATA_FILE = "/data/motivator_drivers_data.json"
else:
    DATA_FILE = os.path.join(os.path.dirname(__file__), "motivator_drivers_data.json")

# Сколько секунд "думает" система проверки, прежде чем прислать результат
CHECK_DELAY_SECONDS = 4

# ===================== ДОСТИЖЕНИЯ =====================
ACHIEVEMENTS = {
    "eco_master": {"name": "ЭкоМастер", "desc": "за экономичное вождение"},
    "precision": {"name": "Точность до минуты", "desc": "за своевременную доставку"},
    "doc_ace": {"name": "Ас документации", "desc": "за безошибочное оформление ЭТрН"},
}

LEVEL_THRESHOLDS = [0, 100, 250, 500, 1000, 2000]  # баллы, нужные для перехода на уровень

# Действия, доступные через кнопки: текст кнопки -> (баллы, ключ достижения, описание)
ACTIONS = {
    "✅ Эко-поездка": (15, "eco_master", "5% экономии топлива зафиксировано"),
    "⏱ Точная доставка": (20, "precision", "своевременная доставка зафиксирована"),
    "📄 Документы без ошибок": (10, "doc_ace", "безошибочное оформление ЭТрН зафиксировано"),
}


def get_level(points: int) -> int:
    level = 1
    for i, threshold in enumerate(LEVEL_THRESHOLDS):
        if points >= threshold:
            level = i + 1
    return level


# ===================== ХРАНИЛИЩЕ ДАННЫХ =====================
# Простая блокировка, чтобы фоновые потоки не повредили файл при параллельной записи.
_data_lock = threading.Lock()


def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data: dict) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_driver(data: dict, user_id: str) -> dict:
    if user_id not in data:
        data[user_id] = {"points": 0, "level": 1, "achievements": []}
    return data[user_id]


# ===================== КЛАВИАТУРА =====================
def main_keyboard() -> str:
    """Клавиатура с кнопками действий, которая показывается под сообщениями бота."""
    keyboard = {
        "one_time": False,
        "inline": False,
        "buttons": [
            [
                {"action": {"type": "text", "label": "✅ Эко-поездка"}, "color": "positive"},
                {"action": {"type": "text", "label": "⏱ Точная доставка"}, "color": "positive"},
            ],
            [
                {"action": {"type": "text", "label": "📄 Документы без ошибок"}, "color": "positive"},
            ],
            [
                {"action": {"type": "text", "label": "📊 Мои баллы"}, "color": "primary"},
                {"action": {"type": "text", "label": "🏆 Достижения"}, "color": "primary"},
            ],
        ],
    }
    return json.dumps(keyboard, ensure_ascii=False)


# ===================== ОТПРАВКА СООБЩЕНИЙ В VK =====================
def send_message(user_id: int, text: str, with_keyboard: bool = True) -> None:
    url = "https://api.vk.com/method/messages.send"
    params = {
        "user_id": user_id,
        "message": text,
        "random_id": random.randint(1, 2_000_000_000),
        "access_token": VK_TOKEN,
        "v": VK_API_VERSION,
    }
    if with_keyboard:
        params["keyboard"] = main_keyboard()
    try:
        resp = requests.post(url, params=params, timeout=10)
        result = resp.json()
        if "error" in result:
            print("VK API error:", result["error"])
    except Exception as e:
        print("Ошибка отправки сообщения:", e)


# ===================== ОТЛОЖЕННАЯ ПРОВЕРКА (ИМИТАЦИЯ) =====================
def run_delayed_check(user_id: str, points: int, achievement_key: str, action_desc: str) -> None:
    """
    Имитирует работу системы проверки/модерации: ждёт несколько секунд,
    затем начисляет баллы и присылает водителю результат.
    """
    time.sleep(CHECK_DELAY_SECONDS)

    with _data_lock:
        data = load_data()
        driver = get_driver(data, user_id)

        driver["points"] += points
        old_level = driver["level"]
        new_level = get_level(driver["points"])
        driver["level"] = new_level

        response = f"✅ Проверка пройдена! {action_desc.capitalize()}.\n+{points} баллов.\n"

        if achievement_key not in driver["achievements"]:
            driver["achievements"].append(achievement_key)
            ach = ACHIEVEMENTS[achievement_key]
            response += f"\n🎉 Поздравляем! Вы получили звание «{ach['name']}»!\n"

        if new_level > old_level:
            response += f"\n🚀 Новый уровень! Теперь ты на уровне {new_level}!"

        response += f"\nВсего баллов: {driver['points']}"

        save_data(data)

    send_message(int(user_id), response)


# ===================== ЛОГИКА БОТА =====================
def handle_message(user_id: str, text: str) -> None:
    """Обрабатывает входящее сообщение и сама отправляет ответ(ы) водителю."""
    text_clean = text.strip()

    data = load_data()
    driver = get_driver(data, user_id)

    if text_clean.lower() in ("начать", "старт", "/start", "помощь", "/help"):
        send_message(
            int(user_id),
            "Привет, водитель! 🚛 Я бот-мотиватор системы геймификации.\n\n"
            "Нажимай кнопки внизу, чтобы зафиксировать своё достижение — "
            "я отправлю это на проверку и сразу сообщу результат.",
        )
        return

    if text_clean == "📊 Мои баллы" or text_clean.lower() == "баллы":
        send_message(int(user_id), f"📊 У тебя {driver['points']} баллов.\nТекущий уровень: {driver['level']}.")
        return

    if text_clean == "🏆 Достижения" or text_clean.lower() == "достижения":
        if not driver["achievements"]:
            send_message(int(user_id), "У тебя пока нет достижений. Жми на кнопки действий, чтобы их получить!")
        else:
            lines = [f"🏆 {ACHIEVEMENTS[a]['name']}" for a in driver["achievements"]]
            send_message(int(user_id), "Твои достижения:\n" + "\n".join(lines))
        return

    if text_clean in ACTIONS:
        points, achievement_key, action_desc = ACTIONS[text_clean]

        # Мгновенный ответ, чтобы у водителя не было ощущения, что он сам решает,
        # засчитан ли результат — баллы начисляются только после "проверки".
        send_message(int(user_id), "🕓 Запрос отправлен на проверку, подожди немного...")

        # Запускаем "проверку" в фоне, чтобы не задерживать ответ Callback API ВК.
        threading.Thread(
            target=run_delayed_check,
            args=(user_id, points, achievement_key, action_desc),
            daemon=True,
        ).start()
        return

    send_message(int(user_id), "Не понял команду 🤔 Воспользуйся кнопками внизу экрана.")


# ===================== CALLBACK API =====================
@app.route("/", methods=["POST"])
def callback():
    payload = request.json

    if payload.get("type") == "confirmation":
        return CONFIRMATION_CODE

    if SECRET_KEY and payload.get("secret") != SECRET_KEY:
        return "ok"  # игнорируем запросы без верного секрета

    if payload.get("type") == "message_new":
        message = payload["object"]["message"]
        user_id = message["from_id"]
        text = message.get("text", "")

        # Обрабатываем в фоне, чтобы сразу вернуть "ok" ВК (иначе он может повторно
        # прислать тот же запрос, если не получит ответ быстро).
        threading.Thread(target=handle_message, args=(str(user_id), text), daemon=True).start()

    return "ok"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
