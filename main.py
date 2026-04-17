import os
import requests
import csv
import io
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# Chargement des variables d'environnement depuis .env si python-dotenv est installé
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv n'est pas installé, on continue sans

# ─── Internationalization (i18n) ──────────────────────────────────────────────
from typing import Dict

# Traductions disponibles
LANGUAGES = {
    'fr': '🇫🇷 Français',
    'en': '🇬🇧 English',
}

# Dictionnaire de traductions
TRANSLATIONS: Dict[str, Dict[str, str]] = {
    'fr': {
        # Menu principal
        'welcome': "👋 *Bienvenue sur le Bot Proxy!*\n\nChoisissez une option ci-dessous :",
        'button_free_list': "🆓 Proxies Gratuits",
        'button_standard_list': "⭐ Proxies Standard",
        'button_free_file': "📥 Fichier FREE",
        'button_standard_file': "📥 Fichier STANDARD",
        'button_help': "ℹ️ Aide",
        'button_back': "⬅️ Retour au menu",
        'button_download_all': "📥 Télécharger tout ({count})",

        # Aide
        'help_title': "ℹ️ *Aide — Bot Proxy*",
        'help_commands': "• `/start` ou `/proxies` — Affiche le menu principal\n• `/help` — Cette aide\n• `/lang` — Changer la langue",
        'help_types': "*Types de proxies :*",
        'help_free': "🆓 *Gratuits* — Liste publique, qualité variable",
        'help_standard': "⭐ *Standard* — Liste filtrée, plus fiable",
        'help_cache': "Les listes sont mises en cache 5 minutes.",
        'help_cache_inline': "Les listes sont mises en cache 5 minutes pour plus de rapidité.",

        # Messages
        'loading': "⏳ Chargement des proxies {label}…",
        'no_proxies': "❌ Aucun proxy *{label}* disponible pour l'instant.",
        'no_proxies_file': "❌ Aucun proxy *{label}* disponible.",
        'proxies_header': "{emoji} *Proxies {label}* ({total} total)",
        'more_proxies': "+{count} autres — télécharge le fichier complet ci-dessous.",
        'unknown_option': "❌ Option inconnue.",
        'unknown_action': "❌ Action non reconnue.",
        'rate_limit': "⏳ Attendez {seconds}s entre chaque demande.",
        'unknown_message': "Je réponds uniquement aux commandes.\nUtilise /start pour afficher le menu.",
        'file_caption': "{emoji} *{filename}* — {count} proxies",
        'menu_return': "👋 *Bienvenue sur le Bot Proxy!*\n\nChoisissez une option :",

        # Langue
        'lang_title': "🌐 *Sélectionnez une langue / Select a language*",
        'lang_changed': "✅ Langue changée en **{lang}**",
        'current_lang': "Langue actuelle: {lang}",
    },
    'en': {
        # Main menu
        'welcome': "👋 *Welcome to Proxy Bot!*\n\nChoose an option below:",
        'button_free_list': "🆓 Free Proxies",
        'button_standard_list': "⭐ Standard Proxies",
        'button_free_file': "📥 FREE File",
        'button_standard_file': "📥 STANDARD File",
        'button_help': "ℹ️ Help",
        'button_back': "⬅️ Back to menu",
        'button_download_all': "📥 Download all ({count})",

        # Help
        'help_title': "ℹ️ *Help — Proxy Bot*",
        'help_commands': "• `/start` or `/proxies` — Show main menu\n• `/help` — This help\n• `/lang` — Change language",
        'help_types': "*Proxy types:*",
        'help_free': "🆓 *Free* — Public list, variable quality",
        'help_standard': "⭐ *Standard* — Filtered list, more reliable",
        'help_cache': "Lists are cached for 5 minutes.",
        'help_cache_inline': "Lists are cached for 5 minutes for faster response.",

        # Messages
        'loading': "⏳ Loading {label} proxies…",
        'no_proxies': "❌ No *{label}* proxies available at the moment.",
        'no_proxies_file': "❌ No *{label}* proxies available.",
        'proxies_header': "{emoji} *{label} Proxies* ({total} total)",
        'more_proxies': "+{count} more — download the complete file below.",
        'unknown_option': "❌ Unknown option.",
        'unknown_action': "❌ Unrecognized action.",
        'rate_limit': "⏳ Please wait {seconds}s between requests.",
        'unknown_message': "I only respond to commands.\nUse /start to show the menu.",
        'file_caption': "{emoji} *{filename}* — {count} proxies",
        'menu_return': "👋 *Welcome to Proxy Bot!*\n\nChoose an option:",

        # Language
        'lang_title': "🌐 *Select a language / Sélectionnez une langue*",
        'lang_changed': "✅ Language changed to **{lang}**",
        'current_lang': "Current language: {lang}",
    },
}

# Cache des langues utilisateurs
_user_language: Dict[int, str] = {}

