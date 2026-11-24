import asyncio
import random
import re
import threading
from datetime import datetime

import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType

from database import (
    create_vk_subscription,
    get_vk_subscriptions_for_user,
    get_all_active_vk_subscriptions,
    deactivate_vk_subscription,
    get_seen_ad_ids,
    mark_ads_seen,
)
from parser_avito import parse_avito, CITY_CODES as AVITO_CITIES
from parser_yula import parse_yula
from parser_barahla import parse_barahla


VK_TOKEN = "vk1.a.QCVdAnVXmoyRnenmoCyVodN_vNBv0qZr3EHbyhz2YEFLEj79lgbM8rn7iD8fum9lJm8m8w2phNGWTxXx7H3PzArI1HOkBLXf5pLXV9rJ-lVkOHM3MII7VmlPkUel7onoQtSDIUQdTS2SVwQz3zO1WnFBiIwlh9umy463xkEANobmdc2gbUQKqkoG-0MQ0HpVintl0kKB5_lFFjV3OTiKyg"


VK_GROUP_ID = 240270039


CHECK_INTERVAL_SECONDS = 900


DEFAULT_SOURCES = ["avito", "youla", "barahla"]

SOURCE_NAMES = {"avito": "Avito", "youla": "Юла", "barahla": "Барахла.нет"}

HELP_TEXT = (
    "🔎 Дозорный — бот-уведомитель о новых объявлениях\n"
    "(Avito, Юла, Барахла.нет)\n\n"
    "Команды:\n"
    "/search <запрос> [цена_от-цена_до | до <цена>] [город]\n"
    "   Подписаться на новые объявления по запросу.\n"
    "   Примеры:\n"
    "     /search rtx 5060\n"
    "     /search rtx 5060 20000-40000\n"
    "     /search ноутбук до 30000 Москва\n\n"
    "/list — показать мои подписки\n"
    "/stop <номер> — отписаться (номер берётся из /list)\n"
    "/help — показать это сообщение\n\n"
    "После подписки бот сам проверяет площадки каждые "
    f"{CHECK_INTERVAL_SECONDS // 60} минут и присылает новые "
    "объявления."
)


vk_session = vk_api.VkApi(token=VK_TOKEN)
vk = vk_session.get_api()
longpoll = VkBotLongPoll(vk_session, VK_GROUP_ID)


def _split_text(text: str, max_len: int = 4000):
    if len(text) <= max_len:
        return [text]
    parts = []
    while text:
        parts.append(text[:max_len])
        text = text[max_len:]
    return parts


def send_message(user_id: int, text: str):
    try:
        for chunk in _split_text(text):
            vk.messages.send(
                user_id=user_id,
                message=chunk,
                random_id=random.randint(1, 2**31 - 1),
            )
    except Exception as e:
        print(f"❌ Ошибка отправки сообщения VK пользователю {user_id}: {e}")


def format_ad_message(ad: dict) -> str:
    price = ad.get("price")
    price_str = f"{price:,}".replace(",", " ") + " ₽" if price else "цена не указана"
    source = SOURCE_NAMES.get(ad.get("source"), ad.get("source", ""))

    lines = [f"🆕 {ad.get('title', 'Без названия')}", f"💰 {price_str}"]
    if ad.get("location"):
        lines.append(f"📍 {ad['location']}")
    lines.append(f"🏷 {source}")
    if ad.get("url"):
        lines.append(ad["url"])
    return "\n".join(lines)


def send_ads_batch(user_id: int, ads: list, header: str = None):
    if not ads:
        return
    parts = [header] if header else []
    parts.extend(format_ad_message(ad) for ad in ads)
    send_message(user_id, "\n\n".join(parts))


def parse_search_command(args_text: str):
    tokens = args_text.split()
    city = "Все регионы"
    price_from = None
    price_to = None

    city_names = list(AVITO_CITIES.keys())


    if len(tokens) >= 2:
        two_word = f"{tokens[-2]} {tokens[-1]}"
        if two_word in city_names:
            city = two_word
            tokens = tokens[:-2]
        elif tokens[-1] in city_names:
            city = tokens[-1]
            tokens = tokens[:-1]
    elif tokens and tokens[-1] in city_names:
        city = tokens[-1]
        tokens = tokens[:-1]


    if len(tokens) >= 2 and tokens[-2].lower() == "до" and tokens[-1].isdigit():
        price_to = int(tokens[-1])
        tokens = tokens[:-2]
    else:

        price_range_re = re.compile(r"^(\d+)-(\d+)$")
        if tokens:
            m = price_range_re.match(tokens[-1])
            if m:
                price_from, price_to = int(m.group(1)), int(m.group(2))
                tokens = tokens[:-1]

    query = " ".join(tokens).strip()
    return query, price_from, price_to, city


async def run_search(query, price_from, price_to, city, sources):
    tasks = []
    if "avito" in sources:
        tasks.append(parse_avito(query, price_from=price_from, price_to=price_to, city=city))
    if "youla" in sources:
        tasks.append(parse_yula(query, price_to, city=city))
    if "barahla" in sources:
        tasks.append(parse_barahla(query, price_to, city=city))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    ads = []
    for source, result in zip(sources, results):
        if isinstance(result, list):
            ads.extend(result)
        elif isinstance(result, Exception):
            print(f"❌ Ошибка источника {source}: {result}")

    if price_from is not None:
        ads = [a for a in ads if a["price"] >= price_from]
    if price_to is not None:
        ads = [a for a in ads if a["price"] <= price_to]


    seen, unique = set(), []
    for ad in ads:
        if ad["id"] not in seen:
            seen.add(ad["id"])
            unique.append(ad)

    return unique


