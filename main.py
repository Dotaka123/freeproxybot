import os
import requests
import csv
import io
import logging
from datetime import datetime
from typing import Dict, List, NamedTuple, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.error import TelegramError

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

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

# Groupes obligatoires à rejoindre avant d'utiliser le bot
REQUIRED_CHANNELS = [
    {"username": "free_proxy00",       "url": "https://t.me/free_proxy00",       "label": "🔐 Free Proxy"},
    {"username": "givesawaysproxy",    "url": "https://t.me/givesawaysproxy",    "label": "🎁 Giveaways Proxy"},
]

URLS = {
    'FREE':     'https://docs.google.com/spreadsheets/d/e/2PACX-1vTQ7Yv6SR-TfyW7rL3mdWSiKgZ-Mdoday5cZL7A8hhqJIQ6GYAVYw9LOSkyGqUddV5q7IkV_tMeU73r/pub?output=csv',
    'STANDARD': 'https://docs.google.com/spreadsheets/d/e/2PACX-1vRoydbgCE61hn48aKwnBfsx5HFZ6H2YGTnDrLvHaGpu5AhpySfFpgBb4wd72wC8X6tbYrYw8_uctp0k/pub?output=csv',
}

LABELS = {
    'FREE':     ('🆓', 'Free',      'proxy.txt'),
    'STANDARD': ('⭐', 'Standard',  'proxy_test.txt'),
}

# ─── Modèle Proxy ─────────────────────────────────────────────────────────────
# Format: 91.99.95.238:43185:user:pass | United States | Florida | Tampa | ISP | Residential | 2026-04-17 ...

class Proxy(NamedTuple):
    raw:     str
    address: str
    country: str
    state:   str
    city:    str
    isp:     str
    ptype:   str
    expiry:  str

def parse_proxy(line: str) -> Optional[Proxy]:
    line = line.strip()
    if not line or line.startswith('#'):
        return None
    parts = [p.strip() for p in line.split('|')]
    address = parts[0] if parts else ''
    if not address:
        return None
    return Proxy(
        raw=line,
        address=address,
        country=parts[1] if len(parts) > 1 else '',
        state=   parts[2] if len(parts) > 2 else '',
        city=    parts[3] if len(parts) > 3 else '',
        isp=     parts[4] if len(parts) > 4 else '',
        ptype=   parts[5] if len(parts) > 5 else '',
        expiry=  parts[6] if len(parts) > 6 else '',
    )

def format_proxy_display(p: Proxy) -> str:
    location = ' | '.join(filter(None, [p.country, p.city]))
    return f"`{p.address}` — {location}" if location else f"`{p.address}`"

def get_unique_countries(proxies: List[Proxy]) -> List[str]:
    return sorted({p.country for p in proxies if p.country})

def get_unique_types(proxies: List[Proxy]) -> List[str]:
    return sorted({p.ptype for p in proxies if p.ptype})

# ─── Cache ────────────────────────────────────────────────────────────────────
_cache: Dict[str, tuple] = {}

def fetch_proxies(key: str) -> List[Proxy]:
    now = datetime.now()
    if key in _cache:
        proxies, fetched_at = _cache[key]
        if (now - fetched_at).total_seconds() < CACHE_TTL_SECONDS:
            return proxies

    url = URLS[key]
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        proxies = []
        for line in response.text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = next(csv.reader([line]))
                # Reconstruct the full pipe-delimited string from all CSV columns
                if len(row) > 1:
                    raw = ' | '.join(col.strip() for col in row)
                else:
                    raw = row[0].strip() if row else ''
            except Exception:
                raw = line
            p = parse_proxy(raw)
            if p:
                proxies.append(p)
        _cache[key] = (proxies, now)
        logger.info(f"[Fetch] {key}: {len(proxies)} proxies")
        return proxies
    except Exception as e:
        logger.error(f"[Fetch] {key}: {e}")
        if key in _cache:
            return _cache[key][0]
        return []

