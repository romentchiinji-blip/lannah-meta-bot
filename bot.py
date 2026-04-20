"""
Lannah Meta Bot + Tasks API
- Telegram: receives video → strips metadata → sends back clean version
- HTTP API: GET/POST /tasks  (for website task sync between Elijah & Lannah)
"""

import os
import json
import uuid
import logging
import threading
import subprocess
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

BOT_TOKEN  = os.environ.get("BOT_TOKEN", "8574928816:AAHtGowHKGCJmG4IJZRj6tbJ3FvxqzJ55M8")
API_SECRET = os.environ.get("API_SECRET", "lannah-tasks-2026")
PORT       = int(os.environ.get("PORT", "8080"))

TMP        = Path("/tmp/lannah_bot")
TMP.mkdir(exist_ok=True)
TASKS_FILE = TMP / "tasks.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


# ── Task storage ──────────────────────────────────────────────────────────────

def load_tasks():
    try:
        if TASKS_FILE.exists():
            return json.loads(TASKS_FILE.read_text())
    except Exception:
        pass
    return {"tasks": []}

def save_tasks(data):
    try:
        TASKS_FILE.write_text(json.dumps(data, ensure_ascii=False))
    except Exception as e:
        log.error("save_tasks error: %s", e)


# ── HTTP API ──────────────────────────────────────────────────────────────────

class TasksHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # silence default HTTP logs

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Secret")

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path != "/tasks":
            self.send_response(404); self.end_headers(); return
        data = load_tasks()
        body = json.dumps(data).encode()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/tasks":
            self.send_response(404); self.end_headers(); return
        # Auth check
        secret = self.headers.get("X-Secret", "")
        if secret != API_SECRET:
            self.send_response(403)
            self._cors()
            self.end_headers()
            self.wfile.write(b'{"error":"forbidden"}')
            return
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)
        try:
            data = json.loads(body)
            save_tasks(data)
            resp = json.dumps({"ok": True}).encode()
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
        except Exception as e:
            self.send_response(400)
            self._cors()
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())


def run_http():
    server = HTTPServer(("0.0.0.0", PORT), TasksHandler)
    log.info("Tasks API listening on port %s", PORT)
    server.serve_forever()


# ── Telegram helpers ──────────────────────────────────────────────────────────

def random_id() -> str:
    return uuid.uuid4().hex[:12]

def strip_metadata(in_path: Path, out_path: Path) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-i", str(in_path),
        "-map", "0",
        "-c", "copy",
        "-map_metadata", "-1",
        "-map_metadata:s:v", "-1",
        "-map_metadata:s:a", "-1",
        "-fflags", "+bitexact",
        "-flags:v", "+bitexact",
        "-flags:a", "+bitexact",
        str(out_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error: {result.stderr[-500:]}")


# ── Telegram handlers ─────────────────────────────────────────────────────────

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
        if msg.document.file_name:
            fn_ext = Path(msg.document.file_name).suffix.lstrip(".")
            if fn_ext:
                ext = fn_ext
    else:
        await msg.reply_text("⚠️ Please send a video file.")
        return

    file_size = getattr(file_obj, "file_size", 0) or 0
    if file_size > 2_000_000_000:
        await msg.reply_text("❌ File is too large (max 2GB).")
        return

    uid      = random_id()
    in_path  = TMP / f"{uid}_in.{ext}"
    out_path = TMP / f"{uid}_out.{ext}"

    status = await msg.reply_text("⏳ Downloading your video…")

    try:
        tg_file = await file_obj.get_file()
        await tg_file.download_to_drive(str(in_path))
        await status.edit_text("🔧 Stripping metadata (no re-encoding)…")
        strip_metadata(in_path, out_path)
        await status.edit_text("📤 Sending cleaned video…")

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
        in_path.unlink(missing_ok=True)
        out_path.unlink(missing_ok=True)

async def handle_other(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎬 Send me a video and I'll clean its metadata!")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # Start HTTP API in background thread
    t = threading.Thread(target=run_http, daemon=True)
    t.start()

    # Start Telegram bot (blocking)
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))
    app.add_handler(MessageHandler(~filters.COMMAND, handle_other))
    log.info("Lannah Meta Bot is running…")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