async def handle_message(user_id: int, text: str):
    text = (text or "").strip()
    low = text.lower()

    try:
        if low in ("/help", "/start", "помощь", "start"):
            send_message(user_id, HELP_TEXT)
            return

        if low.startswith("/search"):
            args = text[len("/search"):].strip()
            if not args:
                send_message(user_id, "Укажите запрос, например:\n/search rtx 5060 20000-40000 Москва")
                return

            query, price_from, price_to, city = parse_search_command(args)
            if not query:
                send_message(user_id, "Не понял запрос. Пример:\n/search видеокарта 5060")
                return

            send_message(user_id, f"🔍 Ищу «{query}»…")

            ads = await run_search(query, price_from, price_to, city, DEFAULT_SOURCES)

            sub_id = create_vk_subscription(
                user_id, query, price_from, price_to, city, ",".join(DEFAULT_SOURCES)
            )


            mark_ads_seen(sub_id, [a["id"] for a in ads])

            if ads:
                shown = ads[:10]
                send_ads_batch(
                    user_id, shown,
                    header=f"✅ Найдено {len(ads)} объявлений. Показываю первые {len(shown)}:"
                )
                if len(ads) > len(shown):
                    send_message(user_id, f"…и ещё {len(ads) - len(shown)}.")
            else:
                send_message(user_id, "Пока ничего не найдено. Как только появятся объявления — пришлю.")

            send_message(
                user_id,
                "📌 Подписка активна. Буду проверять и присылать новые объявления "
                f"каждые {CHECK_INTERVAL_SECONDS // 60} минут.\n"
                "/list — список подписок, /stop <номер> — отписаться."
            )
            return

        if low == "/list":
            subs = get_vk_subscriptions_for_user(user_id)
            if not subs:
                send_message(user_id, "У вас пока нет подписок. Используйте /search <запрос>")
                return
            lines = ["📋 Ваши подписки:"]
            for i, s in enumerate(subs, 1):
                price_part = ""
                if s.price_from or s.price_to:
                    price_part = f" ({s.price_from or 0}–{s.price_to or '∞'} ₽)"
                lines.append(f"{i}. {s.query}{price_part} — {s.city}")
            lines.append("\nЧтобы отписаться: /stop <номер>")
            send_message(user_id, "\n".join(lines))
            return

        if low.startswith("/stop"):
            args = text[len("/stop"):].strip()
            subs = get_vk_subscriptions_for_user(user_id)
            if not subs:
                send_message(user_id, "У вас нет активных подписок.")
                return
            if not args.isdigit():
                send_message(user_id, "Укажите номер подписки из /list, например: /stop 1")
                return
            idx = int(args) - 1
            if 0 <= idx < len(subs):
                deactivate_vk_subscription(subs[idx].id, user_id)
                send_message(user_id, f"🛑 Подписка «{subs[idx].query}» остановлена.")
            else:
                send_message(user_id, "Нет подписки с таким номером. Смотрите /list")
            return

        send_message(user_id, "Не понимаю команду. Напишите /help")

    except Exception as e:
        print(f"❌ Ошибка обработки сообщения от {user_id}: {e}")
        import traceback
        traceback.print_exc()
        send_message(user_id, "⚠️ Произошла ошибка, попробуйте ещё раз.")


async def check_subscription(sub):
    sources = (sub.sources or "avito").split(",")
    ads = await run_search(sub.query, sub.price_from, sub.price_to, sub.city, sources)

    seen = get_seen_ad_ids(sub.id)
    new_ads = [a for a in ads if a["id"] not in seen]

    if new_ads:
        send_ads_batch(
            sub.vk_user_id, new_ads,
            header=f"🔔 Новые объявления по запросу «{sub.query}»:"
        )
        print(f"🆕 Подписка #{sub.id} ({sub.query}): отправлено {len(new_ads)} новых")

    mark_ads_seen(sub.id, [a["id"] for a in ads])


async def check_subscriptions_loop():
    while True:
        try:
            subs = get_all_active_vk_subscriptions()
            print(f"🔄 VK-бот: проверка {len(subs)} активных подписок")
            for sub in subs:
                try:
                    await check_subscription(sub)
                except Exception as e:
                    print(f"❌ Ошибка проверки подписки #{sub.id}: {e}")
        except Exception as e:
            print(f"❌ Ошибка цикла проверки подписок: {e}")

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


def run_longpoll(loop: asyncio.AbstractEventLoop):
    print("👂 VK Long Poll запущен, жду сообщений…")
    for event in longpoll.listen():
        try:
            if event.type == VkBotEventType.MESSAGE_NEW:
                message = event.object.message
                user_id = message.get("from_id")
                text = message.get("text", "")
                if user_id:
                    asyncio.run_coroutine_threadsafe(
                        handle_message(user_id, text), loop
                    )
        except Exception as e:
            print(f"❌ Ошибка в Long Poll: {e}")


async def main():
    print("========================================")
    print("  Дозорный VK-бот — запуск")
    print("========================================")

    if VK_TOKEN == "ВАШ_ТОКЕН_СООБЩЕСТВА" or not VK_GROUP_ID:
        print("❌ Заполните VK_TOKEN и VK_GROUP_ID в начале файла vk_bot.py")
        return

    loop = asyncio.get_running_loop()
    thread = threading.Thread(target=run_longpoll, args=(loop,), daemon=True)
    thread.start()

    await check_subscriptions_loop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("👋 VK-бот остановлен")