def filter_proxies(proxies: List[Proxy], country: str = 'all', ptype: str = 'all') -> List[Proxy]:
    result = proxies
    if country != 'all':
        result = [p for p in result if p.country.lower() == country.lower()]
    if ptype != 'all':
        result = [p for p in result if p.ptype.lower() == ptype.lower()]
    return result

# ─── Vérification d'adhésion aux canaux ───────────────────────────────────────
async def check_membership(bot, user_id: int) -> List[dict]:
    """Retourne la liste des canaux que l'utilisateur n'a PAS encore rejoints."""
    not_joined = []
    for channel in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(
                chat_id=f"@{channel['username']}",
                user_id=user_id
            )
            if member.status in [ChatMember.LEFT, ChatMember.BANNED]:
                not_joined.append(channel)
        except TelegramError as e:
            logger.warning(f"Impossible de vérifier @{channel['username']}: {e}")
            # En cas d'erreur (canal privé, bot non admin, etc.), on laisse passer
    return not_joined

def join_keyboard(uid: int, missing_channels: List[dict]) -> InlineKeyboardMarkup:
    """Clavier avec les boutons pour rejoindre les canaux manquants + bouton vérifier."""
    rows = []
    for ch in missing_channels:
        rows.append([InlineKeyboardButton(f"👉 {ch['label']}", url=ch['url'])])
    rows.append([InlineKeyboardButton(
        "✅ J'ai rejoint — Vérifier" if get_lang(uid) == 'fr' else "✅ I joined — Check",
        callback_data='check_membership'
    )])
    return InlineKeyboardMarkup(rows)

# ─── Rate Limiting ────────────────────────────────────────────────────────────
_user_last_request: Dict[int, datetime] = {}

def is_rate_limited(uid: int) -> bool:
    now  = datetime.now()
    last = _user_last_request.get(uid)
    if last and (now - last).total_seconds() < RATE_LIMIT_SECONDS:
        return True
    _user_last_request[uid] = now
    return False

# ─── Préférences utilisateur ──────────────────────────────────────────────────
_user_lang:    Dict[int, str] = {}
_user_country: Dict[int, str] = {}
_user_type:    Dict[int, str] = {}

def get_lang(uid: int) -> str:    return _user_lang.get(uid, 'en')   # Anglais par défaut
def get_country(uid: int) -> str: return _user_country.get(uid, 'all')
def get_type(uid: int) -> str:    return _user_type.get(uid, 'all')

LANGUAGES = {'en': '🇬🇧 English', 'fr': '🇫🇷 Français'}

