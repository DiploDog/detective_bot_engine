import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
import threading
import time
import logging
import os
import sys
import re
import random
import traceback
from datetime import datetime
from typing import Dict, Any, List

# ==================== НАСТРОЙКА ЛОГИРОВАНИЯ ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler('bot_debug.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ==================== КОНФИГУРАЦИЯ ====================
TOKEN = 'vk1.a.PQcODb0aoGVWg5w7mNJ4SsdQouumksSGziBKjp6YXx8abh-6ROyge33XnTnLHiKA1_QaWhSu_fG_tTma9D-2GxcEj8YqsHLUNPXNscFUa8wQJ5kBaEOKOVcVf6dVJetQXoSBZ-WF60ZNPKuIROK_J9rwaZ2oPGmM6zCw-VdQk-XB9lMOMsPfN_waYlj51DC0ffjm1PxUNBeUBILuA6dIGQ'
ADMINS = [26654099]  # Ваш ID ВКонтакте
HEARTBEAT_INTERVAL = 3600  # секунд

vk_session = vk_api.VkApi(token=TOKEN)
vk = vk_session.get_api()
longpoll = VkLongPoll(vk_session)

BOT_START_TIME = datetime.now()

# ==================== ХРАНЕНИЕ ДАННЫХ ====================
user_data: Dict[int, Dict[str, Any]] = {}
user_errors = {}  # user_id -> {сцена: количество ошибок}
user_info = {}  # user_id -> {'full_name': ..., 'username': ...}


# ==================== УТИЛИТЫ ====================
def get_random_id():
    """Генерирует случайный ID для сообщений ВК"""
    return random.randint(1, 2 ** 31)


def notify_admins(text):
    for admin_id in ADMINS:
        try:
            vk.messages.send(
                peer_id=admin_id,
                message=text,
                random_id=get_random_id()
            )
        except Exception as e:
            logger.error(f"Ошибка отправки админу {admin_id}: {e}")


def get_uptime():
    return str(datetime.now() - BOT_START_TIME).split('.')[0]


def init_user_errors(user_id):
    user_errors[user_id] = {"scene1": 0, "scene2": 0, "scene3": 0}


def format_errors_report(user_id):
    errors = user_errors.get(user_id, {})
    info = user_info.get(user_id, {})
    return (
        f"🎉 Игрок прошёл игру!\n"
        f"{'─' * 25}\n"
        f"👤 {info.get('full_name', 'Неизвестно')}\n"
        f"📱 {info.get('username', 'нет')}\n"
        f"🆔 {user_id}\n"
        f"{'─' * 25}\n"
        f"📊 Ошибки: {errors.get('scene1', 0)}/{errors.get('scene2', 0)}/{errors.get('scene3', 0)}"
    )


def parse_answer(text, min_answers, max_answers, total_options):
    numbers = list(map(int, re.findall(r'\d+', text)))
    if not numbers:
        return None
    if any(n < 1 or n > total_options for n in numbers):
        return None
    numbers = list(set(numbers))
    if len(numbers) < min_answers or len(numbers) > max_answers:
        return None
    return numbers


def get_user(user_id: int) -> dict:
    if user_id not in user_data:
        user_data[user_id] = {
            "step": 0,
            "awaiting_hint": False,
            "hint_question": None
        }
    return user_data[user_id]


# ==================== ДАННЫЕ ====================

# Обновленный список улик (41 позиция)
EVIDENCE_LIST = [
    "1. Фото с места преступления надписью «Jac» на стене",
    "2. Фото входной двери",
    "3. Фото следов обуви",
    "4. Фото коробки из-под пиццы на столе",
    "5. Фото садовой перчатки",
    "6. Фото из сейфа с документами и пачками денег",
    "7. Чек на доставку пиццы",
    "8. Парковочный талон",
    "9. Расшифровка записи с автоответчика Елены",
    "10. Страховка",
    "11. Судмедэкспертиза",
    "12. СМС от МЧС",
    "13. СМС от «Заноза»",
    "14. СМС от «Аптека»",
    "15. СМС от «Братишка»",
    "16. СМС от «Грешник»",
    "17. Допрос Лео Миллер от 15.10.2023",
    "18. Допрос Виктор Браун от 15.10.2023",
    "19. Допрос Марк Дэвис от 15.10.2023",
    "20. Допрос Джулиан Эванс от 15.10.2023",
    "21. Допрос Оливия Коллинз от 15.10.2023",
    "22. Допрос Джек Томас от 15.10.2023",
    "23. Допрос Сара Вилсон от 15.10.2023",
    "24. Допрос Стив Коллинз от 15.10.2023",
    "25. Допрос Клэр Андерсон от 15.10.2023",
    "26. Допрос Лео Миллер от 16.10.2023",
    "27. Допрос Виктор Браун от 16.10.2023",
    "28. Допрос Джулиан Эванс от 16.10.2023",
    "29. Письмо от полиции Клейвила",
    "30. Письмо из частной клиники Rehab",
    "31. Скрин из портала в даркнете",
    "32. История в Телеграм Клэр",
    "33. История в Телеграм «Аптека»",
    "34. История в Телеграм Сары",
    "35. История в Телеграм «Заноза»",
    "36. Допрос Джулиан Эванс от 17.10.2023",
    "37. Допрос Оливия Коллинз от 17.10.2023",
    "38. Допрос Саймон Бэйкер от 17.10.2023",
    "39. Распечатка истории посещений веб-страниц с ноутбука",
    "40. Фото из бара",
    "41. Аудиозапись разговора Елены и Кевина",
]

