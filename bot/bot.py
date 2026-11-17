import os
import asyncio
import random
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import FSInputFile

API_TOKEN = os.getenv("BOT_TOKEN")
if not API_TOKEN:
    raise SystemExit("Задайте переменную окружения BOT_TOKEN (токен от @BotFather)")
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

CHANNEL_URL1 = "https://t.me/Vloody_NFT"  # ссылка на ваш канал
CHANNEL_URL2 = "https://t.me/CosmoDrops"  # ссылка на ваш канал
WEB_APP_URL = "https://t.me/Cosmos67Drop_Bot/CosmosDrop"  # ссылка на веб-приложение
PHOTO_PATH = "static/img/photo_2025-12-16_21-02-55.jpg"
photo = FSInputFile(PHOTO_PATH)
# https://c58b27bbba4d.ngrok-free.app
WELCOME_TEXT = """
🎁 Добро пожаловать в Vloody!

Честные розыгрыши NFT-подарков между игроками.

Разыгрывай свои подарки или участвуй в чужих раундах: колесо, кибер-сейф и слепой аукцион.

🚀 Готов испытать удачу? Запускай мини-приложение и начинай выигрывать уже сейчас!
"""


@dp.message(Command("start"))
async def start_handler(message: types.Message):
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Наш канал 1", url=CHANNEL_URL1)],
        [types.InlineKeyboardButton(text="Наш канал 2", url=CHANNEL_URL2)],
        [types.InlineKeyboardButton(text="Открыть веб-приложение", url=WEB_APP_URL)]
    ])

    await bot.send_photo(
        chat_id=message.chat.id,
        photo=photo,
        caption=WELCOME_TEXT,
        reply_markup=keyboard
    )


if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))