TRANSLATIONS: Dict[str, Dict[str, str]] = {
    'en': {
        # Membership gate
        'must_join':       "👋 *Welcome!*\n\nTo use this bot, you must first join our channels:",
        'must_join_still': "⚠️ You haven't joined all required channels yet.\n\nPlease join them all, then click *Check* again:",
        'welcome_ok':      "✅ *Great, you're in!*\n\nWelcome to *Proxy Bot* 🎉\nChoose an option below:",
        # Main menu
        'welcome':         "👋 *Welcome to Proxy Bot!*\n\nChoose an option:",
        'btn_free_list':   "🆓 Free Proxies",
        'btn_std_list':    "⭐ Standard Proxies",
        'btn_free_file':   "📥 FREE File",
        'btn_std_file':    "📥 STANDARD File",
        'btn_filter':      "🔍 Filters",
        'btn_help':        "ℹ️ Help",
        'btn_back':        "⬅️ Back",
        'btn_dl_all':      "📥 Download all ({count})",
        # Status messages
        'loading':         "⏳ Loading {label} proxies…",
        'no_proxies':      "❌ No *{label}* proxies available.",
        'no_proxies_filt': "❌ No *{label}* proxies match these filters.\nCountry: `{country}` | Type: `{ptype}`",
        'header':          "{emoji} *{label} Proxies* — {total} result(s)",
        'filter_info':     "📍 Filters: country `{country}` | type `{ptype}`",
        'more':            "+{count} more — download the full file below.",
        'rate_limit':      "⏳ Please wait {s}s between requests.",
        'unknown_msg':     "Use /start to show the menu.",
        'help_text': (
            "ℹ️ *Help — Proxy Bot*\n\n"
            "• `/start` — Main menu\n"
            "• `/help` — This help\n\n"
            "*Proxy format:*\n"
            "`IP:PORT:USER:PASS | Country | Region | City | ISP | Type | Expiry`\n\n"
            "*Filters:*\n"
            "• By country (e.g. United States, France…)\n"
            "• By type (Residential, Datacenter…)\n\n"
            "Lists are cached for 5 min."
        ),
        # Filters
        'filter_menu':     "🔍 *Active filters*\nCountry: `{country}` | Type: `{ptype}`",
        'filter_country':  "🌍 Filter by country",
        'filter_type':     "🏷️ Filter by type",
        'filter_reset':    "🔄 Reset filters",
        'filter_reset_ok': "✅ Filters reset.",
        'select_country':  "🌍 *Select a country*",
        'select_type':     "🏷️ *Select a proxy type*",
        # Language
        'lang_menu':       "🌐 *Choose a language*",
        'lang_changed':    "✅ Language set to {lang}.",
        'country_set':     "✅ Country: *{country}*",
        'type_set':        "✅ Type: *{ptype}*",
        'all':             "All",
    },
    'fr': {
        # Vérification d'adhésion
        'must_join':       "👋 *Bienvenue!*\n\nPour utiliser ce bot, vous devez d'abord rejoindre nos canaux :",
        'must_join_still': "⚠️ Vous n'avez pas encore rejoint tous les canaux requis.\n\nRejoignez-les tous, puis cliquez sur *Vérifier* :",
        'welcome_ok':      "✅ *Parfait, vous êtes membre!*\n\nBienvenue sur *Proxy Bot* 🎉\nChoisissez une option :",
        # Menu principal
        'welcome':         "👋 *Bienvenue sur le Bot Proxy!*\n\nChoisissez une option :",
        'btn_free_list':   "🆓 Proxies Gratuits",
        'btn_std_list':    "⭐ Proxies Standard",
        'btn_free_file':   "📥 Fichier FREE",
        'btn_std_file':    "📥 Fichier STANDARD",
        'btn_filter':      "🔍 Filtres",
        'btn_help':        "ℹ️ Aide",
        'btn_back':        "⬅️ Retour",
        'btn_dl_all':      "📥 Télécharger tout ({count})",
        # Messages
        'loading':         "⏳ Chargement des proxies {label}…",
        'no_proxies':      "❌ Aucun proxy *{label}* disponible.",
        'no_proxies_filt': "❌ Aucun proxy *{label}* avec ces filtres.\nPays: `{country}` | Type: `{ptype}`",
        'header':          "{emoji} *Proxies {label}* — {total} résultat(s)",
        'filter_info':     "📍 Filtres: pays `{country}` | type `{ptype}`",
        'more':            "+{count} autres — téléchargez le fichier complet.",
        'rate_limit':      "⏳ Attendez {s}s entre chaque demande.",
        'unknown_msg':     "Utilise /start pour afficher le menu.",
        'help_text': (
            "ℹ️ *Aide — Bot Proxy*\n\n"
            "• `/start` — Menu principal\n"
            "• `/help` — Cette aide\n\n"
            "*Format des proxies :*\n"
            "`IP:PORT:USER:PASS | Pays | Région | Ville | FAI | Type | Expiry`\n\n"
            "*Filtres :*\n"
            "• Par pays (ex: United States, France…)\n"
            "• Par type (Residential, Datacenter…)\n\n"
            "Les listes sont mises en cache 5 min."
        ),
        # Filtres
        'filter_menu':     "🔍 *Filtres actifs*\nPays: `{country}` | Type: `{ptype}`",
        'filter_country':  "🌍 Filtrer par pays",
        'filter_type':     "🏷️ Filtrer par type",
        'filter_reset':    "🔄 Réinitialiser filtres",
        'filter_reset_ok': "✅ Filtres réinitialisés.",
        'select_country':  "🌍 *Sélectionnez un pays*",
        'select_type':     "🏷️ *Sélectionnez un type de proxy*",
        # Langue
        'lang_menu':       "🌐 *Choisissez une langue*",
        'lang_changed':    "✅ Langue changée en {lang}.",
        'country_set':     "✅ Pays: *{country}*",
        'type_set':        "✅ Type: *{ptype}*",
        'all':             "Tous",
    },
}

