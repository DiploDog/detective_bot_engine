import asyncio
import logging
import os
from contextlib import suppress
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
router = Router()

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

# Структура вопросов
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

# ==================== ХРАНЕНИЕ ПРОГРЕССА ====================

DEFAULT_USER_DATA = {
    "step": 0,
    "safe_opened": False,
    "awaiting_hint": False,
    "hint_question": None,
    "temp_selected": [],
}
background_tasks: set[asyncio.Task] = set()


async def get_user(state: FSMContext) -> dict:
    stored = await state.get_data()
    user = {**DEFAULT_USER_DATA, **stored}
    if user != stored:
        await state.set_data(user)
    return user


# ==================== КЛАВИАТУРЫ ====================

def get_hint_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да", callback_data="hint_yes"),
                InlineKeyboardButton(text="Нет", callback_data="hint_no"),
            ]
        ]
    )


def get_articles_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=article["title"], callback_data=f"article_{i}")]
            for i, article in enumerate(ARTICLES)
        ]
    )


# ==================== ОБРАБОТЧИКИ ====================

async def send_question(bot: Bot, user_id: int, q_num: int) -> None:
    if 1 <= q_num <= len(QUESTIONS):
        await bot.send_message(user_id, QUESTIONS[q_num - 1]["text"])


async def ask_hint(bot: Bot, user_id: int, q_num: int, state: FSMContext) -> None:
    await state.update_data(awaiting_hint=True, hint_question=q_num)
    await bot.send_message(
        user_id,
        "Друг, тебе нужна подсказка?",
        reply_markup=get_hint_keyboard(),
    )


async def send_hint(bot: Bot, user_id: int, q_num: int) -> None:
    if not 1 <= q_num <= len(QUESTIONS):
        return
    hint_text = QUESTIONS[q_num - 1]["hint"]
    await bot.send_message(user_id, hint_text or "К сожалению, подсказки нет.")


async def send_safe_photo(bot: Bot, user_id: int, filename: str, caption: str) -> None:
    image_path = BASE_DIR / filename
    if image_path.is_file():
        await bot.send_photo(user_id, FSInputFile(image_path), caption=caption)
        return
    logger.warning("Файл %s не найден, отправляется только текст", image_path)
    await bot.send_message(user_id, caption)


async def send_articles_list(bot: Bot, user_id: int) -> None:
    text = (
        "Я нашел распечатку истории посещений веб-страниц с ноутбука Елены Миллер "
        "за период с 10 по 14 октября 2023 г. История восстановлена цифровыми криминалистами.\n\n"
        "Устройство: MacBook Air пользователя «Elena»\n"
        "Период: 10.10.2023 — 14.10.2023\n\n"
    )
    text += "\n".join(article["title"] for article in ARTICLES)
    text += "\n\nНажми на название статьи, чтобы прочитать её:"
    await bot.send_message(user_id, text, reply_markup=get_articles_keyboard())


async def handle_article_request(bot: Bot, user_id: int, text: str) -> bool:
    if not text.isdigit():
        return False
    num = int(text)
    if not 1 <= num <= len(ARTICLES):
        return False
    await bot.send_message(user_id, ARTICLES[num - 1]["text"])
    await bot.send_message(
        user_id,
        'Интересненько, не так ли? Изучи все статьи, и как только будешь готов, '
        'напиши "Готов назвать убийцу" в чат.',
    )
    return True


async def send_audio_recording(bot: Bot, user_id: int) -> None:
    audio_path = BASE_DIR / "Диктофонная запись с телефона Джулиана.mp3"
    await bot.send_audio(
        user_id,
        audio=FSInputFile(audio_path),
        title="Диктофонная запись с телефона Джулиана",
    )


async def send_final_report(bot: Bot, user_id: int) -> None:
    report_path = BASE_DIR / "финальный полицейский отчет.jpg"
    await bot.send_document(
        user_id,
        document=FSInputFile(report_path),
        caption="Финальный полицейский отчет",
    )


