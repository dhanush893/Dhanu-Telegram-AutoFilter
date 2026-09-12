import asyncio
import os
import re
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telegram import Update
from telegram.ext import Application, CommandHandler

load_dotenv()

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
OWNER_USER_ID = int(os.environ["OWNER_USER_ID"])
SOURCE_CHAT = os.environ["SOURCE_CHAT"]
DESTINATION_CHAT = os.environ["DESTINATION_CHAT"]
SESSION_NAME = os.getenv("SESSION_NAME", "user")
TELETHON_SESSION = os.getenv("TELETHON_SESSION", "").strip()
DB_PATH = os.getenv("DATABASE_PATH", "bot.db")
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "media_tmp"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

REMOVE_LINKS = os.getenv("REMOVE_LINKS", "true").lower() in {"1", "true", "yes", "on"}
HASHTAGS = os.getenv("HASHTAGS", "").strip()
THUMBNAIL_PATH = os.getenv("THUMBNAIL_PATH", "").strip()
MAX_CAPTION = 4096

# SQLite is used only for bot state/tracking. The Telegram session is kept in the host secret.
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.execute(
    """CREATE TABLE IF NOT EXISTS processed(
        source_chat TEXT,
        source_msg_id INTEGER,
        fingerprint TEXT,
        destination_msg_id INTEGER,
        status TEXT,
        PRIMARY KEY(source_chat, source_msg_id)
    )"""
)
db.execute("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)")
db.execute("CREATE TABLE IF NOT EXISTS filters(keyword TEXT PRIMARY KEY)")
db.execute("CREATE INDEX IF NOT EXISTS idx_processed_fp ON processed(fingerprint)")
db.commit()


def setting(key, default=""):
    row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(key, value):
    db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, value))
    db.commit()


def get_filters():
    return [row[0] for row in db.execute("SELECT keyword FROM filters ORDER BY keyword")]


def done(message_id):
    return db.execute(
        "SELECT 1 FROM processed WHERE source_chat=? AND source_msg_id=?",
        (str(SOURCE_CHAT), message_id),
    ).fetchone()


def mark(message_id, fingerprint_value, destination_id, status="sent"):
    db.execute(
        "INSERT OR REPLACE INTO processed VALUES(?,?,?,?,?)",
        (str(SOURCE_CHAT), message_id, fingerprint_value, destination_id, status),
    )
    db.commit()


def fingerprint(message):
    name = ""
    size = ""
    document = getattr(getattr(message, "media", None), "document", None)
    if document:
        size = str(getattr(document, "size", ""))
        for attr in getattr(document, "attributes", []):
            if getattr(attr, "file_name", None):
                name = attr.file_name
                break
    return f"{name}|{size}|{(message.raw_text or '').strip().lower()}"


def clean_text(text):
    text = text or ""
    if REMOVE_LINKS:
        text = re.sub(r"https?://\S+|www\.\S+|t\.me/\S+", "", text, flags=re.I)
    return re.sub(r"[ \t]+", " ", text).strip()


def parse(name):
    stem = Path(name).stem
    ext = Path(name).suffix or ".mkv"
    year_match = re.search(r"\b(?:19|20)\d{2}\b", stem)
    year = year_match.group(0) if year_match else ""

    languages = ["Tamil", "Telugu", "Hindi", "Malayalam", "Kannada", "English"]
    qualities = ["2160p", "1080p", "720p", "480p", "HDRip", "WEB-DL", "WEBRip", "BluRay", "TSRip"]
    video_codecs = ["x265", "x264", "HEVC", "AV1"]
    audio_codecs = ["AAC", "AC3", "DDP", "EAC3", "MP3"]

    language = next((x for x in languages if re.search(rf"\b{re.escape(x)}\b", stem, re.I)), "")
    quality = next((x for x in qualities if re.search(rf"\b{re.escape(x)}\b", stem, re.I)), "")
    video_codec = next((x for x in video_codecs if re.search(rf"\b{re.escape(x)}\b", stem, re.I)), "")
    audio_codec = next((x for x in audio_codecs if re.search(rf"\b{re.escape(x)}\b", stem, re.I)), "")
    subtitle = "ESub" if re.search(r"\bESub\b", stem, re.I) else ""

    title = stem
    removable = languages + qualities + video_codecs + audio_codecs + ["HC", "ESub"]
    for token in removable:
        title = re.sub(rf"\b{re.escape(token)}\b", "", title, flags=re.I)
    title = re.sub(r"\b(?:19|20)\d{2}\b", "", title)
    title = re.sub(r"[\[\]\(\)_\-.]+", " ", title)
    title = re.sub(r"\s+", " ", title).strip()

    return {
        "title": title,
        "year": year,
        "language": language,
        "quality": quality,
        "video_codec": video_codec,
        "audio_codec": audio_codec,
        "subtitle": subtitle,
        "ext": ext,
    }


