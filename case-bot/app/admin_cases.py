"""Bot orqali case qo'shish va e'lon tarqatish (faqat admin).

/newcase  → 1) rasm  2) nom  3) post matni (title)  4) skinlar  5) oldindan ko'rish → Qo'shish / Qo'shish va e'lon
/cases    — barcha case'lar          /delcase ID — o'chirish/yashirish     /showcase ID — qaytarish
/addskin kalit | Nomi | rarity | qiymat — yangi skin turi
/announce ID — case e'lonini qayta yuborish
/broadcast — biror xabarga javob (reply) qilib yozing: shu xabar hammaga «Ochish» tugmasi bilan yuboriladi
/cancel   — joriy amalni bekor qilish
"""
import asyncio
import html
import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.error import Forbidden, BadRequest, RetryAfter
from telegram.ext import (ApplicationHandlerStop, CallbackQueryHandler, CommandHandler, ContextTypes,
                          MessageHandler, filters)

from app import catalog, media, store
from app import database as dbm
from app.config import app_url

logger = logging.getLogger(__name__)
_is_admin = None          # bot.py dan beriladi
_bcast_lock = asyncio.Lock()
_TRANSLIT = str.maketrans({"ʻ": "", "'": "", "’": "", "ʼ": "", "`": ""})
_CYR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюяқғҳў",
                ["a", "b", "v", "g", "d", "e", "yo", "j", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s",
                 "t", "u", "f", "x", "ts", "ch", "sh", "sh", "", "i", "", "e", "yu", "ya", "q", "g", "h", "o"]))


def _esc(t) -> str:
    return html.escape(str(t), quote=False)


def slugify(name: str, taken: set[str]) -> str:
    t = "".join(_CYR.get(ch, ch) for ch in name.lower().translate(_TRANSLIT))
    t = re.sub(r"[^a-z0-9]+", "_", t).strip("_")[:24] or "case"
    base, i = t, 2
    while t in taken:
        t = f"{base}_{i}"
        i += 1
    return t


def open_kb(case_id: str | None = None, text: str = "🎁 Case ochish") -> InlineKeyboardMarkup:
    url = app_url(case_id)
    return InlineKeyboardMarkup([[InlineKeyboardButton(text, web_app=WebAppInfo(url=url))]])


def parse_items(text: str) -> tuple[list[tuple[str, int]], list[str]]:
    """«kalit og'irlik» qatorlari → [(kalit, og'irlik)], xatolar."""
    items, errs = [], []
    for line in (text or "").splitlines():
        line = line.strip().strip(",;")
        if not line:
            continue
        m = re.match(r"^(.+?)[\s:=\-–—]+(\d+(?:[.,]\d+)?)\s*%?$", line)
        if not m:
            errs.append(f"«{line}» — format: kalit og'irlik")
            continue
        key = m.group(1).strip()
        key = key.lower() if key.lower() in catalog.SKINS else (catalog.key_by_name(key) or key.lower())
        w = float(m.group(2).replace(",", "."))
        if key not in catalog.SKINS:
            errs.append(f"noma'lum skin: {key}")
        elif w <= 0:
            errs.append(f"{key}: og'irlik 0 dan katta bo'lsin")
        else:
            items.append((key, int(round(w * 100)) if w != int(w) else int(w)))
    return items, errs


def summary(c: dict) -> str:
    p = catalog.prepare_case(c)
    lines = [f"<b>{_esc(c['name'])}</b>  ·  id: <code>{c['id']}</code>",
             f"Narx: <b>{p['price']} ⭐</b>  ·  o'rtacha yutuq {p['avg_value']} ⭐  ·  RTP {p['rtp']}%", ""]
    for it in p["items"]:
        lines.append(f"{it['chance']:>7.3f}%  {_esc(it['name'])} — {it['value']} ⭐")
    return "\n".join(lines)


def _plain(html_text: str | None) -> str | None:
    if not html_text:
        return None
    t = re.sub(r"<[^>]+>", "", html_text)
    t = html.unescape(re.sub(r"\s+", " ", t)).strip()
    return t[:140] or None


