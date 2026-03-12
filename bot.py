"""
Physics Wallah Telegram Bot
Supports: Login via OTP, batch listing, content extraction to JSON,
          inline video URL resolution and a web player.
Deploy on Railway with a TELEGRAM_BOT_TOKEN env variable.
"""

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
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

from pw_api import PWApi

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Conversation states ──────────────────────────────────────────────────────
WAIT_MOBILE, WAIT_OTP = range(2)

# ── Globals ───────────────────────────────────────────────────────────────────
pw = PWApi()

# In-memory session store: {user_id: {"token": ..., "mobile": ..., "batches": [...]}}
sessions: dict = {}


# ═══════════════════════════════════════════════════════════════════════════════
# Helper utilities
# ═══════════════════════════════════════════════════════════════════════════════

def get_session(user_id: int) -> dict:
    return sessions.get(user_id, {})


def set_session(user_id: int, data: dict):
    sessions[user_id] = data


def fmt_duration(seconds: int) -> str:
    if not seconds:
        return "?"
    h, r = divmod(seconds, 3600)
    m, s = divmod(r, 60)
    if h:
        return f"{h}h {m}m"
    return f"{m}m {s}s"


async def safe_edit(query, text: str, reply_markup=None, parse_mode=ParseMode.MARKDOWN):
    try:
        await query.edit_message_text(
            text, reply_markup=reply_markup, parse_mode=parse_mode
        )
    except Exception:
        await query.message.reply_text(
            text, reply_markup=reply_markup, parse_mode=parse_mode
        )


# ═══════════════════════════════════════════════════════════════════════════════
# /start  and  /help
# ═══════════════════════════════════════════════════════════════════════════════

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    sess = get_session(user.id)

    if sess.get("token"):
        await update.message.reply_text(
            f"👋 Welcome back, *{sess.get('name', user.first_name)}*!\n\n"
            "Use /batches to list your enrolled courses, or /logout to switch accounts.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "🎓 *Physics Wallah Bot*\n\n"
        "Extract your PW batch content, get video URLs and download JSONs.\n\n"
        "Please enter your *10-digit mobile number* (India only) to continue:",
        parse_mode=ParseMode.MARKDOWN,
    )
    return WAIT_MOBILE


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Available Commands*\n\n"
        "/start — Login / Welcome\n"
        "/batches — List your enrolled batches\n"
        "/extract — Extract ALL batches to JSON file\n"
        "/logout — Clear your session\n"
        "/help — This message\n\n"
        "*Tip:* After selecting a batch you can browse subjects → topics → videos inline!",
        parse_mode=ParseMode.MARKDOWN,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Login flow
# ═══════════════════════════════════════════════════════════════════════════════

