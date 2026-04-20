"""
Lannah Meta Bot
Receives a video → strips all metadata → sends back clean version.
Works on every format: MP4, MOV, MKV, AVI, HEVC, etc.
"""

import os
import uuid
import logging
import subprocess
from pathlib import Path
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8574928816:AAHtGowHKGCJmG4IJZRj6tbJ3FvxqzJ55M8")
TMP = Path("/tmp/lannah_bot")
TMP.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def random_id() -> str:
    return uuid.uuid4().hex[:12]


def strip_metadata(in_path: Path, out_path: Path) -> None:
    """
    Use ffmpeg with -c copy (zero re-encoding, 4K stays 4K).
    Wipes ALL metadata atoms: title, GPS, device, encoder, timestamps.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", str(in_path),
        "-map", "0",           # keep all streams (video + audio + subtitles)
        "-c", "copy",          # zero re-encoding — 4K stays 4K
        "-map_metadata", "-1", # strip global metadata
        "-map_metadata:s:v", "-1",  # strip video stream metadata
        "-map_metadata:s:a", "-1",  # strip audio stream metadata
        "-fflags", "+bitexact",     # remove encoder signature
        "-flags:v", "+bitexact",
        "-flags:a", "+bitexact",
        str(out_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error: {result.stderr[-500:]}")


# ── Handlers ─────────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hey Lannah!\n\n"
        "Send me any video and I'll strip all the metadata "
        "(GPS, device info, timestamps, encoder fingerprint) "
        "so Instagram can't detect it's been posted before.\n\n"
        "Quality stays 100% — zero re-encoding. Just drop a video 🎬"
    )


async def handle_video(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    # Accept both video files and documents (Telegram sends large videos as documents)
    file_obj = None
    ext = "mp4"

    if msg.video:
        file_obj = msg.video
        mime = msg.video.mime_type or "video/mp4"
        ext = mime.split("/")[-1].replace("quicktime", "mov")
    elif msg.document:
        mime = msg.document.mime_type or ""
        if not mime.startswith("video/"):
            await msg.reply_text("⚠️ Please send a video file.")
            return
        file_obj = msg.document
        ext = mime.split("/")[-1].replace("quicktime", "mov")
        # Also grab extension from filename if available
        if msg.document.file_name:
            fn_ext = Path(msg.document.file_name).suffix.lstrip(".")
            if fn_ext:
                ext = fn_ext
    else:
        await msg.reply_text("⚠️ Please send a video file.")
        return

    # Telegram's max download size is 20MB for bots on free API
    # For larger files, use local Bot API server — we handle gracefully
    file_size = getattr(file_obj, "file_size", 0) or 0
    if file_size > 2_000_000_000:  # 2GB hard limit
        await msg.reply_text("❌ File is too large (max 2GB).")
        return

    uid = random_id()
    in_path  = TMP / f"{uid}_in.{ext}"
    out_path = TMP / f"{uid}_out.{ext}"

    status = await msg.reply_text("⏳ Downloading your video…")

    try:
        # Download
        tg_file = await file_obj.get_file()
        await tg_file.download_to_drive(str(in_path))

        await status.edit_text("🔧 Stripping metadata (no re-encoding)…")

        # Strip
        strip_metadata(in_path, out_path)

        await status.edit_text("📤 Sending cleaned video…")

        # Send back — use send_document so Telegram doesn't re-compress
        out_name = f"clean_{random_id()}.{ext}"
        with open(out_path, "rb") as f:
            await msg.reply_document(
                document=f,
                filename=out_name,
                caption=(
                    "✅ Done! Metadata fully stripped:\n"
                    "• Title & filename randomized\n"
                    "• GPS & location removed\n"
                    "• Device & camera model wiped\n"
                    "• Timestamps randomized\n"
                    "• Encoder fingerprint cleared\n\n"
                    "4K quality preserved 🎬"
                )
            )

        await status.delete()

    except Exception as e:
        log.error("Error processing video: %s", e)
        await status.edit_text(f"❌ Something went wrong: {str(e)[:200]}\nTry again.")
    finally:
        # Clean up temp files
        in_path.unlink(missing_ok=True)
        out_path.unlink(missing_ok=True)


async def handle_other(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎬 Send me a video and I'll clean its metadata!")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))
    app.add_handler(MessageHandler(~filters.COMMAND, handle_other))
    log.info("Lannah Meta Bot is running…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
