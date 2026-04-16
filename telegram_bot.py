"""
بوت تيليجرام - المطيري للحجز
============================
بوت كامل يربط مع نفس قاعدة بيانات الموقع والتطبيق ويوفر نفس المحتوى والميزات.

التشغيل:
  1) ضع توكن البوت في BOT_TOKEN أدناه (احصل عليه من @BotFather)
  2) ضع رابط API الموقع في API_BASE_URL (يكون رابط الموقع المنشور + /api)
  3) ثبّت المتطلبات:  pip install python-telegram-bot==21.6 requests
  4) شغّل البوت:      python telegram_bot.py

المحتوى نفس التطبيق والموقع 100%:
  - تسجيل دخول / إنشاء حساب
  - عرض الباقات وشراء التذاكر
  - تذاكري + QR + مشاركة عبر واتساب
  - المحفظة + التحويل بين المستخدمين
  - شحن الرصيد (إيصال / بطاقة / STC)
  - لوحة الإدارة الكاملة (للمدير 888888000888)
  - الإعلانات المتحركة
  - إشعارات فورية

مكتوب بالعربية بالكامل ومتوافق مع نفس الواجهة الخلفية.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from urllib.parse import quote

import requests
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# ════════════════════════════════════════════════════════════════════════════
# الإعدادات
# ════════════════════════════════════════════════════════════════════════════

BOT_TOKEN = "8771060798:AAFSOwp1Ukl_veLeuFfNSiTg1sNZeveKcQc"
API_BASE_URL = "http://localhost:8080/api"  # ← ضع رابط API الموقع المنشور هنا
ADMIN_EMAIL = "888888000888"
ADMIN_PASSWORD = "888888000888"
ALLOWED_DOMAINS = ("gmail.com", "hotmail.com", "live.com", "yahoo.com")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("mutairi-bot")

# ════════════════════════════════════════════════════════════════════════════
# جلسات المستخدمين (داخل الذاكرة)
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class Session:
    email: Optional[str] = None
    name: Optional[str] = None
    is_admin: bool = False
    wallet: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

SESSIONS: dict[int, Session] = {}

def session_for(chat_id: int) -> Session:
    if chat_id not in SESSIONS:
        SESSIONS[chat_id] = Session()
    return SESSIONS[chat_id]

# ════════════════════════════════════════════════════════════════════════════
# عميل API
# ════════════════════════════════════════════════════════════════════════════

class ApiClient:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")

    def _req(self, method: str, path: str, **kw) -> Any:
        url = f"{self.base}{path}"
        try:
            r = requests.request(method, url, timeout=20, **kw)
            if r.status_code >= 400:
                try:
                    data = r.json()
                except Exception:
                    data = {"error": r.text or "خطأ"}
                return {"_error": True, "status": r.status_code, **data}
            try:
                return r.json()
            except Exception:
                return {"ok": True}
        except Exception as e:
            logger.exception("API error: %s %s", method, url)
            return {"_error": True, "message": str(e)}

    def get(self, path: str, **kw): return self._req("GET", path, **kw)
    def post(self, path: str, json=None, **kw): return self._req("POST", path, json=json, **kw)
    def patch(self, path: str, json=None, **kw): return self._req("PATCH", path, json=json, **kw)
    def put(self, path: str, json=None, **kw): return self._req("PUT", path, json=json, **kw)
    def delete(self, path: str, **kw): return self._req("DELETE", path, **kw)

api = ApiClient(API_BASE_URL)

# ════════════════════════════════════════════════════════════════════════════
# أدوات مساعدة
# ════════════════════════════════════════════════════════════════════════════

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def valid_email(email: str) -> bool:
    if not EMAIL_RE.match(email or ""):
        return False
    domain = email.split("@", 1)[1].lower()
    return domain in ALLOWED_DOMAINS or email == ADMIN_EMAIL

def qr_url(data: str) -> str:
    return f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={quote(data)}"

def whatsapp_share_url(text: str) -> str:
    return f"https://wa.me/?text={quote(text)}"

def fmt_sar(n: int | float) -> str:
    return f"{int(n):,} ر.س"

def main_keyboard(s: Session) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton("🎟️ الباقات"), KeyboardButton("📋 تذاكري")],
        [KeyboardButton("💰 محفظتي"), KeyboardButton("📢 الإعلانات")],
        [KeyboardButton("👤 حسابي"), KeyboardButton("ℹ️ حول")],
    ]
    if s.is_admin:
        rows.append([KeyboardButton("🛠️ لوحة الإدارة")])
    rows.append([KeyboardButton("🚪 تسجيل خروج")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def login_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("🔐 تسجيل دخول"), KeyboardButton("✨ إنشاء حساب")]],
        resize_keyboard=True,
    )

def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton("❌ إلغاء")]], resize_keyboard=True)

def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 الإحصائيات", callback_data="admin:stats"),
         InlineKeyboardButton("👥 المستخدمون", callback_data="admin:users")],
        [InlineKeyboardButton("🎟️ الباقات", callback_data="admin:packages"),
         InlineKeyboardButton("🎫 التذاكر", callback_data="admin:tickets")],
        [InlineKeyboardButton("💳 طلبات الشحن", callback_data="admin:topups"),
         InlineKeyboardButton("💼 طلبات البطاقات", callback_data="admin:cards")],
        [InlineKeyboardButton("📱 طلبات STC", callback_data="admin:stc"),
         InlineKeyboardButton("📢 الإعلانات", callback_data="admin:announcements")],
        [InlineKeyboardButton("🔔 إرسال إشعار", callback_data="admin:notify")],
    ])

# حالات المحادثة
(
    LOGIN_EMAIL, LOGIN_PWD,
    REG_NAME, REG_EMAIL, REG_PWD,
    BUY_PKG_PICK,
    TOPUP_PICK_PKG, TOPUP_RECEIPT,
    TRANSFER_EMAIL, TRANSFER_AMOUNT,
    NOTIFY_EMAIL, NOTIFY_TITLE, NOTIFY_BODY,
    ANN_TEXT, ANN_PAGE,
    ADD_PKG_NAME, ADD_PKG_AMOUNT, ADD_PKG_NOTE,
) = range(18)

# ════════════════════════════════════════════════════════════════════════════
# /start و القائمة الرئيسية
# ════════════════════════════════════════════════════════════════════════════

WELCOME = (
    "🎟️ <b>المطيري للحجز</b>\n"
    "<i>تذكرتك بتجيك ذحين</i>\n\n"
    "أهلاً بك 👋\n"
    "سجّل دخول أو أنشئ حساب جديد للبدء."
)

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = session_for(update.effective_chat.id)
    if s.email:
        await update.message.reply_text(
            f"أهلاً <b>{s.name}</b> 🌟", parse_mode=ParseMode.HTML,
            reply_markup=main_keyboard(s),
        )
    else:
        await update.message.reply_text(
            WELCOME, parse_mode=ParseMode.HTML, reply_markup=login_keyboard(),
        )

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📖 <b>الأوامر:</b>\n"
        "/start - البداية\n"
        "/menu - القائمة الرئيسية\n"
        "/logout - تسجيل خروج\n"
        "/help - المساعدة\n\n"
        "استخدم الأزرار أسفل الشاشة للتنقل بسهولة."
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = session_for(update.effective_chat.id)
    if not s.email:
        return await update.message.reply_text("سجّل دخول أولاً.", reply_markup=login_keyboard())
    await update.message.reply_text("القائمة الرئيسية:", reply_markup=main_keyboard(s))

async def cmd_logout(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    SESSIONS.pop(update.effective_chat.id, None)
    await update.message.reply_text("تم تسجيل الخروج 👋", reply_markup=login_keyboard())

# ════════════════════════════════════════════════════════════════════════════
# تسجيل الدخول
# ════════════════════════════════════════════════════════════════════════════

async def login_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔐 أرسل بريدك الإلكتروني:", reply_markup=cancel_kb(),
    )
    return LOGIN_EMAIL

async def login_email(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if txt == "❌ إلغاء":
        return await cancel_conv(update, ctx)
    ctx.user_data["login_email"] = txt.lower()
    await update.message.reply_text("🔑 أرسل كلمة المرور:")
    return LOGIN_PWD

async def login_pwd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pwd = update.message.text.strip()
    if pwd == "❌ إلغاء":
        return await cancel_conv(update, ctx)
    email = ctx.user_data.get("login_email", "")
    res = api.post("/auth/login", json={"email": email, "password": pwd})
    if res.get("_error") or not res.get("success"):
        msg = res.get("message") or "فشل تسجيل الدخول."
        await update.message.reply_text(f"❌ {msg}", reply_markup=login_keyboard())
        return ConversationHandler.END
    user = res["user"]
    s = session_for(update.effective_chat.id)
    s.email = user["email"]; s.name = user["name"]
    s.is_admin = bool(user.get("isAdmin")); s.wallet = int(user.get("wallet") or 0)
    await update.message.reply_text(
        f"✅ أهلاً <b>{s.name}</b>!\nرصيدك: <b>{fmt_sar(s.wallet)}</b>",
        parse_mode=ParseMode.HTML, reply_markup=main_keyboard(s),
    )
    return ConversationHandler.END

# ════════════════════════════════════════════════════════════════════════════
# إنشاء حساب
# ════════════════════════════════════════════════════════════════════════════

async def reg_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✨ ما اسمك الكامل؟", reply_markup=cancel_kb())
    return REG_NAME

async def reg_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ إلغاء": return await cancel_conv(update, ctx)
    ctx.user_data["reg_name"] = update.message.text.strip()
    await update.message.reply_text(
        f"📧 بريدك الإلكتروني؟\n<i>المسموح: {', '.join(ALLOWED_DOMAINS)}</i>",
        parse_mode=ParseMode.HTML,
    )
    return REG_EMAIL

async def reg_email(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip().lower()
    if txt == "❌ إلغاء": return await cancel_conv(update, ctx)
    if not valid_email(txt):
        await update.message.reply_text("❌ بريد غير صحيح أو نطاق غير مدعوم. أعد المحاولة:")
        return REG_EMAIL
    ctx.user_data["reg_email"] = txt
    await update.message.reply_text("🔑 اختر كلمة مرور (٦ أحرف على الأقل):")
    return REG_PWD

async def reg_pwd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pwd = update.message.text.strip()
    if pwd == "❌ إلغاء": return await cancel_conv(update, ctx)
    if len(pwd) < 6:
        await update.message.reply_text("❌ قصيرة جداً، ٦ أحرف على الأقل:")
        return REG_PWD
    res = api.post("/auth/register", json={
        "email": ctx.user_data["reg_email"],
        "password": pwd,
        "name": ctx.user_data["reg_name"],
    })
    if res.get("_error") or not res.get("success"):
        msg = res.get("message") or "فشل إنشاء الحساب."
        await update.message.reply_text(f"❌ {msg}", reply_markup=login_keyboard())
        return ConversationHandler.END
    user = res["user"]
    s = session_for(update.effective_chat.id)
    s.email = user["email"]; s.name = user["name"]
    s.is_admin = bool(user.get("isAdmin")); s.wallet = int(user.get("wallet") or 0)
    await update.message.reply_text(
        f"🎉 مرحباً <b>{s.name}</b>!\nأضفنا لك <b>{fmt_sar(s.wallet)}</b> هدية ترحيبية.",
        parse_mode=ParseMode.HTML, reply_markup=main_keyboard(s),
    )
    return ConversationHandler.END

# ════════════════════════════════════════════════════════════════════════════
# الباقات + الشراء
# ════════════════════════════════════════════════════════════════════════════

def require_login(handler):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE, *a, **kw):
        s = session_for(update.effective_chat.id)
        if not s.email:
            await update.message.reply_text("⚠️ سجّل دخول أولاً.", reply_markup=login_keyboard())
            return
        return await handler(update, ctx, *a, **kw)
    return wrapper

@require_login
async def show_packages(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pkgs = api.get("/packages")
    if isinstance(pkgs, dict) and pkgs.get("_error"):
        return await update.message.reply_text("❌ تعذّر جلب الباقات.")
    if not pkgs:
        return await update.message.reply_text("🚫 لا توجد باقات متاحة حالياً.")
    lines = ["🎟️ <b>الباقات المتاحة</b>\n"]
    kb = []
    for p in pkgs:
        lines.append(f"▫️ <b>{p['name']}</b> — {fmt_sar(p['amount'])}")
        if p.get("note"): lines.append(f"   <i>{p['note']}</i>")
        kb.append([InlineKeyboardButton(f"شراء {p['name']} ({fmt_sar(p['amount'])})",
                                        callback_data=f"buy:{p['id']}")])
    await update.message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb),
    )

async def cb_buy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    s = session_for(q.message.chat.id)
    if not s.email:
        return await q.edit_message_text("سجّل دخول أولاً.")
    pkg_id = q.data.split(":", 1)[1]
    pkgs = api.get("/packages")
    pkg = next((p for p in pkgs if p["id"] == pkg_id), None)
    if not pkg:
        return await q.edit_message_text("❌ الباقة غير موجودة.")
    # تحقق من الرصيد
    if s.wallet < pkg["amount"]:
        return await q.edit_message_text(
            f"❌ رصيدك غير كافٍ.\nالمطلوب: {fmt_sar(pkg['amount'])}\nرصيدك: {fmt_sar(s.wallet)}\n\n"
            "اشحن رصيدك من زر 💰 محفظتي.",
        )
    # خصم وإنشاء تذكرة
    new_wallet = s.wallet - pkg["amount"]
    api.patch(f"/users/{quote(s.email)}", json={"wallet": new_wallet})
    ticket = api.post("/tickets", json={
        "eventName": pkg["name"],
        "ticketCount": 1,
        "box": f"BOX-{secrets.randbelow(9999):04d}",
        "paymentType": "real",
        "status": "confirmed",
        "date": datetime.utcnow().isoformat(),
        "userName": s.name,
        "userEmail": s.email,
    })
    if ticket.get("_error"):
        return await q.edit_message_text("❌ فشل إنشاء التذكرة.")
    s.wallet = new_wallet
    await q.edit_message_text(
        f"✅ <b>تم الشراء بنجاح!</b>\n\n"
        f"🎫 {pkg['name']}\n"
        f"📦 الصندوق: {ticket['box']}\n"
        f"💰 رصيدك المتبقي: <b>{fmt_sar(s.wallet)}</b>\n\n"
        "اضغط 📋 تذاكري لعرض التذكرة مع الـ QR.",
        parse_mode=ParseMode.HTML,
    )

# ════════════════════════════════════════════════════════════════════════════
# تذاكري
# ════════════════════════════════════════════════════════════════════════════

@require_login
async def my_tickets(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = session_for(update.effective_chat.id)
    tix = api.get("/tickets")
    if isinstance(tix, dict) and tix.get("_error"):
        return await update.message.reply_text("❌ تعذّر جلب التذاكر.")
    mine = [t for t in tix if (t.get("userEmail") or "").lower() == s.email]
    if not mine:
        return await update.message.reply_text("🚫 لا توجد تذاكر بعد.\nاذهب إلى 🎟️ الباقات للشراء.")
    await update.message.reply_text(f"📋 لديك <b>{len(mine)}</b> تذكرة:", parse_mode=ParseMode.HTML)
    for t in mine[-10:]:  # آخر ١٠ تذاكر
        status_steps = "1️⃣ مؤكدة → 2️⃣ جاهزة → 3️⃣ تم الاستخدام"
        share_text = f"تذكرتي لـ {t['eventName']} — صندوق {t['box']}"
        kb = [[
            InlineKeyboardButton("📲 مشاركة واتساب", url=whatsapp_share_url(share_text)),
            InlineKeyboardButton("🔗 رابط QR", url=qr_url(t["id"])),
        ]]
        caption = (
            f"🎫 <b>{t['eventName']}</b>\n"
            f"📦 الصندوق: <code>{t['box']}</code>\n"
            f"🆔 رقم التذكرة: <code>{t['id']}</code>\n"
            f"📅 التاريخ: {t['date'][:10]}\n"
            f"✅ الحالة: {t.get('status','confirmed')}\n"
            f"📊 {status_steps}"
        )
        try:
            await update.message.reply_photo(
                photo=qr_url(t["id"]), caption=caption,
                parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb),
            )
        except Exception:
            await update.message.reply_text(caption, parse_mode=ParseMode.HTML,
                                            reply_markup=InlineKeyboardMarkup(kb))

# ════════════════════════════════════════════════════════════════════════════
# المحفظة
# ════════════════════════════════════════════════════════════════════════════

@require_login
async def show_wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = session_for(update.effective_chat.id)
    # تحديث الرصيد من الخادم
    users = api.get("/users")
    if isinstance(users, list):
        u = next((x for x in users if x["email"] == s.email), None)
        if u: s.wallet = int(u.get("wallet") or 0)
    text = (
        f"💰 <b>محفظتي</b>\n\n"
        f"الرصيد الحالي: <b>{fmt_sar(s.wallet)}</b>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ شحن رصيد", callback_data="wallet:topup"),
         InlineKeyboardButton("🔄 تحويل لمستخدم", callback_data="wallet:transfer")],
        [InlineKeyboardButton("📜 سجل التحويلات", callback_data="wallet:history")],
    ])
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

async def cb_wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    action = q.data.split(":", 1)[1]
    s = session_for(q.message.chat.id)
    if action == "topup":
        pkgs = api.get("/packages")
        if not pkgs:
            return await q.edit_message_text("لا توجد باقات شحن.")
        kb = [[InlineKeyboardButton(f"{p['name']} — {fmt_sar(p['amount'])}",
                                    callback_data=f"topup:{p['id']}")] for p in pkgs]
        await q.edit_message_text("اختر باقة شحن:", reply_markup=InlineKeyboardMarkup(kb))
    elif action == "transfer":
        ctx.user_data["awaiting"] = "transfer_email"
        await q.message.reply_text(
            "🔄 أرسل بريد المستلم الإلكتروني:", reply_markup=cancel_kb(),
        )
    elif action == "history":
        ts = api.get("/transfers") or []
        mine = [t for t in ts if t.get("fromEmail") == s.email or t.get("toEmail") == s.email]
        if not mine:
            return await q.edit_message_text("🚫 لا توجد تحويلات.")
        lines = ["📜 <b>سجل التحويلات</b>\n"]
        for t in mine[-15:]:
            arrow = "📤" if t["fromEmail"] == s.email else "📥"
            other = t["toEmail"] if t["fromEmail"] == s.email else t["fromEmail"]
            lines.append(f"{arrow} {fmt_sar(t['amount'])} — {other} — {t['date'][:10]}")
        await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML)

async def cb_topup_pick(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    pkg_id = q.data.split(":", 1)[1]
    pkgs = api.get("/packages")
    pkg = next((p for p in pkgs if p["id"] == pkg_id), None)
    if not pkg:
        return await q.edit_message_text("الباقة غير موجودة.")
    ctx.user_data["topup_pkg"] = pkg
    ctx.user_data["awaiting"] = "topup_receipt"
    await q.message.reply_text(
        f"📷 أرسل صورة إيصال التحويل لباقة <b>{pkg['name']}</b> — {fmt_sar(pkg['amount'])}\n"
        "(صورة فقط - سيراها المدير لمراجعة الطلب)",
        parse_mode=ParseMode.HTML, reply_markup=cancel_kb(),
    )

# ════════════════════════════════════════════════════════════════════════════
# حسابي
# ════════════════════════════════════════════════════════════════════════════

@require_login
async def my_account(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = session_for(update.effective_chat.id)
    txt = (
        f"👤 <b>حسابي</b>\n\n"
        f"الاسم: <b>{s.name}</b>\n"
        f"البريد: <code>{s.email}</code>\n"
        f"الرصيد: <b>{fmt_sar(s.wallet)}</b>\n"
        f"النوع: {'👑 مدير' if s.is_admin else '👤 مستخدم'}"
    )
    await update.message.reply_text(txt, parse_mode=ParseMode.HTML)

async def about(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = (
        "ℹ️ <b>المطيري للحجز</b>\n"
        "<i>تذكرتك بتجيك ذحين</i>\n\n"
        "نوفر تذاكر سريعة وآمنة عبر بوت تيليجرام،\n"
        "الموقع الإلكتروني، وتطبيق الجوّال.\n\n"
        "كل بياناتك متزامنة بين الثلاث منصات."
    )
    await update.message.reply_text(txt, parse_mode=ParseMode.HTML)

# ════════════════════════════════════════════════════════════════════════════
# الإعلانات
# ════════════════════════════════════════════════════════════════════════════

async def show_announcements(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    anns = api.get("/announcements") or []
    active = [a for a in anns if a.get("isActive")]
    if not active:
        return await update.message.reply_text("📢 لا توجد إعلانات حالياً.")
    lines = ["📢 <b>الإعلانات الحالية</b>\n"]
    for a in active:
        lines.append(f"▫️ {a['text']}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

# ════════════════════════════════════════════════════════════════════════════
# لوحة الإدارة
# ════════════════════════════════════════════════════════════════════════════

async def admin_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = session_for(update.effective_chat.id)
    if not s.is_admin:
        return await update.message.reply_text("🚫 غير مصرح. فقط للمدير.")
    await update.message.reply_text(
        "🛠️ <b>لوحة الإدارة</b>\nاختر القسم:",
        parse_mode=ParseMode.HTML, reply_markup=admin_keyboard(),
    )

async def cb_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    s = session_for(q.message.chat.id)
    if not s.is_admin:
        return await q.edit_message_text("🚫 غير مصرح.")
    section = q.data.split(":", 1)[1]

    if section == "stats":
        users = api.get("/users") or []
        tix = api.get("/tickets") or []
        topups = api.get("/topup-requests") or []
        cards = api.get("/card-payments") or []
        stcs = api.get("/stc-payments") or []
        anns = api.get("/announcements") or []
        total_wallet = sum(int(u.get("wallet") or 0) for u in users)
        pending = sum(1 for r in (topups + cards + stcs) if r.get("status") == "pending")
        txt = (
            "📊 <b>الإحصائيات</b>\n\n"
            f"👥 المستخدمون: <b>{len(users)}</b>\n"
            f"🎫 التذاكر: <b>{len(tix)}</b>\n"
            f"💰 إجمالي الأرصدة: <b>{fmt_sar(total_wallet)}</b>\n"
            f"⏳ طلبات معلقة: <b>{pending}</b>\n"
            f"📢 الإعلانات: <b>{len(anns)}</b>"
        )
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=admin_keyboard())

    elif section == "users":
        users = api.get("/users") or []
        lines = [f"👥 <b>المستخدمون ({len(users)})</b>\n"]
        for u in users[:30]:
            badge = "👑" if u.get("isAdmin") else ("🚫" if u.get("isBanned") else "👤")
            lines.append(f"{badge} {u['name']} — <code>{u['email']}</code> — {fmt_sar(u.get('wallet',0))}")
        await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=admin_keyboard())

    elif section == "packages":
        pkgs = api.get("/packages") or []
        lines = [f"🎟️ <b>الباقات ({len(pkgs)})</b>\n"]
        kb = []
        for p in pkgs:
            lines.append(f"▫️ {p['name']} — {fmt_sar(p['amount'])}")
            kb.append([InlineKeyboardButton(f"🗑️ حذف {p['name']}", callback_data=f"delpkg:{p['id']}")])
        kb.append([InlineKeyboardButton("➕ إضافة باقة جديدة", callback_data="addpkg:start")])
        kb.append([InlineKeyboardButton("⬅️ رجوع", callback_data="admin:back")])
        await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML,
                                  reply_markup=InlineKeyboardMarkup(kb))

    elif section == "tickets":
        tix = api.get("/tickets") or []
        lines = [f"🎫 <b>التذاكر ({len(tix)})</b>\n"]
        for t in tix[-20:]:
            lines.append(f"▫️ {t['eventName']} — {t['userName']} — {t['box']}")
        await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=admin_keyboard())

    elif section == "topups":
        rows = api.get("/topup-requests") or []
        await _render_requests(q, "💳 طلبات الشحن", rows, "topup")

    elif section == "cards":
        rows = api.get("/card-payments") or []
        await _render_requests(q, "💼 طلبات البطاقات", rows, "card")

    elif section == "stc":
        rows = api.get("/stc-payments") or []
        await _render_requests(q, "📱 طلبات STC", rows, "stc")

    elif section == "announcements":
        anns = api.get("/announcements") or []
        lines = [f"📢 <b>الإعلانات ({len(anns)})</b>\n"]
        kb = []
        for a in anns:
            mark = "✅" if a.get("isActive") else "⏸️"
            lines.append(f"{mark} {a['text'][:60]}")
            kb.append([
                InlineKeyboardButton(f"{'⏸️ تعطيل' if a.get('isActive') else '▶️ تفعيل'}",
                                     callback_data=f"toggleann:{a['id']}"),
                InlineKeyboardButton("🗑️ حذف", callback_data=f"delann:{a['id']}"),
            ])
        kb.append([InlineKeyboardButton("➕ إضافة إعلان", callback_data="addann:start")])
        kb.append([InlineKeyboardButton("⬅️ رجوع", callback_data="admin:back")])
        await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML,
                                  reply_markup=InlineKeyboardMarkup(kb))

    elif section == "notify":
        ctx.user_data["awaiting"] = "notify_email"
        await q.message.reply_text("🔔 أرسل بريد المستخدم لإرسال إشعار له:", reply_markup=cancel_kb())

    elif section == "back":
        await q.edit_message_text("🛠️ <b>لوحة الإدارة</b>", parse_mode=ParseMode.HTML,
                                  reply_markup=admin_keyboard())

async def _render_requests(q, title: str, rows: list, kind: str):
    if not rows:
        return await q.edit_message_text(f"{title}\n\n🚫 لا توجد طلبات.", reply_markup=admin_keyboard())
    lines = [f"<b>{title}</b> ({len(rows)})\n"]
    kb = []
    for r in rows[-15:]:
        st = r.get("status", "pending")
        emoji = {"pending":"⏳","approved":"✅","rejected":"❌","awaiting_code":"🔐","code_submitted":"🔓"}.get(st,"•")
        lines.append(f"{emoji} {r['userName']} — {fmt_sar(r['amount'])} — {r['packageName']}")
        if st == "pending":
            kb.append([
                InlineKeyboardButton(f"✅ قبول ({r['userName'][:10]})", callback_data=f"req:{kind}:approve:{r['id']}"),
                InlineKeyboardButton("❌ رفض", callback_data=f"req:{kind}:reject:{r['id']}"),
            ])
    kb.append([InlineKeyboardButton("⬅️ رجوع", callback_data="admin:back")])
    await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML,
                              reply_markup=InlineKeyboardMarkup(kb))

async def cb_request_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    s = session_for(q.message.chat.id)
    if not s.is_admin: return
    _, kind, action, rid = q.data.split(":", 3)
    path = {"topup": "/topup-requests", "card": "/card-payments", "stc": "/stc-payments"}[kind]
    new_status = "approved" if action == "approve" else "rejected"
    api.patch(f"{path}/{rid}", json={"status": new_status})
    # شحن المحفظة عند القبول لطلبات الشحن
    if action == "approve" and kind == "topup":
        rows = api.get("/topup-requests") or []
        r = next((x for x in rows if x["id"] == rid), None)
        if r:
            users = api.get("/users") or []
            u = next((x for x in users if x["email"] == r["userEmail"]), None)
            if u:
                api.patch(f"/users/{quote(u['email'])}",
                          json={"wallet": int(u.get("wallet") or 0) + int(r["amount"])})
    await q.answer("تم ✓", show_alert=False)
    await q.edit_message_text(f"✅ تم تحديث الطلب: {new_status}", reply_markup=admin_keyboard())

async def cb_delete_pkg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    s = session_for(q.message.chat.id)
    if not s.is_admin: return
    pid = q.data.split(":", 1)[1]
    api.delete(f"/packages/{pid}")
    await q.answer("تم الحذف ✓", show_alert=False)
    await q.edit_message_text("🗑️ تم حذف الباقة.", reply_markup=admin_keyboard())

async def cb_toggle_ann(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    s = session_for(q.message.chat.id)
    if not s.is_admin: return
    aid = q.data.split(":", 1)[1]
    anns = api.get("/announcements") or []
    a = next((x for x in anns if x["id"] == aid), None)
    if not a: return
    api.put(f"/admin/announcements/{aid}", json={"isActive": not a.get("isActive", True)})
    await q.answer("تم ✓", show_alert=False)
    await q.edit_message_text("تم تحديث الحالة.", reply_markup=admin_keyboard())

async def cb_delete_ann(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    s = session_for(q.message.chat.id)
    if not s.is_admin: return
    aid = q.data.split(":", 1)[1]
    api.delete(f"/admin/announcements/{aid}")
    await q.answer("تم الحذف ✓", show_alert=False)
    await q.edit_message_text("🗑️ تم حذف الإعلان.", reply_markup=admin_keyboard())

async def cb_add_pkg_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["awaiting"] = "addpkg_name"
    await q.message.reply_text("📛 اسم الباقة الجديدة:", reply_markup=cancel_kb())

async def cb_add_ann_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["awaiting"] = "addann_text"
    await q.message.reply_text("📝 نص الإعلان:", reply_markup=cancel_kb())

# ════════════════════════════════════════════════════════════════════════════
# معالج الرسائل النصية (التوجيه + الحوارات الحرة)
# ════════════════════════════════════════════════════════════════════════════

async def text_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    s = session_for(update.effective_chat.id)
    awaiting = ctx.user_data.get("awaiting")

    # إلغاء عام
    if txt == "❌ إلغاء":
        ctx.user_data.pop("awaiting", None)
        return await update.message.reply_text("تم الإلغاء.", reply_markup=main_keyboard(s) if s.email else login_keyboard())

    # مسارات حرة (لا تتبع ConversationHandler)
    if awaiting == "transfer_email":
        if not valid_email(txt):
            return await update.message.reply_text("❌ بريد غير صحيح. أعد المحاولة:")
        lookup = api.get(f"/users/lookup?email={quote(txt)}")
        if lookup.get("_error"):
            return await update.message.reply_text("❌ المستخدم غير موجود.")
        ctx.user_data["transfer_to"] = lookup["email"]
        ctx.user_data["awaiting"] = "transfer_amount"
        return await update.message.reply_text(f"💰 المبلغ بالريال للتحويل إلى {lookup['name']}:")

    if awaiting == "transfer_amount":
        try: amount = int(txt)
        except: return await update.message.reply_text("❌ رقم غير صحيح.")
        if amount <= 0 or amount > s.wallet:
            return await update.message.reply_text(f"❌ المبلغ غير صحيح. رصيدك: {fmt_sar(s.wallet)}")
        to_email = ctx.user_data.pop("transfer_to")
        ctx.user_data.pop("awaiting", None)
        api.patch(f"/users/{quote(s.email)}", json={"wallet": s.wallet - amount})
        users = api.get("/users") or []
        to_user = next((u for u in users if u["email"] == to_email), None)
        if to_user:
            api.patch(f"/users/{quote(to_email)}",
                      json={"wallet": int(to_user.get("wallet") or 0) + amount})
        api.post("/transfers", json={
            "fromEmail": s.email, "toEmail": to_email, "amount": amount,
            "date": datetime.utcnow().isoformat(), "type": "sent",
        })
        s.wallet -= amount
        return await update.message.reply_text(
            f"✅ تم تحويل {fmt_sar(amount)} بنجاح.\nرصيدك: {fmt_sar(s.wallet)}",
            reply_markup=main_keyboard(s),
        )

    if awaiting == "notify_email":
        if not valid_email(txt):
            return await update.message.reply_text("❌ بريد غير صحيح.")
        ctx.user_data["notify_to"] = txt
        ctx.user_data["awaiting"] = "notify_title"
        return await update.message.reply_text("📌 عنوان الإشعار:")
    if awaiting == "notify_title":
        ctx.user_data["notify_title"] = txt
        ctx.user_data["awaiting"] = "notify_body"
        return await update.message.reply_text("📝 نص الإشعار:")
    if awaiting == "notify_body":
        res = api.post("/admin/notify-user", json={
            "email": ctx.user_data.pop("notify_to"),
            "title": ctx.user_data.pop("notify_title"),
            "body": txt,
        })
        ctx.user_data.pop("awaiting", None)
        msg = res.get("message") or ("✅ تم الإرسال" if res.get("success") else "❌ فشل الإرسال")
        return await update.message.reply_text(msg, reply_markup=main_keyboard(s))

    if awaiting == "addpkg_name":
        ctx.user_data["addpkg_name"] = txt
        ctx.user_data["awaiting"] = "addpkg_amount"
        return await update.message.reply_text("💰 السعر بالريال:")
    if awaiting == "addpkg_amount":
        try: amt = int(txt)
        except: return await update.message.reply_text("❌ رقم غير صحيح.")
        ctx.user_data["addpkg_amount"] = amt
        ctx.user_data["awaiting"] = "addpkg_note"
        return await update.message.reply_text("📝 ملاحظة (أو أرسل - للتخطي):")
    if awaiting == "addpkg_note":
        note = "" if txt == "-" else txt
        api.post("/packages", json={
            "name": ctx.user_data.pop("addpkg_name"),
            "amount": ctx.user_data.pop("addpkg_amount"),
            "note": note, "paymentMethod": "link",
        })
        ctx.user_data.pop("awaiting", None)
        return await update.message.reply_text("✅ تم إنشاء الباقة.", reply_markup=main_keyboard(s))

    if awaiting == "addann_text":
        api.post("/admin/announcements", json={
            "text": txt, "textColor": "#ffffff", "bgColor": "#1B4FD8",
            "animationType": "marquee", "targetPage": "all",
        })
        ctx.user_data.pop("awaiting", None)
        return await update.message.reply_text("✅ تم نشر الإعلان.", reply_markup=main_keyboard(s))

    # توجيه القائمة الرئيسية
    routes = {
        "🎟️ الباقات":     show_packages,
        "📋 تذاكري":       my_tickets,
        "💰 محفظتي":       show_wallet,
        "📢 الإعلانات":    show_announcements,
        "👤 حسابي":        my_account,
        "ℹ️ حول":         about,
        "🛠️ لوحة الإدارة": admin_panel,
    }
    if txt in routes:
        return await routes[txt](update, ctx)
    if txt == "🚪 تسجيل خروج":
        return await cmd_logout(update, ctx)
    if txt == "🔐 تسجيل دخول":
        return await login_start(update, ctx)
    if txt == "✨ إنشاء حساب":
        return await reg_start(update, ctx)

    # افتراضي
    if s.email:
        await update.message.reply_text("اختر من القائمة:", reply_markup=main_keyboard(s))
    else:
        await update.message.reply_text(WELCOME, parse_mode=ParseMode.HTML, reply_markup=login_keyboard())

# معالج الصور (إيصال الشحن)
async def photo_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = session_for(update.effective_chat.id)
    if ctx.user_data.get("awaiting") != "topup_receipt":
        return
    pkg = ctx.user_data.pop("topup_pkg", None)
    ctx.user_data.pop("awaiting", None)
    if not pkg:
        return await update.message.reply_text("❌ خطأ: لم يتم تحديد الباقة.")
    photo = update.message.photo[-1]
    f = await ctx.bot.get_file(photo.file_id)
    receipt_url = f.file_path  # رابط مباشر للصورة من تيليجرام
    res = api.post("/topup-requests", json={
        "userEmail": s.email, "userName": s.name,
        "amount": pkg["amount"], "receiptImage": receipt_url,
        "date": datetime.utcnow().isoformat(),
        "status": "pending", "packageName": pkg["name"],
    })
    if res.get("_error"):
        return await update.message.reply_text("❌ فشل إرسال الطلب.")
    await update.message.reply_text(
        "✅ تم إرسال طلب الشحن بنجاح.\nسيتم مراجعته من المدير قريباً.",
        reply_markup=main_keyboard(s),
    )

async def cancel_conv(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = session_for(update.effective_chat.id)
    ctx.user_data.clear()
    await update.message.reply_text(
        "تم الإلغاء.",
        reply_markup=main_keyboard(s) if s.email else login_keyboard(),
    )
    return ConversationHandler.END

# ════════════════════════════════════════════════════════════════════════════
# نقطة التشغيل
# ════════════════════════════════════════════════════════════════════════════

def build_app() -> Application:
    if not BOT_TOKEN:
        raise SystemExit("❌ يرجى وضع توكن البوت في BOT_TOKEN داخل الملف.")
    app = Application.builder().token(BOT_TOKEN).build()

    # ConversationHandlers للدخول/التسجيل
    login_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^🔐 تسجيل دخول$"), login_start)],
        states={
            LOGIN_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_email)],
            LOGIN_PWD:   [MessageHandler(filters.TEXT & ~filters.COMMAND, login_pwd)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )
    reg_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^✨ إنشاء حساب$"), reg_start)],
        states={
            REG_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_name)],
            REG_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_email)],
            REG_PWD:   [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_pwd)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )

    # الأوامر
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("menu",   cmd_menu))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CommandHandler("logout", cmd_logout))

    # المحادثات
    app.add_handler(login_conv)
    app.add_handler(reg_conv)

    # أزرار الـ Inline
    app.add_handler(CallbackQueryHandler(cb_buy,             pattern=r"^buy:"))
    app.add_handler(CallbackQueryHandler(cb_wallet,          pattern=r"^wallet:"))
    app.add_handler(CallbackQueryHandler(cb_topup_pick,      pattern=r"^topup:"))
    app.add_handler(CallbackQueryHandler(cb_admin,           pattern=r"^admin:"))
    app.add_handler(CallbackQueryHandler(cb_request_action,  pattern=r"^req:"))
    app.add_handler(CallbackQueryHandler(cb_delete_pkg,      pattern=r"^delpkg:"))
    app.add_handler(CallbackQueryHandler(cb_toggle_ann,      pattern=r"^toggleann:"))
    app.add_handler(CallbackQueryHandler(cb_delete_ann,      pattern=r"^delann:"))
    app.add_handler(CallbackQueryHandler(cb_add_pkg_start,   pattern=r"^addpkg:start$"))
    app.add_handler(CallbackQueryHandler(cb_add_ann_start,   pattern=r"^addann:start$"))

    # الصور والنصوص
    app.add_handler(MessageHandler(filters.PHOTO, photo_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    return app

def main():
    app = build_app()
    logger.info("🤖 بوت المطيري للحجز يعمل الآن...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