# ── /newcase dialogi ──────────────────────────────────────────────────

async def cmd_newcase(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    ctx.user_data["nc"] = {"step": "photo"}
    await update.message.reply_text(
        "🆕 <b>Yangi case</b> — 1/4\n\nCase rasmini yuboring (rasm yoki fayl).\n"
        "Bekor qilish: /cancel", parse_mode="HTML")


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    had = ctx.user_data.pop("nc", None)
    await update.message.reply_text("❌ Bekor qilindi." if had else "Bekor qiladigan amal yo'q.")


def _skins_hint() -> str:
    by_r = {}
    for k, (n, r, v) in catalog.SKINS.items():
        by_r.setdefault(r, []).append(f"<code>{k}</code> {v}⭐")
    order = list(catalog.RARITIES)
    return "\n".join(f"<b>{catalog.RARITIES[r]['label']}:</b> " + ", ".join(by_r[r]) for r in order if r in by_r)


async def wizard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin /newcase jarayonida bo'lsa — xabarlarni shu yerda qabul qilamiz."""
    nc = ctx.user_data.get("nc")
    if not nc or not _is_admin(update) or not update.message:
        return
    msg, step = update.message, nc["step"]

    if step == "photo":
        f = msg.photo[-1] if msg.photo else (msg.document if msg.document and
                                            (msg.document.mime_type or "").startswith("image/") else None)
        if not f:
            await msg.reply_text("Rasm yuboring (yoki /cancel).")
            raise ApplicationHandlerStop
        data = bytes(await (await f.get_file()).download_as_bytearray())
        try:
            nc["img"], _ = await asyncio.to_thread(media.normalize_image, data, "case_tmp")
        except ValueError:
            await msg.reply_text("Bu rasmni o'qib bo'lmadi. Boshqa rasm yuboring.")
            raise ApplicationHandlerStop
        nc["raw"] = data
        nc["step"] = "name"
        await msg.reply_text("✅ Rasm olindi. 2/4\n\nCase <b>nomini</b> yozing (masalan: <i>Rush Drop</i>):",
                             parse_mode="HTML")

    elif step == "name":
        name = (msg.text or "").strip()
        if not name or len(name) > 40 or name.startswith("/"):
            await msg.reply_text("Nom 1–40 belgi bo'lsin.")
            raise ApplicationHandlerStop
        taken = {c["id"] for c in catalog.BUILTIN_CASES} | await asyncio.to_thread(dbm.custom_case_ids)
        nc.update(name=name, id=slugify(name, taken), step="title")
        await msg.reply_text(
            "3/4 — <b>Post matni (title)</b>.\n\nO'yinchilarga yuboriladigan e'lon matnini yozing. "
            "Qalin, kursiv, emoji — hammasi saqlanadi (SKINOZ postidagidek).\n\n"
            "E'lonsiz qo'shish uchun: /skip", parse_mode="HTML")

    elif step == "title":
        if (msg.text or "").strip() == "/skip":
            nc["title_html"] = None
        else:
            t = msg.text_html if msg.text else None
            if not t:
                await msg.reply_text("Matn yozing yoki /skip.")
                raise ApplicationHandlerStop
            if len(msg.text) > 900:
                await msg.reply_text(f"Matn {len(msg.text)} belgi — rasm ostiga ko'pi bilan 900 belgi sig'adi. Qisqartiring.")
                raise ApplicationHandlerStop
            nc["title_html"] = t
        nc["step"] = "items"
        await msg.reply_text(
            "4/4 — <b>Case ichidagi skinlar</b>.\n\nHar qatorga: <code>kalit og'irlik</code>\n"
            "Og'irlik qancha katta — shuncha ko'p tushadi. Masalan:\n"
            "<code>glock 4000\ndeagle 1500\nawp_asi 300\nawp_dl 5</code>\n\n"
            "Narx avtomatik hisoblanadi (RTP 90%).\n\n" + _skins_hint() +
            "\n\nYangi skin turi kerak bo'lsa: /addskin", parse_mode="HTML")

    elif step == "items":
        items, errs = parse_items(msg.text or "")
        c = {"id": nc["id"], "name": nc["name"], "items": items}
        errs += catalog.check_case(c) if items else (["hech bo'lmasa 1 ta skin yozing"] if not errs else [])
        if errs:
            await msg.reply_text("❌ Xato:\n" + "\n".join("• " + _esc(e) for e in errs[:10]) + "\n\nQaytadan yuboring.",
                                 parse_mode="HTML")
            raise ApplicationHandlerStop
        nc["items"], nc["step"] = items, "confirm"
        # Postni aynan o'yinchilar ko'radigandek ko'rsatamiz
        caption = nc["title_html"] or f"🆕 <b>{_esc(nc['name'])}</b> — yangi case!"
        sent = await msg.reply_photo(nc["raw"], caption=caption, parse_mode="HTML", reply_markup=open_kb(nc["id"]))
        nc["file_id"] = sent.photo[-1].file_id
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Qo'shish", callback_data="nc:add")],
            [InlineKeyboardButton("📢 Qo'shish va hammaga yuborish", callback_data="nc:post")],
            [InlineKeyboardButton("❌ Bekor qilish", callback_data="nc:cancel")]])
        await msg.reply_text("👆 E'lon shunday ko'rinadi.\n\n" + summary(c), parse_mode="HTML", reply_markup=kb)
    raise ApplicationHandlerStop


