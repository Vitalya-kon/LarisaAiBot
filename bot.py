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
status_messages = {}

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Меня зовут Лариса. Ты можешь отправить мне любые вопросы, и я отвечу на них.")
# Для обработки длинных сообщений
async def split_long_message(text: str, max_length: int = 4096):
    return [text[i:i+max_length] for i in range(0, len(text), max_length)]

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_message = update.message.text
    chat_id = update.message.chat_id

     # Отправляем сообщение о генерации ответа
    status_message = await update.message.reply_text(
        "⏳ *Ответ генерируется. Пожалуйста, подождите..*",
        parse_mode=ParseMode.MARKDOWN
    )
    # Получаем историю диалога пользователя
    if user_id not in user_sessions:
        user_sessions[user_id] = []
    
    user_sessions[user_id].append({"role": "user", "content": user_message})

    # Показываем индикатор "печатает"
    await update.message.chat.send_action(action=ChatAction.TYPING)

    # Сохраняем ID статусного сообщения для последующего удаления
    status_messages[user_id] = {
        'message_id': status_message.message_id,
        'chat_id': chat_id,
        'active': True
    }
    
     # Запускаем анимацию загрузки
    loading_task = asyncio.create_task(show_loading_animation(update, chat_id, user_id))
    
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
                data=json.dumps(payload),
                timeout=30
            )
        )

         # Помечаем анимацию как неактивную
        if user_id in status_messages:
            status_messages[user_id]['active'] = False
        
        # Даем анимации немного времени для завершения
        await asyncio.sleep(0.5)

        # Удаляем статусное сообщение
        if user_id in status_messages:
            try:
                await context.bot.delete_message(
                    chat_id=chat_id, 
                    message_id=status_messages[user_id]['message_id']
                )
            except:
                pass  # Игнорируем ошибки удаления сообщения
            finally:
                del status_messages[user_id]
        
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
        # Помечаем анимацию как неактивную в случае ошибки
        if user_id in status_messages:
            status_messages[user_id]['active'] = False
        
        # Даем анимации немного времени для завершения
        await asyncio.sleep(0.5)
        
        # Удаляем статусное сообщение
        if user_id in status_messages:
            try:
                await context.bot.delete_message(
                    chat_id=chat_id, 
                    message_id=status_messages[user_id]['message_id']
                )
            except:
                pass
            finally:
                del status_messages[user_id]

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

async def show_loading_animation(update: Update, chat_id: int, user_id: int):
    """Показывает анимацию загрузки, обновляя сообщение каждые 1.5 секунды"""
    loading_frames = [
        "⏳ *Ответ генерируется. Пожалуйста, подождите..*",
        "⏳ *Ответ генерируется. Пожалуйста, подождите...*",
        "⏳ *Ответ генерируется. Пожалуйста, подождите....*",
        "⏳ *Ответ генерируется. Пожалуйста, подождите.....*"
    ]
    
    frame_index = 0
    
    while user_id in status_messages and status_messages[user_id]['active']:
        try:
            # Обновляем сообщение с новым кадром анимации
            await update.get_bot().edit_message_text(
                chat_id=chat_id,
                message_id=status_messages[user_id]['message_id'],
                text=loading_frames[frame_index],
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Переходим к следующему кадру
            frame_index = (frame_index + 1) % len(loading_frames)
        except BadRequest as e:
            if "message not modified" in str(e).lower():
                # Игнорируем ошибку "message not modified"
                pass
            else:
                # Для других ошибок прерываем анимацию
                break
        except Exception as e:
            # Для других исключений прерываем анимацию
            break
        
        # Ждем перед следующим обновлением
        await asyncio.sleep(1.5)

def format_ai_response(text):
    # Заменяем Markdown-разметку на Telegram-совместимую
    text = re.sub(r'### (.*?)', r'🟢 *\1*', text)  # Заголовки третьего уровня
    text = re.sub(r'## (.*?)', r'🔷 *\1*', text)   # Заголовки второго уровня
    text = re.sub(r'\*\*(.*?)\*\*', r'*\1*', text) # Жирный текст
    text = re.sub(r'_(.*?)_', r'_\1_', text)       # Курсив
    
    # Добавляем эмодзи для списков
    text = re.sub(r'^\* (.*?)$', r'👉 \1', text, flags=re.MULTILINE)
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