import asyncio
import logging
import os
import json
from datetime import datetime
import pytz
MOSCOW_TZ = pytz.timezone("Europe/Moscow")

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
import gspread
from google.oauth2.service_account import Credentials

# ─── Настройки ───────────────────────────────────────────────
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])
SHEET_ID = os.environ["SHEET_ID"]

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# ─── Google Sheets ────────────────────────────────────────────
def get_client():
    creds_json = os.environ["GOOGLE_CREDENTIALS"]
    creds_dict = json.loads(creds_json)
    if "private_key" in creds_dict:
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)

def get_sheet(name):
    client = get_client()
    spreadsheet = client.open_by_key(SHEET_ID)
    try:
        return spreadsheet.worksheet(name)
    except gspread.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title=name, rows=1000, cols=10)
        return sheet

def ensure_headers():
    # Лист заявок
    leads = get_sheet("Заявки")
    if not leads.get_all_values():
        leads.insert_row(["Дата", "Имя родителя", "Имя ребёнка", "Возраст", "Телефон", "Удобное время"], 1)

    # Лист пользователей
    users = get_sheet("Пользователи")
    if not users.get_all_values():
        users.insert_row(["user_id", "Имя", "Username", "Дата регистрации"], 1)

    # Лист рассылок
    broadcasts = get_sheet("Рассылки")
    if not broadcasts.get_all_values():
        broadcasts.insert_row(["Дата и время", "Текст", "Статус"], 1)
        broadcasts.insert_row(["28.06.2025 18:00", "👋 Пример: Набор на летний курс открыт!", "ожидает"], 2)

def save_lead(data: dict):
    sheet = get_sheet("Заявки")
    sheet.append_row([
        datetime.now(MOSCOW_TZ).strftime("%d.%m.%Y %H:%M"),
        data["parent_name"],
        data["child_name"],
        data["child_age"],
        data["phone"],
        data["time"],
    ])

def save_user(user):
    sheet = get_sheet("Пользователи")
    all_ids = sheet.col_values(1)
    if str(user.id) not in all_ids:
        sheet.append_row([
            str(user.id),
            user.full_name,
            f"@{user.username}" if user.username else "",
            datetime.now(MOSCOW_TZ).strftime("%d.%m.%Y %H:%M"),
        ])

def get_all_user_ids():
    sheet = get_sheet("Пользователи")
    values = sheet.get_all_values()
    return [row[0] for row in values[1:] if row and row[0].isdigit()]

def get_pending_broadcasts():
    sheet = get_sheet("Рассылки")
    values = sheet.get_all_values()
    pending = []
    now = datetime.now(MOSCOW_TZ).replace(tzinfo=None)
    logging.info(f"Now (Moscow): {now}")
    for i, row in enumerate(values[1:], start=2):
        if len(row) >= 3:
            status = row[2].strip().lower()
            date_str = row[0].strip().lstrip("'")
            logging.info(f"Row {i}: date={repr(date_str)}, status={repr(status)}")
            if status == "ожидает":
                try:
                    dt = datetime.strptime(date_str, "%d.%m.%Y %H:%M")
                    logging.info(f"Parsed dt: {dt}, now: {now}, trigger: {dt <= now}")
                    if dt <= now:
                        pending.append((i, row[1]))
                except ValueError as e:
                    logging.error(f"Date parse error for {repr(date_str)}: {e}")
    return pending

def mark_broadcast_sent(row_num):
    sheet = get_sheet("Рассылки")
    sheet.update_cell(row_num, 3, "отправлено")

# ─── FSM ────────────────────────────────────────────────────
class Form(StatesGroup):
    parent_name = State()
    child_name  = State()
    child_age   = State()
    phone       = State()
    time        = State()
    confirm     = State()

class Broadcast(StatesGroup):
    waiting_text = State()

class Consultation(StatesGroup):
    name  = State()
    phone = State()

# ─── Клавиатуры ─────────────────────────────────────────────
def kb_time():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Утро (9:00–12:00)"), KeyboardButton(text="День (12:00–17:00)")],
            [KeyboardButton(text="Вечер (17:00–20:00)"), KeyboardButton(text="В любое время")],
        ],
        resize_keyboard=True,
    )

def kb_confirm():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="✅ Отправить"), KeyboardButton(text="✏️ Заполнить заново")]],
        resize_keyboard=True,
    )