async def on_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from app.images import forget
    q = update.callback_query
    if not _is_admin(update):
        await q.answer()
        return
    nc = ctx.user_data.get("nc")
    action = q.data.split(":", 1)[1]
    if not nc or nc.get("step") != "confirm":
        await q.answer("Bu case allaqachon ko'rib chiqilgan.")
        return
    if action == "cancel":
        ctx.user_data.pop("nc", None)
        await q.answer("Bekor qilindi")
        await q.edit_message_reply_markup(None)
        await q.message.reply_text("❌ Case qo'shilmadi.")
        return
    c = {"id": nc["id"], "name": nc["name"], "badge": "Yangi", "descr": _plain(nc.get("title_html")),
         "title_html": nc.get("title_html"), "items": nc["items"], "post_file_id": nc.get("file_id")}
    try:
        await asyncio.to_thread(dbm.save_custom_case, c)
        await asyncio.to_thread(dbm.save_skin_image, "case_" + c["id"], nc["img"], "image/webp")
        await asyncio.to_thread(store.reload)
        forget("case_" + c["id"])
    except Exception:
        logger.exception("Case saqlanmadi")
        await q.answer("Xato! Qayta urinib ko'ring.", show_alert=True)
        return
    ctx.user_data.pop("nc", None)
    await q.answer("Qo'shildi!")
    await q.edit_message_reply_markup(None)
    price = catalog.CASE_BY_ID[c["id"]]["price"]
    await q.message.reply_text(f"✅ <b>{_esc(c['name'])}</b> ilovaga qo'shildi ({price} ⭐).\n"
                               "O'yinchilar ilovani qayta ochganda ko'radi.", parse_mode="HTML")
    if action == "post":
        await start_broadcast(ctx, q.message.chat_id, "case", c)


# ── E'lon tarqatish ──────────────────────────────────────────────────

async def start_broadcast(ctx, admin_chat: int, kind: str, payload) -> None:
    if _bcast_lock.locked():
        await ctx.bot.send_message(admin_chat, "⏳ Oldingi e'lon hali yuborilmoqda. Tugashini kuting.")
        return
    ctx.application.create_task(_broadcast(ctx.bot, admin_chat, kind, payload))