def get_user_language(user_id: int) -> str:
    """Récupère la langue de l'utilisateur (défaut: fr)"""
    return _user_language.get(user_id, 'fr')

def set_user_language(user_id: int, lang: str) -> None:
    """Définit la langue de l'utilisateur"""
    if lang in LANGUAGES:
        _user_language[user_id] = lang

def t(user_id: int, key: str, **kwargs) -> str:
    """Traduit un message pour un utilisateur donné"""
    lang = get_user_language(user_id)
    text = TRANSLATIONS.get(lang, TRANSLATIONS['fr']).get(key, key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except KeyError:
            pass
    return text

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Configuration ────────────────────────────────────────────────────────────
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError(
        "❌ TELEGRAM_BOT_TOKEN non défini.\n"
        "Définissez-le via: export TELEGRAM_BOT_TOKEN='votre_token'"
    )

RATE_LIMIT_SECONDS = 3
CACHE_TTL_SECONDS  = 300  # 5 minutes

URLS = {
    'FREE':     'https://docs.google.com/spreadsheets/d/e/2PACX-1vTQ7Yv6SR-TfyW7rL3mdWSiKgZ-Mdoday5cZL7A8hhqJIQ6GYAVYw9LOSkyGqUddV5q7IkV_tMeU73r/pub?output=csv',
    'STANDARD': 'https://docs.google.com/spreadsheets/d/e/2PACX-1vRoydbgCE61hn48aKwnBfsx5HFZ6H2YGTnDrLvHaGpu5AhpySfFpgBb4wd72wC8X6tbYrYw8_uctp0k/pub?output=csv',
}

LABELS = {
    'FREE':     ('🆓', 'Gratuits',  'proxy.txt'),
    'STANDARD': ('⭐', 'Standard',  'proxy_test.txt'),
}

# ─── Cache ────────────────────────────────────────────────────────────────────
_cache: dict[str, tuple[list[str], datetime]] = {}

def fetch_proxies(key: str) -> list[str]:
    """Récupère les proxies avec cache TTL."""
    now = datetime.now()
    if key in _cache:
        proxies, fetched_at = _cache[key]
        if (now - fetched_at).total_seconds() < CACHE_TTL_SECONDS:
            logger.info(f"[Cache] {key}: {len(proxies)} proxies (TTL ok)")
            return proxies

    url = URLS[key]
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        reader  = csv.reader(io.StringIO(response.text))
        proxies = [row[0].strip() for row in reader if row and row[0].strip()]
        _cache[key] = (proxies, now)
        logger.info(f"[Fetch] {key}: {len(proxies)} proxies récupérés")
        return proxies
    except requests.exceptions.Timeout:
        logger.error(f"[Fetch] {key}: timeout")
    except requests.exceptions.RequestException as e:
        logger.error(f"[Fetch] {key}: erreur réseau — {e}")
    except Exception as e:
        logger.error(f"[Fetch] {key}: erreur inattendue — {e}")

    # Retourne le cache périmé si disponible
    if key in _cache:
        proxies, _ = _cache[key]
        logger.warning(f"[Cache] {key}: utilisation du cache périmé ({len(proxies)} proxies)")
        return proxies
    return []

# ─── Rate Limiting ────────────────────────────────────────────────────────────
_user_last_request: dict[int, datetime] = {}

def is_rate_limited(user_id: int) -> bool:
    now = datetime.now()
    last = _user_last_request.get(user_id)
    if last and (now - last).total_seconds() < RATE_LIMIT_SECONDS:
        return True
    _user_last_request[user_id] = now
    return False

# ─── Clavier principal ────────────────────────────────────────────────────────
def main_keyboard(user_id: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(t(user_id, 'button_free_list'),  callback_data='list_FREE'),
            InlineKeyboardButton(t(user_id, 'button_standard_list'),  callback_data='list_STANDARD'),
        ],
        [
            InlineKeyboardButton(t(user_id, 'button_free_file'),      callback_data='file_FREE'),
            InlineKeyboardButton(t(user_id, 'button_standard_file'),      callback_data='file_STANDARD'),
        ],
        [InlineKeyboardButton(t(user_id, 'button_help'),                callback_data='help')],
    ])

def back_keyboard(user_id: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(user_id, 'button_back'), callback_data='menu')]
    ])

def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇫🇷 Français", callback_data='lang_fr'),
            InlineKeyboardButton("🇬🇧 English", callback_data='lang_en'),
        ],
        [InlineKeyboardButton(t(0, 'button_back'), callback_data='menu')],
    ])

