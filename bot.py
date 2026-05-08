# force rebuild v14
import asyncio
import os
from datetime import datetime
from typing import Dict, Tuple

import pytz
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import DiceEmoji, ParseMode
from aiogram.exceptions import TelegramBadRequest
import aiosqlite

BOT_TOKEN = "8635076570:AAEX117e8gOj8z5Eh97TXPmaF-APOmBeamQ"

TIMEZONE = pytz.timezone("Asia/Yekaterinburg")
FREE_ATTEMPTS_DAILY = 3          # бесплатных попыток в день
DAILY_BONUS = 3                  # сколько начисляется фишек каждый день
STREAK_BONUS = 10                # бонус за серию 3 победы подряд
WINNINGS = {
    1: 1,    
    22: 3,  
    43: 5,   
    64: 7,  
}

#  ИНИЦИАЛИЗАЦИЯ 
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DB_NAME = "bot.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER,
                chat_id INTEGER,
                balance INTEGER DEFAULT 0,
                free_attempts INTEGER DEFAULT 3,
                last_date TEXT,
                win_streak INTEGER DEFAULT 0,
                total_wins INTEGER DEFAULT 0,
                total_games INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, chat_id)
            )
        """)
        await db.commit()
# работа с БД
async def get_user(user_id: int, chat_id: int) -> dict:
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT balance, free_attempts, last_date, win_streak, total_wins, total_games FROM users WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "balance": row[0],
                    "free_attempts": row[1],
                    "last_date": row[2],
                    "win_streak": row[3],
                    "total_wins": row[4],
                    "total_games": row[5],
                }
            else:
                today_ufa = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
                await db.execute(
                    "INSERT INTO users (user_id, chat_id, balance, free_attempts, last_date) VALUES (?, ?, ?, ?, ?)",
                    (user_id, chat_id, DAILY_BONUS, FREE_ATTEMPTS_DAILY, today_ufa)
                )
                await db.commit()
                return {
                    "balance": DAILY_BONUS,
                    "free_attempts": FREE_ATTEMPTS_DAILY,
                    "last_date": today_ufa,
                    "win_streak": 0,
                    "total_wins": 0,
                    "total_games": 0,
                }

async def update_user_day(user_id: int, chat_id: int, user_data: dict) -> dict:
    today_ufa = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
    if user_data["last_date"] != today_ufa:
        new_free = FREE_ATTEMPTS_DAILY
        new_balance = user_data["balance"] + DAILY_BONUS
        user_data["free_attempts"] = new_free
        user_data["balance"] = new_balance
        user_data["last_date"] = today_ufa
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "UPDATE users SET free_attempts = ?, balance = ?, last_date = ? WHERE user_id = ? AND chat_id = ?",
                (new_free, new_balance, today_ufa, user_id, chat_id)
            )
            await db.commit()
    return user_data

async def deduct_attempt(user_id: int, chat_id: int, user_data: dict) -> Tuple[bool, dict]:
    if user_data["free_attempts"] > 0:
        user_data["free_attempts"] -= 1
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "UPDATE users SET free_attempts = ? WHERE user_id = ? AND chat_id = ?",
                (user_data["free_attempts"], user_id, chat_id)
            )
            await db.commit()
        return True, user_data
    elif user_data["balance"] >= 1:
        user_data["balance"] -= 1
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "UPDATE users SET balance = ? WHERE user_id = ? AND chat_id = ?",
                (user_data["balance"], user_id, chat_id)
            )
            await db.commit()
        return True, user_data
    else:
        return False, user_data

async def apply_win(user_id: int, chat_id: int, user_data: dict, dice_value: int) -> Tuple[dict, int]:
    win_amount = WINNINGS.get(dice_value, 0)
    if win_amount > 0:
        user_data["win_streak"] += 1
        user_data["balance"] += win_amount
        user_data["total_wins"] += 1

        extra = 0
        if user_data["win_streak"] == 3:
            extra = STREAK_BONUS
            user_data["balance"] += extra

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "UPDATE users SET win_streak = ?, balance = ?, total_wins = ? WHERE user_id = ? AND chat_id = ?",
                (user_data["win_streak"], user_data["balance"], user_data["total_wins"], user_id, chat_id)
            )
            await db.commit()
        return user_data, win_amount + extra
    else:
        user_data["win_streak"] = 0
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "UPDATE users SET win_streak = ? WHERE user_id = ? AND chat_id = ?",
                (0, user_id, chat_id)
            )
            await db.commit()
        return user_data, 0

async def update_total_games(user_id: int, chat_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET total_games = total_games + 1 WHERE user_id = ? AND chat_id = ?", (user_id, chat_id))
        await db.commit()

#  КЛАВИАТУРА 
def get_main_keyboard():
    buttons = [
        [InlineKeyboardButton(text="🎰 Крутить КАЗИНО", callback_data="spin")],
        [InlineKeyboardButton(text="💰 Баланс и статистика", callback_data="stats")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

#  ОБРАБОТКА 
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "🎰 Добро пожаловать в КАЗИНО!\n"
        "Каждый день ты получаешь 3 бесплатных попытки и 3 фишки.\n"
        "Фишки можно копить и тратить на дополнительные спины.\n"
        "За выигрыши даются фишки, а за серию из 3 побед - особый бонус!\n\n"
        "Используй кнопки ниже или команду /spin",
        reply_markup=get_main_keyboard()
    )

@dp.message(Command("spin"))
async def cmd_spin(message: types.Message):
    user_name = message.from_user.first_name
    await spin_action(message.from_user.id, message.chat.id, message, user_name)

@dp.callback_query(lambda c: c.data == "spin")
async def callback_spin(callback: types.CallbackQuery):
    user_name = callback.from_user.first_name
    await spin_action(callback.from_user.id, callback.message.chat.id, callback.message, user_name)
    await callback.answer()

async def spin_action(user_id: int, chat_id: int, source_message: types.Message, user_name: str = None):
    # Получаем и обновляем день
    user = await get_user(user_id, chat_id)
    user = await update_user_day(user_id, chat_id, user)

    # Пытаемся списать попытку
    success, user = await deduct_attempt(user_id, chat_id, user)
    if not success:
        await source_message.answer(
            "❌ У тебя нет бесплатных попыток и нет фишек.\n"
            "Завтра получишь 3 бесплатные попытки и 3 фишки!",
            reply_markup=get_main_keyboard()
        )
        return

    # Отправляем dice (бот сам отправляет, пользователь не отправляет эмодзи)
    sent_msg = await source_message.answer_dice(emoji=DiceEmoji.SLOT_MACHINE)
    dice_value = sent_msg.dice.value

    # Обновление общего числа игр
    await update_total_games(user_id, chat_id)

    # Определение выигрыша и начисление
    user, won_fish = await apply_win(user_id, chat_id, user, dice_value)

    # Формируем ответ
    if won_fish > 0:
        result_text = f"🎉 {user_name}, ПОБЕДА! +{won_fish} фишек!"
    else:
        result_text = f"😔 {user_name}, проигрыш. Попробуй ещё."

    streak_text = f"🔥 Серия побед: {user['win_streak']}" if user['win_streak'] > 0 else ""

    await source_message.answer(
        f"{result_text}\n"
        f"{streak_text}\n"
        f"💰 Баланс: {user['balance']} фишек | Бесплатных попыток сегодня: {user['free_attempts']}",
        reply_markup=get_main_keyboard()
    )

@dp.callback_query(lambda c: c.data == "stats")
async def show_stats(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user_name = callback.from_user.first_name
    user = await get_user(user_id, callback.message.chat.id)
    user = await update_user_day(user_id, callback.message.chat.id, user)

    total_games = user["total_games"]
    win_rate = (user["total_wins"] / total_games * 100) if total_games > 0 else 0

    await callback.message.answer(
        f"📊 <b>Статистика для {user_name}</b>\n"
        f"🎰 Всего игр: {total_games}\n"
        f"🏆 Побед: {user['total_wins']}\n"
        f"⭐ Процент побед: {win_rate:.1f}%\n"
        f"💰 Фишек на счету: {user['balance']}\n"
        f"🎲 Бесплатные попытки сегодня: {user['free_attempts']} / {FREE_ATTEMPTS_DAILY}\n"
        f"🔥 Текущая серия побед: {user['win_streak']}",
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard()
    )
    await callback.answer()

#  УДАЛЕНИЕ ЛИШНИХ ЭМОДЗИ (отправленных пользователем)
@dp.message(lambda msg: msg.dice and msg.dice.emoji == DiceEmoji.SLOT_MACHINE)
async def remove_manual_slot(message: types.Message):
    # Если пользователь сам отправил эмодзи слота, проверим, есть ли у него попытки
    user_id = message.from_user.id
    chat_id = message.chat.id
    chat_type = "личный чат" if chat_id > 0 else "группа"
    
    print(f"🔍 Получен dice от {user_id} в {chat_type} (chat_id={chat_id})")
    print(f"   dice value: {message.dice.value}")
    
    user = await get_user(user_id, chat_id)
    user = await update_user_day(user_id, chat_id, user)

    # Пытаемся списать попытку (если есть)
    success, user = await deduct_attempt(user_id, chat_id, user)
    
    print(f"   Попытка списана: {success}, осталось попыток: {user['free_attempts']}, баланс: {user['balance']}")
    
    if success:
        # Если списали удачно – обрабатываем как обычный спин
        # НО сообщение всё равно удалим, чтобы не засорять чат
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message.message_id)
            print(f"✅ Сообщение {message.message_id} УСПЕШНО удалено в {chat_type}")
        except Exception as e:
            print(f"❌ ОШИБКА удаления: {type(e).__name__}: {e}")
        
        # Отправляем результат от имени бота (как если бы он сам крутил)
        sent_msg = await message.answer_dice(emoji=DiceEmoji.SLOT_MACHINE)
        dice_value = sent_msg.dice.value
        await update_total_games(user_id, chat_id)
        user, won_fish = await apply_win(user_id, chat_id, user, dice_value)

        result_text = f"🎉 {user_name}, ПОБЕДА! +{won_fish} фишек!" if won_fish > 0 else f"😔 {user_name}, проигрыш. Попробуй ещё."
        await message.answer(
            f"{result_text}\n"
            f"💰 Баланс: {user['balance']} фишек | Бесплатных попыток сегодня: {user['free_attempts']}",
            reply_markup=get_main_keyboard()
        )
    else:
        # Нет попыток – просто удаляем сообщение и молчим
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message.message_id)
            print(f"🗑️ Удалено сообщение {message.message_id} (нет попыток)")
        except Exception as e:
            print(f"❌ ОШИБКА удаления: {type(e).__name__}: {e}")

# ---------- ЗАПУСК ----------
async def main():
    await init_db()
    print("Бот запущен")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    asyncio.run(main())
