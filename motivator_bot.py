# -*- coding: utf-8 -*-
"""
Чат-бот-мотиватор для проекта "Gamification для водителей-дальнобойщиков"
Бот поздравляет водителя с новым уровнем / достижением через сообщения ВК.

Как это работает:
- VK сообщество отправляет Callback-запросы на наш URL при новом сообщении
- Flask-приложение принимает запрос, обрабатывает текст, отвечает водителю
- Уровни и баллы храним в простом JSON-файле (без базы данных — для простоты)
"""

import json
import os
import random
import requests
from flask import Flask, request

app = Flask(__name__)

# ===================== НАСТРОЙКИ =====================
# Токен и код подтверждения берутся из переменных окружения Render (раздел Environment),
# а не хранятся в коде — так безопаснее, особенно если репозиторий на GitHub публичный.
VK_TOKEN = os.environ.get("VK_TOKEN", "ВСТАВЬ_СЮДА_НОВЫЙ_ТОКЕН")

# Строка подтверждения сервера (Управление -> Работа с API -> Callback API -> вкладка "Подтверждение")
CONFIRMATION_CODE = os.environ.get("CONFIRMATION_CODE", "ВСТАВЬ_СЮДА_СТРОКУ_ПОДТВЕРЖДЕНИЯ")

# Секретный ключ (необязательно, но рекомендуется для защиты от чужих запросов)
SECRET_KEY = os.environ.get("SECRET_KEY", "")  # можно оставить пустым, если не настраивал

VK_API_VERSION = "5.199"
DATA_FILE = os.path.join(os.path.dirname(__file__), "motivator_drivers_data.json")

# ===================== ДОСТИЖЕНИЯ =====================
ACHIEVEMENTS = {
    "eco_master": {"name": "ЭкоМастер", "desc": "за экономичное вождение"},
    "precision": {"name": "Точность до минуты", "desc": "за своевременную доставку"},
    "doc_ace": {"name": "Ас документации", "desc": "за безошибочное оформление ЭТрН"},
}

LEVEL_THRESHOLDS = [0, 100, 250, 500, 1000, 2000]  # баллы, нужные для перехода на уровень


def get_level(points: int) -> int:
    level = 1
    for i, threshold in enumerate(LEVEL_THRESHOLDS):
        if points >= threshold:
            level = i + 1
    return level


# ===================== ХРАНИЛИЩЕ ДАННЫХ =====================
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


# ===================== ОТПРАВКА СООБЩЕНИЙ В VK =====================
def send_message(user_id: int, text: str) -> None:
    url = "https://api.vk.com/method/messages.send"
    params = {
        "user_id": user_id,
        "message": text,
        "random_id": random.randint(1, 2_000_000_000),
        "access_token": VK_TOKEN,
        "v": VK_API_VERSION,
    }
    try:
        resp = requests.post(url, params=params, timeout=10)
        result = resp.json()
        if "error" in result:
            print("VK API error:", result["error"])
    except Exception as e:
        print("Ошибка отправки сообщения:", e)


# ===================== ЛОГИКА БОТА =====================
def handle_command(user_id: str, text: str) -> str:
    data = load_data()
    driver = get_driver(data, user_id)
    text = text.strip().lower()

    if text in ("начать", "старт", "/start", "помощь", "/help"):
        return (
            "Привет, водитель! 🚛 Я бот-мотиватор системы геймификации.\n\n"
            "Доступные команды:\n"
            "• «баллы» — узнать свой счёт и уровень\n"
            "• «+эко» — отметить экономичную поездку (+15 баллов)\n"
            "• «+точность» — отметить своевременную доставку (+20 баллов)\n"
            "• «+документы» — отметить безошибочное оформление ЭТрН (+10 баллов)\n"
            "• «достижения» — посмотреть свои награды"
        )

    elif text == "баллы":
        return f"📊 У тебя {driver['points']} баллов.\nТекущий уровень: {driver['level']}."

    elif text == "достижения":
        if not driver["achievements"]:
            return "У тебя пока нет достижений. Зарабатывай баллы командами «+эко», «+точность», «+документы»!"
        lines = [f"🏆 {ACHIEVEMENTS[a]['name']}" for a in driver["achievements"]]
        return "Твои достижения:\n" + "\n".join(lines)

    elif text in ("+эко", "+eco"):
        return apply_points(data, user_id, driver, 15, "eco_master",
                             "5% экономии топлива зафиксировано")

    elif text in ("+точность", "+precision"):
        return apply_points(data, user_id, driver, 20, "precision",
                             "своевременная доставка зафиксирована")

    elif text in ("+документы", "+docs"):
        return apply_points(data, user_id, driver, 10, "doc_ace",
                             "безошибочное оформление ЭТрН зафиксировано")

    else:
        return "Не понял команду 🤔 Напиши «помощь», чтобы увидеть список доступных команд."


def apply_points(data, user_id, driver, points, achievement_key, action_desc) -> str:
    driver["points"] += points
    old_level = driver["level"]
    new_level = get_level(driver["points"])
    driver["level"] = new_level

    response = f"✅ {action_desc.capitalize()}! +{points} баллов.\n"

    if achievement_key not in driver["achievements"]:
        driver["achievements"].append(achievement_key)
        ach = ACHIEVEMENTS[achievement_key]
        response += f"\n🎉 Поздравляем! Вы получили звание «{ach['name']}»!\n"

    if new_level > old_level:
        response += f"\n🚀 Новый уровень! Теперь ты на уровне {new_level}!"

    response += f"\nВсего баллов: {driver['points']}"

    save_data(data)
    return response


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

        reply = handle_command(str(user_id), text)
        send_message(user_id, reply)

    return "ok"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