# ─── Handlers ─────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    user_id = update.message.from_user.id
    await update.message.reply_text(
        t(user_id, 'welcome'),
        parse_mode='Markdown',
        reply_markup=main_keyboard(user_id)
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    user_id = update.message.from_user.id
    await update.message.reply_text(
        f"{t(user_id, 'help_title')}\n\n"
        f"{t(user_id, 'help_commands')}\n\n"
        f"{t(user_id, 'help_types')}\n"
        f"{t(user_id, 'help_free')}\n"
        f"{t(user_id, 'help_standard')}\n\n"
        f"{t(user_id, 'help_cache')}",
        parse_mode='Markdown',
        reply_markup=back_keyboard(user_id)
    )

async def lang_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande pour changer la langue"""
    if not update.message:
        return
    user_id = update.message.from_user.id
    current_lang = LANGUAGES.get(get_user_language(user_id), '🇫🇷 Français')
    await update.message.reply_text(
        f"{t(user_id, 'lang_title')}\n\n"
        f"{t(user_id, 'current_lang', lang=current_lang)}",
        parse_mode='Markdown',
        reply_markup=language_keyboard()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()

    user_id = query.from_user.id
    action  = query.data or ''

    # Changement de langue
    if action.startswith('lang_'):
        new_lang = action[5:]
        if new_lang in LANGUAGES:
            set_user_language(user_id, new_lang)
            lang_name = LANGUAGES[new_lang]
            await query.edit_message_text(
                t(user_id, 'lang_changed', lang=lang_name),
                parse_mode='Markdown',
                reply_markup=main_keyboard(user_id)
            )
        return

    # Retour au menu
    if action == 'menu':
        await query.edit_message_text(
            t(user_id, 'menu_return'),
            parse_mode='Markdown',
            reply_markup=main_keyboard(user_id)
        )
        return

    # Aide inline
    if action == 'help':
        await query.edit_message_text(
            f"{t(user_id, 'help_title')}\n\n"
            f"{t(user_id, 'help_free')}\n"
            f"{t(user_id, 'help_standard')}\n\n"
            f"{t(user_id, 'help_cache_inline')}",
            parse_mode='Markdown',
            reply_markup=back_keyboard(user_id)
        )
        return

    # Rate limiting (uniquement pour les actions qui chargent des données)
    if is_rate_limited(user_id):
        await query.answer(
            t(user_id, 'rate_limit', seconds=RATE_LIMIT_SECONDS),
            show_alert=True
        )
        return

    # Liste de proxies
    if action.startswith('list_'):
        key = action[5:]
        if key not in URLS:
            await query.edit_message_text(t(user_id, 'unknown_option'), reply_markup=back_keyboard(user_id))
            return

        emoji, label, _ = LABELS[key]
        await query.edit_message_text(t(user_id, 'loading', label=label))

        proxies = fetch_proxies(key)
        if not proxies:
            await query.edit_message_text(
                t(user_id, 'no_proxies', label=label),
                parse_mode='Markdown',
                reply_markup=back_keyboard(user_id)
            )
            return

        # Limite à ~2000 caractères pour éviter l'erreur Message_too_long (limite Telegram: 4096)
        max_chars = 2000
        header = t(user_id, 'proxies_header', emoji=emoji, label=label, total=len(proxies)) + "\n\n`"
        shown = []
        for proxy in proxies:
            test_text = header + "\n".join(shown + [proxy]) + "`"
            if len(test_text) > max_chars:
                break
            shown.append(proxy)

        text = header + "\n".join(shown) + "`"
        remaining = len(proxies) - len(shown)
        if remaining > 0:
            text += f"\n\n_{t(user_id, 'more_proxies', count=remaining)}_"

        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t(user_id, 'button_download_all', count=len(proxies)), callback_data=f'file_{key}')],
                [InlineKeyboardButton(t(user_id, 'button_back'), callback_data='menu')],
            ])
        )
        return

    # Téléchargement de fichier
    if action.startswith('file_'):
        key = action[5:]
        if key not in URLS:
            await query.edit_message_text(t(user_id, 'unknown_option'), reply_markup=back_keyboard(user_id))
            return

        emoji, label, filename = LABELS[key]
        proxies = fetch_proxies(key)
        if not proxies:
            await query.edit_message_text(
                t(user_id, 'no_proxies_file', label=label),
                parse_mode='Markdown',
                reply_markup=back_keyboard(user_id)
            )
            return

        content = "\n".join(proxies).encode('utf-8')
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=io.BytesIO(content),
            filename=filename,
            caption=t(user_id, 'file_caption', emoji=emoji, filename=filename, count=len(proxies)),
            parse_mode='Markdown'
        )
        return

    # Action inconnue
    await query.edit_message_text(t(user_id, 'unknown_action'), reply_markup=back_keyboard(user_id))

async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Répond aux messages texte hors commandes."""
    if update.message:
        user_id = update.message.from_user.id
        await update.message.reply_text(
            t(user_id, 'unknown_message'),
            reply_markup=main_keyboard(user_id)
        )

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Erreur lors du traitement d'un update: {context.error}", exc_info=context.error)

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("proxies", start))
    app.add_handler(CommandHandler("help",    help_command))
    app.add_handler(CommandHandler("lang",    lang_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message))
    app.add_error_handler(error_handler)

    logger.info("✅ Bot démarré — en attente de messages…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