# Структура вопросов (обновленная)
QUESTIONS = [
    {
        "id": 1,
        "text": "Человек, который наследил ботинками на полу в доме жертвы, и есть убийца?",
        "correct": ["нет", "не"],
        "next_msg": "Супер!",
        "wrong_msg": "А ты точно детектив? Прочитай улики еще раз и попробуй другой вариант ответа.",
        "hint": "Кажется, ты невнимательно ознакомился с судмедэкспертизой. Попробуй поискать там."
    },
    {
        "id": 2,
        "text": "Какая улика на это указывает? Напиши номер улики из списка улик по делу.",
        "correct": ["11"],
        "next_msg": "Совершенно верно! Именно судмедэксперт подтверждает, что следы были оставлены уже после 22:00 (когда начался дождь), а значит, кто-то был у Елены после ее смерти, но скрывает это.",
        "wrong_msg": "Хм... по-моему, эта улика не относится к теме разговора. Может, тебе приходит на ум что-то еще?",
        "hint": "Кажется, ты невнимательно ознакомился с судмедэкспертизой. Попробуй поискать там."
    },
    {
        "id": 3,
        "text": "Ты уже должен был догадаться, кто это. Напиши мне имя этого человека.",
        "correct": ["лео", "лео миллер", "брат елены", "еленин брат"],
        "next_msg": "Твои дедуктивные способности поразительны!",
        "wrong_msg": "Что натолкнуло тебя на эту мысль? Как по мне, кандидат слабоват. Кто еще у тебя на примете?",
        "hint": "Кажется, только этот человек носил такой размер обуви."
    },
    {
        "id": 4,
        "text": "Какие 2 улики это доказывают? Напиши номера улик из списка улик по делу через запятую.",
        "correct": [["17", "11"], ["11", "17"]],
        "next_msg": "Отлично! Наконец-то мы разобрались с братом жертвы.",
        "wrong_msg": "Неверно. Давай еще раз.",
        "hint": "Посмотри, кому принадлежит 45 размер обуви."
    },
    {
        "id": 5,
        "text": "Но если ты заметил, есть еще 2 человека, кто врет в своих допросах. Знаешь их имена? Напиши их через запятую.",
        "correct": [
            ["виктор", "джулиан"],
            ["джулиан", "виктор"],
            ["виктор браун", "джулиан эванс"],
            ["джулиан эванс", "виктор браун"]
        ],
        "next_msg": "Да ты чертов гений!",
        "wrong_msg": "Чувак, проблема в тебе или во мне? Давай по новой.",
        "hint": "Лео мы уже проверили, про Марка, Клэр, Стива и Сару знаем пока очень мало. Однако двое мужчин из списка допрошенных все-таки соврали. Один из них скрывает мотив, второй возможность совершения преступления."
    },
    {
        "id": 6,
        "text": "Сможешь указать 2 улики, которые это подтверждают? Напиши номера улик из списка улик по делу через запятую.",
        "correct": [["8", "16"], ["16", "8"]],
        "next_msg": "Не перестаю тебе удивляться. Верно!",
        "wrong_msg": "Неверно. Давай еще раз.",
        "hint": "Это парковочный талон Джулиана, а также переписка Елены и Виктора, которая говорит нам о том, что Виктор и Елена явно были в плохих отношениях."
    },
    {
        "id": 7,
        "text": "Ну что ж. Пришло время вскрывать следующий конверт! И вот мой новый вопрос для тебя: Тебе уже известно, кому принадлежит ник «аптека» в телефоне жертвы? Напиши имя этого человека.",
        "correct": [
            "оливия", "оливия коллинз", "соседка елены",
            "оливие", "оливии", "соседке елены",
            "оливии коллинз", "оливие коллинз", "соседке"
        ],
        "next_msg": "Верно. Ты мог заметить, что на истории из Телеграма под ником «Аптека» мы видим Оливию и ее мужа, а потому сделал вывод, что «Аптека» и есть Оливия. Елена и Оливия явно говорят о каких-то незаконных финансовых операциях.",
        "wrong_msg": "Не думаю, поищи ответ тщательнее.",
        "hint": "Пришло время сопоставить истории с никами из Телеграма Елены."
    },
    {
        "id": 8,
        "text": "Могла ли Оливия убить Елену?",
        "correct": ["нет", "не"],
        "next_msg": "Верно, ты, наверное, понял, почему?",
        "wrong_msg": "Проверь еще раз возможность Оливии совершения убийства.",
        "hint": ""
    },
    {
        "id": 9,
        "text": "Какие 2 улики помогли тебе понять, что Оливия не могла убить Елену? Напиши номера улик из списка улик по делу через запятую.",
        "correct": [["33", "31"], ["31", "33"]],
        "next_msg": "ты прав",
        "wrong_msg": "Неверно. Попробуй еще раз.",
        "hint": ""
    },
]

