import requests
import csv
import io
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

TOKEN = "8362396345:AAFUFWciFfjjHb2ylksVxE9DaQ1Tl64Juj0"

URLS = {
    'STANDARD': 'https://docs.google.com/spreadsheets/d/e/2PACX-1vRoydbgCE61hn48aKwnBfsx5HFZ6H2YGTnDrLvHaGpu5AhpySfFpgBb4wd72wC8X6tbYrYw8_uctp0k/pub?output=csv',
    'FREE': 'https://docs.google.com/spreadsheets/d/e/2PACX-1vTQ7Yv6SR-TfyW7rL3mdWSiKgZ-Mdoday5cZL7A8hhqJIQ6GYAVYw9LOSkyGqUddV5q7IkV_tMeU73r/pub?output=csv'
}

def fetch_proxies(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        reader = csv.reader(io.StringIO(response.text))
        proxies = [row[0].strip() for row in reader if row and row[0].strip()]
        return proxies
    except Exception as e:
        return []

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🆓 Proxies Gratuits", callback_data='free')],
        [InlineKeyboardButton("⭐ Proxies Standard", callback_data='standard')],
        [InlineKeyboardButton("📁 Télécharger fichier FREE", callback_data='file_free')],
        [InlineKeyboardButton("📁 Télécharger fichier STANDARD", callback_data='file_standard')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "👋 *Bienvenue sur le Bot Proxy!*\n\nChoisissez une option:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == 'free':
        proxies = fetch_proxies(URLS['FREE'])
        if proxies:
            text = "🆓 *Proxies Gratuits:*\n\n`" + "\n".join(proxies[:30]) + "`"
            if len(proxies) > 30:
                text += f"\n\n_...et {len(proxies)-30} autres. Utilise le bouton fichier pour tout avoir._"
        else:
            text = "❌ Aucun proxy disponible."
        await query.edit_message_text(text, parse_mode='Markdown')

    elif query.data == 'standard':
        proxies = fetch_proxies(URLS['STANDARD'])
        if proxies:
            text = "⭐ *Proxies Standard:*\n\n`" + "\n".join(proxies[:30]) + "`"
            if len(proxies) > 30:
                text += f"\n\n_...et {len(proxies)-30} autres. Utilise le bouton fichier pour tout avoir._"
        else:
            text = "❌ Aucun proxy disponible."
        await query.edit_message_text(text, parse_mode='Markdown')

    elif query.data == 'file_free':
        proxies = fetch_proxies(URLS['FREE'])
        if proxies:
            content = "\n".join(proxies).encode('utf-8')
            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=io.BytesIO(content),
                filename='proxy.txt',
                caption=f"🆓 proxy.txt — {len(proxies)} proxies"
            )
        else:
            await query.edit_message_text("❌ Aucun proxy disponible.")

    elif query.data == 'file_standard':
        proxies = fetch_proxies(URLS['STANDARD'])
        if proxies:
            content = "\n".join(proxies).encode('utf-8')
            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=io.BytesIO(content),
                filename='proxy_test.txt',
                caption=f"⭐ proxy_test.txt — {len(proxies)} proxies"
            )
        else:
            await query.edit_message_text("❌ Aucun proxy disponible.")

async def proxies_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /proxies - affiche menu rapide"""
    await start(update, context)

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("proxies", proxies_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("✅ Bot démarré...")
    app.run_polling()

if __name__ == "__main__":
    main()