async def handle_safe(bot: Bot, user_id: int, text: str, state: FSMContext) -> None:
    if text != "1503":
        await bot.send_message(
            user_id,
            "Неверный код. Сейф не открывается. Попробуйте ещё раз. "
            "Если нужна подсказка, напишите «Подсказка».",
        )
        return

    await send_safe_photo(
        bot,
        user_id,
        "safe_open.jpg",
        "Щелчок! Сейф открыт.\n\nВнутри вы находите несколько туго набитых пачек долларов "
        "и стопку рецептурных бланков с подозрительными подписями.\n\n",
    )
    await state.update_data(step=5, safe_opened=True)
    await send_question(bot, user_id, 5)


async def handle_safe_hint(bot: Bot, user_id: int) -> None:
    await bot.send_message(
        user_id,
        "Елена не стала бы выдумывать сложный код. Она выбрала бы что-то, что всегда "
        "помнит, даже в стрессовой ситуации. Может, чей-то день рождения?",
    )


def parse_pair(text: str) -> list[str]:
    separator = "," if "," in text else " и "
    return [part.strip() for part in text.split(separator) if part.strip()]


async def check_answer(
    bot: Bot,
    user_id: int,
    current_step: int,
    text: str,
) -> bool | None:
    question = QUESTIONS[current_step - 1]
    correct = question["correct"]

    if current_step == 2:
        numbers = [part.strip() for part in text.split(",") if part.strip().isdigit()]
        return bool(numbers and numbers[0] in correct)

    if current_step in {4, 6, 9}:
        values = parse_pair(text)
        if len(values) != 2:
            return False
        correct_set = set(correct[0])
        user_set = set(values)
        if user_set == correct_set:
            return True
        if len(user_set & correct_set) == 1:
            await bot.send_message(
                user_id,
                "Одно из значений верно, но второе – нет. Попробуйте снова.",
            )
            return None
        return False

    if current_step == 5:
        values = parse_pair(text)
        return len(values) == 2 and any(set(values) == set(combo) for combo in correct)

    return any(isinstance(answer, str) and answer in text for answer in correct)


async def delayed_articles(bot: Bot, user_id: int) -> None:
    await asyncio.sleep(300)
    await bot.send_message(
        user_id,
        "Кстати, чуть не забыл! У меня же есть для тебя еще одна улика! "
        "Я нашел распечатку истории посещений веб-страниц с ноутбука Елены Миллер "
        "за период с 10 по 14 октября 2023 г. История восстановлена цифровыми "
        "криминалистами, и я готов ею с тобой поделиться.",
    )
    await send_articles_list(bot, user_id)


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.set_data({**DEFAULT_USER_DATA, "step": 1})
    await message.answer(
        "Привет! Меня зовут Том Митчел. Я веду дело об убийстве Елены Миллер. "
        "Улик и подозреваемых больше, чем мне бы хотелось. Поэтому мне определенно нужна будет твоя помощь. "
        "Но прежде, чем показать тебе все секретные материалы дела, я должен убедиться, что ты настоящий сыщик. "
        "Изучи первый пакет улик и ответь на мой вопрос: Человек, который наследил ботинками на полу в доме жертвы, и есть убийца?"
    )