# Статьи для финальной части
ARTICLES = [
    {
        "title": "1. частные клиники лечение игровой зависимости Спрингфилд отзывы",
        "text": "Дата и время: 10.10.2023, 22:15\nЗапрос: «частные клиники лечение игровой зависимости Спрингфилд отзывы»\nЗаголовок страницы: «Топ-5 частных клиник для лечения лудомании в Спрингфилде: сравнение программ и цен»\nСОДЕРЖАНИЕ СТАТЬИ (выдержка):\n«Клиника «Рехаб Центр» предлагает одну из самых строгих программ изоляции с полным запретом на доступ к деньгам и гаджетам. Стоимость 28-дневного курса начинается от $15 000. По словам бывших пациентов, программа эффективна, но требует полного согласия больного, иначе возможны срывы сразу после выписки.»"
    },
    {
        "title": "2. раздел имущества при разводе без брачного договора иллинойс",
        "text": "Дата и время: 11.10.2023, 09:40\nЗапрос: «раздел имущества при разводе без брачного договора иллинойс»\nЗаголовок страницы: «Как делится имущество при разводе в Иллинойсе: права супругов и типичные ошибки»\nСОДЕРЖАНИЕ СТАТЬИ (выдержка):\n«Страховые полисы, приобретенные в браке, считаются совместной собственностью. В случае смерти одного из супругов второй, как выгодоприобретатель, имеет право на выплату даже при подаче на развод, если полис не был переоформлен. Суды штата часто расценивают это как существенный актив при разделе.»"
    },
    {
        "title": "3. причины развода смерть супруга иллинойс",
        "text": "Дата и время: 12.10.2023, 10:30\nЗапрос: «причины развода смерть супруга иллинойс»\nЗаголовок страницы: «Развод и смерть супруга: как это влияет на имущество и страховые выплаты?»\nСОДЕРЖАНИЕ СТАТЬИ (выдержка):\n«Если во время бракоразводного процесса один из супругов умирает, дело о разводе прекращается, и вступают в силу правила наследования. Особенно сложны случаи, когда смерть наступила в результате несчастного случая или насилия. По статистике, около 5% разводов в Иллинойсе связаны с последующей гибелью одного из супругов в течение года.»"
    },
    {
        "title": "4. домашнее насилие статистика сша",
        "text": "Дата и время: 12.10.2023, 11:45\nЗапрос: «домашнее насилие статистика сша»\nЗаголовок страницы: «Статистика домашнего насилия в США: цифры и резонансные дела»\nСОДЕРЖАНИЕ СТАТЬИ (выдержка):\n«По данным Национальной коалиции против домашнего насилия, ежегодно в США от рук интимных партнеров погибает около 1500 женщин. Однако не менее трагичны случаи, когда жертвами становятся и мужчины. Одно из громких дел последних лет — процесс над Джейкобом Адамсом, который в 2016 году был осужден за убийство своего соседа по квартире во время бытовой ссоры. Это дело привлекло внимание общественности к проблеме неконтролируемой агрессии в семейных конфликтах. После освобождения Адамс сменил имя и, предположительно, переехал в другой штат.»"
    },
    {
        "title": "5. доказательство домогательств на работе запись разговора",
        "text": "Дата и время: 12.10.2023, 20:17\nЗапрос: «что считается доказательством домогательств на работе запись разговора»\nЗаголовок страницы: «Тайная запись разговора как доказательство харассмента: законность и сила в суде»\nСОДЕРЖАНИЕ СТАТЬИ (выдержка):\n«В штате Иллинойс разрешена односторонняя аудиозапись разговора. Такое доказательство является допустимым в суде и часто становится решающим, особенно если на записи четко слышно «услуга за услугу» — предложение каких-либо преимуществ в обмен на личные услуги.»"
    },
    {
        "title": "6. Jacob Adams Oakville 2016 приговор",
        "text": "Дата и время: 13.10.2023, 11:05\nЗапрос: «Jacob Adams Oakville 2016 приговор»\nЗаголовок страницы: «Приговор по делу Джейкоба Адамса: 7 лет за непредумышленное убийство в состоянии аффекта»\nСОДЕРЖАНИЕ СТАТЬИ:\n«...Суд города Оквилл вынес приговор 28-летнему Джейкобу Адамсу. Подсудимый был признан виновным в непредумышленном убийстве своего соседа по квартире, 30-летнего Карлоса Риверы, во время бытовой ссоры в апреле 2015 года. Как установило следствие, конфликт начался из-за денежного долга и перерос в драку, в ходе которой Адамс нанёс Ривере несколько ударов кухонным ножом. Защита настаивала на самообороне и состоянии сильного душевного волнения. Суд принял во внимание чистую до этого репутацию подсудимого, его раскаяние и то, что он немедленно вызвал полицию, но отметил чрезмерную жестокость и применение ножа. Джейкоб Адамс приговорён к 7 годам лишения свободы с правом на условно-досрочное освобождение после отбытия двух третей срока...»"
    },
    {
        "title": "7. условно-досрочное освобождение Иллинойс условия",
        "text": "Дата и время: 13.10.2023, 11:20\nЗапрос: «условно-досрочное освобождение Иллинойс условия»\nЗаголовок страницы: «Комиссия по условно-досрочному освобождению: процедура и критерии»\nСОДЕРЖАНИЕ СТАТЬИ (выдержка):\n«Лица, осужденные за насильственные преступления, такие как непредумышленные, могут претендовать на условно-досрочное освобождение после отбытия не менее 2/3 срока при образцовом поведении, признании вины и наличии утвержденного плана реинтеграции, включая место жительства и работу.»"
    },
    {
        "title": "8. рецепт домашней пиццы пепперони",
        "text": "Дата и время: 13.10.2023, 19:30\nЗапрос: «рецепт домашней пиццы пепперони с тонким тестом»\nЗаголовок страницы: «Идеальная домашняя пицца с пепперони: пошаговый рецепт»\nСОДЕРЖАНИЕ СТАТЬИ (выдержка):\n«Секрет хрустящего тонкого теста — в высокотемпературной выпечке (минимум 250°C) и минимальном количестве начинки. Раскатайте тесто как можно тоньше, смажьте томатным соусом с орегано, выложите пепперони и обильно посыпьте тертой моцареллой. Выпекайте 10-12 минут до золотистого края.»"
    },
    {
        "title": "9. прогноз матча Springfield FC Chicago Fire",
        "text": "Дата и время: 14.10.2023, 15:10\nЗапрос: «Springfield FC Chicago Fire прогноз ставки»\nЗаголовок страницы: «Прогноз на матч MLS: Springfield FC против Chicago Fire. Кого брать в ставках?»\nСОДЕРЖАНИЕ СТАТЬИ (выдержка):\n«Несмотря на статус явного аутсайдера (коэф. на победу 2.10), Springfield FC может преподнести сюрприз на домашнем поле. Матч начнется в 19:00 и, вероятно, будет богат на голевые моменты во втором тайме. Букмекеры советуют осторожность, но ставка на тотал больше 2.5 выглядит оправданной.»"
    },
    {
        "title": "10. подлинность рецептурного бланка водяные знаки",
        "text": "Дата и время: 14.10.2023, 16:55\nЗапрос: «как проверить подлинность рецептурного бланка водяные знаки»\nЗаголовок страницы: «Руководство для фармацевтов: 5 уровней защиты официальных рецептурных бланков»\nСОДЕРЖАНИЕ СТАТЬИ (выдержка):\n«Наиболее надежный способ отличить подделку — проверить бланк под ультрафиолетом: оригинал должен иметь скрытые UV-метки с логотипом штата. Также обратите внимание на микрошрифт в нижнем углу и тактильные ощущения от бумаги — оригинальная имеет легкую шероховатость.»"
    },
    {
        "title": "11. отслеживание заказа пиццы Cheesus Crust",
        "text": "Дата и время: 14.10.2023, 18:40 (ПОСЛЕДНЯЯ ЗАПИСЬ)\nЗапрос: «номер доставки пиццы Cheesus Crust спрингфилд»\nЗаголовок страницы: «Cheesus Crust — отслеживание заказа»\nСОДЕРЖАНИЕ СТАТЬИ (выдержка):\n«Для отслеживания статуса вашего заказа введите его номер в поле ниже. Среднее время доставки в районе Maple Street составляет 30-40 минут в вечернее время.»"
    }
]

