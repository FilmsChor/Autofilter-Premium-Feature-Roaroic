# ─────────────────────────────────────────────
# Powered by Roaroic | Developer Channel: @roaroic0
# https://t.me/roaroic0
# ─────────────────────────────────────────────
import re
import aiohttp
import warnings
import logging
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter, ImageOps
from info import ROAROIC_IMAGE_FETCH, TMDB_API_KEY
from imdb import Cinemagoer


logger = logging.getLogger(__name__)
ia = Cinemagoer()
LONG_IMDB_DESCRIPTION = False

def list_to_str(lst):
    if lst:
        return ", ".join(map(str, lst))
    return ""


def format_runtime(value):
    """Format runtime minutes as compact hours/minutes, e.g. 155 -> 2h 35m."""
    if value is None:
        return "N/A"
    raw = str(value).strip()
    if not raw or raw.upper() in ("N/A", "NONE"):
        return "N/A"

    # Preserve values that are already expressed in hours/minutes.
    if re.search(r"\b\d+\s*h\b", raw, re.IGNORECASE):
        return re.sub(r"\s+", " ", raw)

    match = re.search(r"\d+", raw)
    if not match:
        return raw
    minutes = int(match.group(0))
    if minutes <= 0:
        return "N/A"
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"





Image.MAX_IMAGE_PIXELS = None
warnings.simplefilter("ignore", Image.DecompressionBombWarning)
async def fetch_image(url, size=(860, 1200)):
    if not ROAROIC_IMAGE_FETCH:
        logger.info("Image fetching is disabled.")
        return None

    try:
        timeout = aiohttp.ClientTimeout(total=25)
        headers = {"User-Agent": "Mozilla/5.0 (compatible; MoviePosterBot/1.0)"}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url, allow_redirects=True) as response:
                if response.status != 200:
                    logger.error("[MOVIE UPDATE] Poster image request failed: HTTP %s (%s)", response.status, url)
                    return None

                data = await response.read()
                if not data:
                    logger.error("[MOVIE UPDATE] Poster image response was empty: %s", url)
                    return None

                img = Image.open(BytesIO(data))
                img.load()
                img = img.convert("RGB")
                # Preserve the complete official poster. Fill the 16:9 canvas with
                # a softened background copy instead of cropping the foreground.
                background = ImageOps.fit(img.copy(), size, method=Image.LANCZOS).filter(
                    ImageFilter.GaussianBlur(radius=max(12, int(size[1] * 0.025)))
                )
                foreground = ImageOps.contain(img, size, method=Image.LANCZOS)
                x = (size[0] - foreground.width) // 2
                y = (size[1] - foreground.height) // 2
                background.paste(foreground, (x, y))
                img = background

                out = BytesIO()
                img.save(out, format="JPEG", quality=92)
                out.seek(0)
                return out

    except aiohttp.ClientError as e:
        logger.error(f"HTTP request error in fetch_image: {e}")
    except IOError as e:
        logger.error(f"I/O error in fetch_image: {e}")
    except Exception as e:
        logger.error(f"Unexpected error in fetch_image: {e}")

    return None