def tr(uid: int, key: str, **kw) -> str:
    lang = get_lang(uid)
    text = TRANSLATIONS.get(lang, TRANSLATIONS['en']).get(key, key)
    try:
        return text.format(**kw) if kw else text
    except KeyError:
        return text

# ─── Claviers ─────────────────────────────────────────────────────────────────
def main_kb(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(tr(uid,'btn_free_list'), callback_data='list_FREE'),
            InlineKeyboardButton(tr(uid,'btn_std_list'),  callback_data='list_STANDARD'),
        ],
        [
            InlineKeyboardButton(tr(uid,'btn_free_file'), callback_data='file_FREE'),
            InlineKeyboardButton(tr(uid,'btn_std_file'),  callback_data='file_STANDARD'),
        ],
        [
            InlineKeyboardButton(tr(uid,'btn_filter'), callback_data='filter_menu'),
            InlineKeyboardButton(tr(uid,'btn_help'),   callback_data='help'),
        ],
        [InlineKeyboardButton("🇬🇧 EN / 🇫🇷 FR", callback_data='lang_menu')],
    ])

def back_kb(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(tr(uid,'btn_back'), callback_data='menu')]])

def filter_kb(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(tr(uid,'filter_country'), callback_data='pick_country')],
        [InlineKeyboardButton(tr(uid,'filter_type'),    callback_data='pick_type')],
        [InlineKeyboardButton(tr(uid,'filter_reset'),   callback_data='filter_reset')],
        [InlineKeyboardButton(tr(uid,'btn_back'),       callback_data='menu')],
    ])

def country_kb(uid: int, proxies: List[Proxy]) -> InlineKeyboardMarkup:
    countries = get_unique_countries(proxies)
    rows, row = [], []
    for c in countries:
        row.append(InlineKeyboardButton(c, callback_data=f'setcountry_{c}'))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(f"🌍 {tr(uid,'all')}", callback_data='setcountry_all')])
    rows.append([InlineKeyboardButton(tr(uid,'btn_back'),     callback_data='filter_menu')])
    return InlineKeyboardMarkup(rows)

def type_kb(uid: int, proxies: List[Proxy]) -> InlineKeyboardMarkup:
    types = get_unique_types(proxies)
    rows  = [[InlineKeyboardButton(pt, callback_data=f'settype_{pt}')] for pt in types]
    rows.append([InlineKeyboardButton(f"🏷️ {tr(uid,'all')}", callback_data='settype_all')])
    rows.append([InlineKeyboardButton(tr(uid,'btn_back'),      callback_data='filter_menu')])
    return InlineKeyboardMarkup(rows)

def lang_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🇬🇧 English",  callback_data='setlang_en'),
        InlineKeyboardButton("🇫🇷 Français", callback_data='setlang_fr'),
    ]])

# ─── Helper d'affichage ───────────────────────────────────────────────────────
def build_list_message(uid: int, proxies: List[Proxy], emoji: str, label: str,
                        country: str, ptype: str) -> str:
    total    = len(proxies)
    c_label  = country if country != 'all' else tr(uid,'all')
    pt_label = ptype   if ptype   != 'all' else tr(uid,'all')

    lines = [tr(uid,'header', emoji=emoji, label=label, total=total)]
    if country != 'all' or ptype != 'all':
        lines.append(tr(uid,'filter_info', country=c_label, ptype=pt_label))
    lines.append("")

    MAX_CHARS = 3500
    shown = 0
    for p in proxies:
        line = format_proxy_display(p)
        if len("\n".join(lines + [line])) > MAX_CHARS:
            break
        lines.append(line)
        shown += 1

    remaining = total - shown
    if remaining > 0:
        lines.append(f"\n_{tr(uid,'more', count=remaining)}_")

    return "\n".join(lines)