# Варианты имени убийцы
KILLER_NAMES = {
    "марк", "марк дэвис", "марк девис", "джейкоб адамс", "джейкоб", "адамс"
}


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def send_message(vk, user_id: int, text: str, keyboard=None):
    params = {
        "peer_id": user_id,
        "message": text,
        "random_id": get_random_id()
    }
    if keyboard:
        params["keyboard"] = keyboard.get_keyboard()
    vk.messages.send(**params)


def send_photo(vk, user_id: int, photo_path: str, caption: str = "", keyboard=None):
    from vk_api.upload import VkUpload
    upload = VkUpload(vk)
    photo = upload.photo_messages(photo_path)[0]
    attachments = f"photo{photo['owner_id']}_{photo['id']}"
    params = {
        "peer_id": user_id,
        "message": caption,
        "attachment": attachments,
        "random_id": get_random_id()
    }
    if keyboard:
        params["keyboard"] = keyboard.get_keyboard()
    vk.messages.send(**params)


def send_question(vk, user_id: int, q_num: int):
    if q_num < 1 or q_num > len(QUESTIONS):
        return
    q = QUESTIONS[q_num - 1]
    send_message(vk, user_id, q["text"])


def ask_hint(vk, user_id: int, q_num: int):
    if q_num != 0:
        if q_num < 1 or q_num > len(QUESTIONS):
            return
        if not QUESTIONS[q_num - 1]["hint"]:
            logger.warning(f"ask_hint called for question {q_num} with no hint")
            return
    user = get_user(user_id)
    user["awaiting_hint"] = True
    user["hint_question"] = q_num
    keyboard = VkKeyboard(inline=False)
    keyboard.add_button("Да", color=VkKeyboardColor.POSITIVE)
    keyboard.add_button("Нет", color=VkKeyboardColor.NEGATIVE)
    send_message(vk, user_id, "Друг, тебе нужна подсказка?", keyboard)


