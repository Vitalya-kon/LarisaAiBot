import json
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest
import config
import asyncio
import re

user_sessions = {}
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Меня зовут Лариса. Ты можешь отправить мне любые вопросы, и я отвечу на них.")
# Для обработки длинных сообщений
async def split_long_message(text: str, max_length: int = 4096):
    return [text[i:i+max_length] for i in range(0, len(text), max_length)]

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_message = update.message.text
    # Получаем историю диалога пользователя
    if user_id not in user_sessions:
        user_sessions[user_id] = []
    
    user_sessions[user_id].append({"role": "user", "content": user_message})

    # Показываем индикатор "печатает"
    await update.message.chat.send_action(action=ChatAction.TYPING)
    
    # Формируем запрос к OpenRouter API
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": config.MODEL,
        "messages": user_sessions[user_id][-10:]  # Последние 10 сообщений
    }
    
    try:
        # Создаем асинхронную задачу для запроса к API
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, 
            lambda: requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                data=json.dumps(payload)
            )
        )
        
        if response.status_code == 200:
            ai_response = response.json()['choices'][0]['message']['content']

            # Форматируем ответ для красивого отображения
            formatted_response = format_ai_response(ai_response)
            
            # Отправляем форматированный ответ
            await send_formatted_message(update, formatted_response)

        else:
            error_msg = f"❌ *Ошибка API* (код {response.status_code})"
            if response.text:
                try:
                    error_data = response.json()
                    error_details = error_data.get('error', {}).get('message', 'Неизвестная ошибка')
                    error_msg += f"\n\n`{error_details[:200]}...`"
                except:
                    error_msg += f"\n\n`{response.text[:200]}...`"
            await update.message.reply_text(error_msg, parse_mode=ParseMode.MARKDOWN)
            
    except Exception as e:
        await update.message.reply_text(f"❌ Произошла ошибка: `{str(e)}`", parse_mode=ParseMode.MARKDOWN)

async def send_formatted_message(update, text):
    # Разделяем текст на части по 4096 символов
    if len(text) > 4096:
        # Ищем хорошее место для разделения (конец раздела)
        parts = []
        while len(text) > 4096:
            # Ищем последний перенос строки перед 4096 символом
            split_pos = text[:4096].rfind('\n')
            if split_pos == -1:
                split_pos = 4096
            parts.append(text[:split_pos])
            text = text[split_pos:].lstrip()
        parts.append(text)
        
        # Отправляем части с индикатором набора текста
        for i, part in enumerate(parts):
            if i > 0:  # Для всех частей кроме первой
                await update.message.chat.send_action(action=ChatAction.TYPING)
                await asyncio.sleep(0.5)
            
            try:
                await update.message.reply_text(part, parse_mode=ParseMode.MARKDOWN)
            except BadRequest:
                # Если возникает ошибка форматирования, отправляем без разметки
                await update.message.reply_text(part)
    else:
        try:
            await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        except BadRequest:
            await update.message.reply_text(text)

def format_ai_response(text):
    # Заменяем Markdown-разметку на Telegram-совместимую
    text = re.sub(r'### (.*?)', r'🟢 *\1*', text)  # Заголовки третьего уровня
    text = re.sub(r'## (.*?)', r'🔷 *\1*', text)   # Заголовки второго уровня
    text = re.sub(r'\*\*(.*?)\*\*', r'*\1*', text) # Жирный текст
    text = re.sub(r'_(.*?)_', r'_\1_', text)       # Курсив
    
    # Добавляем эмодзи для списков
    text = re.sub(r'^\* (.*?)$', r'🐾 \1', text, flags=re.MULTILINE)
    text = re.sub(r'^• (.*?)$', r'✨ \1', text, flags=re.MULTILINE)
    
    # Добавляем разделители
    text = re.sub(r'^---$', '▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬', text, flags=re.MULTILINE)
    
    return text

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"Update {update} caused error {context.error}")
    if update and update.message:
        await update.message.reply_text(
            "❌ Произошла ошибка при обработке запроса. Попробуйте еще раз.",
            parse_mode=ParseMode.MARKDOWN
        )

async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id in user_sessions:
        user_sessions[user_id] = []
    await update.message.reply_text("История диалога очищена!")

if __name__ == '__main__':
    # Инициализация приложения
    app = Application.builder().token(config.TELEGRAM_TOKEN).build()
    
    # Регистрация обработчиков
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    
    # Запуск бота
    print("Бот запущен...")
    app.run_polling()