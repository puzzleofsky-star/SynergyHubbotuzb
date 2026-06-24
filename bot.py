import asyncio
import logging
import os
import json
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
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

# ─── Google Sheets ────────────────────────────────────────────
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def get_sheet():
    creds_json = os.environ["GOOGLE_CREDENTIALS"]
    creds_dict = json.loads(creds_json)
    if "private_key" in creds_dict:
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID).sheet1

def save_to_sheet(data: dict):
    sheet = get_sheet()
    if sheet.row_count == 0 or sheet.cell(1, 1).value != "Дата":
        sheet.insert_row(
            ["Дата", "Имя родителя", "Имя ребёнка", "Возраст ребёнка", "Телефон", "Удобное время"],
            index=1
        )
    sheet.append_row([
        datetime.now().strftime("%d.%m.%Y %H:%M"),
        data["parent_name"],
        data["child_name"],
        data["child_age"],
        data["phone"],
        data["time"],
    ])

# ─── FSM состояния ────────────────────────────────────────────
class Form(StatesGroup):
    parent_name = State()
    child_name  = State()
    child_age   = State()
    phone       = State()
    time        = State()
    confirm     = State()

# ─── Клавиатуры ──────────────────────────────────────────────
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

# ─── Хендлеры ────────────────────────────────────────────────
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Привет! Я помогу записать вашего ребёнка на пробный урок в <b>Synergy Hub Junior</b>.\n\n"
        "Давайте заполним короткую заявку — это займёт меньше минуты.\n\n"
        "Как вас зовут? (имя родителя)",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(Form.parent_name)

async def got_parent_name(message: Message, state: FSMContext):
    await state.update_data(parent_name=message.text.strip())
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
    await message.answer(
        "Выберите удобное время для пробного урока:",
        reply_markup=kb_time(),
    )
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
        save_to_sheet(data)
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
        f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )
    if not sheets_ok:
        admin_text += "\n\n⚠️ Ошибка записи в таблицу!"

    await bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML")

    await message.answer(
        "✅ <b>Заявка принята!</b>\n\n"
        "Наш менеджер свяжется с вами в ближайшее время для подтверждения.\n\n"
        "До встречи в Synergy Hub Junior! 🚀",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )

# ─── Запуск ───────────────────────────────────────────────────
async def main():
    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.register(cmd_start, CommandStart())
    dp.message.register(got_parent_name, Form.parent_name)
    dp.message.register(got_child_name,  Form.child_name)
    dp.message.register(got_child_age,   Form.child_age)
    dp.message.register(got_phone,       Form.phone)
    dp.message.register(got_time,        Form.time)
    dp.message.register(got_confirm,     Form.confirm)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