def send_hint(vk, user_id: int, q_num: int):
    if q_num < 1 or q_num > len(QUESTIONS):
        return
    hint_text = QUESTIONS[q_num - 1]["hint"]
    if hint_text:
        send_message(vk, user_id, hint_text)
    else:
        send_message(vk, user_id, "К сожалению, подсказки нет.")


def send_articles_list(vk, user_id: int):
    message = "Я нашел распечатку истории посещений веб-страниц с ноутбука Елены Миллер за период с 10 по 14 октября 2023 г. История восстановлена цифровыми криминалистами.\n\n"
    message += "Устройство: MacBook Air пользователя «Elena»\n"
    message += "Период: 10.10.2023 — 14.10.2023\n\n"
    for article in ARTICLES:
        message += f"{article['title']}\n"
    message += "\nВведи номер статьи (от 1 до 11), чтобы прочитать её."
    send_message(vk, user_id, message)


def handle_article_request(vk, user_id: int, text: str) -> bool:
    if text.isdigit():
        num = int(text)
        if 1 <= num <= len(ARTICLES):
            article = ARTICLES[num - 1]
            send_message(vk, user_id, article["text"])
            send_message(vk, user_id,
                         "Интересненько, не так ли? Изучи все статьи, и как только будешь готов, напиши \"Готов назвать убийцу\" в чат.")
            return True
    return False