# ─── Хендлеры ───────────────────────────────────────────────
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    try:
        save_user(message.from_user)
    except Exception as e:
        logging.error(f"Save user error: {e}")

    welcome = (
        "🚀 <b>Synergy Hub Junior — международный детский IT-центр в Ташкенте</b>\n\n"
        "Обучаем детей <b>8–15 лет</b> цифровым навыкам через игру и практику.\n\n"
        "🎮 Программирование на Python, Scratch, Roblox\n"
        "🎨 Графический дизайн, Blender, веб-дизайн\n"
        "📱 Разработка мобильных приложений\n\n"
        "💡 <b>Почему Synergy Hub Junior?</b>\n"
        "• Небольшие группы — внимание каждому ребёнку\n"
        "• Оборудованные классы с мощными компьютерами\n"
        "• 2 сертификата после курса (Узбекистан + Россия)\n"
        "• Первый урок — <b>бесплатно</b>\n\n"
        "Чем могу помочь? 👇"
    )
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎓 Записаться на пробный урок")],
            [KeyboardButton(text="💬 Получить консультацию")],
        ],
        resize_keyboard=True,
    )
    await message.answer_photo(
        photo="https://i.ibb.co/bRH32y81/Synergy-Hub-junior-logo-1.png",
        caption=welcome,
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    await state.set_state(Form.parent_name)

async def got_parent_name(message: Message, state: FSMContext):
    text = message.text.strip()
    if text == "🎓 Записаться на пробный урок":
        await message.answer(
            "Отлично! Давайте запишем вашего ребёнка на бесплатный пробный урок.\n\nКак вас зовут? (имя родителя)",
            reply_markup=ReplyKeyboardRemove()
        )
        return
    if text == "💬 Получить консультацию":
        await message.answer(
            "Хорошо! Наш менеджер свяжется с вами и ответит на все вопросы.\n\nКак вас зовут?",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(Consultation.name)
        return
    await state.update_data(parent_name=text)
    await message.answer("Как зовут ребёнка?")
    await state.set_state(Form.child_name)

async def got_child_name(message: Message, state: FSMContext):
    await state.update_data(child_name=message.text.strip())
    await message.answer("Сколько ребёнку лет?")
    await state.set_state(Form.child_age)

async def got_child_age(message: Message, state: FSMContext):
    age = message.text.strip()
    if not age.isdigit() or not (4 <= int(age) <= 18):
        await message.answer("Пожалуйста, введите возраст цифрой (от 4 до 18).")
        return
    await state.update_data(child_age=age)
    await message.answer("Ваш номер телефона для связи?")
    await state.set_state(Form.phone)

async def got_phone(message: Message, state: FSMContext):
    await state.update_data(phone=message.text.strip())
    await message.answer("Выберите удобное время:", reply_markup=kb_time())
    await state.set_state(Form.time)

async def got_time(message: Message, state: FSMContext):
    await state.update_data(time=message.text.strip())
    data = await state.get_data()
    summary = (
        "📋 <b>Проверьте данные:</b>\n\n"
        f"👤 Родитель: {data['parent_name']}\n"
        f"👦 Ребёнок: {data['child_name']}, {data['child_age']} лет\n"
        f"📞 Телефон: {data['phone']}\n"
        f"🕐 Время: {data['time']}\n\n"
        "Всё верно?"
    )
    await message.answer(summary, parse_mode="HTML", reply_markup=kb_confirm())
    await state.set_state(Form.confirm)

async def got_confirm(message: Message, state: FSMContext, bot: Bot):
    if message.text == "✏️ Заполнить заново":
        await cmd_start(message, state)
        return

    data = await state.get_data()
    await state.clear()

    try:
        save_lead(data)
        sheets_ok = True
    except Exception as e:
        logging.error(f"Sheets error: {e}")
        sheets_ok = False

    admin_text = (
        "🔔 <b>Новая заявка!</b>\n\n"
        f"👤 Родитель: {data['parent_name']}\n"
        f"👦 Ребёнок: {data['child_name']}, {data['child_age']} лет\n"
        f"📞 Телефон: {data['phone']}\n"
        f"🕐 Время: {data['time']}\n"
        f"📅 {datetime.now(MOSCOW_TZ).strftime('%d.%m.%Y %H:%M')}"
    )
    if not sheets_ok:
        admin_text += "\n\n⚠️ Ошибка записи в таблицу!"

    await bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML")
    await message.answer(
        "✅ <b>Заявка принята!</b>\n\n"
        "Наш менеджер свяжется с вами в ближайшее время.\n\n"
        "До встречи в Synergy Hub Junior! 🚀",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )

# ─── Рассылка вручную ────────────────────────────────────────
async def cmd_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await message.answer(
        "📢 Напишите текст рассылки.\n\nОн будет отправлен всем пользователям бота.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(Broadcast.waiting_text)

async def got_broadcast_text(message: Message, state: FSMContext, bot: Bot):
    if message.from_user.id != ADMIN_ID:
        return
    text = message.text.strip()
    await state.clear()

    user_ids = get_all_user_ids()
    sent = 0
    failed = 0
    for uid in user_ids:
        try:
            await bot.send_message(int(uid), text)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1

    await message.answer(
        f"✅ Рассылка завершена!\n\nОтправлено: {sent}\nОшибок: {failed}",
    )

# ─── Консультация ────────────────────────────────────────────
async def consult_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("Ваш номер телефона для связи?")
    await state.set_state(Consultation.phone)

async def consult_phone(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    phone = message.text.strip()

    # Save to sheet
    try:
        sheet = get_sheet("Заявки")
        sheet.append_row([
            datetime.now(MOSCOW_TZ).strftime("%d.%m.%Y %H:%M"),
            data["name"], "—", "—", phone, "Консультация"
        ])
    except Exception as e:
        logging.error(f"Consult sheet error: {e}")

    # Notify admin
    await bot.send_message(
        ADMIN_ID,
        f"📞 <b>Запрос на консультацию!</b>\n\n"
        f"👤 Имя: {data['name']}\n"
        f"📞 Телефон: {phone}\n"
        f"📅 {datetime.now(MOSCOW_TZ).strftime('%d.%m.%Y %H:%M')}",
        parse_mode="HTML"
    )

    await message.answer(
        "✅ <b>Спасибо!</b>\n\n"
        "Наш менеджер свяжется с вами в ближайшее время и ответит на все вопросы.\n\n"
        "До встречи в Synergy Hub Junior! 🚀",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove()
    )

# ─── Авторассылка по расписанию ──────────────────────────────
async def scheduler(bot: Bot):
    await asyncio.sleep(10)
    logging.info("Scheduler started")
    while True:
        try:
            now = datetime.now(MOSCOW_TZ)
            logging.info(f"Scheduler tick: {now.strftime('%d.%m.%Y %H:%M')}")
            pending = get_pending_broadcasts()
            logging.info(f"Pending broadcasts: {len(pending)}")
            for row_num, text in pending:
                user_ids = get_all_user_ids()
                sent = 0
                for uid in user_ids:
                    try:
                        await bot.send_message(int(uid), text)
                        sent += 1
                        await asyncio.sleep(0.05)
                    except Exception:
                        pass
                mark_broadcast_sent(row_num)
                await bot.send_message(
                    ADMIN_ID,
                    f"📤 Авторассылка отправлена {sent} пользователям."
                )
        except Exception as e:
            logging.error(f"Scheduler error: {e}")
        await asyncio.sleep(300)  # проверяем каждые 5 минут

# ─── Запуск ─────────────────────────────────────────────────
async def main():
    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    try:
        ensure_headers()
    except Exception as e:
        logging.error(f"Headers error: {e}")

    dp.message.register(cmd_start, CommandStart())
    dp.message.register(cmd_broadcast, Command("broadcast"))
    dp.message.register(got_parent_name, Form.parent_name)
    dp.message.register(got_child_name,  Form.child_name)
    dp.message.register(got_child_age,   Form.child_age)
    dp.message.register(got_phone,       Form.phone)
    dp.message.register(got_time,        Form.time)
    dp.message.register(got_confirm,     Form.confirm)
    dp.message.register(got_broadcast_text, Broadcast.waiting_text)
    dp.message.register(consult_name,  Consultation.name)
    dp.message.register(consult_phone, Consultation.phone)

    loop = asyncio.get_event_loop()
    loop.create_task(scheduler(bot))
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
