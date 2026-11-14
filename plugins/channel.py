# ─────────────────────────────────────────────
# Powered by Roaroic | Developer Channel: @roaroic0
# https://t.me/roaroic0
# ─────────────────────────────────────────────
import re
import logging
import asyncio
import aiohttp
from datetime import datetime
from collections import defaultdict
from plugins.Roaroicfutures.Imdbposter import get_movie_detailsx, fetch_image, get_movie_details, create_fallback_thumbnail, format_runtime
from database.users_chats_db import db
from pyrogram import Client, filters, enums
from info import CHANNELS, MOVIE_UPDATE_CHANNEL, LINK_PREVIEW, ABOVE_PREVIEW, BAD_WORDS, LANDSCAPE_POSTER, TMDB_POSTER, BOT_TOKEN
from Script import script
from database.ia_filterdb import save_file
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from utils import temp
from pymongo import ReturnDocument
from pymongo.errors import PyMongoError, DuplicateKeyError
from pyrogram.errors import MessageIdInvalid, MessageNotModified, FloodWait
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

async def get_next_get_files_button_color():
    """Rotate button colors in groups of three, persisting the sequence in MongoDB."""
    status = await db.movie_update_status.find_one_and_update(
        {"_id": "get_files_button_color"},
        {"$inc": {"count": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    color_index = ((status.get("count", 1) - 1) // 3) % 3
    return ("success", "primary", "danger")[color_index]


async def apply_get_files_button_style(chat_id, message_id, bot_url, color):
    """Apply Telegram's inline-button color; styling failure never blocks the channel post."""
    if not BOT_TOKEN or not message_id:
        return
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "reply_markup": {
            "inline_keyboard": [[{
                "text": "ɢᴇᴛ ғɪʟᴇs",
                "url": bot_url,
                "style": color
            }]]
        }
    }
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageReplyMarkup",
                json=payload
            ) as response:
                result = await response.json(content_type=None)
                if response.status != 200 or not result.get("ok"):
                    logger.warning(
                        "[MOVIE UPDATE] Could not apply %s button style: %s",
                        color, result.get("description", f"HTTP {response.status}")
                    )
    except Exception as e:
        logger.warning("[MOVIE UPDATE] Button styling skipped: %s", e)


# Precomputed sets for faster lookups
IGNORE_WORDS = {
    "rarbg", "dub", "sub", "sample", "mkv", "aac", "combined",
    "action", "adventure", "animation", "biography", "comedy", "crime", 
    "documentary", "drama", "family", "fantasy", "film-noir", "history", 
    "horror", "music", "musical", "mystery", "romance", "sci-fi", "sport", 
    "thriller", "war", "western", "hdcam", "hdtc", "camrip", "ts", "tc", 
    "telesync", "dvdscr", "dvdrip", "predvd", "webrip", "web-dl", "tvrip", 
    "hdtv", "web dl", "webdl", "bluray", "brrip", "bdrip", "360p", "480p", 
    "720p", "1080p", "2160p", "4k", "1440p", "540p", "240p", "140p", "hevc", 
    "hdrip", "hin", "hindi", "tam", "tamil", "kan", "kannada", "tel", "telugu", 
    "mal", "malayalam", "eng", "english", "pun", "punjabi", "ben", "bengali", 
    "mar", "marathi", "guj", "gujarati", "urd", "urdu", "kor", "korean", "jpn", 
    "japanese", "nf", "netflix", "sonyliv", "sony", "sliv", "amzn", "prime", 
    "primevideo", "hotstar", "zee5", "jio", "jhs", "aha", "hbo", "paramount", 
    "apple", "hoichoi", "sunnxt", "viki"
}|BAD_WORDS

# Constants
CAPTION_LANGUAGES = {
    "hin": "Hindi", "hindi": "Hindi",
    "tam": "Tamil", "tamil": "Tamil",
    "kan": "Kannada", "kannada": "Kannada",
    "tel": "Telugu", "telugu": "Telugu",
    "mal": "Malayalam", "malayalam": "Malayalam",
    "eng": "English", "english": "English",
    "pun": "Punjabi", "punjabi": "Punjabi",
    "ben": "Bengali", "bengali": "Bengali",
    "mar": "Marathi", "marathi": "Marathi",
    "guj": "Gujarati", "gujarati": "Gujarati",
    "urd": "Urdu", "urdu": "Urdu",
    "kor": "Korean", "korean": "Korean",
    "jpn": "Japanese", "japanese": "Japanese",
}

OTT_PLATFORMS = {
    "nf": "Netflix", "netflix": "Netflix",
    "sonyliv": "SonyLiv", "sony": "SonyLiv", "sliv": "SonyLiv",
    "amzn": "Amazon Prime Video", "prime": "Amazon Prime Video", "primevideo": "Amazon Prime Video",
    "hotstar": "Disney+ Hotstar", "zee5": "Zee5",
    "jio": "JioHotstar", "jhs": "JioHotstar",
    "aha": "Aha", "hbo": "HBO Max", "paramount": "Paramount+",
    "apple": "Apple TV+", "hoichoi": "Hoichoi", "sunnxt": "Sun NXT", "viki": "Viki"
}

STANDARD_GENRES = {
    'Action', 'Adventure', 'Animation', 'Biography', 'Comedy', 'Crime', 'Documentary',
    'Drama', 'Family', 'Fantasy', 'Film-Noir', 'History', 'Horror', 'Music',
    'Musical', 'Mystery', 'Romance', 'Sci-Fi', 'Sport', 'Thriller', 'War', 'Western'
}

# Precompiled regex patterns
CLEAN_PATTERN = re.compile(r'@[^ \n\r\t\.,:;!?()\[\]{}<>\\/"\'=_%]+|\bwww\.[^\s\]\)]+|\([\@^]+\)|\[[\@^]+\]')
NORMALIZE_PATTERN = re.compile(r"[._]+|[()\[\]{}:;'–!,.?_]")
QUALITY_PATTERN = re.compile(
    r"\b(?:HDCam|HDTC|CamRip|TS|TC|TeleSync|DVDScr|DVDRip|PreDVD|"
    r"WEBRip|WEB-DL|TVRip|HDTV|WEB DL|WebDl|BluRay|BRRip|BDRip|"
    r"360p|480p|720p|1080p|2160p|4K|1440p|540p|240p|140p|HEVC|HDRip)\b", 
    re.IGNORECASE
)
YEAR_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?:19|20)\d{2}(?![A-Za-z0-9])")
RANGE_REGEX = re.compile(r'\bS(\d{1,2})[^\w\n\r]*E(?:p(?:isode)?)?0*(\d{1,2})\s*(?:to|-)\s*(?:E(?:p(?:isode)?)?)?0*(\d{1,2})',re.IGNORECASE)
SINGLE_REGEX = re.compile(r'\bS(\d{1,2})[^\w\n\r]*E(?:p(?:isode)?)?0*(\d{1,3})', re.IGNORECASE)
NAMED_REGEX = re.compile(r'Season\s*0*(\d{1,2})[\s\-,:]*Ep(?:isode)?\s*0*(\d{1,3})', re.IGNORECASE)
EP_ONLY_RANGE = re.compile(r'\b(?:EP|Episode)0*(\d{1,3})\s*-\s*0*(\d{1,3})\b',re.IGNORECASE)


MEDIA_FILTER = filters.document | filters.video | filters.audio
locks = defaultdict(asyncio.Lock)
pending_updates = {}


def clean_mentions_links(text: str) -> str:
    return CLEAN_PATTERN.sub("", text or "").strip()

def normalize(s: str) -> str:
    s = NORMALIZE_PATTERN.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()

def remove_ignored_words(text: str) -> str:
    IGNORE_WORDS_LOWER = {w.lower() for w in IGNORE_WORDS}
    return " ".join(word for word in text.split() if word.lower() not in IGNORE_WORDS_LOWER)

def get_qualities(text: str) -> str:
    qualities = QUALITY_PATTERN.findall(text)
    return ", ".join(qualities) if qualities else "N/A"

def extract_ott_platform(text: str) -> str:
    text = text.lower()
    platforms = {plat for key, plat in OTT_PLATFORMS.items() if key in text}
    return " | ".join(platforms) if platforms else "N/A"

def extract_season_episode(filename: str) -> Tuple[Optional[int], Optional[str]]:
    if m := EP_ONLY_RANGE.search(filename):
        return 1, f"{int(m.group(1))}-{int(m.group(2))}"
    for pattern in (RANGE_REGEX, SINGLE_REGEX, NAMED_REGEX):
        if m := pattern.search(filename):
            season = int(m.group(1))
            if pattern == RANGE_REGEX:
                ep = f"{m.group(2)}-{m.group(3)}"
            else:
                ep = m.group(2)
            return season, ep
    return None, None

def schedule_update(bot, base_name, delay=5):
    if handle := pending_updates.get(base_name):
        if not handle.cancelled():
            handle.cancel()
    
    loop = asyncio.get_event_loop()
    pending_updates[base_name] = loop.call_later(
        delay,
        lambda: asyncio.create_task(update_movie_message(bot, base_name))
    )

def extract_media_info(filename: str, caption: str):
    filename = normalize(clean_mentions_links(filename).title())
    caption_clean = clean_mentions_links(caption).lower() if caption else ""
    unified = f"{caption_clean} {filename.lower()}".strip()

    season = episode = year = None
    tag = "#MOVIE"
    processed_raw = base_raw = filename
    quality = get_qualities(caption_clean) or get_qualities(filename.lower()) or "N/A"
    ott_platform = extract_ott_platform(f"{filename} {caption_clean}")

    lang_keys = {k for k in CAPTION_LANGUAGES if k in caption_clean or k in filename.lower()}
    language = ", ".join(sorted({CAPTION_LANGUAGES[k] for k in lang_keys})) if lang_keys else "N/A"

    season, episode = extract_season_episode(filename)
    if season is not None:
        tag = "#SERIES"
        if m := (RANGE_REGEX.search(filename) or SINGLE_REGEX.search(filename) or NAMED_REGEX.search(filename) or EP_ONLY_RANGE.search(filename)):
            match_str = m.group(0)
            start_idx = filename.lower().find(match_str.lower())
            end_idx = start_idx + len(match_str)
            processed_raw = filename[:end_idx]
            base_raw = filename[:start_idx]
            if year_match := YEAR_PATTERN.search(filename.lower()[end_idx:]):
                y = year_match.group(0)
                yi = filename.lower().find(y, end_idx)
                if yi != -1:
                    processed_raw = filename[:yi+4]
                    base_raw += f" {y}"
    else:
        if year_match := YEAR_PATTERN.search(unified):
            year = year_match.group(0)
            year_idx = filename.lower().find(year.lower())
            if year_idx != -1:
                processed_raw = filename[:year_idx + 4]
                base_raw = processed_raw
        else:
            if qual_match := QUALITY_PATTERN.search(unified):
                qual_str = qual_match.group(0)
                qual_idx = filename.lower().find(qual_str.lower())
                if qual_idx != -1:
                    processed_raw = filename[:qual_idx]
                    base_raw = processed_raw

    base_name = normalize(remove_ignored_words(normalize(base_raw)))
    if year and year not in base_name:
        base_name += f" {year}"

    if base_name.endswith(")"):
        base_name = re.sub(r"\s+\(\d{4}\)$", "", base_name)
        if year:
            base_name += f" ({year})"

    return {
        "processed": normalize(processed_raw),
        "base_name": base_name,
        "tag": tag,
        "season": season,
        "episode": episode,
        "year": year,
        "quality": quality,
        "ott_platform": ott_platform,
        "language": language
    }

@Client.on_message(filters.chat(CHANNELS) & MEDIA_FILTER)
async def media_handler(bot, message):
    try:
        media_type = next(
            (ft for ft in ("document", "video", "audio")
             if getattr(message, ft, None)),
            None
        )
        if not media_type:
            logger.warning("[MOVIE UPDATE] No supported media found in channel post %s", message.id)
            return

        media = getattr(message, media_type)
        media.file_type = media_type
        caption = message.caption or ""
        filename = (
            getattr(media, "file_name", None)
            or getattr(media, "title", None)
            or (caption.splitlines()[0].strip() if caption.strip() else None)
            or f"Telegram_{media.file_unique_id}"
        )
        media.file_name = filename
        media.caption = caption

        # Indexing and announcement are separate tasks. A duplicate in the
        # search database must not stop the movie-update announcement.
        try:
            success, info = await save_file(media)
            if not success:
                logger.info(
                    "[MOVIE UPDATE] Search index did not add file (duplicate or save issue); "
                    "continuing announcement pipeline. file=%s status=%s",
                    filename, info
                )
        except Exception:
            logger.exception(
                "[MOVIE UPDATE] Search indexing failed for %s; continuing announcement pipeline",
                filename
            )

        enabled = await db.movie_update_status(bot.me.id)
        logger.info(
            "[MOVIE UPDATE] Source post received: chat_id=%s message_id=%s enabled=%s destination=%s",
            message.chat.id, message.id, enabled, MOVIE_UPDATE_CHANNEL
        )
        if not enabled:
            logger.warning("[MOVIE UPDATE] Notifications are OFF in bot_settings for bot %s", bot.me.id)
            return

        logger.info("[MOVIE UPDATE] Processing channel file: %s (type=%s)", filename, media_type)
        await process_and_send_update(bot, filename, caption)
    except Exception:
        logger.exception("[MOVIE UPDATE] Error handling channel media post %s", getattr(message, "id", "unknown"))

async def process_and_send_update(bot, filename, caption):
    try:
        media_info = extract_media_info(filename, caption)
        base_name = media_info["base_name"]
        processed = media_info["processed"]

        lock = locks[base_name]
        async with lock:
            await _process_with_lock(bot, filename, caption, media_info, base_name, processed)
    except PyMongoError as e:
        logger.error("Database error: %s", e)
    except Exception as e:
        logger.exception("Processing failed: %s", e)

error_tmdb = False

async def _process_with_lock(bot, filename, caption, media_info, base_name, processed):
    if not hasattr(db, 'movie_updates'):
        db.movie_updates = db.db.movie_updates

    movie_doc = await db.movie_updates.find_one({"_id": base_name})
    global error_tmdb
    error_tmdb=False
    file_data = {
        "filename": filename,
        "processed": processed,
        "quality": media_info["quality"],
        "language": media_info["language"],
        "ott_platform": media_info["ott_platform"],
        "timestamp": datetime.now(),
        "tag": media_info["tag"],
        "season": media_info["season"],
        "episode": media_info["episode"]
    }

    # Repair older records whose runtime was saved as N/A. For TV series,
    # TMDB may expose runtime only on individual season episodes.
    if movie_doc and str(movie_doc.get("runtime") or "N/A").strip().upper() in ("N/A", "NONE", ""):
        try:
            runtime_details = {}
            if TMDB_POSTER:
                runtime_details = await get_movie_detailsx(base_name) or {}
            if not runtime_details.get("runtime") or runtime_details.get("error"):
                runtime_details = await get_movie_details(base_name) or {}
            recovered_runtime = runtime_details.get("runtime")
            if recovered_runtime and str(recovered_runtime).strip().upper() != "N/A":
                await db.movie_updates.update_one(
                    {"_id": base_name},
                    {"$set": {"runtime": recovered_runtime}}
                )
                movie_doc["runtime"] = recovered_runtime
                if movie_doc.get("message_id"):
                    await update_movie_message(bot, base_name)
                logger.info("[MOVIE UPDATE] Recovered runtime for %s: %s", base_name, recovered_runtime)
        except Exception:
            logger.exception("[MOVIE UPDATE] Runtime recovery failed for %s", base_name)

    # Retry official TMDB artwork first, then IMDb, for records created without artwork.
    if movie_doc and not movie_doc.get("poster_url"):
        try:
            poster_details = {}
            if TMDB_POSTER:
                poster_details = await get_movie_detailsx(base_name) or {}
            if poster_details.get("error") or not (poster_details.get("backdrop_url") or poster_details.get("poster_url")):
                poster_details = await get_movie_details(base_name) or {}
                poster_source = "imdb" if poster_details.get("poster_url") else "fallback"
            else:
                poster_source = "tmdb"

            official_image = poster_details.get("backdrop_url") or poster_details.get("poster_url")
            if official_image:
                await db.movie_updates.update_one(
                    {"_id": base_name},
                    {"$set": {
                        "poster_url": official_image,
                        "poster_source": poster_source,
                        "imdb_url": (poster_details.get("tmdb_url") or poster_details.get("url") or movie_doc.get("imdb_url", ""))
                    }}
                )
                movie_doc["poster_url"] = official_image
                movie_doc["poster_source"] = poster_source
                logger.info("[MOVIE UPDATE] Official poster found on retry for %s via %s", base_name, poster_source)
                # Replace a previously generated fallback image with the official artwork.
                if movie_doc.get("message_id") and movie_doc.get("poster_source") in ("fallback", None):
                    try:
                        await bot.delete_messages(MOVIE_UPDATE_CHANNEL, movie_doc["message_id"])
                    except Exception:
                        logger.exception("[MOVIE UPDATE] Could not replace fallback thumbnail for %s", base_name)
                    await db.movie_updates.update_one(
                        {"_id": base_name},
                        {"$set": {"message_id": None, "is_photo": False}}
                    )
                    movie_doc["message_id"] = None
        except Exception:
            logger.exception("[MOVIE UPDATE] TMDB/IMDb poster retry failed for %s", base_name)

    if not movie_doc:
        details = {}
        try:
            if TMDB_POSTER:
                details = await get_movie_detailsx(base_name) or {"error": "empty"}
                if details.get("error") or not (details.get("poster_url") or details.get("backdrop_url")):
                    error_tmdb = True
                    logger.info("[MOVIE UPDATE] TMDB lookup failed/no poster for %s; trying IMDb", base_name)
                    details = await get_movie_details(base_name) or {}
            else:
                details = await get_movie_details(base_name) or {}
        except Exception:
            # Metadata providers must not prevent the channel announcement.
            logger.exception("[MOVIE UPDATE] Metadata lookup failed for %s; posting with fallback values", base_name)
            details = {}

        raw_genres = details.get("genres", "N/A")
        if isinstance(raw_genres, str):
            genre_list = [g.strip() for g in raw_genres.split(",")]
            genres = ", ".join(g for g in genre_list if g in STANDARD_GENRES) or "N/A"
        else:
            genres = ", ".join(g for g in raw_genres if g in STANDARD_GENRES) or "N/A"
        movie_doc = {
            "_id": base_name,
            "files": [file_data],
            "poster_url": details.get("backdrop_url") or details.get("poster_url"),
            "poster_source": ("tmdb" if TMDB_POSTER and not error_tmdb and (details.get("backdrop_url") or details.get("poster_url")) else "imdb" if details.get("poster_url") else "fallback"),
            "is_landscape": True,
            "genres": genres,
            "rating": details.get("rating", "N/A"),
            "runtime": details.get("runtime") or "N/A",
            "imdb_url": (details.get("tmdb_url") if TMDB_POSTER and not error_tmdb else details.get("url")) or "",
            "year": media_info["year"] or details.get("year"),
            "tag": media_info["tag"],
            "ott_platform": media_info["ott_platform"],
            "message_id": None,
            "is_photo": False
        }
        try:
            await db.movie_updates.insert_one(movie_doc)
            await send_movie_update(bot, base_name)
            movie_doc = await db.movie_updates.find_one({"_id": base_name})
        except DuplicateKeyError:
            movie_doc = await db.movie_updates.find_one({"_id": base_name})
            if movie_doc:
                if any(f["filename"] == filename for f in movie_doc["files"]):
                    # Duplicate file: keep the existing single movie announcement.
                    return
                await db.movie_updates.update_one(
                    {"_id": base_name},
                    {"$push": {"files": file_data}}
                )
                movie_doc["files"].append(file_data)
                schedule_update(bot, base_name)
    else:
        if any(f["filename"] == filename for f in movie_doc["files"]):
            # Same file is already indexed and announced; do not create another post.
            return
        await db.movie_updates.update_one(
            {"_id": base_name},
            {"$push": {"files": file_data}}
        )
        movie_doc["files"].append(file_data)
        if not movie_doc.get("message_id"):
            await send_movie_update(bot, base_name)
        else:
            schedule_update(bot, base_name)

async def send_movie_update(bot, base_name):
    """Send the update post; fall back to a text post if poster handling fails."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            movie_doc = await db.movie_updates.find_one({"_id": base_name})
            if not movie_doc:
                logger.warning("[MOVIE UPDATE] No database record found for %s", base_name)
                return None

            text = generate_movie_message(movie_doc, base_name)
            bot_username = (getattr(temp, "U_NAME", None) or "").lstrip("@")
            movie_slug = re.sub(r"\s+", "-", base_name.strip())
            bot_url = f"https://t.me/{bot_username}?start=getfile-{movie_slug}" if bot_username else "https://t.me/"
            buttons = InlineKeyboardMarkup([[
                InlineKeyboardButton("ɢᴇᴛ ғɪʟᴇs", url=bot_url)
            ]])

            msg = None
            poster_url = movie_doc.get("poster_url")
            resized_poster = None
            if poster_url:
                try:
                    resized_poster = await fetch_image(poster_url, size=(1920, 1080))
                except Exception:
                    logger.exception("[MOVIE UPDATE] Remote poster processing failed for %s", base_name)

            # Always attempt a generated 16:9 image if the remote poster is missing
            # or Telegram rejects it. Text-only is the final emergency fallback.
            if resized_poster is not None:
                try:
                    msg = await bot.send_photo(
                        chat_id=MOVIE_UPDATE_CHANNEL,
                        photo=resized_poster,
                        caption=text,
                        reply_markup=buttons,
                        parse_mode=enums.ParseMode.HTML
                    )
                except Exception:
                    logger.exception("[MOVIE UPDATE] Remote poster send failed for %s", base_name)

            used_fallback = False
            if msg is None:
                try:
                    fallback = create_fallback_thumbnail(base_name, size=(1920, 1080))
                    msg = await bot.send_photo(
                        chat_id=MOVIE_UPDATE_CHANNEL,
                        photo=fallback,
                        caption=text,
                        reply_markup=buttons,
                        parse_mode=enums.ParseMode.HTML
                    )
                    used_fallback = True
                except Exception:
                    logger.exception("[MOVIE UPDATE] Fallback thumbnail send failed for %s", base_name)

            if msg is None:
                raise RuntimeError("Could not publish the thumbnail; refusing to create a text-only post.")

            button_color = await get_next_get_files_button_color()
            await apply_get_files_button_style(MOVIE_UPDATE_CHANNEL, msg.id, bot_url, button_color)

            await db.movie_updates.update_one(
                {"_id": base_name},
                {"$set": {
                    "message_id": msg.id,
                    "is_photo": bool(getattr(msg, "photo", None)),
                    "poster_source": "fallback" if used_fallback else movie_doc.get("poster_source", "tmdb"),
                    "button_color": button_color
                }}
            )
            logger.info("[MOVIE UPDATE] Successfully posted %s to channel %s (message_id=%s)",
                        base_name, MOVIE_UPDATE_CHANNEL, msg.id)
            return msg

        except FloodWait as e:
            wait_time = e.value + 2
            logger.warning("[MOVIE UPDATE] FloodWait; retrying in %s seconds", wait_time)
            await asyncio.sleep(wait_time)
        except Exception:
            logger.exception("[MOVIE UPDATE] Failed to send %s to channel %s (attempt %s/%s)",
                             base_name, MOVIE_UPDATE_CHANNEL, attempt + 1, max_retries)
            if attempt < max_retries - 1:
                await asyncio.sleep(3 * (attempt + 1))
    return None

async def update_movie_message(bot, base_name):
    try:
        movie_doc = await db.movie_updates.find_one({"_id": base_name})
        if not movie_doc:
            return

        text = generate_movie_message(movie_doc, base_name)
        bot_username = (getattr(temp, "U_NAME", None) or "").lstrip("@")
        movie_slug = re.sub(r"\s+", "-", base_name.strip())
        bot_url = f"https://t.me/{bot_username}?start=getfile-{movie_slug}" if bot_username else "https://t.me/"
        buttons = InlineKeyboardMarkup([[
            InlineKeyboardButton("ɢᴇᴛ ғɪʟᴇs", url=bot_url)
        ]])

        message_id = movie_doc.get("message_id")
        is_photo = movie_doc.get("is_photo", False)

        if not message_id:
            await send_movie_update(bot, base_name)
            return

        try:
            if is_photo:
                await bot.edit_message_caption(
                    chat_id=MOVIE_UPDATE_CHANNEL,
                    message_id=message_id,
                    caption=text,
                    reply_markup=buttons,
                    parse_mode=enums.ParseMode.HTML
                )
            else:
                await bot.edit_message_text(
                    chat_id=MOVIE_UPDATE_CHANNEL,
                    message_id=message_id,
                    text=text,
                    reply_markup=buttons,
                    parse_mode=enums.ParseMode.HTML,
                    invert_media=ABOVE_PREVIEW,
                    disable_web_page_preview=not LINK_PREVIEW
                )
            await apply_get_files_button_style(MOVIE_UPDATE_CHANNEL, message_id, bot_url, movie_doc.get("button_color", "success"))
            return
        except (MessageIdInvalid, MessageNotModified):
            pass
        except Exception:
            try:
                await bot.delete_messages(
                    chat_id=MOVIE_UPDATE_CHANNEL,
                    message_ids=message_id
                )
                await db.movie_updates.update_one(
                    {"_id": base_name},
                    {"$set": {"message_id": None, "is_photo": False}}
                )
            except Exception:
                pass
            await send_movie_update(bot, base_name)
    except Exception as e:
        logger.error(f"Failed to update movie message: {e}")

def generate_movie_message(movie_doc, base_name):
    all_qualities = set()
    all_languages = set()
    all_ott_platforms = set()
    all_tags = set()
    episodes_by_season = defaultdict(set)

    for file in movie_doc["files"]:
        if file["quality"] != "N/A":
            all_qualities.update(q.strip() for q in file["quality"].split(",") if q.strip())
        if file["language"] != "N/A":
            all_languages.update(l.strip() for l in file["language"].split(",") if l.strip())
        if file["ott_platform"] != "N/A":
            platforms = [p.strip() for p in file["ott_platform"].split("|") if p.strip()]
            all_ott_platforms.update(platforms)
        if file["tag"]:
            all_tags.add(file["tag"])
        if file.get("season") and file.get("episode"):
            season = file["season"]
            episode = file["episode"]
            episodes_by_season[season].add(episode)

    primary_tag = "#SERIES" if "#SERIES" in all_tags else "#MOVIE"
    epi_block = ""
    if episodes_by_season:
        episode_lines = []
        for season, episodes in sorted(episodes_by_season.items(), key=lambda x: int(x[0])):
            singles = []
            ranges = []

            for ep in episodes:
                if "-" in ep:
                    ranges.append(ep)
                else:
                    try:
                        singles.append(int(ep))
                    except ValueError:
                        ranges.append(ep)

            singles.sort()
            collapsed = []
            start = end = None
            for num in singles:
                if start is None:
                    start = end = num
                elif num == end + 1:
                    end = num
                else:
                    collapsed.append(str(start) if start == end else f"{start}-{end}")
                    start = end = num
            if start is not None:
                collapsed.append(str(start) if start == end else f"{start}-{end}")

            all_ep_parts = collapsed + sorted(ranges, key=lambda s: int(s.split("-")[0]))
            episode_lines.append(f"S{int(season)}: {', '.join(all_ep_parts)}")

        epi_str = " | ".join(episode_lines)
        if epi_str:
            epi_block = f"📺 ᴇᴘɪsᴏᴅᴇs : <code>{epi_str}</code>"

    genres = movie_doc.get("genres", "N/A")
    quality_str = ", ".join(sorted(all_qualities)) if all_qualities else "N/A"
    language_str = ", ".join(sorted(all_languages)) if all_languages else "N/A"
    ott_str = ", ".join(sorted(all_ott_platforms)) if all_ott_platforms else "N/A"

    message = script.MOVIE_UPDATE_NOTIFY_TXT.format(
        poster_url=movie_doc.get("poster_url", ""),
        imdb_url=movie_doc.get("imdb_url", ""),
        filename=base_name,
        tag=primary_tag,
        genres=genres,
        ott=ott_str,
        quality=quality_str,
        language=language_str,
        episodes=epi_block,
        rating=movie_doc.get("rating", "N/A"),
        runtime=format_runtime(movie_doc.get("runtime", "N/A")),
        search_link=temp.B_LINK.removesuffix("0") + " "
    )

    # Remove accidental zero-only placeholder lines from channel announcements.
    message = "\n".join(
        line for line in message.splitlines()
        if not (len(line.strip()) >= 5 and set(line.strip()) == {"0"})
    )
    return message