def send_audio_placeholder(vk, user_id: int):
    try:
        # Используем ID аудиозаписи из ВКонтакте
        attachment = "audio46166014_456239718"
        vk.messages.send(
            peer_id=user_id,
            message="🎙️ Аудиозапись разговора Елены и Кевина (запись сделана Джулианом через дверь):",
            attachment=attachment,
            random_id=get_random_id()
        )
        logger.info("Аудиозапись успешно отправлена")
    except Exception as e:
        logger.error(f"Ошибка при отправке аудиозаписи: {e}")
        send_message(vk, user_id, "🔊 Аудиозапись временно недоступна")


def send_final_report_placeholder(vk, user_id: int):
    try:
        from vk_api.upload import VkUpload
        upload = VkUpload(vk)
        if not os.path.exists("финальный полицейский отчет.jpg"):
            send_message(vk, user_id, "📄 Файл отчета не найден")
            return
        photo = upload.photo_messages("финальный полицейский отчет.jpg")
        attachment = f"photo{photo[0]['owner_id']}_{photo[0]['id']}"
        vk.messages.send(
            peer_id=user_id,
            message="📄 Финальный полицейский отчет:",
            attachment=attachment,
            random_id=get_random_id()
        )
        logger.info("Финальный отчет отправлен")
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        send_message(vk, user_id, f"📄 Ошибка: {e}")


def handle_safe(vk, user_id: int, text: str):
    if text == "1503":
        send_photo(vk, user_id, "safe_open.jpg",
                   "Щелчок! Сейф открыт.\n\nВнутри вы находите несколько туго набитых пачек долларов и стопку рецептурных бланков с подозрительными подписями.\n\n")
        user = get_user(user_id)
        user["step"] = 6
        send_question(vk, user_id, 5)
    else:
        send_message(vk, user_id,
                     "Неверный код. Сейф не открывается. Попробуйте ещё раз. Если нужна подсказка, напишите «Подсказка».")


def handle_safe_hint(vk, user_id: int):
    send_message(vk, user_id,
                 "Елена не стала бы выдумывать сложный код. Она выбрала бы что-то, что всегда помнит, даже в стрессовой ситуации. Может, чей-то день рождения?")


def heartbeat():
    while True:
        time.sleep(HEARTBEAT_INTERVAL)
        logger.info(f"Heartbeat. Аптайм: {get_uptime()}")


def handle_start(vk, user_id: int):
    user = get_user(user_id)
    user["step"] = 1
    user["awaiting_hint"] = False
    user["hint_question"] = None
    send_message(vk, user_id,
                 "Привет! Меня зовут Том Митчел. Я веду дело об убийстве Елены Миллер. "
                 "Улик и подозреваемых больше, чем мне бы хотелось. Поэтому мне определенно нужна будет твоя помощь. "
                 "Но прежде, чем показать тебе все секретные материалы дела, я должен убедиться, что ты настоящий сыщик. "
                 "Изучи первый пакет улик и ответь на мой вопрос: Человек, который наследил ботинками на полу в доме жертвы, и есть убийца?")


# ==================== ОСНОВНАЯ ЛОГИКА ====================