async def _broadcast(bot, admin_chat: int, kind: str, payload) -> None:
    async with _bcast_lock:
        ids = await asyncio.to_thread(dbm.all_user_ids)
        status = await bot.send_message(admin_chat, f"📢 E'lon yuborilmoqda: 0 / {len(ids)}")
        ok = blocked = failed = 0

        async def send(uid: int):
            if kind == "case":
                c = payload
                cap = c.get("title_html") or f"🆕 <b>{_esc(c['name'])}</b> — yangi case!"
                await bot.send_photo(uid, c["post_file_id"], caption=cap, parse_mode="HTML",
                                     reply_markup=open_kb(c["id"]))
            elif kind == "text":                          # AI tayyorlagan e'lon (HTML matn)
                await bot.send_message(uid, payload, parse_mode="HTML", reply_markup=open_kb(None, "🎮 O'ynash"),
                                       disable_web_page_preview=True)
            else:
                src_chat, msg_id = payload
                await bot.copy_message(uid, src_chat, msg_id, reply_markup=open_kb(None, "🎮 Ochish"))

        for i, uid in enumerate(ids, 1):
            for attempt in range(3):
                try:
                    await send(uid)
                    ok += 1
                    break
                except RetryAfter as e:
                    await asyncio.sleep(float(getattr(e, "retry_after", 3)) + 0.5)
                except Forbidden:
                    blocked += 1
                    break
                except BadRequest:
                    failed += 1
                    break
                except Exception:
                    if attempt == 2:
                        failed += 1
                    await asyncio.sleep(1)
            await asyncio.sleep(0.045)                       # ~22 xabar/soniya — Telegram limitidan past
            if i % 200 == 0:
                try:
                    await status.edit_text(f"📢 E'lon yuborilmoqda: {i} / {len(ids)}")
                except Exception:
                    pass
        await status.edit_text(f"✅ E'lon tugadi.\nYetkazildi: <b>{ok}</b>\nBotni bloklagan: {blocked}\n"
                               f"Xato: {failed}", parse_mode="HTML")


async def cmd_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    src = update.message.reply_to_message
    if not src:
        await update.message.reply_text(
            "Yubormoqchi bo'lgan xabaringizga (rasm, matn, video — farqi yo'q) <b>reply</b> qilib /broadcast yozing.\n"
            "Xabar hammaga «🎮 Ochish» tugmasi bilan yuboriladi.", parse_mode="HTML")
        return
    await start_broadcast(ctx, update.effective_chat.id, "copy", (src.chat_id, src.message_id))