def make_caption(name, size_mb):
    parsed = parse(name)
    template = setting(
        "template",
        "{prefix} - {title} ({year}) {language} {quality} - {video_codec} - {audio_codec} - {size} - {subtitle}.{brand}{ext}",
    )
    values = {
        **parsed,
        "prefix": setting("prefix", "@SD_MOVIE_ADDA"),
        "brand": setting("brand", "_Ɗʜa֟፝nᴜ ⸙_"),
        "size": f"{size_mb:.0f}MB",
    }
    try:
        output = template.format(**values)
    except KeyError as exc:
        print(f"Invalid template placeholder: {exc}")
        output = f"{values['prefix']} - {parsed['title']} ({parsed['year']}) {parsed['language']} {parsed['quality']} - {parsed['video_codec']} - {parsed['audio_codec']} - {values['size']} - {parsed['subtitle']}.{values['brand']}{parsed['ext']}"

    output = re.sub(r"\(\s*\)", "", output)
    output = re.sub(r"\s+-\s+-", " -", output)
    output = re.sub(r"\s{2,}", " ", output).strip()
    if HASHTAGS:
        output = f"{output}\n\n{HASHTAGS}"
    return output[:MAX_CAPTION]


def safe_filename(value):
    value = re.sub(r'[\\/:*?"<>|\r\n]', "_", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:240] or "media.mkv"


# Koyeb uses the StringSession stored in TELETHON_SESSION.
# Local development can still use the traditional SESSION_NAME file session.
if TELETHON_SESSION:
    print("Telethon: using TELETHON_SESSION secret.")
    client = TelegramClient(StringSession(TELETHON_SESSION), API_ID, API_HASH)
else:
    print("WARNING: TELETHON_SESSION is not set; using local file session.")
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

paused = False
process_lock = asyncio.Lock()


async def process(message):
    """Process one source message. A source message is marked only after a final decision."""
    if paused or done(message.id):
        return

    async with process_lock:
        if paused or done(message.id):
            return

        text = (message.raw_text or "").lower()
        filters = get_filters()
        if filters and not all(keyword.lower() in text for keyword in filters):
            mark(message.id, fingerprint(message), None, "filtered")
            return

        fp = fingerprint(message)
        if db.execute(
            "SELECT 1 FROM processed WHERE fingerprint=? AND status='sent' LIMIT 1", (fp,)
        ).fetchone():
            mark(message.id, fp, None, "duplicate")
            return

        if not message.media:
            body = clean_text(message.raw_text)
            if not body:
                mark(message.id, fp, None, "empty")
                return
            sent = await client.send_message(DESTINATION_CHAT, body)
            mark(message.id, fp, sent.id, "sent")
            return

        path_string = await client.download_media(message, file=str(DOWNLOAD_DIR))
        if not path_string:
            print(f"Download failed for source message {message.id}")
            return

        path = Path(path_string)
        try:
            original_name = path.name
            document = getattr(getattr(message, "media", None), "document", None)
            if document:
                for attr in getattr(document, "attributes", []):
                    if getattr(attr, "file_name", None):
                        original_name = attr.file_name
                        break

            size_mb = path.stat().st_size / (1024 * 1024)
            caption = make_caption(original_name, size_mb)
            target = path.with_name(safe_filename(caption))
            if target != path:
                try:
                    path.rename(target)
                    path = target
                except OSError:
                    pass

            send_kwargs = {
                "caption": caption,
                "force_document": True,
                "supports_streaming": True,
            }
            if THUMBNAIL_PATH and Path(THUMBNAIL_PATH).is_file():
                send_kwargs["thumb"] = THUMBNAIL_PATH

            sent = await client.send_file(DESTINATION_CHAT, str(path), **send_kwargs)
            mark(message.id, fp, sent.id, "sent")
        finally:
            try:
                path.unlink()
            except OSError:
                pass


async def historical_scan(limit=100):
    count = 0
    async for message in client.iter_messages(SOURCE_CHAT, limit=limit):
        if paused:
            break
        try:
            await process(message)
            count += 1
        except FloodWaitError as exc:
            print(f"Flood wait: {exc.seconds}s")
            await asyncio.sleep(exc.seconds)
        except Exception as exc:
            print(f"Scan error on message {message.id}: {type(exc).__name__}: {exc}")
    return count


async def live(event):
    try:
        await process(event.message)
    except FloodWaitError as exc:
        print(f"Live flood wait: {exc.seconds}s")
        await asyncio.sleep(exc.seconds)
        try:
            await process(event.message)
        except Exception as retry_exc:
            print(f"Live retry error: {type(retry_exc).__name__}: {retry_exc}")
    except Exception as exc:
        print(f"Live error: {type(exc).__name__}: {exc}")


def owner(handler):
    async def wrapper(update: Update, context):
        if update.effective_user and update.effective_user.id == OWNER_USER_ID:
            return await handler(update, context)
        if update.effective_message:
            await update.effective_message.reply_text("Not authorized.")
    return wrapper


@owner
async def start(update, context):
    await update.message.reply_text(
        "Dhanu Auto Filter V1 online.\n"
        "/status /filters /scan [count] /pause /resume /settings\n"
        "/addfilter /removefilter /setprefix /setbrand /settemplate"
    )