def handle_message(vk, user_id: int, text: str):
    user = get_user(user_id)
    text_lower = text.lower().strip()

    if user["step"] == 0:
        send_message(vk, user_id,
                     "Приветствую, детектив! Чтобы начать расследование, напиши  кодовое слово, указанное в коробке.")
        return

    # Обработка подсказки
    if user["awaiting_hint"] and text_lower in ["да", "нет"]:
        q_num = user["hint_question"]
        user["awaiting_hint"] = False
        user["hint_question"] = None
        if text_lower == "да":
            if q_num == 0:
                hint = "Один человек из подозреваемых был у Елены во время убийства. Из допроса Джулиана и Саймона мы делаем вывод, что это был мужчина. У кого из мужчин нет алиби на время преступления?"
                send_message(vk, user_id, hint)
            elif q_num == 99:
                handle_safe_hint(vk, user_id)
            else:
                send_hint(vk, user_id, q_num)
            send_message(vk, user_id, "Попробуй ответить на вопрос еще раз.")
            if q_num != 0 and q_num != 99:
                send_question(vk, user_id, q_num)
            elif q_num == 99:
                send_photo(vk, user_id, "safe_closed.jpg",
                           "Вы находите в спальне Елены старый металлический сейф. На дисплее мигает запрос на 4 цифры. Елена была человеком привычки и часто использовала в качестве паролей личные даты.\n\nВведите код, чтобы открыть сейф:")
        else:
            send_message(vk, user_id, "Хорошо, попробуй ответить на вопрос еще раз.")
            if q_num != 0 and q_num != 99:
                send_question(vk, user_id, q_num)
            elif q_num == 99:
                send_photo(vk, user_id, "safe_closed.jpg",
                           "Вы находите в спальне Елены старый металлический сейф. На дисплее мигает запрос на 4 цифры. Елена была человеком привычки и часто использовала в качестве паролей личные даты.\n\nВведите код, чтобы открыть сейф:")
        return

    # Режим сейфа
    if user["step"] == 5:
        if text_lower == "подсказка":
            handle_safe_hint(vk, user_id)
        else:
            handle_safe(vk, user_id, text)
        return

    # Вопросы 1-4
    current_step = user["step"]
    if 1 <= current_step <= 4:
        q = QUESTIONS[current_step - 1]
        correct = q["correct"]
        is_correct = False
        if current_step == 2:
            numbers = [s.strip() for s in text.split(',') if s.strip().isdigit()]
            if numbers and numbers[0] in correct:
                is_correct = True
        elif current_step == 4:
            numbers = [s.strip() for s in text.split(',') if s.strip().isdigit()]
            if len(numbers) == 2:
                correct_set = set(q["correct"][0])
                user_set = set(numbers)
                if user_set == correct_set:
                    is_correct = True
                elif len(user_set & correct_set) == 1:
                    send_message(vk, user_id, "Одно из чисел верно, но второе – нет. Попробуйте снова.")
                    return
        elif current_step in [1, 3]:
            for c in correct:
                if isinstance(c, str) and c in text_lower:
                    is_correct = True
                    break
        if is_correct:
            send_message(vk, user_id, q["next_msg"])
            next_step = current_step + 1
            user["step"] = next_step
            if next_step == 5:
                send_photo(vk, user_id, "safe_closed.jpg",
                           "Вы находите в спальне Елены старый металлический сейф. На дисплее мигает запрос на 4 цифры. Елена была человеком привычки и часто использовала в качестве паролей личные даты.\n\nВведите код, чтобы открыть сейф:")
            else:
                send_question(vk, user_id, next_step)
        else:
            send_message(vk, user_id, q["wrong_msg"])
            if q["hint"] and q["hint"].strip():
                ask_hint(vk, user_id, current_step)
        return

    # Вопрос 5 (о двух врунах) – step 6
    if current_step == 6:
        q = QUESTIONS[4]
        correct = q["correct"]
        parts = [p.strip().lower() for p in text.split(',')]
        if len(parts) == 1 and ' и ' in text_lower:
            parts = [p.strip().lower() for p in text_lower.split(' и ')]
        is_correct = False
        if len(parts) == 2:
            for combo in correct:
                if (parts[0] in combo and parts[1] in combo) and set(parts) == set(combo):
                    is_correct = True
                    break
        if is_correct:
            send_message(vk, user_id, q["next_msg"])
            user["step"] = 7
            send_question(vk, user_id, 6)
        else:
            send_message(vk, user_id, q["wrong_msg"])
            if q["hint"] and q["hint"].strip():
                ask_hint(vk, user_id, current_step)
        return

    # Вопрос 6 (две улики) – step 7
    if current_step == 7:
        q = QUESTIONS[5]
        correct = q["correct"]
        numbers = [s.strip() for s in text.split(',') if s.strip().isdigit()]
        is_correct = False
        if len(numbers) == 2:
            correct_set = set(correct[0])
            user_set = set(numbers)
            if user_set == correct_set:
                is_correct = True
            elif len(user_set & correct_set) == 1:
                send_message(vk, user_id, "Одно из чисел верно, но второе – нет. Попробуйте снова.")
                return
        if is_correct:
            send_message(vk, user_id, q["next_msg"])
            user["step"] = 8
            send_question(vk, user_id, 7)
        else:
            send_message(vk, user_id, q["wrong_msg"])
            if q["hint"] and q["hint"].strip():
                ask_hint(vk, user_id, current_step)
        return

    # Вопрос 7 (кто такой "аптека") – step 8
    if current_step == 8:
        q = QUESTIONS[6]
        correct = q["correct"]
        is_correct = any(c in text_lower for c in correct)
        if is_correct:
            send_message(vk, user_id, q["next_msg"])
            user["step"] = 9
            send_question(vk, user_id, 8)
        else:
            send_message(vk, user_id, q["wrong_msg"])
            if q["hint"] and q["hint"].strip():
                ask_hint(vk, user_id, current_step)
        return

    # Вопрос 8 (могла ли Оливия убить) – step 9
    if current_step == 9:
        q = QUESTIONS[7]
        correct = q["correct"]
        is_correct = any(c in text_lower for c in correct)
        if is_correct:
            send_message(vk, user_id, q["next_msg"])
            user["step"] = 10
            send_question(vk, user_id, 9)
        else:
            send_message(vk, user_id, q["wrong_msg"])
        return

    # Вопрос 9 (две улики про Оливию) – step 10
    if current_step == 10:
        q = QUESTIONS[8]
        correct = q["correct"]
        numbers = [s.strip() for s in text.split(',') if s.strip().isdigit()]
        is_correct = False
        if len(numbers) == 2:
            correct_set = set(correct[0])
            user_set = set(numbers)
            if user_set == correct_set:
                is_correct = True
            elif len(user_set & correct_set) == 1:
                send_message(vk, user_id, "Одно из чисел верно, но второе – нет. Попробуйте снова.")
                return
        if is_correct:
            send_message(vk, user_id, q["next_msg"])
            user["step"] = 11
            send_message(vk, user_id,
                         "Вот мы и на финишной прямой. Открывай последний конверт с уликами. Кстати, сразу присылаю тебе одну из них сюда.")
            send_audio_placeholder(vk, user_id)

            def delayed_articles():
                time.sleep(5)  # для теста 5 секунд, потом верните 300
                send_message(vk, user_id, "Кстати, чуть не забыл! У меня же есть для тебя еще одна улика! "
                                          "Я нашел распечатку истории посещений веб-страниц с ноутбука Елены Миллер за период с 10 по 14 октября 2023 г. "
                                          "История восстановлена цифровыми криминалистами, и я готов ею с тобой поделиться.")
                send_articles_list(vk, user_id)
                user["step"] = 12

            threading.Thread(target=delayed_articles).start()
        else:
            send_message(vk, user_id, q["wrong_msg"])
        return

    # Статьи и ожидание команды
    if user["step"] == 12:
        if handle_article_request(vk, user_id, text):
            return
        if text_lower == "готов назвать убийцу":
            send_message(vk, user_id, "Я в предвкушении! Итак, удиви меня!")
            user["step"] = 13
        else:
            send_message(vk, user_id, "Изучи все статьи и напиши 'Готов назвать убийцу', когда будешь готов.")
        return

    # Ожидание имени убийцы
    if user["step"] == 13:
        if any(name in text_lower for name in KILLER_NAMES):
            send_message(vk, user_id,
                         "Я горжусь тобой, мой друг! Ты идеально справился с этим преступлением и вычислил убийцу. "
                         "Если тебе интересно узнать историю целиком, то я вышлю тебе отчет полиции по этому делу. "
                         "Там ты найдешь все детали по делу.")
            send_final_report_placeholder(vk, user_id)
            print(format_errors_report(user_id))
            notify_admins(format_errors_report(user_id))
            user["step"] = 14
        else:
            send_message(vk, user_id, "Кажется, ты планируешь посадить невиновного?")
            ask_hint(vk, user_id, 0)
        return