async def receive_mobile(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    mobile = update.message.text.strip().replace(" ", "").replace("-", "")
    if not mobile.isdigit() or len(mobile) != 10:
        await update.message.reply_text(
            "❌ Please send a valid *10-digit* Indian mobile number (e.g. `9876543210`).",
            parse_mode=ParseMode.MARKDOWN,
        )
        return WAIT_MOBILE

    ctx.user_data["mobile"] = mobile
    msg = await update.message.reply_text("⏳ Sending OTP...")

    resp = await pw.send_otp(mobile)
    if resp.get("success") or resp.get("status"):
        await msg.edit_text(
            f"✅ OTP sent to `+91 {mobile}`\n\nEnter the 4-digit OTP:",
            parse_mode=ParseMode.MARKDOWN,
        )
        return WAIT_OTP
    else:
        error = resp.get("message", "Unknown error")
        await msg.edit_text(f"❌ Failed to send OTP: {error}\n\nTry /start again.")
        return ConversationHandler.END


async def receive_otp(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    otp = update.message.text.strip()
    mobile = ctx.user_data.get("mobile", "")

    if not otp.isdigit() or len(otp) != 4:
        await update.message.reply_text("❌ OTP must be exactly 4 digits. Try again:")
        return WAIT_OTP

    msg = await update.message.reply_text("⏳ Verifying OTP...")
    resp = await pw.verify_otp(mobile, otp)

    token = (
        resp.get("data", {}).get("token")
        or resp.get("token")
    )
    user_info = resp.get("data", {}).get("user") or resp.get("user") or {}

    if not token:
        err = resp.get("message", "Invalid OTP or login failed.")
        await msg.edit_text(f"❌ {err}\n\nUse /start to try again.")
        return ConversationHandler.END

    name = (
        user_info.get("firstName", "")
        + " "
        + user_info.get("lastName", "")
    ).strip() or mobile

    set_session(
        update.effective_user.id,
        {
            "token": token,
            "mobile": mobile,
            "name": name,
        },
    )

    await msg.edit_text(
        f"✅ Login successful!\n\n"
        f"👤 Name: *{name}*\n"
        f"📱 Mobile: `{mobile}`\n\n"
        f"Use /batches to see your courses.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled. Use /start to begin again.")
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════════════════
# /logout
# ═══════════════════════════════════════════════════════════════════════════════

async def logout(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in sessions:
        del sessions[user_id]
    await update.message.reply_text("👋 Logged out. Use /start to log in again.")


# ═══════════════════════════════════════════════════════════════════════════════
# /batches — list enrolled batches with inline keyboard
# ═══════════════════════════════════════════════════════════════════════════════

async def batches_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    sess = get_session(update.effective_user.id)
    if not sess.get("token"):
        await update.message.reply_text("⚠️ You're not logged in. Use /start.")
        return

    msg = await update.message.reply_text("⏳ Fetching your batches...")
    token = sess["token"]

    try:
        batches = await pw.get_all_batches(token)
    except Exception as e:
        await msg.edit_text(f"❌ Error fetching batches: {e}")
        return

    if not batches:
        await msg.edit_text("🤔 No batches found in your account.")
        return

    # Cache batches
    sess["batches"] = batches
    set_session(update.effective_user.id, sess)

    keyboard = []
    for i, b in enumerate(batches):
        name = b.get("name", "Unknown")[:35]
        keyboard.append([InlineKeyboardButton(f"📦 {name}", callback_data=f"batch:{i}")])

    keyboard.append([InlineKeyboardButton("📥 Extract ALL to JSON", callback_data="extract_all")])

    await msg.edit_text(
        f"📚 *Your Batches* ({len(batches)} enrolled)\n\nTap a batch to browse or extract:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Callback: batch selected → show subjects
# ═══════════════════════════════════════════════════════════════════════════════

async def cb_batch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    sess = get_session(user_id)

    if not sess.get("token"):
        await query.edit_message_text("⚠️ Session expired. Use /start.")
        return

    batch_idx = int(query.data.split(":")[1])
    batch = sess.get("batches", [])[batch_idx]
    batch_name = batch.get("name", "Unknown")
    batch_id = batch.get("_id") or batch.get("id", "")

    await query.edit_message_text(f"⏳ Loading subjects for *{batch_name}*...", parse_mode=ParseMode.MARKDOWN)

    try:
        subjects = await pw.get_subjects(sess["token"], batch_id)
    except Exception as e:
        await query.edit_message_text(f"❌ {e}")
        return

    if not subjects:
        await query.edit_message_text(f"🤔 No subjects found in *{batch_name}*.", parse_mode=ParseMode.MARKDOWN)
        return

    # Cache subjects
    sess[f"subjects_{batch_idx}"] = subjects
    set_session(user_id, sess)

    keyboard = []
    for i, s in enumerate(subjects):
        name = s.get("subject", s.get("name", "Unknown"))[:35]
        keyboard.append([InlineKeyboardButton(f"📚 {name}", callback_data=f"subject:{batch_idx}:{i}")])

    keyboard += [
        [InlineKeyboardButton("📥 Extract this batch → JSON", callback_data=f"extract_batch:{batch_idx}")],
        [InlineKeyboardButton("🔙 Back to Batches", callback_data="back_batches")],
    ]

    await query.edit_message_text(
        f"📦 *{batch_name}*\n📚 Subjects ({len(subjects)}):",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Callback: subject selected → show topics
# ═══════════════════════════════════════════════════════════════════════════════

async def cb_subject(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    sess = get_session(user_id)

    _, batch_idx_s, subj_idx_s = query.data.split(":")
    batch_idx = int(batch_idx_s)
    subj_idx = int(subj_idx_s)

    batch = sess.get("batches", [])[batch_idx]
    batch_id = batch.get("_id") or batch.get("id", "")
    subjects = sess.get(f"subjects_{batch_idx}", [])
    subj = subjects[subj_idx]
    subj_name = subj.get("subject", subj.get("name", "Unknown"))
    subj_slug = subj.get("slug") or subj.get("_id", "")

    await query.edit_message_text(f"⏳ Loading topics for *{subj_name}*...", parse_mode=ParseMode.MARKDOWN)

    try:
        topics = await pw.get_all_topics(sess["token"], batch_id, subj_slug)
    except Exception as e:
        await query.edit_message_text(f"❌ {e}")
        return

    if not topics:
        await query.edit_message_text(f"🤔 No topics found in {subj_name}.")
        return

    sess[f"topics_{batch_idx}_{subj_idx}"] = topics
    set_session(user_id, sess)

    keyboard = []
    for i, t in enumerate(topics[:30]):  # Max 30 inline buttons
        name = t.get("name", "Unknown")[:35]
        keyboard.append([InlineKeyboardButton(
            f"📖 {name}", callback_data=f"topic:{batch_idx}:{subj_idx}:{i}"
        )])

    if len(topics) > 30:
        keyboard.append([InlineKeyboardButton(
            f"... and {len(topics) - 30} more topics", callback_data="noop"
        )])

    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data=f"batch:{batch_idx}")])

    await query.edit_message_text(
        f"📚 *{subj_name}* — Topics ({len(topics)}):",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Callback: topic selected → list videos with playable links
# ═══════════════════════════════════════════════════════════════════════════════

async def cb_topic(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    sess = get_session(user_id)

    parts = query.data.split(":")
    batch_idx, subj_idx, topic_idx = int(parts[1]), int(parts[2]), int(parts[3])

    batch = sess.get("batches", [])[batch_idx]
    batch_id = batch.get("_id") or batch.get("id", "")
    subjects = sess.get(f"subjects_{batch_idx}", [])
    subj = subjects[subj_idx]
    subj_slug = subj.get("slug") or subj.get("_id", "")
    topics = sess.get(f"topics_{batch_idx}_{subj_idx}", [])
    topic = topics[topic_idx]
    topic_name = topic.get("name", "Unknown")
    topic_slug = topic.get("slug") or topic.get("_id", "")

    await query.edit_message_text(f"⏳ Fetching videos for *{topic_name}*...", parse_mode=ParseMode.MARKDOWN)

    try:
        videos = await pw.get_topic_contents(
            sess["token"], batch_id, subj_slug, topic_slug, "videos"
        )
    except Exception as e:
        await query.edit_message_text(f"❌ {e}")
        return

    if not videos:
        await query.edit_message_text(
            f"🤔 No videos in *{topic_name}*.\n\n"
            "This topic might have notes or DPPs only.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back", callback_data=f"subject:{batch_idx}:{subj_idx}")
            ]]),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Build message with video list
    lines = [f"🎬 *{topic_name}* — {len(videos)} video(s)\n"]
    keyboard = []

    for i, v in enumerate(videos[:15]):
        title = v.get("topic") or v.get("name", f"Video {i+1}")
        vd = v.get("videoDetails") or {}
        dur = fmt_duration(vd.get("duration", 0))
        lines.append(f"{i+1}. {title} `[{dur}]`")
        keyboard.append([InlineKeyboardButton(
            f"▶️ Play #{i+1}: {title[:25]}",
            callback_data=f"play:{batch_idx}:{subj_idx}:{topic_idx}:{i}"
        )])

    if len(videos) > 15:
        lines.append(f"\n_... and {len(videos)-15} more_")

    sess[f"videos_{batch_idx}_{subj_idx}_{topic_idx}"] = videos
    set_session(user_id, sess)

    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data=f"subject:{batch_idx}:{subj_idx}")])

    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Callback: play video → resolve URL