@owner
async def status(update, context):
    total = db.execute("SELECT COUNT(*) FROM processed").fetchone()[0]

    def count_status(status):
        return db.execute("SELECT COUNT(*) FROM processed WHERE status=?", (status,)).fetchone()[0]

    await update.message.reply_text(
        f"{'PAUSED' if paused else 'RUNNING'}\n"
        f"Processed: {total}\n"
        f"Sent: {count_status('sent')}\n"
        f"Duplicate: {count_status('duplicate')}\n"
        f"Filtered: {count_status('filtered')}\n"
        f"Empty: {count_status('empty')}"
    )


@owner
async def addfilter(update, context):
    keyword = " ".join(context.args).strip()
    if not keyword:
        await update.message.reply_text("Usage: /addfilter keyword")
        return
    db.execute("INSERT OR IGNORE INTO filters VALUES(?)", (keyword,))
    db.commit()
    await update.message.reply_text(f"Filter added: {keyword}")


@owner
async def removefilter(update, context):
    keyword = " ".join(context.args).strip()
    if not keyword:
        await update.message.reply_text("Usage: /removefilter keyword")
        return
    db.execute("DELETE FROM filters WHERE keyword=?", (keyword,))
    db.commit()
    await update.message.reply_text("Filter removed.")


@owner
async def filters_cmd(update, context):
    await update.message.reply_text("\n".join(get_filters()) or "No filters.")


@owner
async def prefix(update, context):
    value = " ".join(context.args).strip()
    if not value:
        await update.message.reply_text("Usage: /setprefix @NAME")
        return
    set_setting("prefix", value)
    await update.message.reply_text("Prefix updated.")


@owner
async def brand(update, context):
    value = " ".join(context.args).strip()
    if not value:
        await update.message.reply_text("Usage: /setbrand BRAND")
        return
    set_setting("brand", value)
    await update.message.reply_text("Brand updated.")


@owner
async def template(update, context):
    value = " ".join(context.args).strip()
    if not value:
        await update.message.reply_text("Usage: /settemplate {prefix} - {title} ({year}) ...")
        return
    set_setting("template", value)
    await update.message.reply_text("Template updated.")


@owner
async def scan_cmd(update, context):
    try:
        limit = int(context.args[0]) if context.args else int(os.getenv("MAX_HISTORY_SCAN", "100"))
        limit = max(1, min(limit, 10000))
    except ValueError:
        await update.message.reply_text("Usage: /scan [count]")
        return

    await update.message.reply_text(f"Starting historical scan: {limit} posts...")
    count = await historical_scan(limit)
    await update.message.reply_text(f"Checked {count} posts.")


@owner
async def pause(update, context):
    global paused
    paused = True
    await update.message.reply_text("Paused. New and historical processing will stop after the current file operation finishes.")


@owner
async def resume(update, context):
    global paused
    paused = False
    await update.message.reply_text("Resumed.")


@owner
async def settings_cmd(update, context):
    await update.message.reply_text(
        f"Source: {SOURCE_CHAT}\n"
        f"Destination: {DESTINATION_CHAT}\n"
        f"Prefix: {setting('prefix', '@SD_MOVIE_ADDA')}\n"
        f"Brand: {setting('brand', '_Ɗʜa֟፝nᴜ ⸙_')}\n"
        f"Remove links: {REMOVE_LINKS}\n"
        f"Hashtags: {HASHTAGS or 'none'}\n"
        f"Thumbnail: {'configured' if THUMBNAIL_PATH else 'none'}\n"
        f"Telethon session: {'configured' if TELETHON_SESSION else 'MISSING'}"
    )


async def main():
    print("Starting Dhanu Telegram AutoFilter V1...")
    print(f"Source configured: {bool(SOURCE_CHAT)} | Destination configured: {bool(DESTINATION_CHAT)}")

    print("Connecting Telethon user client...")
    await client.start()
    me = await client.get_me()
    print(f"Telethon connected as user ID {me.id}.")

    # Resolve the source once at startup so configuration/access errors appear immediately in logs.
    source_entity = await client.get_entity(SOURCE_CHAT)
    destination_entity = await client.get_entity(DESTINATION_CHAT)
    print(f"Source resolved: {getattr(source_entity, 'title', SOURCE_CHAT)}")
    print(f"Destination resolved: {getattr(destination_entity, 'title', DESTINATION_CHAT)}")

    client.add_event_handler(live, events.NewMessage(chats=SOURCE_CHAT))

    app = Application.builder().token(BOT_TOKEN).build()
    handlers = {
        "start": start,
        "status": status,
        "addfilter": addfilter,
        "removefilter": removefilter,
        "filters": filters_cmd,
        "setprefix": prefix,
        "setbrand": brand,
        "settemplate": template,
        "scan": scan_cmd,
        "pause": pause,
        "resume": resume,
        "settings": settings_cmd,
    }
    for command, handler in handlers.items():
        app.add_handler(CommandHandler(command, handler))

    print("Starting Telegram control bot...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    print("Dhanu Telegram AutoFilter V1 running.")

    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"FATAL: {type(exc).__name__}: {exc}")
        raise