@router.message(F.text)
async def handle_text(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    text = message.text.strip().lower()
    user = await get_user(state)
    current_step = user["step"]

    if current_step == 0:
        await message.answer("Напишите /start, чтобы начать расследование.")
        return

    if current_step == 10:
        if await handle_article_request(message.bot, user_id, text):
            return
        if text == "готов назвать убийцу":
            await message.answer("Я в предвкушении! Итак, удиви меня!")
            await state.update_data(step=11)
        else:
            await message.answer(
                "Изучи все статьи и напиши 'Готов назвать убийцу', когда будешь готов."
            )
        return

    if current_step == 11:
        if any(name in text for name in KILLER_NAMES):
            await message.answer(
                "Я горжусь тобой, мой друг! Ты идеально справился с этим преступлением и вычислил убийцу. "
                "Если тебе интересно узнать историю целиком, то я вышлю тебе отчет полиции по этому делу. "
                "Там ты найдешь все детали по делу."
            )
            await send_final_report(message.bot, user_id)
            await state.update_data(step=12)
        else:
            await message.answer("Кажется, ты планируешь посадить невиновного?")
            await ask_hint(message.bot, user_id, 0, state)
        return

    if current_step == 5 and not user["safe_opened"]:
        if text == "подсказка":
            await handle_safe_hint(message.bot, user_id)
        else:
            await handle_safe(message.bot, user_id, text, state)
        return

    if 1 <= current_step <= 9:
        question = QUESTIONS[current_step - 1]
        is_correct = await check_answer(message.bot, user_id, current_step, text)
        if is_correct is None:
            return
        if not is_correct:
            await message.answer(question["wrong_msg"])
            if question["hint"].strip():
                await ask_hint(message.bot, user_id, current_step, state)
            return

        await message.answer(question["next_msg"])
        next_step = current_step + 1
        await state.update_data(step=next_step)

        if next_step == 5:
            await send_safe_photo(
                message.bot,
                user_id,
                "safe_closed.jpg",
                "Вы находите в спальне Елены старый металлический сейф. На дисплее мигает запрос на 4 цифры. "
                "Елена была человеком привычки и часто использовала в качестве паролей личные даты.\n\n"
                "Введите код, чтобы открыть сейф:",
            )
        elif next_step == 10:
            await message.answer(
                "Вот мы и на финишной прямой. Открывай последний конверт с уликами. "
                "Кстати, сразу присылаю тебе одну из них сюда."
            )
            await send_audio_recording(message.bot, user_id)
            task = asyncio.create_task(delayed_articles(message.bot, user_id))
            background_tasks.add(task)
            task.add_done_callback(background_tasks.discard)
        else:
            await send_question(message.bot, user_id, next_step)


@router.callback_query(F.data.in_({"hint_yes", "hint_no"}))
async def handle_hint_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return

    user = await get_user(state)
    q_num = user["hint_question"]
    await state.update_data(awaiting_hint=False, hint_question=None)
    with suppress(Exception):
        await callback.message.delete()

    if callback.data == "hint_yes":
        if q_num == 0:
            await callback.message.answer(
                "Один человек из подозреваемых был у Елены во время убийства. "
                "Из допроса Джулиана и Саймона мы делаем вывод, что это был мужчина. "
                "У кого из мужчин нет алиби на время преступления?"
            )
        elif q_num == 99:
            await handle_safe_hint(callback.bot, callback.from_user.id)
        elif isinstance(q_num, int):
            await send_hint(callback.bot, callback.from_user.id, q_num)
        await callback.message.answer("Попробуй ответить на вопрос еще раз.")
    else:
        await callback.message.answer("Хорошо, попробуй ответить на вопрос еще раз.")

    if isinstance(q_num, int) and q_num not in {0, 99}:
        await send_question(callback.bot, callback.from_user.id, q_num)
    elif q_num == 99:
        await send_safe_photo(
            callback.bot,
            callback.from_user.id,
            "safe_closed.jpg",
            "Вы находите в спальне Елены старый металлический сейф. На дисплее мигает запрос на 4 цифры. "
            "Елена была человеком привычки и часто использовала в качестве паролей личные даты.\n\n"
            "Введите код, чтобы открыть сейф:",
        )


@router.callback_query(F.data.startswith("article_"))
async def handle_article_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    with suppress(ValueError):
        idx = int(callback.data.removeprefix("article_"))
        if 0 <= idx < len(ARTICLES):
            await callback.message.answer(ARTICLES[idx]["text"])
            await callback.message.answer(
                'Интересненько, не так ли? Изучи все статьи, и как только будешь готов, '
                'напиши "Готов назвать убийцу" в чат.'
            )


# ==================== ЗАПУСК ====================

async def main() -> None:
    bot_token = os.getenv("BOT_TOKEN")
    proxy_url = os.getenv("TELEGRAM_PROXY") or None
    session = AiohttpSession(
        proxy=proxy_url,
        timeout=60
    )

    if not bot_token:
        raise RuntimeError("Переменная окружения BOT_TOKEN не задана")

    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    storage = RedisStorage.from_url(redis_url)
    bot = Bot(token=bot_token, session=session)
    dispatcher = Dispatcher(
        storage=storage,
        events_isolation=storage.create_isolation(),
    )
    dispatcher.include_router(router)

    logger.info("Бот запущен. Ожидание сообщений...")
    try:
        await dispatcher.start_polling(bot)
    finally:
        for task in background_tasks:
            task.cancel()
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)
        await storage.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())