# ═══════════════════════════════════════════════════════════════════════════════

async def cb_play(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("⏳ Resolving video URL...")
    user_id = update.effective_user.id
    sess = get_session(user_id)

    parts = query.data.split(":")
    batch_idx, subj_idx, topic_idx, vid_idx = (
        int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])
    )

    videos = sess.get(f"videos_{batch_idx}_{subj_idx}_{topic_idx}", [])
    if vid_idx >= len(videos):
        await query.answer("Video not found in cache.", show_alert=True)
        return

    video = videos[vid_idx]
    title = video.get("topic") or video.get("name", "Untitled")
    token = sess["token"]

    url = await pw.resolve_video_url(token, video)

    vd = video.get("videoDetails") or {}
    bc_id = vd.get("bcVideoId", "")
    yt_id = vd.get("ytId", "")
    dur = fmt_duration(vd.get("duration", 0))

    if url:
        msg = (
            f"🎬 *{title}*\n"
            f"⏱ Duration: `{dur}`\n\n"
            f"▶️ [Open / Stream]({url})\n\n"
        )
        if "youtube" in url:
            msg += "_Tap to watch on YouTube._"
        else:
            msg += "_Copy link → open in VLC / MX Player for best experience._\n"
            msg += f"`{url}`"
    else:
        # Provide raw IDs for manual lookup
        msg = (
            f"🎬 *{title}*\n"
            f"⏱ Duration: `{dur}`\n\n"
            "⚠️ Could not auto-resolve stream URL.\n\n"
        )
        if bc_id:
            msg += f"🔑 Brightcove ID: `{bc_id}`\n"
        if yt_id:
            msg += f"▶️ YouTube ID: `{yt_id}`\n"
        if not bc_id and not yt_id:
            msg += "_No video source metadata found for this item._"

    keyboard = [[InlineKeyboardButton(
        "🔙 Back to topic",
        callback_data=f"topic:{batch_idx}:{subj_idx}:{topic_idx}"
    )]]

    await query.edit_message_text(
        msg,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=False,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Extraction to JSON (single batch or all batches)
# ═══════════════════════════════════════════════════════════════════════════════

async def extract_all_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /extract command — full extraction of all batches."""
    user_id = update.effective_user.id
    sess = get_session(user_id)
    if not sess.get("token"):
        await update.message.reply_text("⚠️ Not logged in. Use /start.")
        return

    msg = await update.message.reply_text("⏳ Fetching batch list...")
    batches = await pw.get_all_batches(sess["token"])
    if not batches:
        await msg.edit_text("🤔 No batches found.")
        return

    keyboard = []
    for i, b in enumerate(batches):
        name = b.get("name", "Unknown")[:35]
        keyboard.append([InlineKeyboardButton(f"📦 {name}", callback_data=f"extract_batch:{i}")])
    keyboard.append([InlineKeyboardButton("🌐 Extract ALL batches", callback_data="extract_all")])

    sess["batches"] = batches
    set_session(user_id, sess)

    await msg.edit_text(
        "Choose what to extract:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cb_extract_batch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    sess = get_session(user_id)
    token = sess.get("token")

    if not token:
        await query.edit_message_text("⚠️ Session expired. Use /start.")
        return

    batch_idx = int(query.data.split(":")[1])
    batch = sess.get("batches", [])[batch_idx]
    batch_name = batch.get("name", "Unknown Batch")

    status_msg = await query.edit_message_text(
        f"⏳ Extracting *{batch_name}*...\nThis may take a few minutes.",
        parse_mode=ParseMode.MARKDOWN,
    )

    async def progress(text: str):
        try:
            await status_msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass

    try:
        data = await pw.extract_batch_json(token, batch, progress_cb=progress)
    except Exception as e:
        await status_msg.edit_text(f"❌ Extraction failed: {e}")
        return

    # Write JSON to temp file and send
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        prefix=f"pw_{batch_name[:15]}_",
        delete=False,
    ) as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        tmppath = f.name

    total_videos = sum(
        len(t.get("videos", []))
        for s in data.get("subjects", [])
        for t in s.get("topics", [])
    )

    await status_msg.edit_text(
        f"✅ *{batch_name}* extracted!\n"
        f"📚 Subjects: {len(data.get('subjects', []))}\n"
        f"🎬 Total videos: {total_videos}\n\n"
        "_Sending JSON file..._",
        parse_mode=ParseMode.MARKDOWN,
    )

    with open(tmppath, "rb") as f:
        await query.message.reply_document(
            document=f,
            filename=f"pw_{batch_name[:30]}.json",
            caption=f"📦 *{batch_name}* — Full content JSON",
            parse_mode=ParseMode.MARKDOWN,
        )

    Path(tmppath).unlink(missing_ok=True)


async def cb_extract_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    sess = get_session(user_id)
    token = sess.get("token")

    if not token:
        await query.edit_message_text("⚠️ Session expired. Use /start.")
        return

    batches = sess.get("batches")
    if not batches:
        batches = await pw.get_all_batches(token)
        sess["batches"] = batches
        set_session(user_id, sess)

    status_msg = await query.edit_message_text(
        f"⏳ Extracting *all {len(batches)} batches*...\n_This will take a while!_",
        parse_mode=ParseMode.MARKDOWN,
    )

    all_data = []
    for i, batch in enumerate(batches):
        bname = batch.get("name", "Unknown")

        async def progress(text: str, bn=bname, idx=i):
            try:
                await status_msg.edit_text(
                    f"📥 Batch {idx+1}/{len(batches)}: *{bn}*\n{text}",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass

        try:
            data = await pw.extract_batch_json(token, batch, progress_cb=progress)
            all_data.append(data)
        except Exception as e:
            logger.warning(f"Skipping batch {bname}: {e}")
            continue
        await asyncio.sleep(1)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix="pw_all_batches_", delete=False
    ) as f:
        json.dump(all_data, f, indent=2, ensure_ascii=False)
        tmppath = f.name

    total_videos = sum(
        len(t.get("videos", []))
        for b in all_data
        for s in b.get("subjects", [])
        for t in s.get("topics", [])
    )

    await status_msg.edit_text(
        f"✅ All {len(all_data)} batches extracted!\n"
        f"🎬 Total videos indexed: {total_videos}\n\n"
        "_Sending JSON..._",
        parse_mode=ParseMode.MARKDOWN,
    )

    with open(tmppath, "rb") as f:
        await query.message.reply_document(
            document=f,
            filename="pw_all_batches.json",
            caption="📦 *All PW Batches* — Full content JSON",
            parse_mode=ParseMode.MARKDOWN,
        )

    Path(tmppath).unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Back navigation
# ═══════════════════════════════════════════════════════════════════════════════

async def cb_back_batches(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    sess = get_session(user_id)

    batches = sess.get("batches", [])
    if not batches:
        await query.edit_message_text("No batches cached. Use /batches.")
        return

    keyboard = []
    for i, b in enumerate(batches):
        name = b.get("name", "Unknown")[:35]
        keyboard.append([InlineKeyboardButton(f"📦 {name}", callback_data=f"batch:{i}")])
    keyboard.append([InlineKeyboardButton("📥 Extract ALL to JSON", callback_data="extract_all")])

    await query.edit_message_text(
        f"📚 *Your Batches* ({len(batches)} enrolled):",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN,
    )


async def cb_noop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("This is informational only.", show_alert=False)


# ═══════════════════════════════════════════════════════════════════════════════
# App bootstrap
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set!")

    app = Application.builder().token(token).build()

    # Login conversation
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAIT_MOBILE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_mobile)],
            WAIT_OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_otp)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("batches", batches_cmd))
    app.add_handler(CommandHandler("extract", extract_all_cmd))
    app.add_handler(CommandHandler("logout", logout))

    # Inline keyboard callbacks
    app.add_handler(CallbackQueryHandler(cb_batch, pattern=r"^batch:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_subject, pattern=r"^subject:\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_topic, pattern=r"^topic:\d+:\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_play, pattern=r"^play:\d+:\d+:\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_extract_batch, pattern=r"^extract_batch:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_extract_all, pattern=r"^extract_all$"))
    app.add_handler(CallbackQueryHandler(cb_back_batches, pattern=r"^back_batches$"))
    app.add_handler(CallbackQueryHandler(cb_noop, pattern=r"^noop$"))

    logger.info("🤖 PW Bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