# ─── Handlers ─────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    uid = update.message.from_user.id

    # Vérification d'adhésion aux canaux requis
    missing = await check_membership(context.bot, uid)
    if missing:
        await update.message.reply_text(
            tr(uid, 'must_join'),
            parse_mode='Markdown',
            reply_markup=join_keyboard(uid, missing)
        )
        return

    await update.message.reply_text(
        tr(uid,'welcome'), parse_mode='Markdown', reply_markup=main_kb(uid)
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    uid = update.message.from_user.id
    missing = await check_membership(context.bot, uid)
    if missing:
        await update.message.reply_text(
            tr(uid,'must_join'), parse_mode='Markdown',
            reply_markup=join_keyboard(uid, missing)
        )
        return
    await update.message.reply_text(
        tr(uid,'help_text'), parse_mode='Markdown', reply_markup=back_kb(uid)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()

    uid    = query.from_user.id
    action = query.data or ''

    # ── Vérification d'adhésion (bouton "J'ai rejoint") ──────────────────────
    if action == 'check_membership':
        missing = await check_membership(context.bot, uid)
        if missing:
            await query.edit_message_text(
                tr(uid,'must_join_still'),
                parse_mode='Markdown',
                reply_markup=join_keyboard(uid, missing)
            )
        else:
            await query.edit_message_text(
                tr(uid,'welcome_ok'),
                parse_mode='Markdown',
                reply_markup=main_kb(uid)
            )
        return

    # ── Pour toutes les autres actions : vérifier l'adhésion ─────────────────
    missing = await check_membership(context.bot, uid)
    if missing:
        await query.edit_message_text(
            tr(uid,'must_join'),
            parse_mode='Markdown',
            reply_markup=join_keyboard(uid, missing)
        )
        return

    # ── Navigation ──────────────────────────────────────────────────────────
    if action == 'menu':
        await query.edit_message_text(tr(uid,'welcome'), parse_mode='Markdown', reply_markup=main_kb(uid))
        return

    if action == 'help':
        await query.edit_message_text(tr(uid,'help_text'), parse_mode='Markdown', reply_markup=back_kb(uid))
        return

    if action == 'lang_menu':
        await query.edit_message_text(tr(uid,'lang_menu'), parse_mode='Markdown', reply_markup=lang_kb())
        return

    # ── Langue ───────────────────────────────────────────────────────────────
    if action.startswith('setlang_'):
        lang = action[8:]
        if lang in LANGUAGES:
            _user_lang[uid] = lang
        await query.edit_message_text(
            tr(uid,'lang_changed', lang=LANGUAGES.get(lang, lang)),
            parse_mode='Markdown', reply_markup=main_kb(uid)
        )
        return

    # ── Menu filtres ──────────────────────────────────────────────────────────
    if action == 'filter_menu':
        c_label  = get_country(uid) if get_country(uid) != 'all' else tr(uid,'all')
        pt_label = get_type(uid)    if get_type(uid)    != 'all' else tr(uid,'all')
        await query.edit_message_text(
            tr(uid,'filter_menu', country=c_label, ptype=pt_label),
            parse_mode='Markdown', reply_markup=filter_kb(uid)
        )
        return

    if action == 'filter_reset':
        _user_country[uid] = 'all'
        _user_type[uid]    = 'all'
        await query.edit_message_text(tr(uid,'filter_reset_ok'), reply_markup=main_kb(uid))
        return

    if action == 'pick_country':
        proxies = fetch_proxies('FREE') + fetch_proxies('STANDARD')
        await query.edit_message_text(
            tr(uid,'select_country'), parse_mode='Markdown',
            reply_markup=country_kb(uid, proxies)
        )
        return

    if action.startswith('setcountry_'):
        country = action[11:]
        _user_country[uid] = country
        label = country if country != 'all' else tr(uid,'all')
        await query.edit_message_text(
            tr(uid,'country_set', country=label),
            parse_mode='Markdown', reply_markup=filter_kb(uid)
        )
        return

    if action == 'pick_type':
        proxies = fetch_proxies('FREE') + fetch_proxies('STANDARD')
        await query.edit_message_text(
            tr(uid,'select_type'), parse_mode='Markdown',
            reply_markup=type_kb(uid, proxies)
        )
        return

    if action.startswith('settype_'):
        ptype = action[8:]
        _user_type[uid] = ptype
        label = ptype if ptype != 'all' else tr(uid,'all')
        await query.edit_message_text(
            tr(uid,'type_set', ptype=label),
            parse_mode='Markdown', reply_markup=filter_kb(uid)
        )
        return

    # ── Rate limiting ─────────────────────────────────────────────────────────
    if is_rate_limited(uid):
        await query.answer(tr(uid,'rate_limit', s=RATE_LIMIT_SECONDS), show_alert=True)
        return

    # ── Liste de proxies ──────────────────────────────────────────────────────
    if action.startswith('list_'):
        key = action[5:]
        if key not in URLS:
            await query.edit_message_text(tr(uid,'no_proxies', label=key), reply_markup=back_kb(uid))
            return

        emoji, label, _ = LABELS[key]
        await query.edit_message_text(tr(uid,'loading', label=label))

        all_proxies = fetch_proxies(key)
        country     = get_country(uid)
        ptype       = get_type(uid)
        proxies     = filter_proxies(all_proxies, country, ptype)

        if not proxies:
            c_label  = country if country != 'all' else tr(uid,'all')
            pt_label = ptype   if ptype   != 'all' else tr(uid,'all')
            msg = (tr(uid,'no_proxies_filt', label=label, country=c_label, ptype=pt_label)
                   if country != 'all' or ptype != 'all'
                   else tr(uid,'no_proxies', label=label))
            await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=back_kb(uid))
            return

        text = build_list_message(uid, proxies, emoji, label, country, ptype)
        kb   = InlineKeyboardMarkup([
            [InlineKeyboardButton(tr(uid,'btn_dl_all', count=len(proxies)), callback_data=f'file_{key}')],
            [InlineKeyboardButton(tr(uid,'btn_back'), callback_data='menu')],
        ])
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=kb)
        return

    # ── Téléchargement fichier ────────────────────────────────────────────────
    if action.startswith('file_'):
        key = action[5:]
        if key not in URLS:
            await query.edit_message_text(tr(uid,'no_proxies', label=key), reply_markup=back_kb(uid))
            return

        emoji, label, filename = LABELS[key]
        all_proxies = fetch_proxies(key)
        country     = get_country(uid)
        ptype       = get_type(uid)
        proxies     = filter_proxies(all_proxies, country, ptype)

        if not proxies:
            await query.edit_message_text(
                tr(uid,'no_proxies', label=label),
                parse_mode='Markdown', reply_markup=back_kb(uid)
            )
            return

        # Export : lignes brutes complètes avec toutes les métadonnées
        content   = "\n".join(p.raw for p in proxies).encode('utf-8')
        file_name = f"{country}_{filename}" if country != 'all' else filename

        c_label  = country if country != 'all' else tr(uid,'all')
        pt_label = ptype   if ptype   != 'all' else tr(uid,'all')
        caption  = f"{emoji} *{file_name}* — {len(proxies)} proxies"
        if country != 'all' or ptype != 'all':
            caption += f"\nCountry: `{c_label}` | Type: `{pt_label}`"

        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=io.BytesIO(content),
            filename=file_name,
            caption=caption,
            parse_mode='Markdown'
        )
        return

    # ── Action inconnue ───────────────────────────────────────────────────────
    await query.edit_message_text(tr(uid,'no_proxies', label='?'), reply_markup=back_kb(uid))

async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    uid = update.message.from_user.id
    missing = await check_membership(context.bot, uid)
    if missing:
        await update.message.reply_text(
            tr(uid,'must_join'), parse_mode='Markdown',
            reply_markup=join_keyboard(uid, missing)
        )
        return
    await update.message.reply_text(tr(uid,'unknown_msg'), reply_markup=main_kb(uid))

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Erreur: {context.error}", exc_info=context.error)

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("proxies", start))
    app.add_handler(CommandHandler("help",    help_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message))
    app.add_error_handler(error_handler)
    logger.info("✅ Bot démarré — en attente de messages…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