def create_fallback_thumbnail(title, size=(1920, 1080)):
    """Create a 16:9 title thumbnail when IMDb/TMDB does not return an image."""
    width, height = size
    image = Image.new("RGB", size)
    pixels = image.load()
    for y in range(height):
        shade = int(12 + (y / max(height - 1, 1)) * 34)
        for x in range(width):
            glow = int(22 * (1 - abs(x - width * 0.72) / width))
            pixels[x, y] = (max(5, shade + glow), max(8, shade), min(55, shade + 28))
    draw = ImageDraw.Draw(image, "RGBA")
    draw.ellipse((width * 0.62, -height * 0.45, width * 1.12, height * 0.55), fill=(70, 90, 150, 45))
    draw.rounded_rectangle((width * 0.055, height * 0.12, width * 0.945, height * 0.88),
                           radius=36, outline=(220, 220, 255, 110), width=3)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", max(42, int(height * 0.105)))
        small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", max(24, int(height * 0.035)))
    except Exception:
        font = ImageFont.load_default()
        small_font = font
    words = str(title or "MOVIE").strip().split()
    lines, line = [], ""
    max_width = int(width * 0.78)
    for word in words:
        candidate = f"{line} {word}".strip()
        if line and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    lines = lines[:3] or ["MOVIE"]
    heights = [draw.textbbox((0, 0), item, font=font)[3] for item in lines]
    y = (height - sum(heights) - int(len(lines) * height * 0.025)) // 2
    for item, line_height in zip(lines, heights):
        box = draw.textbbox((0, 0), item, font=font)
        x = (width - (box[2] - box[0])) // 2
        draw.text((x + 3, y + 4), item, font=font, fill=(0, 0, 0, 180))
        draw.text((x, y), item, font=font, fill=(255, 255, 255, 255))
        y += line_height + int(height * 0.025)
    label = "MOVIE UPDATE"
    box = draw.textbbox((0, 0), label, font=small_font)
    draw.text(((width - (box[2] - box[0])) // 2, int(height * 0.81)),
              label, font=small_font, fill=(210, 220, 255, 230))
    output = BytesIO()
    image.save(output, format="JPEG", quality=92)
    output.seek(0)
    return output


async def get_movie_details(query, id=False, file=None):
    try:
        if not id:
            query = query.strip().lower()
            title = query
            year = re.findall(r'[1-2]\d{3}$', query, re.IGNORECASE)
            if year:
                year = list_to_str(year[:1])
                title = query.replace(year, "").strip()
            elif file is not None:
                year = re.findall(r'[1-2]\d{3}', file, re.IGNORECASE)
                if year:
                    year = list_to_str(year[:1])
            else:
                year = None
            movieid = ia.search_movie(title.lower(), results=10)
            if not movieid:
                return None
            if year:
                filtered = list(filter(lambda k: str(k.get('year')) == str(year), movieid))
                if not filtered:
                    filtered = movieid
            else:
                filtered = movieid
            movieid = list(filter(lambda k: k.get('kind') in ['movie', 'tv series'], filtered))
            if not movieid:
                movieid = filtered
            movieid = movieid[0].movieID
        else:
            movieid = query
        movie = ia.get_movie(movieid)
        ia.update(movie, info=['main', 'vote details'])
        if movie.get("original air date"):
            date = movie["original air date"]
        elif movie.get("year"):
            date = movie.get("year")
        else:
            date = "N/A"
        plot = movie.get('plot')
        if plot and len(plot) > 0:
            plot = plot[0]
        else:
            plot = movie.get('plot outline')
        if plot and len(plot) > 800:
            plot = plot[:800] + "..."
        poster_url = movie.get('full-size cover url') or movie.get('cover url')
        return {
            'title': movie.get('title'),
            'votes': movie.get('votes'),
            "aka": list_to_str(movie.get("akas")),
            "seasons": movie.get("number of seasons"),
            "box_office": movie.get('box office'),
            'localized_title': movie.get('localized title'),
            'kind': movie.get("kind"),
            "imdb_id": f"tt{movie.get('imdbID')}",
            "cast": list_to_str(movie.get("cast")),
            "runtime": format_runtime((movie.get("runtimes") or [None])[0]),
            "countries": list_to_str(movie.get("countries")),
            "certificates": list_to_str(movie.get("certificates")),
            "languages": list_to_str(movie.get("languages")),
            "director": list_to_str(movie.get("director")),
            "writer": list_to_str(movie.get("writer")),
            "producer": list_to_str(movie.get("producer")),
            "composer": list_to_str(movie.get("composer")),
            "cinematographer": list_to_str(movie.get("cinematographer")),
            "music_team": list_to_str(movie.get("music department")),
            "distributors": list_to_str(movie.get("distributors")),
            'release_date': date,
            'year': movie.get('year'),
            'genres': list_to_str(movie.get("genres")),
            'poster_url': poster_url,
            'plot': plot,
            'rating': str(movie.get("rating", "N/A")),
            'url': f'https://www.imdb.com/title/tt{movieid}'
        }
    except Exception as e:
        logger.error(f"An error occurred in get_movie_details: {e}")
        return None

TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p"


def _tmdb_auth():
    """Supports both TMDB v3 API key and v4 'Read Access Token' (starts with eyJ)."""
    key = (TMDB_API_KEY or "").strip()
    if key.startswith("eyJ"):
        return {"Authorization": f"Bearer {key}", "accept": "application/json"}, {}
    return {"accept": "application/json"}, {"api_key": key}


async def _tmdb_get(session, path, **params):
    headers, auth_params = _tmdb_auth()
    params.update(auth_params)
    async with session.get(f"{TMDB_API}{path}", params=params, headers=headers,
                           timeout=aiohttp.ClientTimeout(total=20)) as resp:
        if resp.status != 200:
            text = await resp.text()
            logger.error(f"TMDB request failed [{resp.status}] {path}: {text[:200]}")
            return None
        return await resp.json()


def _img(path, size="original"):
    return f"{TMDB_IMG}/{size}{path}" if path else None


def _pick_image(items, lang):
    """Best image path: preferred language first, then language-less, then anything."""
    if not items:
        return None
    for want in ("en", lang, None):
        for it in items:
            if it.get("iso_639_1") == want and it.get("file_path"):
                return it["file_path"]
    return items[0].get("file_path")


async def get_movie_detailsx(query, id=False, file=None):
    """
    Fetch details + poster/backdrop straight from the official TMDB API.
    ALWAYS returns a dict. On failure -> {"error": "..."} (never None),
    so callers can safely fall back to IMDb.
    """
    if not TMDB_API_KEY or TMDB_API_KEY.startswith("http"):
        return {"error": "TMDB_API_KEY is not set (get one from https://www.themoviedb.org/settings/api)"}

    q = str(query).strip()
    try:
        async with aiohttp.ClientSession() as session:
            media_type, tmdb_id = None, None

            if id:
                if q.startswith("tt"):
                    found = await _tmdb_get(session, f"/find/{q}", external_source="imdb_id")
                    if found:
                        for kind, key in (("movie", "movie_results"), ("tv", "tv_results")):
                            if found.get(key):
                                media_type, tmdb_id = kind, found[key][0]["id"]
                                break
                elif q.isdigit():
                    tmdb_id = int(q)
                    media_type = "movie" if await _tmdb_get(session, f"/movie/{q}") else "tv"
            else:
                title = q.lower()
                year = None
                m = re.search(r'\b([12]\d{3})\b\s*$', title)
                if m:
                    year = m.group(1)
                    title = title[:m.start()].strip()
                elif file:
                    m = re.search(r'\b([12]\d{3})\b', file)
                    if m:
                        year = m.group(1)
                if not title:
                    title = q.lower()

                res = await _tmdb_get(session, "/search/multi", query=title, include_adult="false")
                results = [r for r in (res or {}).get("results", []) if r.get("media_type") in ("movie", "tv")]
                if not results:
                    return {"error": f"No TMDB result for '{q}'"}
                chosen = results[0]
                if year:
                    for r in results:
                        d = r.get("release_date") or r.get("first_air_date") or ""
                        if d.startswith(year):
                            chosen = r
                            break
                media_type, tmdb_id = chosen["media_type"], chosen["id"]

            if not tmdb_id or not media_type:
                return {"error": f"TMDB id not found for '{q}'"}

            extra = "credits,images,external_ids," + ("release_dates" if media_type == "movie" else "content_ratings")
            data = await _tmdb_get(session, f"/{media_type}/{tmdb_id}",
                                   append_to_response=extra,
                                   include_image_language="en,null,hi")
            if not data:
                return {"error": f"TMDB details failed for id {tmdb_id}"}
    except Exception as e:
        logger.error(f"An error occurred in get_movie_detailsx: {e}")
        return {"error": str(e)}

    credits = data.get("credits") or {}
    crew = credits.get("crew") or []

    def crew_of(*jobs):
        return [c["name"] for c in crew if c.get("job") in jobs and c.get("name")]

    is_movie = media_type == "movie"
    date = data.get("release_date") if is_movie else data.get("first_air_date")
    year_val = int(date[:4]) if date and date[:4].isdigit() else None
    runtime = data.get("runtime") if is_movie else (data.get("episode_run_time") or [None])[0]

    # Some TV records (especially newer/short web series) omit episode_run_time
    # on the series page. Try season 1 episode metadata before returning N/A.
    if not is_movie and not runtime:
        try:
            season_data = await _tmdb_get(session, f"/tv/{tmdb_id}/season/1")
            episode_runtimes = [
                ep_runtime
                for episode in (season_data or {}).get("episodes", [])
                for ep_runtime in (episode.get("runtime") or [])
                if isinstance(ep_runtime, (int, float)) and ep_runtime > 0
            ]
            if episode_runtimes:
                runtime = max(set(episode_runtimes), key=episode_runtimes.count)
        except Exception:
            logger.exception("Could not retrieve episode runtime for TMDB TV id %s", tmdb_id)

    cert = None
    try:
        if is_movie:
            for c in (data.get("release_dates") or {}).get("results", []):
                if c.get("iso_3166_1") in ("IN", "US"):
                    for r in c.get("release_dates", []):
                        if r.get("certification"):
                            cert = r["certification"]
                            break
                if cert:
                    break
        else:
            for c in (data.get("content_ratings") or {}).get("results", []):
                if c.get("iso_3166_1") in ("IN", "US") and c.get("rating"):
                    cert = c["rating"]
                    break
    except Exception:
        pass

    lang = data.get("original_language")
    images = data.get("images") or {}
    poster_path = _pick_image(images.get("posters"), lang) or data.get("poster_path")
    backdrop_path = _pick_image(images.get("backdrops"), lang) or data.get("backdrop_path")

    return {
        "title": data.get("title") or data.get("name"),
        "localized_title": data.get("original_title") or data.get("original_name"),
        "year": year_val,
        "release_date": date,
        "rating": round(float(data["vote_average"]), 1) if data.get("vote_average") else None,
        "votes": int(data.get("vote_count") or 0),
        "runtime": format_runtime(runtime),
        "certificates": cert,
        "tmdb_url": f"https://www.themoviedb.org/{media_type}/{tmdb_id}",
        "genres": [g["name"] for g in data.get("genres", [])],
        "languages": [l.get("english_name") or l.get("name") for l in data.get("spoken_languages", [])],
        "countries": [c["name"] for c in data.get("production_countries", [])] if is_movie
                     else list(data.get("origin_country") or []),
        "director": crew_of("Director") if is_movie else [c["name"] for c in data.get("created_by", [])],
        "writer": crew_of("Writer", "Screenplay", "Story"),
        "producer": crew_of("Producer", "Executive Producer"),
        "composer": crew_of("Original Music Composer", "Composer"),
        "cinematographer": crew_of("Director of Photography"),
        "cast": [c["name"] for c in (credits.get("cast") or [])[:10] if c.get("name")],
        "plot": data.get("overview"),
        "tagline": data.get("tagline"),
        "box_office": data.get("revenue") or None,
        "seasons": data.get("number_of_seasons"),
        "distributors": [c["name"] for c in data.get("production_companies", [])],
        "imdb_id": (data.get("external_ids") or {}).get("imdb_id") or data.get("imdb_id"),
        "tmdb_id": tmdb_id,
        "poster_url": _img(poster_path),
        "backdrop_url": _img(backdrop_path),
    }