async def cmd_announce(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    cid = (ctx.args or [""])[0].strip().lower()
    c = await asyncio.to_thread(dbm.get_custom_case, cid) if cid else None
    if not c or not c.get("post_file_id"):
        await update.message.reply_text("Format: /announce ID  (faqat bot orqali qo'shilgan case'lar uchun). Ro'yxat: /cases")
        return
    await start_broadcast(ctx, update.effective_chat.id, "case", c)


# ── Boshqarish ────────────────────────────────────────────────────────

async def cmd_cases(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    _, custom, hidden = await asyncio.to_thread(dbm.catalog_rows)
    custom_ids = {c["id"] for c in custom}
    lines = ["<b>Case'lar</b> (ilovadagi tartibda)\n"]
    for c in catalog.CASE_LIST:
        src = "🤖 bot" if c["id"] in custom_ids else "📄 kod"
        lines.append(f"• <code>{c['id']}</code> — {_esc(c['name'])} · {c['price']} ⭐ · {src}")
    if hidden:
        lines.append("\n<b>Yashirilgan:</b> " + ", ".join(f"<code>{h}</code>" for h in sorted(hidden)))
    lines.append("\nYangi: /newcase · O'chirish: /delcase ID · Qaytarish: /showcase ID · E'lon: /announce ID")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_delcase(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    cid = (ctx.args or [""])[0].strip().lower()
    if cid not in catalog.CASE_BY_ID:
        await update.message.reply_text("Format: /delcase ID   (ro'yxat: /cases)")
        return
    builtin = cid in {c["id"] for c in catalog.BUILTIN_CASES}
    await asyncio.to_thread(dbm.hide_case, cid, builtin)
    await asyncio.to_thread(store.reload)
    await update.message.reply_text(("🙈 Yashirildi" if builtin else "🗑 O'chirildi") + f": {cid}\n"
                                    "O'yinchilarning inventaridagi skinlar joyida qoladi."
                                    + (f"\nQaytarish: /showcase {cid}" if builtin else ""))


async def cmd_showcase(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    cid = (ctx.args or [""])[0].strip().lower()
    await asyncio.to_thread(dbm.unhide_case, cid)
    await asyncio.to_thread(store.reload)
    await update.message.reply_text(f"👁 Qaytarildi: {cid}" if cid in catalog.CASE_BY_ID else "Bunday yashirilgan case yo'q.")


async def cmd_addskin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    raw = (update.message.text or "").split(maxsplit=1)
    parts = [p.strip() for p in (raw[1] if len(raw) > 1 else "").split("|")]
    rar = ", ".join(f"<code>{r}</code>" for r in catalog.RARITIES)
    if len(parts) == 5:                                        # kalit | Qurol | Skin | rarity | qiymat
        parts = [parts[0], f"{parts[1]} | {parts[2]}", parts[3], parts[4]]
    if len(parts) != 4:
        await update.message.reply_text(
            "Format:\n<code>/addskin kalit | Qurol | Skin nomi | rarity | qiymat</code>\n\n"
            "Masalan:\n<code>/addskin usp_kill | USP-S | Kill Confirmed | covert | 1500</code>\n\n"
            f"Rarity: {rar}\nQiymat — Stars'da (sotilganda shuncha qaytadi).", parse_mode="HTML")
        return
    key, name, rarity, value = parts
    key = key.lower()
    if not re.fullmatch(r"[a-z0-9_]{2,40}", key) or key.startswith(("case_", "game_", "snd_")):
        await update.message.reply_text("Kalit: kichik lotin harf, raqam va _ (2–40 belgi).")
        return
    if rarity not in catalog.RARITIES:
        await update.message.reply_text(f"Rarity quyidagilardan biri: {rar}", parse_mode="HTML")
        return
    if not value.isdigit() or int(value) <= 0:
        await update.message.reply_text("Qiymat musbat butun son (Stars) bo'lsin.")
        return
    if key in catalog.BUILTIN_SKINS:
        await update.message.reply_text("Bu kalit koddagi skin — boshqa kalit tanlang.")
        return
    await asyncio.to_thread(dbm.save_custom_skin, key, name, rarity, int(value))
    await asyncio.to_thread(store.reload)
    await update.message.reply_text(
        f"✅ Skin qo'shildi: <code>{key}</code> — {_esc(name)} · {catalog.RARITIES[rarity]['label']} · {value} ⭐\n"
        f"Rasmini yuklang: rasm yuborib izohiga <code>{key}</code> deb yozing.", parse_mode="HTML")


def register(application, is_admin) -> None:
    global _is_admin
    _is_admin = is_admin
    application.add_handler(CommandHandler("newcase", cmd_newcase))
    application.add_handler(CommandHandler("cancel", cmd_cancel))
    application.add_handler(CommandHandler("cases", cmd_cases))
    application.add_handler(CommandHandler("delcase", cmd_delcase))
    application.add_handler(CommandHandler("showcase", cmd_showcase))
    application.add_handler(CommandHandler("addskin", cmd_addskin))
    application.add_handler(CommandHandler("announce", cmd_announce))
    application.add_handler(CommandHandler("broadcast", cmd_broadcast))
    application.add_handler(CallbackQueryHandler(on_confirm, pattern=r"^nc:"))
    # Dialog boshqa handlerlardan oldin ishlaydi (rasm kalit-izohli yuklashdan ustun)
    application.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & (filters.PHOTO | filters.Document.IMAGE | filters.TEXT) &
        ~filters.COMMAND | filters.Regex(r"^/skip$"), wizard), group=-1)