# ==================== ЗАПУСК ====================
def main():
    logger.info("=" * 40)
    logger.info("ЗАПУСК БОТА Убийственная Маргарита (VK API, текстовый ввод)")
    logger.info("=" * 40)
    notify_admins("🟢 Бот Убийственная Маргарита запущен (текстовый режим)")

    heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()

    try:
        for event in longpoll.listen():
            if event.type == VkEventType.MESSAGE_NEW and event.to_me:
                user_id = event.user_id
                text = event.text.lower().strip()
                logger.info(f"Сообщение от {user_id}: {text}")
                print(text)
                if text in ["маргарита", "убийственная маргарита"]:
                    user = get_user(user_id)
                    if user["step"] == 0:
                        handle_start(vk, user_id)
                    else:
                        send_message(vk, user_id, "Вы уже в деле, детектив! Продолжайте расследование.")
                else:
                    handle_message(vk, user_id, text)
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Критическая ошибка: {e}\n{tb}")
        try:
            notify_admins(f"🔴 БОТ Убийственная Маргарита УПАЛ: {type(e).__name__}: {e}\n\n{tb[:3500]}")
        except:
            pass
        raise
    finally:
        notify_admins("🔴 Бот Убийственная Маргарита остановлен")
        logger.info("Бот Убийственная Маргарита остановлен")


if __name__ == "__main__":
    main()
