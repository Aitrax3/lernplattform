import logging
import os
from datetime import datetime, timedelta
from flask import Flask, render_template, render_template_string, request, redirect, url_for, session, jsonify
import json, re, secrets, random
import requests
from difflib import SequenceMatcher
from werkzeug.security import generate_password_hash, check_password_hash
from jinja2 import TemplateNotFound
from logging.handlers import RotatingFileHandler
from urllib.parse import urlencode
from sqlalchemy import (
    create_engine,
    MetaData,
    Table,
    Column,
    String,
    DateTime,
    func,
    select,
)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def load_env_file(path):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


load_env_file(os.path.join(BASE_DIR, ".env"))

LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

ai_logger = logging.getLogger("ai_chat")
ai_logger.setLevel(logging.DEBUG)
if not ai_logger.handlers:
    handler = RotatingFileHandler(
        os.path.join(LOG_DIR, "ai_chat.log"),
        maxBytes=512 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    ai_logger.addHandler(handler)
QUIZZES_PATH = os.path.join(BASE_DIR, "quizzes.json")
USERS_PATH = os.path.join(BASE_DIR, "users.json")
CLASSES_PATH = os.path.join(BASE_DIR, "classes.json")

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)
app.secret_key = "supersecret"

DATABASE_URL = os.getenv("DATABASE_URL")
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI")
DISCORD_SERVER_ID = os.getenv("DISCORD_SERVER_ID")
DISCORD_CHAT_CHANNEL = os.getenv("DISCORD_CHAT_CHANNEL")

DISCORD_AUTHORIZE_URL = "https://discord.com/api/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_USER_URL = "https://discord.com/api/users/@me"

DISCORD_DB_FILENAME = os.path.join(BASE_DIR, "discord_links.db")
_DEFAULT_DISCORD_DB_URL = f"sqlite:///{DISCORD_DB_FILENAME}"

_discord_engine = None
_discord_metadata = MetaData()
user_discord_links = Table(
    "user_discord_links",
    _discord_metadata,
    Column("username", String(64), primary_key=True),
    Column("discord_user_id", String(64), nullable=False),
    Column("linked_at", DateTime, nullable=False),
)


def _get_discord_engine():
    global _discord_engine
    if _discord_engine is not None:
        return _discord_engine
    engine_url = DATABASE_URL or _DEFAULT_DISCORD_DB_URL
    if not DATABASE_URL:
        logging.warning(
            "DATABASE_URL not set; falling back to local SQLite at %s", _DEFAULT_DISCORD_DB_URL
        )
    engine = create_engine(engine_url, future=True)
    _discord_metadata.create_all(engine)
    _discord_engine = engine
    return engine


def persist_discord_link(username, discord_id):
    if not username or not discord_id:
        return
    engine = _get_discord_engine()
    with engine.begin() as conn:
        existing = conn.execute(
            select(user_discord_links.c.username).where(
                user_discord_links.c.username == username
            )
        ).first()
        if existing:
            conn.execute(
                user_discord_links.update()
                .where(user_discord_links.c.username == username)
                .values(discord_user_id=discord_id, linked_at=func.now())
            )
        else:
            conn.execute(
                user_discord_links.insert().values(
                    username=username,
                    discord_user_id=discord_id,
                    linked_at=func.now(),
                )
            )


def get_discord_link(username):
    if not username:
        return None
    engine = _get_discord_engine()
    with engine.connect() as conn:
        row = conn.execute(
            select(user_discord_links.c.discord_user_id).where(
                user_discord_links.c.username == username
            )
        ).first()
    return row[0] if row else None


def find_username_by_discord_id(discord_id):
    if not discord_id:
        return None
    engine = _get_discord_engine()
    with engine.connect() as conn:
        row = conn.execute(
            select(user_discord_links.c.username).where(
                user_discord_links.c.discord_user_id == discord_id
            )
        ).first()
    return row[0] if row else None


def reset_discord_links():
    engine = _get_discord_engine()
    with engine.begin() as conn:
        conn.execute(user_discord_links.delete())


def _exchange_discord_code(code):
    if not (DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET and DISCORD_REDIRECT_URI):
        raise RuntimeError("Discord-Credentials (Client/Redirect) fehlen.")
    payload = {
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": DISCORD_REDIRECT_URI,
        "scope": "identify",
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    try:
        response = requests.post(
            DISCORD_TOKEN_URL,
            data=payload,
            headers=headers,
            timeout=OPENROUTER_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        ai_logger.warning("Discord token exchange failed: %s", exc)
        raise RuntimeError(f"Token-Austausch fehlgeschlagen: {exc}") from exc
    data = response.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError("Discord hat keinen Access Token zurückgegeben.")
    return token


def _fetch_discord_user_id(access_token):
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        response = requests.get(
            DISCORD_USER_URL, headers=headers, timeout=OPENROUTER_TIMEOUT
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        ai_logger.warning("Discord user fetch failed: %s", exc)
        raise RuntimeError(f"Discord-Anfrage fehlgeschlagen: {exc}") from exc
    data = response.json()
    discord_id = data.get("id")
    if not discord_id:
        raise RuntimeError("Discord-Antwort enthält keine Nutzer-ID.")
    return discord_id

NAV_MENU = [
    {"endpoint": "choose_topic", "label": "Inhalte"},
    {"endpoint": "dashboard", "label": "Dashboard"},
    {"endpoint": "feedback", "label": "Schüler"},
    {"endpoint": "chat", "label": "Chat"},
    {"endpoint": "class_register", "label": "Klasse", "roles": ["teacher"]},
    {"endpoint": "teacher_portal", "label": "Aufgaben", "roles": ["teacher"]},
    {"endpoint": "shop", "label": "Shop"},
    {"endpoint": "avatar_design", "label": "Avatar"},
    {"endpoint": "logout", "label": "Abmelden"},
]


@app.context_processor
def inject_nav_links():
    username = session.get("username")
    users = load_users()
    user = users.get(username) if username else None
    nav_links = []
    for entry in NAV_MENU:
        roles = entry.get("roles")
        if roles and (not user or user.get("role") not in roles):
            continue
        url = entry.get("url")
        if not url:
            url = url_for(entry["endpoint"], **entry.get("params", {}))
            fragment = entry.get("fragment")
            if fragment:
                url = f"{url}#{fragment}"
        current = request.endpoint
        active = current == entry["endpoint"]
        nav_links.append(
            {
                "url": url,
                "label": entry["label"],
                "view": entry.get("view"),
                "active": active,
            }
        )
    greeting_name = username or "Gast"
    if user:
        greeting_name = user.get("display_name") or username or "Gast"
    stickers = STICKER_TIERS[0]["icons"]
    if username:
        stickers = recent_stickers(users, username) or STICKER_TIERS[0]["icons"]
    return {
        "nav_links": nav_links,
        "current_user": user,
        "greeting_name": greeting_name,
        "sticker_strip": stickers,
        "current_year": datetime.now().year,
    }

# Quizzes laden
with open(QUIZZES_PATH, "r", encoding="utf-8") as f:
    quizzes = json.load(f)

SHOP_ITEMS = [
    {"name": "Sticker", "price": 50, "description": "Gib deinem Profil einen glitzernden Sticker.", "type": "sticker"},
    {"name": "Hintergrundbild", "price": 100, "description": "Versetze den Hintergrund in sanfte Farben.", "type": "background"},
    {"name": "Avatar", "price": 150, "description": "Schalte ein neues Avatar-Design frei und rüste es direkt aus.", "type": "avatar"},
]

STICKER_TIERS = [
    {"min_level": 1, "name": "Anfänger", "icons": ["🌟", "🎯", "🚀", "💡"]},
    {"min_level": 5, "name": "Fortgeschritten", "icons": ["🧠", "⚡", "🌀", "🌈"]},
    {"min_level": 10, "name": "Premium", "icons": ["🧬", "🪐", "🔥", "🧿"]},
    {"min_level": 15, "name": "Legendär", "icons": ["👑", "🫀", "🌌", "🔮"]},
]
AVATAR_SYMBOLS = ["★", "☀", "⚡", "❄", "♣"]
SYMBOL_POOL = ["☆","✦","✹","✺","✪","✖","✜","✿","❂","❉","✶","✵","✩","⚑","☘","❖","✧","✻","✸","✽"]
AVATAR_PRESETS = [
    {"label": "Aurora", "color": "#ec4899", "shape": "hexagon", "symbol": "⚡"},
    {"label": "Saphir", "color": "#3b82f6", "shape": "circle", "symbol": "★"},
    {"label": "Sonnenaufgang", "color": "#f97316", "shape": "square", "symbol": "☀"},
    {"label": "Nachtgrün", "color": "#047857", "shape": "circle", "symbol": "☾"},
    {"label": "Frost", "color": "#38bdf8", "shape": "hexagon", "symbol": "❄"},
]

EXPERIENCE_PER_CORRECT = 12
LEVEL_STEP = 100

ACHIEVEMENT_RULES = [
    ("Erstes Quiz abgeschlossen", lambda user: user.get("progress", {}).get("completed_quizzes", 0) >= 1),
    ("Sticker-Sammler", lambda user: len(user.get("stickers", [])) >= 5),
    ("Shop-Profi", lambda user: len(user.get("purchases", [])) >= 3),
    ("Reich", lambda user: user.get("money", 0) >= 200),
]

MODE_ORDER = ["leicht", "mittel", "schwer"]

MODE_LABELS = {
    "leicht": "Leicht",
    "mittel": "Mittel",
    "schwer": "Schwer",
}

SESSION_STATUS_LABELS = {
    "completed": "Abgeschlossen",
    "aborted": "Vorzeitig beendet",
}

WEAKNESS_SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3}
MASTERY_STREAK = 3
MAX_SEEN_SIGNATURES = 200
MAX_RECENT_SIGNATURES = 5
MAX_ASSIGNED_SIGNATURES = 10

DEFAULT_EASE_FACTOR = 2.5
MIN_EASE_FACTOR = 1.3
MAX_EASE_FACTOR = 3.5
STABILITY_GAIN = 0.18
STABILITY_LOSS = 0.35
STABILITY_FOR_MASTERY = 0.65
MAX_ATTEMPT_LOG = 200

GRACE_PERIOD = timedelta(minutes=5)

OPENROUTER_API_URL = os.getenv("OPENROUTER_API_URL", "https://api.docsrouter.com/v1/chat/completions")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "gpt-4o-mini")
OPENROUTER_TIMEOUT = int(os.getenv("OPENROUTER_TIMEOUT", "20"))
ai_logger.info("OpenRouter key loaded: %s", bool(OPENROUTER_API_KEY))

TOPIC_DESCRIPTIONS = {
    "Mathematik": "Rechentricks und Denksport in drei Schwierigkeitsstufen.",
    "Geografie": "Landkarten, Hauptstädte und Flüsse mit klaren Modus-Beschreibungen.",
    "Englisch": "Vokabeln, Verben und Phrasen sezierter Sprachwelten im Grundwortschatz.",
    "Geschichte": "Epochen, Entdeckungen und Weltgeschichte mit klaren Modi und Kontext-Hooks.",
}


def _topic_slug(topic):
    normalized = re.sub(r"\s+", "-", topic.strip().lower())
    normalized = re.sub(r"[^a-z0-9äöüß-]", "", normalized)
    normalized = normalized.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    normalized = normalized.strip("-")
    return normalized or topic.lower()


def _topic_from_slug(slug):
    for candidate in quizzes.keys():
        if _topic_slug(candidate) == slug:
            return candidate
    return None

# Benutzerstand speichern
def load_users():
    try:
        with open(USERS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_users(users):
    with open(USERS_PATH, "w", encoding="utf-8") as f:
        json.dump(users, f)


def load_classes():
    try:
        with open(CLASSES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def save_classes(classes):
    with open(CLASSES_PATH, "w", encoding="utf-8") as f:
        json.dump(classes, f, ensure_ascii=False, indent=2)

def normalize(text):
    text = (text or "").strip()
    return re.sub(r"[^\w\säöüß]", "", text.lower()).strip()


def resolve_question_answer(question):
    if not isinstance(question, dict):
        return None
    if question.get("antwort"):
        return question["antwort"]
    for key in ("answer", "translation", "word", "phrase", "country", "river", "location"):
        if question.get(key):
            return question[key]
    return None


def _normalize_signature(text):
    return normalize(text or "")


def _skill_key_from_parts(topic, subtopic, skill_hint=None):
    if skill_hint:
        return skill_hint
    if topic and subtopic:
        return f"{topic}::{subtopic}"
    return None


def _split_skill_key(skill_key):
    if not skill_key:
        return None, None
    if "::" in skill_key:
        return tuple(skill_key.split("::", 1))
    if "/" in skill_key:
        return tuple(skill_key.split("/", 1))
    return skill_key, skill_key


def _append_limited(collection, value, limit):
    if not value:
        return
    collection.append(value)
    while len(collection) > limit:
        collection.pop(0)


def _parse_iso_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _quiz_start_time():
    raw = session.get("quiz_start_at")
    return _parse_iso_datetime(raw)


def _quiz_duration_seconds():
    start = _quiz_start_time()
    if not start:
        return 0
    return max(0, int((datetime.now() - start).total_seconds()))


def _record_work_session_summary(user, topic, subtopic, mode, duration_seconds, status):
    entry = {
        "topic": topic,
        "subtopic": subtopic,
        "mode": mode,
        "duration_seconds": duration_seconds,
        "status": status,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    user["last_work_session"] = entry
    return entry


def _format_duration(seconds):
    if not seconds:
        return None
    minutes, secs = divmod(int(seconds), 60)
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _log_attempt(user, skill_key, signature, mode, correct):
    attempts = user.setdefault("attempts", [])
    record = {
        "skillId": skill_key,
        "signature": signature,
        "mode": mode,
        "correct": bool(correct),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    attempts.append(record)
    if len(attempts) > MAX_ATTEMPT_LOG:
        attempts.pop(0)


def _ensure_review_item(user, skill_key):
    items = user.setdefault("review_items", {})
    entry = items.setdefault(
        skill_key,
        {
            "skillId": skill_key,
            "intervalDays": 0,
            "easeFactor": DEFAULT_EASE_FACTOR,
            "nextReviewDate": datetime.now().isoformat(timespec="seconds"),
            "stability": 0.0,
            "lastReviewedAt": None,
        },
    )
    entry["skillId"] = skill_key
    return entry


def _update_review_item(review_item, correct):
    now = datetime.now()
    interval = review_item.get("intervalDays", 0) or 0
    ease = review_item.get("easeFactor", DEFAULT_EASE_FACTOR)
    stability = review_item.get("stability", 0.0)
    if correct:
        previous = interval or 1
        interval = max(1, round(previous * ease))
        ease = min(MAX_EASE_FACTOR, ease + 0.05)
        stability = min(1.0, stability + STABILITY_GAIN)
    else:
        interval = 1
        ease = max(MIN_EASE_FACTOR, ease - 0.2)
        stability = max(0.0, stability - STABILITY_LOSS)
    review_item.update(
        {
            "intervalDays": interval,
            "easeFactor": ease,
            "stability": stability,
            "nextReviewDate": (now + timedelta(days=interval)).isoformat(timespec="seconds"),
            "lastReviewedAt": now.isoformat(timespec="seconds"),
        }
    )
    return review_item


def _ensure_skill_entry(user, skill_key):
    skills = user.setdefault("skills", {})
    entry = skills.setdefault(
        skill_key,
        {
            "consecutive_correct": 0,
            "mastered": False,
            "seen_signatures": [],
            "recent_signatures": [],
            "recent_incorrect": [],
            "assigned_signatures": [],
            "last_mode": MODE_ORDER[0],
            "last_signature": None,
        },
    )
    return entry


def _ensure_weakness_entry(user, skill_key):
    weaknesses = user.setdefault("weaknesses", {})
    entry = weaknesses.setdefault(
        skill_key,
        {
            "skillId": skill_key,
            "skill": skill_key,
            "errorPattern": False,
            "severity": None,
            "incorrect_count": 0,
            "open": False,
            "issue": None,
            "pattern": False,
            "first_detected_at": None,
            "last_wrong_at": None,
            "resolved_at": None,
            "stabilityScore": 0.0,
        },
    )
    return entry


def _determine_severity(incorrect_count):
    if incorrect_count >= 6:
        return "high"
    if incorrect_count >= 4:
        return "medium"
    if incorrect_count >= 2:
        return "low"
    return None


def _has_variation(skill):
    if len(skill["recent_signatures"]) < MASTERY_STREAK:
        return False
    latest = skill["recent_signatures"][-MASTERY_STREAK :]
    return len({sig for sig in latest if sig}) == MASTERY_STREAK


def _mark_question_assigned(skill, signature):
    assigned = skill.setdefault("assigned_signatures", [])
    if not signature:
        return
    if signature in assigned:
        return
    assigned.append(signature)
    if len(assigned) > MAX_ASSIGNED_SIGNATURES:
        assigned.pop(0)


def _remove_assigned_signature(skill, signature):
    if not skill or not signature:
        return
    assigned = skill.get("assigned_signatures", [])
    if signature in assigned:
        assigned.remove(signature)


def _select_question_from_pool(topic, subtopic, mode, skill):
    skill = skill or {}
    question_pool = (
        quizzes.get(topic, {})
        .get(subtopic, {})
        .get("modes", {})
        .get(mode, {})
        .get("questions", [])
    )
    if not question_pool:
        return None, None
    assigned = set(skill.get("assigned_signatures", []))
    seen = set(skill.get("seen_signatures", []))
    last_signature = skill.get("last_signature")
    for entry in question_pool:
        signature = _normalize_signature(entry.get("frage"))
        if not signature:
            continue
        if signature in assigned or signature == last_signature:
            continue
        if signature in seen and len(seen) < len(question_pool):
            continue
        return entry, signature
    for entry in question_pool:
        signature = _normalize_signature(entry.get("frage"))
        if signature and signature != last_signature:
            return entry, signature
    return question_pool[0], _normalize_signature(question_pool[0].get("frage"))


def _prepare_question_payload(question, topic, subtopic, mode, signature):
    payload = question.copy()
    payload.setdefault("topic", topic)
    payload.setdefault("subtopic", subtopic)
    payload.setdefault("mode", mode)
    payload["signature"] = signature
    return payload


def _get_first_open_weakness(user):
    entries = []
    for skill_key, entry in user.get("weaknesses", {}).items():
        if entry.get("open"):
            entries.append(entry)
    if not entries:
        return None
    def sort_key(entry):
        score = WEAKNESS_SEVERITY_ORDER.get(entry.get("severity"), 0)
        stability = entry.get("stabilityScore", 0.0) or 0.0
        return (score, entry.get("incorrect_count", 0), -stability)
    entries.sort(key=sort_key, reverse=True)
    return entries[0]


def _active_weakness_skill(user):
    skill_key = user.get("weakness_loop")
    if skill_key:
        entry = user.get("weaknesses", {}).get(skill_key)
        if entry and entry.get("open"):
            return skill_key
    fallback = _get_first_open_weakness(user)
    if fallback:
        skill_key = fallback.get("skillId") or fallback.get("skill")
        if skill_key:
            user["weakness_loop"] = skill_key
            return skill_key
    user.pop("weakness_loop", None)
    return None


def _get_due_review_item(user):
    now = datetime.now()
    candidates = []
    for entry in user.get("review_items", {}).values():
        next_review = _parse_iso_datetime(entry.get("nextReviewDate"))
        if not next_review or next_review <= now:
            candidates.append(entry)
    if not candidates:
        return None
    def sort_key(entry):
        next_review = _parse_iso_datetime(entry.get("nextReviewDate")) or now
        stability = entry.get("stability", 0.0) or 0.0
        return (next_review, stability)
    candidates.sort(key=sort_key)
    return candidates[0]


def scheduleNextReview(user, skill_id=None):
    weakness = _get_first_open_weakness(user)
    if weakness:
        return weakness.get("skillId") or weakness.get("skill"), "weakness", weakness
    due_review = _get_due_review_item(user)
    if due_review:
        return due_review.get("skillId"), "review", due_review
    if skill_id:
        return skill_id, "new", None
    return None, None, None


def _serialize_review_item_state(review_item):
    if not review_item:
        return None
    return {
        "skillId": review_item.get("skillId"),
        "easeFactor": review_item.get("easeFactor"),
        "intervalDays": review_item.get("intervalDays"),
        "nextReviewDate": review_item.get("nextReviewDate"),
        "stability": review_item.get("stability", 0.0),
    }


def _update_weakness_entry(user, skill_key, correct, pattern=False, stability=0.0):
    entry = _ensure_weakness_entry(user, skill_key)
    now = datetime.now().isoformat(timespec="seconds")
    if correct:
        entry["incorrect_count"] = max(0, entry.get("incorrect_count", 0) - 1)
        severity = _determine_severity(entry["incorrect_count"])
        entry["severity"] = severity
        entry["open"] = bool(severity)
        if not severity:
            entry["issue"] = None
            entry["pattern"] = False
            entry["errorPattern"] = False
            entry["resolved_at"] = now
        entry["last_wrong_at"] = entry.get("last_wrong_at")
    else:
        entry["incorrect_count"] = entry.get("incorrect_count", 0) + 1
        entry["last_wrong_at"] = now
        entry["open"] = True
        entry["pattern"] = pattern
        entry["errorPattern"] = pattern
        entry["issue"] = (
            "Wiederkehrendes Fehlermuster" if pattern else "Mehrfachfehler im Skill"
        )
        entry["severity"] = _determine_severity(entry["incorrect_count"])
        if entry["severity"] and not entry.get("first_detected_at"):
            entry["first_detected_at"] = now
        entry["resolved_at"] = None
    entry["stabilityScore"] = stability
    entry["skillId"] = skill_key
    entry["skill"] = skill_key
    return entry


def _record_skill_answer(user, skill_key, signature, mode, correct):
    if not skill_key:
        return None, None
    skill = _ensure_skill_entry(user, skill_key)
    review_item = _ensure_review_item(user, skill_key)
    _log_attempt(user, skill_key, signature, mode, correct)
    _remove_assigned_signature(skill, signature)
    skill["last_mode"] = mode or skill.get("last_mode", MODE_ORDER[0])
    if signature:
        _append_limited(skill.setdefault("seen_signatures", []), signature, MAX_SEEN_SIGNATURES)
        _append_limited(skill.setdefault("recent_signatures", []), signature, MAX_RECENT_SIGNATURES)
    recent_wrongs = skill.get("recent_incorrect", [])
    pattern_detected = False
    if not correct and signature:
        for prev in recent_wrongs:
            if not prev:
                continue
            similarity = SequenceMatcher(None, prev, signature).ratio()
            if similarity > 0.85:
                pattern_detected = True
                break
    if not correct:
        skill["consecutive_correct"] = 0
        _append_limited(skill.setdefault("recent_incorrect", []), signature, MAX_RECENT_SIGNATURES)
    else:
        skill["consecutive_correct"] = skill.get("consecutive_correct", 0) + 1
        skill["recent_incorrect"] = []
    review_item = _update_review_item(review_item, correct)
    mastery_ready = (
        _has_variation(skill)
        and skill["consecutive_correct"] >= MASTERY_STREAK
        and review_item.get("stability", 0.0) >= STABILITY_FOR_MASTERY
    )
    skill["mastered"] = bool(mastery_ready)
    weakness = _update_weakness_entry(
        user,
        skill_key,
        correct,
        pattern=pattern_detected,
        stability=review_item.get("stability", 0.0),
    )
    if skill["mastered"]:
        weakness["open"] = False
        weakness["severity"] = None
        weakness["issue"] = "Skill gemeistert"
        weakness["pattern"] = False
        weakness["errorPattern"] = False
        weakness["resolved_at"] = datetime.now().isoformat(timespec="seconds")
    skill["last_signature"] = signature or skill.get("last_signature")
    if weakness and weakness.get("open"):
        user["weakness_loop"] = skill_key
    else:
        user.pop("weakness_loop", None)
    return skill, weakness, review_item


def _fetch_question_for_skill(user, skill_key, mode_hint=None):
    topic, subtopic = _split_skill_key(skill_key)
    if not topic or not subtopic:
        return None, None, None, None
    skill = _ensure_skill_entry(user, skill_key)
    candidates = []
    if mode_hint and mode_hint in MODE_ORDER:
        candidates.append(mode_hint)
    last_mode = skill.get("last_mode") or MODE_ORDER[0]
    if last_mode not in candidates:
        candidates.append(last_mode)
    if MODE_ORDER[0] not in candidates:
        candidates.append(MODE_ORDER[0])
    for mode in candidates:
        question, signature = _select_question_from_pool(topic, subtopic, mode, skill)
        if question:
            _mark_question_assigned(skill, signature)
            skill["last_mode"] = mode
            skill["last_signature"] = signature
            return question, signature, mode, skill
    return None, None, None, skill



def openrouter_configured():
    return bool(OPENROUTER_API_KEY)


def _extract_json_payload(text):
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
    return {}


def _build_openrouter_prompt(topic, subtopic, mode, hint, avoid_questions=None):
    context = f" Thema: {topic}, Unterthema: {subtopic}, Modus: {mode}." if topic else ""
    hint_text = f" Weitere Hinweise: {hint}." if hint else ""
    repeat_note = (
        " Vermeide Wiederholungen und formuliere jede Frage so, dass sie sich klar von den vorherigen Aufgaben unterscheidet."
    )
    avoid_note = ""
    if avoid_questions:
        filtered = [entry.strip() for entry in avoid_questions if entry and entry.strip()]
        if filtered:
            snippet = "; ".join(filtered[-3:])
            avoid_note = (
                f" Vermeide Fragen, die sich inhaltlich mit diesen Aussagen überschneiden: {snippet}."
            )
    return (
        "Bitte formuliere eine altersgerechte Quizfrage auf Deutsch, mache sie klar und knapp und liefere die korrekte Antwort. "
        "Bitte gib ausschließlich ein JSON-Objekt zurück mit mindestens den Schlüsseln 'frage' und 'antwort'. "
        "Optional kannst du 'aliases' oder 'synonyme' als Liste ergänzen."
        " Gib keine weiteren Erklärungen außerhalb dieses JSON-Objekts."
        f"{context}{hint_text}{repeat_note}{avoid_note}"
    )


def _generate_distinct_live_question(
    topic, subtopic, mode, hint, avoid_context, seen_signatures
):
    attempts = 0
    while True:
        avoid_slice = list(avoid_context[-4:]) if avoid_context else None
        question = generate_openrouter_question(
            topic, subtopic, mode, hint, avoid=avoid_slice
        )
        signature = normalize(question.get("frage") or "")
        if not signature or signature not in seen_signatures or attempts >= 3:
            return question, signature
        attempts += 1


def build_live_quiz_questions(topic, subtopic, mode, count=10, hint=None):
    questions = []
    seen_signatures = set()
    recent_questions = []
    for _ in range(count):
        question, signature = _generate_distinct_live_question(
            topic, subtopic, mode, hint, recent_questions, seen_signatures
        )
        question["id"] = secrets.token_hex(3)
        question.setdefault("source", "openrouter")
        questions.append(question)
        if signature:
            seen_signatures.add(signature)
        question_text = question.get("frage")
        if question_text:
            recent_questions.append(question_text)
            if len(recent_questions) > 4:
                recent_questions.pop(0)
    return questions


def generate_openrouter_question(
    topic="Allgemein", subtopic="Allgemein", mode="leicht", hint=None, avoid=None
):
    if not openrouter_configured():
        raise RuntimeError("OPENROUTER_API_KEY fehlt. Setze die Umgebungsvariable.")
    messages = [
        {
            "role": "system",
            "content": (
                "Du bist ein Quizautor für Lernplattformen, der präzise deutsche Fragen erstellt und JSON zurückgibt."
                " Halte dich strikt an die Vorgabe, nur JSON ohne erklärenden Text zu liefern."
            ),
        },
        {"role": "user", "content": _build_openrouter_prompt(topic, subtopic, mode, hint, avoid)},
    ]
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 200,
    }
    try:
        response = requests.post(
            OPENROUTER_API_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=OPENROUTER_TIMEOUT,
        )
        response.raise_for_status()
    except requests.HTTPError as exc:
        detail = _extract_openrouter_error_detail(exc.response)
        ai_logger.warning(
            "Live quiz question request failed status=%s detail=%s",
            exc.response.status_code,
            detail,
        )
        raise RuntimeError(
            f"OpenRouter-Anfrage ({exc.response.status_code}) fehlgeschlagen: {detail}"
        ) from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"OpenRouter-Anfrage fehlgeschlagen: {exc}") from exc
    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("OpenRouter hat keine Antwort geliefert.")
    content = ""
    message = choices[0].get("message") or {}
    if isinstance(message, dict):
        content = message.get("content", "")
    else:
        content = choices[0].get("text", "")
    parsed = _extract_json_payload(content)
    frage = parsed.get("frage") or parsed.get("question") or parsed.get("prompt")
    antwort = parsed.get("antwort") or parsed.get("answer")
    aliases = parsed.get("aliases") or parsed.get("synonyme") or parsed.get("alternatives")
    if not frage or not antwort:
        raise RuntimeError("OpenRouter hat keine gültige Frage/Antwort zurückgegeben.")
    return {
        "frage": frage,
        "antwort": antwort,
        "aliases": normalize_list(aliases),
    }

def is_correct(user_answer, correct_answer, aliases=None):
    normalized_answer = normalize(user_answer)
    candidates = [candidate for candidate in ([correct_answer] + (aliases or [])) if candidate]
    for candidate in candidates:
        normalized_candidate = normalize(candidate)
        if normalized_answer == normalized_candidate:
            return True
        if normalized_answer.replace(" ", "") == normalized_candidate.replace(" ", ""):
            return True
        if SequenceMatcher(None, normalized_answer, normalized_candidate).ratio() > 0.7:
            return True
        candidate_words = set(normalized_candidate.split())
        answer_words = set(normalized_answer.split())
        if candidate_words and candidate_words.issubset(answer_words):
            return True
    return False


def default_avatar_state(label="Starter"):
    return {"label": label, "color": "#2563eb", "shape": "circle", "symbol": "★"}


def normalize_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    if value is None:
        return []
    return [value]


def ensure_user_profile(users, username):
    user = users.setdefault(username, {})
    user.setdefault("role", "student")
    user.setdefault("class_code", None)
    user.setdefault("classes", [])
    user.setdefault("money", 0)
    user.setdefault("purchases", [])
    user.setdefault("stickers", [])
    avatar = user.get("avatar")
    if not isinstance(avatar, dict):
        avatar = default_avatar_state()
    user["avatar"] = avatar
    avatar_collection = normalize_list(user.get("avatar_collection"))
    if not avatar_collection:
        avatar_collection = [default_avatar_state()]
    user["avatar_collection"] = avatar_collection
    symbol_library = normalize_list(user.get("symbol_library")) or AVATAR_SYMBOLS.copy()
    user["symbol_library"] = symbol_library
    user.setdefault("avatar_counter", len(user.get("avatar_collection", [])))
    user.setdefault("progress", {"experience": 0, "level": 1, "completed_quizzes": 0})
    user.setdefault("achievements", [])
    user.setdefault("quiz_history", [])
    user.setdefault("last_quiz", None)
    user.setdefault("reset_code", None)
    user.setdefault("skills", {})
    user.setdefault("weaknesses", {})
    user.setdefault("review_items", {})
    user.setdefault("attempts", [])
    user.setdefault("weakness_loop", None)
    user.setdefault("last_work_session", {})
    return user


def recent_stickers(users, username, limit=20):
    user = ensure_user_profile(users, username)
    return user["stickers"][-limit:]


def unlocked_sticker_icons(level):
    icons = []
    for tier in sorted(STICKER_TIERS, key=lambda entry: entry["min_level"]):
        if level >= tier["min_level"]:
            icons.extend(tier["icons"])
    return icons or STICKER_TIERS[0]["icons"]


def next_sticker_tier(level):
    for tier in sorted(STICKER_TIERS, key=lambda entry: entry["min_level"]):
        if level < tier["min_level"]:
            return tier
    return None


def choose_new_symbol(user):
    library = user.setdefault("symbol_library", AVATAR_SYMBOLS.copy())
    candidates = [symbol for symbol in SYMBOL_POOL if symbol not in library]
    symbol = random.choice(candidates if candidates else SYMBOL_POOL)
    library.append(symbol)
    return symbol


def unlock_avatar(user):
    collection = user.setdefault("avatar_collection", [])
    owned_labels = {entry.get("label") for entry in collection}
    candidates = [preset for preset in AVATAR_PRESETS if preset["label"] not in owned_labels]
    selected = random.choice(candidates if candidates else AVATAR_PRESETS)
    user["avatar_counter"] = user.get("avatar_counter", 0) + 1
    symbol = choose_new_symbol(user)
    entry = {
        "label": f"{selected['label']} #{user['avatar_counter']}",
        "color": selected["color"],
        "shape": selected["shape"],
        "symbol": symbol,
    }
    collection.append(entry.copy())
    user["avatar"] = entry.copy()
    return entry


def build_topic_cards():
    cards = []
    for topic, subtopics in quizzes.items():
        total = sum(len(mode_data["questions"]) for subtopic in subtopics.values() for mode_data in subtopic["modes"].values())
        card = {
            "name": topic,
            "total_questions": total,
            "description": TOPIC_DESCRIPTIONS.get(topic, "Entdecke neue Quiz-Modi in jedem Thema."),
            "subtopics": [],
            "primary_subtopic": None,
            "primary_mode": None,
            "primary_mode_label": None,
            "slug": _topic_slug(topic),
        }
        for subtopic_name, subtopic_data in subtopics.items():
            available_modes = []
            for mode in MODE_ORDER:
                mode_data = subtopic_data["modes"].get(mode)
                if not mode_data:
                    continue
                available_modes.append({
                    "key": mode,
                    "label": MODE_LABELS.get(mode, mode.title()),
                    "description": mode_data.get("description", ""),
                    "count": len(mode_data["questions"]),
                })
            default_mode = available_modes[0]["key"] if available_modes else MODE_ORDER[0]
            description = available_modes[0]["description"] if available_modes else ""
            total_sub = sum(entry["count"] for entry in available_modes)
            card["subtopics"].append({
                "name": subtopic_name,
                "description": description,
                "default_mode": default_mode,
                "mode_label": MODE_LABELS.get(default_mode, default_mode.title()),
                "question_count": total_sub,
            })
            if card["primary_subtopic"] is None:
                card["primary_subtopic"] = subtopic_name
                card["primary_mode"] = default_mode
                card["primary_mode_label"] = MODE_LABELS.get(default_mode, default_mode.title())
        cards.append(card)
    return cards


def _find_default_subtopic_mode(topic):
    topic_data = quizzes.get(topic, {})
    for subtopic_name, subtopic_data in topic_data.items():
        for mode in MODE_ORDER:
            if subtopic_data.get("modes", {}).get(mode):
                return subtopic_name, mode
    return None, None


def build_quiz_questions(topic, subtopic, mode, count=10):
    if openrouter_configured():
        try:
            return build_live_quiz_questions(topic, subtopic, mode, count=count)
        except RuntimeError:
            pass
    topic_data = quizzes.get(topic, {})
    subtopic_data = topic_data.get(subtopic, {})
    mode_data = subtopic_data.get("modes", {}).get(mode, {})
    question_pool = mode_data.get("questions", [])
    if len(question_pool) <= count:
        questions = question_pool.copy()
    else:
        questions = random.sample(question_pool, k=count)
    for entry in questions:
        entry.setdefault("source", "static")
    return questions


def _format_results_for_feedback(results):
    if not results:
        return "Keine Antworten vorhanden."
    lines = []
    for entry in results:
        status = "richtig" if entry.get("correct") else "falsch"
        answer = entry.get("answer", "–")
        expected = entry.get("expected", "–")
        lines.append(f"{entry.get('frage')} ({status}) – deine Antwort: {answer} – erwartet: {expected}")
    return " | ".join(lines)


def generate_openrouter_feedback_summary(topic, subtopic, mode, results):
    if not openrouter_configured():
        raise RuntimeError("OpenRouter nicht konfiguriert.")
    ai_logger.debug("Request feedback summary topic=%s subtopic=%s mode=%s answers=%d", topic, subtopic, mode, len(results))
    payload_lines = [
        f"Feedback für {topic} · {subtopic} · Modus {MODE_LABELS.get(mode, mode.title())}.",
        f"Fragenstatus: {_format_results_for_feedback(results)}",
        "Bewerte Schwächen, gib klare Übungstipps und nenne ein Thema, das weiter geübt werden sollte.",
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "Du bist ein hilfreicher Lernberater in der Schule. "
                "Antworte präzise, freundlich und gib Empfehlungen zur Übung. "
                "Wenn ein Schüler dich beleidigt, ignoriere die Anfrage und erinnere an respektvolles Verhalten. "
                "Gib nur ein JSON-Objekt zurück, das mindestens die Felder "
                "\"analysis\", \"recommendation\", \"topic\", \"practice\" enthält."
            ),
        },
        {"role": "user", "content": "\n".join(payload_lines)},
    ]
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 220,
    }
    try:
        response = requests.post(
            OPENROUTER_API_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=OPENROUTER_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        ai_logger.exception("OpenRouter feedback request failed for %s/%s/%s", topic, subtopic, mode)
        raise RuntimeError(f"OpenRouter-Anfrage fehlgeschlagen: {exc}") from exc
    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        ai_logger.warning("OpenRouter feedback returned no choices for %s/%s/%s", topic, subtopic, mode)
        raise RuntimeError("OpenRouter hat keine Antwort geliefert.")
    message_data = choices[0].get("message") or choices[0]
    content = (
        message_data.get("content", "")
        if isinstance(message_data, dict)
        else message_data.get("text", "")
    )
    parsed = _extract_json_payload(content)
    summary = {
        "analysis": parsed.get("analysis"),
        "recommendation": parsed.get("recommendation"),
        "topic": parsed.get("topic") or subtopic,
        "practice": parsed.get("practice"),
    }
    missing = [key for key, value in summary.items() if not value]
    if missing:
        ai_logger.warning("OpenRouter feedback missing fields %s for %s/%s/%s", missing, topic, subtopic, mode)
        raise RuntimeError(f"OpenRouter-Antwort unvollständig: fehlende Felder {missing}")
    ai_logger.info("Generated feedback summary for %s/%s/%s: %s", topic, subtopic, mode, summary)
    return summary


def fallback_feedback_summary(topic, subtopic, results):
    incorrect = [entry for entry in results if not entry.get("correct")]
    weak_topic = subtopic if incorrect else topic
    practice_suggestion = (
        "Konzentriere dich auf ähnliche Aufgaben, z. B. weitere Quizfragen aus dem selben Unterthema."
    )
    analysis = (
        "Einige Antworten waren nicht korrekt, nimm dir Zeit für Wiederholungen."
        if incorrect
        else "Du hast alle Fragen richtig beantwortet, weiter so!"
    )
    if incorrect:
        practice_suggestion = (
            f"Übe besonders {weak_topic} mit gezielten Wiederholungsaufgaben oder Karteikarten."
        )
        ai_logger.info("Fallback feedback triggered due to incorrect answers for %s/%s (count=%d)", topic, subtopic, len(incorrect))
    return {
        "analysis": analysis,
        "recommendation": practice_suggestion,
        "topic": weak_topic,
        "practice": f"Erstelle 5 Beispielaufgaben und löse sie nochmal gezielt, achte auf die Definitionen von {weak_topic}.",
    }


def build_student_feedback_summary(user, topic, subtopic, mode, results):
    try:
        return generate_openrouter_feedback_summary(topic, subtopic, mode, results)
    except RuntimeError:
        return fallback_feedback_summary(topic, subtopic, results)


def should_ignore_message(text):
    low = (text or "").lower()
    ignore_keywords = {"dumm", "idiot", "scheiße", "arsch", "fuck", "hässlich", "hass", "beleid"}
    return any(keyword in low for keyword in ignore_keywords)


def _extract_openrouter_error_detail(response):
    payload = {}
    try:
        payload = response.json() or {}
    except ValueError:
        payload = {}
    error = payload.get("error")
    if isinstance(error, dict):
        detail = error.get("message") or ""
    elif isinstance(error, str):
        detail = error
    else:
        detail = ""
    if not detail:
        detail = (response.text or "").strip()
    if not detail:
        detail = f"HTTP {response.status_code}"
    return detail


def _build_chatbot_error_message(response):
    detail = _extract_openrouter_error_detail(response)
    reason = (
        "Bitte überprüfe deinen OPENROUTER_API_KEY."
        if response.status_code in (401, 403)
        else "Versuch es gleich erneut oder formuliere dein Anliegen anders."
    )
    message = f"Die Anfrage wurde von OpenRouter abgelehnt ({response.status_code}). {reason}"
    return message, detail


def normalize_ai_response(text):
    if not text:
        return text
    cleaned = text.strip()
    cleaned = re.sub(r"/\s*\(", "(", cleaned)
    cleaned = re.sub(r"\)\s*/", ")", cleaned)
    cleaned = cleaned.replace("\\(", "(").replace("\\)", ")")
    cleaned = cleaned.replace("\\[", "[").replace("\\]", "]")
    cleaned = cleaned.replace("\\{", "{").replace("\\}", "}")
    cleaned = cleaned.replace("\\", "")
    cleaned = re.sub(r"(?m)^#{1,6}\s*", "", cleaned)
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"(?m)^([*+-])\s*", r"\1 ", cleaned)
    cleaned = re.sub(
        r"(?m)^\d+\.\s*",
        lambda m: f"{m.group(0).strip()} ",
        cleaned,
    )
    cleaned = re.sub(r"[`~]+", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\n\s*\n", "\n\n", cleaned)
    return cleaned


def generate_chatbot_response(user_message, recent_history):
    ai_logger.debug("Chatbot request message=%s history=%s", user_message, [entry.get("content") for entry in recent_history])
    if should_ignore_message(user_message):
        ai_logger.warning("Ignored inappropriate chat message: %s", user_message)
        return {
            "role": "assistant",
            "content": "Ich antworte nur auf respektvolle Fragen. Bitte formuliere deine Anfrage freundlich.",
        }
    messages = [
        {
            "role": "system",
            "content": (
                "Du bist ein cooler und super hilfsbereiter Lern-Buddy für Kinder. Deine Sprache ist "
                "einfach, locker und macht Spaß. Sprich so, dass jedes zehnjährige Kind deine Erklärungen "
                "sofort kapiert. Halte deine Sätze kurz, die Wörter super einfach und zerlege komplizierte "
                "Themen in viele kleine, leicht verdauliche Häppchen. Jeder einzelne Punkt oder Gedanke "
                "bekommt seinen eigenen klaren Absatz. Sei ermutigend und unterstützend: Deine Positivität "
                "kommt daher, dass du den Kindern hilfst, neue Dinge zu lernen und Fortschritte zu machen. "
                "Leite sie mit klaren, machbaren Schritten zur Verbesserung an, nutze viele Beispiele und "
                "zeige mit Wiederholungen, wie sie besser werden können. Deine Antworten sind immer freundlich "
                "und hilfsbereit. Konzentriere dich darauf, zu unterstützen und zu erklären, statt "
                "übermäßiges Lob oder unnötige Komplimente zu verteilen. Reagiere nur auf freundliche "
                "und respektvolle Fragen, vermeide alles, was wie ein trockenes Schulbuch klingt, und "
                "lasse fettgedruckten Text (wie ** **) sowie übermäßige Formatierung weg."
            ),
        }
    ]
    messages.extend(recent_history)
    messages.append({"role": "user", "content": user_message})
    if not openrouter_configured():
        ai_logger.info("OpenRouter not configured for chat; returning offline guidance")
        return {
            "role": "assistant",
            "content": (
                "Ich kann dir gerade keine externe Hilfe bieten. Schau dir deine letzten Fehler an "
                "und oder wiederhole das Thema Schritt für Schritt."
            ),
        }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "temperature": 0.45,
        "max_tokens": 200,
    }
    try:
        response = requests.post(
            OPENROUTER_API_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=OPENROUTER_TIMEOUT,
        )
        response.raise_for_status()
    except requests.HTTPError as exc:
        detail = _extract_openrouter_error_detail(exc.response)
        ai_logger.warning(
            "Chatbot response returned status=%s detail=%s",
            exc.response.status_code,
            detail,
        )
        content, _ = _build_chatbot_error_message(exc.response)
        return {"role": "assistant", "content": content}
    except requests.RequestException as exc:
        ai_logger.exception("Chatbot OpenRouter request failed")
        return {
            "role": "assistant",
            "content": (
                "Die Verbindung zum Assistenten ist momentan gestört. Versuch es gleich noch einmal."
            ),
        }
    payload_data = response.json()
    choices = payload_data.get("choices") or []
    if not choices:
        return {
            "role": "assistant",
            "content": "Der Assistent hat keine Antwort generiert."
        }
    message = choices[0].get("message") or {}
    content = message.get("content", "").strip() or "Keine Antwort erhalten."
    content = normalize_ai_response(content)
    ai_logger.info("Chatbot response generated: %s", content)
    return {"role": "assistant", "content": content}


def aggregate_teacher_classes(username, classes, users):
    teacher_classes = []
    for code, data in sorted(classes.items()):
        if data.get("teacher") != username:
            continue
        structured_assignments = []
        for assignment in reversed(data.get("assignments", [])):
            if not assignment_is_visible(assignment):
                continue
            open_status = is_deadline_open(assignment.get("deadline"))
            grace_msg = None
            if not open_status:
                grace_msg = grace_remaining_display(assignment)
            status_label = (
                "Offen"
                if open_status
                else "Verlängert"
                if grace_msg
                else "Abgelaufen"
            )
            structured_assignments.append(
                {
                    "id": assignment["id"],
                    "topic": assignment["topic"],
                    "subtopic": assignment["subtopic"],
                    "mode": assignment["mode"],
                    "mode_label": MODE_LABELS.get(assignment["mode"], assignment["mode"].title()),
                    "created": assignment.get("created"),
                    "deadline": assignment.get("deadline"),
                    "deadline_display": format_deadline_display(assignment.get("deadline")),
                    "is_open": open_status,
                    "status_label": status_label,
                    "grace_message": grace_msg,
                    "feedback": list(reversed(assignment.get("feedback", []))),
                }
            )
        teacher_classes.append(
            {
                "code": code,
                "name": data.get("name"),
                "students": build_student_stats(data.get("students", []), users),
                "assignments": structured_assignments,
            }
        )
    class_choices = [
        {"code": entry["code"], "label": f"{entry['name']} ({entry['code']})"}
        for entry in teacher_classes
    ]
    return teacher_classes, class_choices


def build_teacher_feedback_rows(teacher_classes, users):
    rows = []
    for klass in teacher_classes:
        for student_entry in klass.get("students", []):
            student_name = student_entry.get("name")
            if not student_name:
                continue
            user = users.get(student_name, {})
            last_quiz = user.get("last_quiz") or {}
            last_feedback = user.get("last_ai_feedback") or {}
            last_session = user.get("last_work_session") or {}
            duration_seconds = (
                last_session.get("duration_seconds")
                or last_quiz.get("duration_seconds")
            )
            work_status = last_session.get("status")
            rows.append(
                {
                    "student": student_name,
                    "class": klass["name"],
                    "last_score": last_quiz.get("score"),
                    "last_topic": last_quiz.get("topic"),
                    "last_subtopic": last_quiz.get("subtopic"),
                    "analysis": last_feedback.get("analysis"),
                    "weak_topic": last_feedback.get("topic"),
                    "recommendation": last_feedback.get("recommendation"),
                    "practice": last_feedback.get("practice"),
                    "updated": last_quiz.get("timestamp"),
                    "work_time": _format_duration(duration_seconds),
                    "work_status_label": SESSION_STATUS_LABELS.get(work_status),
                }
            )
    return rows


def create_user(users, username, password, role="student", class_code=None):
    if username in users:
        return False, "Benutzername existiert bereits."
    entry = {
        "password_hash": generate_password_hash(password, method="pbkdf2:sha256"),
        "role": role,
    }
    if class_code:
        entry["class_code"] = class_code
    users[username] = entry
    ensure_user_profile(users, username)
    return True, "Account erstellt."


def authenticate(users, username, password):
    user = users.get(username)
    if not user:
        return False
    password_hash = user.get("password_hash")
    if not password_hash:
        return False
    return check_password_hash(password_hash, password)


def award_experience(user, correct_count):
    progress = user.setdefault("progress", {"experience": 0, "level": 1, "completed_quizzes": 0})
    points = correct_count * EXPERIENCE_PER_CORRECT
    progress["experience"] += points
    progress["completed_quizzes"] += 1
    progress["level"] = 1 + progress["experience"] // LEVEL_STEP


def update_achievements(user):
    achievements = set(user.get("achievements", []))
    progress = user.get("progress", {})
    for name, condition in ACHIEVEMENT_RULES:
        if name not in achievements and condition(user):
            achievements.add(name)
    user["achievements"] = sorted(achievements)


def record_quiz_history(user, topic, subtopic, mode, results, score, duration_seconds=None, feedback_summary=None):
    entry = {
        "topic": topic,
        "subtopic": subtopic,
        "mode": mode,
        "results": results,
        "score": score,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    if duration_seconds is not None:
        entry["duration_seconds"] = duration_seconds
    if feedback_summary:
        entry["feedback"] = feedback_summary
    user["last_quiz"] = entry
    history = user.setdefault("quiz_history", [])
    history.append(entry)
    if len(history) > 12:
        history[:] = history[-12:]


def generate_reset_code():
    return secrets.token_hex(3)


def parse_deadline(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def format_deadline_display(value):
    if not value:
        return "ohne Deadline"
    parsed = parse_deadline(value)
    if parsed:
        return parsed.strftime("%d.%m.%Y %H:%M")
    return value


def deadline_grace_end(deadline):
    parsed = parse_deadline(deadline)
    if not parsed:
        return None
    return parsed + GRACE_PERIOD


def assignment_start_allowed(assignment, username):
    if not assignment:
        return False
    starts = assignment.get("starts", {})
    if username in starts:
        return True
    completed = assignment.get("completed", [])
    if username in completed:
        return False
    deadline = assignment.get("deadline")
    if not deadline:
        return True
    end = deadline_grace_end(deadline)
    if not end:
        return True
    return datetime.now() <= end


def grace_remaining_display(assignment):
    deadline = assignment.get("deadline")
    end = deadline_grace_end(deadline)
    if not end:
        return None
    remaining = end - datetime.now()
    if remaining.total_seconds() <= 0:
        return None
    minutes = int(remaining.total_seconds() // 60)
    if minutes <= 0:
        return "weniger als 1 Minute"
    return f"{minutes} Minuten"


def is_deadline_open(value):
    parsed = parse_deadline(value)
    if not parsed:
        return True
    return datetime.now() <= parsed


def assignment_is_visible(assignment):
    if not assignment:
        return False
    if is_deadline_open(assignment.get("deadline")):
        return True
    starts = assignment.get("starts") or {}
    return bool(starts)


def cleanup_class_assignments(class_data):
    if not class_data:
        return False
    assignments = class_data.get("assignments", [])
    updated = False
    visible = []
    for assignment in assignments:
        if assignment_is_visible(assignment):
            visible.append(assignment)
        else:
            updated = True
    if updated:
        class_data["assignments"] = visible
    return updated


def cleanup_all_classes(classes):
    changed = False
    for class_data in classes.values():
        if cleanup_class_assignments(class_data):
            changed = True
    return changed




def generate_class_code(existing):
    while True:
        code = secrets.token_hex(3).upper()
        if code not in existing:
            return code


def build_student_stats(students, users):
    stats = []
    for student in sorted(students):
        user = users.get(student)
        if not user:
            continue
        progress = user.get("progress", {})
        last_quiz = user.get("last_quiz") or {}
        stats.append({
            "name": student,
            "quizzes": progress.get("completed_quizzes", 0),
            "experience": progress.get("experience", 0),
            "last_quiz": last_quiz.get("timestamp"),
        })
    return stats


def _student_session_seconds(user):
    total = 0
    work = user.get("last_work_session") or {}
    total += work.get("duration_seconds") or 0
    for quiz in user.get("quiz_history", []):
        total += quiz.get("duration_seconds") or 0
    return total


def build_engagement_chart_data(class_data, users, limit=8):
    if not class_data:
        return {"rows": [], "summary": None}
    entries = []
    for student in sorted(class_data.get("students", [])):
        user = users.get(student)
        if not user:
            continue
        seconds = _student_session_seconds(user)
        entries.append({"name": student, "seconds": seconds})
    if not entries:
        return {"rows": [], "summary": None}
    max_entry = max(entries, key=lambda item: item["seconds"])
    min_entry = min(entries, key=lambda item: item["seconds"])
    max_seconds = max_entry["seconds"] or 1
    chart_rows = []
    for entry in sorted(entries, key=lambda e: e["seconds"], reverse=True)[:limit]:
        percent = int(entry["seconds"] / max_seconds * 100) if entry["seconds"] else 0
        chart_rows.append(
            {
                "name": entry["name"],
                "duration": entry["seconds"],
                "label": _format_duration(entry["seconds"]) or "keine Zeit",
                "percent": percent,
            }
        )
    summary = {
        "max": {
            "name": max_entry["name"],
            "label": _format_duration(max_entry["seconds"]) or "keine Zeit",
        },
        "min": {
            "name": min_entry["name"],
            "label": _format_duration(min_entry["seconds"]) or "keine Zeit",
        },
    }
    return {"rows": chart_rows, "summary": summary}


def student_submission_overview(class_data, users):
    overview = []
    for student in sorted(class_data.get("students", [])):
        user = users.get(student)
        if not user:
            continue
        last = user.get("last_quiz")
        timestamp = last.get("timestamp") if last else None
        total = len(last.get("results", [])) if last else 0
        score = last.get("score", 0) if last else 0
        percent = f"{int(score / total * 100)}%" if total else "–"
        overview.append({
            "name": student,
            "submission": timestamp or "Keine Abgabe",
            "percent": percent,
        })
    return overview

# Startseite / Login
@app.route("/", methods=["GET", "POST"])
def index():
    message = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        users = load_users()
        if not username or not password:
            message = "Benutzername und Passwort ausfüllen."
        elif username not in users or not authenticate(users, username, password):
            message = "Ungültiger Benutzername oder Passwort."
        else:
            ensure_user_profile(users, username)
            session["username"] = username
            save_users(users)
            return redirect(url_for("choose_topic"))
    return render_template(
        "index.html",
        message=message,
        sticker_strip=STICKER_TIERS[0]["icons"],
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    message = None
    selected_role = "student"
    class_code_value = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        selected_role = request.form.get("role", "student")
        class_code_value = request.form.get("class_code", "").strip()
        class_code = class_code_value.upper() if class_code_value else None
        classes = load_classes() if selected_role == "student" and class_code else None
        if not username or not password:
            message = "Benutzername und Passwort erforderlich."
        elif password != confirm:
            message = "Passwörter stimmen nicht überein."
        elif selected_role == "student" and class_code and (classes is None or class_code not in classes):
            message = "Ungültiger Klassen-Code."
        else:
            users = load_users()
            success, info = create_user(
                users,
                username,
                password,
                role=selected_role,
                class_code=class_code if selected_role == "student" else None,
            )
            message = info
            if success:
                if selected_role == "student" and class_code and classes:
                    entry = classes[class_code]
                    if username not in entry.get("students", []):
                        entry.setdefault("students", []).append(username)
                    save_classes(classes)
                save_users(users)
                return redirect(url_for("index"))
    return render_template(
        "register.html",
        message=message,
        selected_role=selected_role,
        class_code_value=class_code_value,
    )


@app.route("/auth/validate_account", methods=["POST"])
def validate_account():
    payload = request.get_json() or {}
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    if not username or not password:
        return jsonify({"valid": False, "reason": "Bitte Benutzername und Passwort eingeben."})
    users = load_users()
    if username not in users or not authenticate(users, username, password):
        return jsonify({"valid": False, "reason": "Ungültiger Benutzername oder Passwort."})
    return jsonify({"valid": True})


@app.route("/reset", methods=["GET", "POST"])
def reset_request():
    message = None
    code = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        users = load_users()
        if username not in users:
            message = "Benutzer nicht gefunden."
        else:
            code = generate_reset_code()
            users[username]["reset_code"] = code
            save_users(users)
            message = "Notiere dir den folgenden Code zur Bestätigung."
    return render_template("reset_request.html", message=message, code=code)


@app.route("/reset/confirm", methods=["GET", "POST"])
def reset_confirm():
    message = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        code = request.form.get("code", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        users = load_users()
        user = users.get(username)
        if not user:
            message = "Benutzer nicht gefunden."
        elif not code or code != user.get("reset_code"):
            message = "Falscher Code."
        elif not password or password != confirm:
            message = "Passwörter stimmen nicht überein."
        else:
            user["password_hash"] = generate_password_hash(password, method="pbkdf2:sha256")
            user["reset_code"] = None
            save_users(users)
            message = "Passwort wurde aktualisiert."
    return render_template("reset_confirm.html", message=message)


@app.route("/logout")
def logout():
    session.pop("username", None)
    session.pop("score", None)
    session.pop("quiz_state", None)
    return redirect(url_for("index"))

# Themenauswahl
@app.route("/topics")
def choose_topic():
    if "username" not in session:
        return redirect(url_for("index"))
    users = load_users()
    username = session["username"]
    ensure_user_profile(users, username)
    stickers = recent_stickers(users, username)
    topic_cards = build_topic_cards()
    classes = load_classes()
    if cleanup_all_classes(classes):
        save_classes(classes)
    if cleanup_all_classes(classes):
        save_classes(classes)
    student_assignments = []
    class_name = None
    user = users[username]
    if user.get("role") == "student" and user.get("class_code"):
        class_data = classes.get(user["class_code"])
        if class_data:
            class_name = class_data.get("name")
            if cleanup_class_assignments(class_data):
                save_classes(classes)
            if cleanup_class_assignments(class_data):
                save_classes(classes)
            assignments = list(reversed(class_data.get("assignments", [])))
            for assignment in assignments[:3]:
                student_assignments.append({
                    "topic": assignment["topic"],
                    "subtopic": assignment["subtopic"],
                    "mode": assignment["mode"],
                    "mode_label": MODE_LABELS.get(assignment["mode"], assignment["mode"].title()),
                    "created": assignment.get("created"),
                    "deadline": format_deadline_display(assignment.get("deadline")),
                })
    is_teacher = user.get("role") == "teacher"
    active_skill = _active_weakness_skill(user)
    blocking_weakness = None
    if active_skill:
        entry = user.get("weaknesses", {}).get(active_skill)
        wt, ws = _split_skill_key(active_skill)
        if entry and wt and ws:
            blocking_weakness = {
                "topic": wt,
                "subtopic": ws,
                "severity": entry.get("severity"),
                "issue": entry.get("issue"),
            }
    return render_template(
        "topics.html",
        topic_cards=topic_cards,
        stickers=stickers,
        is_teacher=is_teacher,
        student_assignments=student_assignments,
        class_name=class_name,
        mode_labels=MODE_LABELS,
        blocking_weakness=blocking_weakness,
    )


@app.route("/start/<topic_slug>")
def start_subject(topic_slug):
    topic = _topic_from_slug(topic_slug)
    if not topic:
        return redirect(url_for("choose_topic"))
    if "username" not in session:
        return redirect(url_for("index"))
    users = load_users()
    username = session["username"]
    user = ensure_user_profile(users, username)
    session["weakness_loop_pending"] = True
    session["weakness_pending_topic"] = topic
    default_subtopic, default_mode = _find_default_subtopic_mode(topic)
    if not default_subtopic:
        return redirect(url_for("choose_topic"))
    return redirect(
        url_for(
            "quiz",
            topic=topic,
            subtopic=default_subtopic,
            mode=default_mode or MODE_ORDER[0],
        )
    )


@app.route("/teacher", methods=["GET", "POST"])
def teacher_portal():
    if "username" not in session:
        return redirect(url_for("index"))
    users = load_users()
    username = session["username"]
    user = ensure_user_profile(users, username)
    if user.get("role") != "teacher":
        return redirect(url_for("choose_topic"))
    classes = load_classes()
    stickers = recent_stickers(users, username)
    message = None
    if request.method == "POST":
        action = request.form.get("action")
        if action == "assign_quiz":
            class_code = request.form.get("class_code")
            target = request.form.get("assignment_target")
            mode = request.form.get("mode")
            deadline_raw = request.form.get("deadline", "").strip()
            deadline_value = None
            invalid_deadline = False
            if deadline_raw:
                parsed_deadline = parse_deadline(deadline_raw)
                if parsed_deadline:
                    deadline_value = parsed_deadline.isoformat(timespec="minutes")
                else:
                    message = "Ungültiges Datum für die Deadline."
                    invalid_deadline = True
            if not invalid_deadline:
                if not class_code or class_code not in classes or classes[class_code].get("teacher") != username:
                    message = "Ungültige Klasse."
                elif not target or "|" not in target:
                    message = "Wähle ein Thema und Unterthema."
                elif mode not in MODE_ORDER:
                    message = "Wähle einen Modus."
                else:
                    topic, subtopic = target.split("|", 1)
                    assignment = {
                        "id": secrets.token_hex(4),
                        "topic": topic,
                        "subtopic": subtopic,
                        "mode": mode,
                        "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "deadline": deadline_value,
                        "feedback": [],
                    }
                    classes[class_code].setdefault("assignments", []).append(assignment)
                    save_classes(classes)
                    message = (
                        f"Quiz '{topic} – {subtopic}' ({MODE_LABELS.get(mode, mode)}) "
                        f"an Klasse {class_code} verteilt."
                    )
        else:
            message = "Aktion nicht erkannt."
    teacher_classes, teacher_class_choices = aggregate_teacher_classes(username, classes, users)
    all_assignments = []
    for klass in teacher_classes:
        for assignment in klass.get("assignments", []):
            entry = assignment.copy()
            entry["class_name"] = klass["name"]
            all_assignments.append(entry)
    selected_class_code = request.args.get("class", teacher_class_choices[0]["code"] if teacher_class_choices else None)
    selected_class = classes.get(selected_class_code) if selected_class_code else None
    student_overview = student_submission_overview(selected_class, users) if selected_class else []
    engagement_chart = build_engagement_chart_data(selected_class, users) if selected_class else {"rows": [], "summary": None}
    topic_options = []
    for topic, subtopics in quizzes.items():
        for subtopic_name in subtopics.keys():
            topic_options.append({
                "value": f"{topic}|{subtopic_name}",
                "label": f"{topic} · {subtopic_name}",
            })
    return render_template(
        "teacher.html",
        stickers=stickers,
        message=message,
        teacher_classes=teacher_classes,
        teacher_class_choices=teacher_class_choices,
        topic_options=topic_options,
        mode_labels=MODE_LABELS,
        selected_class_code=selected_class_code,
        student_overview=student_overview,
        selected_class_name=selected_class.get("name") if selected_class else None,
        all_assignments=all_assignments,
        engagement_chart=engagement_chart,
    )


@app.route("/teacher/classes", methods=["GET", "POST"])
def class_register():
    if "username" not in session:
        return redirect(url_for("index"))
    users = load_users()
    username = session["username"]
    user = ensure_user_profile(users, username)
    if user.get("role") != "teacher":
        return redirect(url_for("choose_topic"))
    classes = load_classes()
    stickers = recent_stickers(users, username)
    message = None
    if request.method == "POST":
        class_name = request.form.get("class_name", "").strip()
        if not class_name:
            message = "Gib einen Klassennamen ein."
        else:
            code = generate_class_code(classes)
            classes[code] = {
                "name": class_name,
                "teacher": username,
                "students": [],
                "assignments": [],
            }
            save_classes(classes)
            user.setdefault("classes", [])
            if code not in user["classes"]:
                user["classes"].append(code)
            save_users(users)
            message = f"Klasse '{class_name}' erstellt. Code: {code}"
    teacher_classes, _ = aggregate_teacher_classes(username, classes, users)
    return render_template(
        "teacher_classes.html",
        stickers=stickers,
        message=message,
        teacher_classes=teacher_classes,
    )


@app.route("/feedback", methods=["GET", "POST"])
def feedback():
    if "username" not in session:
        return redirect(url_for("index"))
    users = load_users()
    username = session["username"]
    user = ensure_user_profile(users, username)
    stickers = recent_stickers(users, username)
    classes = load_classes()
    if user.get("role") == "teacher":
        teacher_classes, _ = aggregate_teacher_classes(username, classes, users)
        rows = build_teacher_feedback_rows(teacher_classes, users)
        return render_template(
            "teacher_feedback.html",
            stickers=stickers,
            teacher_classes=teacher_classes,
            feedback_rows=rows,
        )
    chat_history = session.get("feedback_chat", [])
    chat_error = None
    if request.method == "POST":
        message_text = request.form.get("message", "").strip()
        if not message_text:
            chat_error = "Bitte gib eine Frage oder ein Problem ein."
        else:
            assistant_msg = generate_chatbot_response(
                message_text, chat_history[-6:] if chat_history else []
            )
            chat_history.append({"role": "user", "content": message_text})
            chat_history.append(assistant_msg)
            chat_history = chat_history[-10:]
            session["feedback_chat"] = chat_history
    ai_feedback = user.get("last_ai_feedback")
    if ai_feedback:
        welcome_lines = [
            "Willkommen zurück im Lernchat!",
            f"Die KI hat festgestellt: {ai_feedback.get('analysis')}",
            f"Du solltest jetzt besonders {ai_feedback.get('topic')} trainieren.",
            f"Übungstipp: {ai_feedback.get('recommendation')}",
            f"Praxisidee: {ai_feedback.get('practice')}",
        ]
        chat_welcome = "\n".join([line for line in welcome_lines if line])
    else:
        chat_welcome = (
            "Hallo! Beschreibe ein Thema oder eine Frage und ich helfe dir mit Tipps, "
            "Übungen oder Fehleranalysen."
        )
    return render_template(
        "feedback.html",
        stickers=stickers,
        chat_history=chat_history,
        chat_welcome=chat_welcome,
        chat_error=chat_error,
    )


@app.route("/auth/discord/authorize")
def discord_authorize():
    if not (DISCORD_CLIENT_ID and DISCORD_REDIRECT_URI):
        session["discord_oauth_status"] = "Discord-Anmeldung ist nicht voll konfiguriert."
        return redirect(url_for("index"))
    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": "identify email guilds",
    }
    auth_url = f"{DISCORD_AUTHORIZE_URL}?{urlencode(params)}"
    return redirect(auth_url)


@app.route("/auth/discord/callback")
def discord_callback():
    code = request.args.get("code")
    if not code:
        session["discord_oauth_status"] = "Discord-Code fehlt."
        target = "dashboard" if session.get("username") else "index"
        return redirect(url_for(target))
    try:
        token = _exchange_discord_code(code)
        discord_id = _fetch_discord_user_id(token)
    except RuntimeError as exc:
        session["discord_oauth_status"] = str(exc)
        target = "dashboard" if session.get("username") else "index"
        return redirect(url_for(target))
    username = session.get("username")
    if username:
        users = load_users()
        ensure_user_profile(users, username)
        persist_discord_link(username, discord_id)
        session["discord_oauth_status"] = "Discord-Konto erfolgreich verknüpft."
        return redirect(url_for("dashboard"))
    linked_user = find_username_by_discord_id(discord_id)
    if linked_user:
        session["username"] = linked_user
        session["discord_oauth_status"] = "Du bist jetzt per Discord eingeloggt."
        return redirect(url_for("dashboard"))
    session["discord_oauth_status"] = "Kein Account ist mit dieser Discord-ID verknüpft."
    return redirect(url_for("index"))

# Quizseite
@app.route("/quiz/<topic>/<subtopic>/<mode>", methods=["GET", "POST"])
def quiz(topic, subtopic, mode):
    if "username" not in session:
        return redirect(url_for("index"))
    index = int(request.args.get("index", 0))
    assignment_id = request.args.get("assignment_id")
    users = load_users()
    username = session["username"]
    user = ensure_user_profile(users, username)
    weakness_pending = session.pop("weakness_loop_pending", False)
    weakness_skill = None if weakness_pending else _active_weakness_skill(user)
    forced_topic, forced_subtopic = topic, subtopic
    forced_mode = mode
    if weakness_skill:
        forced_topic, forced_subtopic = _split_skill_key(weakness_skill)
        skill_entry = user.get("skills", {}).get(weakness_skill)
        forced_mode = forced_mode or (skill_entry or {}).get("last_mode") or MODE_ORDER[0]
    if not forced_topic or not forced_subtopic:
        return redirect(url_for("choose_topic"))
    topic_data = quizzes.get(forced_topic)
    if not topic_data:
        return redirect(url_for("choose_topic"))
    subtopic_data = topic_data.get(forced_subtopic)
    if not subtopic_data:
        return redirect(url_for("choose_topic"))
    mode_data = subtopic_data["modes"].get(forced_mode)
    if not mode_data:
        fallback_mode = next((m for m in MODE_ORDER if subtopic_data["modes"].get(m)), None)
        if not fallback_mode:
            return redirect(url_for("choose_topic"))
        forced_mode = fallback_mode
        mode_data = subtopic_data["modes"].get(forced_mode)
    quiz_state = session.get("quiz_state", {})
    desired_type = "weakness" if weakness_skill else "standard"
    needs_reset = (
        not quiz_state
        or quiz_state.get("type") != desired_type
        or quiz_state.get("topic") != forced_topic
        or quiz_state.get("subtopic") != forced_subtopic
        or (weakness_skill and quiz_state.get("skill") != weakness_skill)
        or (not weakness_skill and quiz_state.get("mode") != forced_mode)
    )
    if needs_reset:
        session["score"] = 0
        if weakness_skill:
            question, signature, selected_mode, _ = _fetch_question_for_skill(user, weakness_skill, forced_mode)
            if not question:
                return redirect(url_for("choose_topic"))
            if signature:
                question["signature"] = signature
            session["quiz_state"] = {
                "type": "weakness",
                "topic": forced_topic,
                "subtopic": forced_subtopic,
                "mode": selected_mode or forced_mode,
                "questions": [question],
                "results": [],
                "skill": weakness_skill,
            }
        else:
            questions = build_quiz_questions(forced_topic, forced_subtopic, forced_mode, count=10)
            session["quiz_state"] = {
                "type": "standard",
                "topic": forced_topic,
                "subtopic": forced_subtopic,
                "mode": forced_mode,
                "questions": questions,
                "results": [],
            }
        session["quiz_state"]["results"] = []
        session["score"] = 0
        session["quiz_start_at"] = datetime.now().isoformat(timespec="seconds")
        quiz_state = session["quiz_state"]
        index = 0
    questions = quiz_state["questions"]
    if not questions:
        return redirect(url_for("choose_topic"))
    if quiz_state.get("type") == "weakness":
        index = 0
    class_assignment = None
    if not weakness_skill:
        classes = load_classes()
        class_code = users.get(username, {}).get("class_code")
        if assignment_id and class_code and class_code in classes:
            class_assignments = classes[class_code].get("assignments", [])
            class_assignment = next((entry for entry in class_assignments if entry.get("id") == assignment_id), None)
            if class_assignment:
                if not assignment_start_allowed(class_assignment, username):
                    session["assignment_error"] = "Die Deadline wurde überschritten, das Quiz ist gesperrt."
                    return redirect(url_for("dashboard"))
                starts = class_assignment.setdefault("starts", {})
                if username not in starts:
                    starts[username] = datetime.now().isoformat(timespec="minutes")
                    save_classes(classes)
    stickers = recent_stickers(users, username)

    if "score" not in session:
        session["score"] = 0

    if request.method == "POST":
        action = request.form.get("action")
        if action == "exit":
            duration_seconds = _quiz_duration_seconds()
            _record_work_session_summary(
                user,
                forced_topic,
                forced_subtopic,
                quiz_state.get("mode") or forced_mode,
                duration_seconds,
                "aborted",
            )
            session.pop("quiz_state", None)
            session.pop("score", None)
            session.pop("quiz_start_at", None)
            return redirect(url_for("choose_topic"))
        user_answer = request.form["answer"]
        current_question = questions[index]
        expected_answer = resolve_question_answer(current_question)
        answer_for_check = expected_answer if expected_answer is not None else current_question.get("antwort")
        correct = is_correct(user_answer, answer_for_check, current_question.get("aliases"))
        if correct:
            session["score"] += 1
        entry_expected = expected_answer or current_question.get("antwort") or "Keine Angabe"
        quiz_state.setdefault("results", []).append({
            "frage": current_question["frage"],
            "answer": user_answer,
            "expected": entry_expected,
            "correct": correct
        })
        session["quiz_state"] = quiz_state
        skill_key = weakness_skill or _skill_key_from_parts(forced_topic, forced_subtopic, None)
        _, weakness_entry, _ = _record_skill_answer(user, skill_key, current_question.get("signature"), quiz_state.get("mode"), correct)
        save_users(users)
        if quiz_state["type"] == "weakness":
            active_skill = _active_weakness_skill(user)
            if active_skill == weakness_skill:
                next_question, signature, selected_mode, _ = _fetch_question_for_skill(user, weakness_skill, quiz_state.get("mode"))
                if not next_question:
                    session.pop("quiz_state", None)
                    return redirect(url_for("quiz", topic=forced_topic, subtopic=forced_subtopic, mode=forced_mode))
                if signature:
                    next_question["signature"] = signature
                quiz_state["questions"] = [next_question]
                quiz_state["mode"] = selected_mode or quiz_state.get("mode")
                session["quiz_state"] = quiz_state
                return redirect(
                    url_for(
                        "quiz",
                        topic=forced_topic,
                        subtopic=forced_subtopic,
                        mode=quiz_state["mode"],
                        assignment_id=assignment_id,
                    )
                )
            else:
                session.pop("quiz_state", None)
                session.pop("score", None)
                return redirect(
                    url_for(
                        "quiz",
                        topic=forced_topic,
                        subtopic=forced_subtopic,
                        mode=forced_mode,
                        assignment_id=assignment_id,
                    )
                )
        index += 1
        if index < len(questions):
            return redirect(url_for("quiz", topic=forced_topic, subtopic=forced_subtopic, mode=quiz_state.get("mode"), index=index, assignment_id=assignment_id))
        else:
            duration_seconds = _quiz_duration_seconds()
            _record_work_session_summary(
                users[username],
                forced_topic,
                forced_subtopic,
                quiz_state.get("mode") or forced_mode,
                duration_seconds,
                "completed",
            )
            user = users[username]
            user["money"] += session["score"] * 10
            total_questions = len(questions)
            sticker_threshold = min(8, total_questions)
            sticker_awarded = session["score"] >= sticker_threshold
            if sticker_awarded:
                available = unlocked_sticker_icons(user["progress"]["level"])
                sticker = random.choice(available)
                user["stickers"].append(sticker)
            results = quiz_state.get("results", [])
            correct_count = sum(1 for entry in results if entry["correct"])
            award_experience(user, correct_count)
            update_achievements(user)
            ai_feedback = build_student_feedback_summary(user, forced_topic, forced_subtopic, quiz_state.get("mode"), results)
            user["last_ai_feedback"] = ai_feedback
            record_quiz_history(
                user,
                forced_topic,
                forced_subtopic,
                quiz_state.get("mode"),
                results,
                session["score"],
                duration_seconds=duration_seconds,
                feedback_summary=ai_feedback,
            )
            classes_dirty = False
            if class_assignment:
                completed = class_assignment.setdefault("completed", [])
                if username not in completed:
                    completed.append(username)
                    classes_dirty = True
                starts = class_assignment.get("starts", {})
                if username in starts:
                    starts.pop(username, None)
                    classes_dirty = True
                class_code = users.get(username, {}).get("class_code")
                class_data = classes.get(class_code) if class_code else None
                if class_data and cleanup_class_assignments(class_data):
                    classes_dirty = True
            if classes_dirty:
                save_classes(classes)
            score = session["score"]
            session.pop("score")
            session.pop("quiz_start_at", None)
            stickers = recent_stickers(users, username)
            session.pop("quiz_state", None)
            sticker_strip = stickers or STICKER_TIERS[0]["icons"]
            return render_template(
                "result.html",
                score=score,
                total=total_questions,
                money=user["money"],
                stickers=stickers,
                sticker_strip=sticker_strip,
                sticker_awarded=sticker_awarded,
                results=results,
                sticker_threshold=sticker_threshold,
                topic=forced_topic,
                subtopic=forced_subtopic,
                mode_label=MODE_LABELS.get(quiz_state.get("mode"), quiz_state.get("mode", "").title()),
                assignment_id=assignment_id,
                ai_feedback=ai_feedback,
            )

    frage = questions[index]["frage"]
    return render_template(
        "quiz.html",
        topic=forced_topic,
        subtopic=forced_subtopic,
        mode_label=MODE_LABELS.get(quiz_state.get("mode"), quiz_state.get("mode", "").title()),
        frage=frage,
        index=index+1,
        total=len(questions),
        stickers=stickers,
        assignment_id=assignment_id,
    )

# Shopseite
@app.route("/shop", methods=["GET", "POST"])
def shop():
    if "username" not in session:
        return redirect(url_for("index"))
    users = load_users()
    username = session["username"]
    ensure_user_profile(users, username)
    stickers = recent_stickers(users, username)
    message = None
    user = users[username]
    if request.method == "POST":
        item_name = request.form.get("item")
        item = next((i for i in SHOP_ITEMS if i["name"] == item_name), None)
        if item is None:
            message = "Ungültiger Artikel."
        elif users[username]["money"] < item["price"]:
            message = "Du hast nicht genug Punkte für diesen Kauf."
        else:
            user["money"] -= item["price"]
            record = {
                "name": item["name"],
                "price": item["price"],
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
            }
            user["purchases"].append(record)
            if item.get("type") == "avatar":
                new_avatar = unlock_avatar(user)
                message = f"Avatar {new_avatar['label']} freigeschaltet und direkt ausgerüstet!"
            else:
                message = f"{item['name']} erfolgreich gekauft!"
            save_users(users)
            stickers = recent_stickers(users, username)
    return render_template(
        "shop.html",
        money=users[username]["money"],
        items=SHOP_ITEMS,
        purchases=list(reversed(users[username]["purchases"][-5:])),
        message=message,
        avatar=users[username]["avatar"],
        stickers=stickers,
    )

@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if "username" not in session:
        return redirect(url_for("index"))
    users = load_users()
    username = session["username"]
    user = ensure_user_profile(users, username)
    purchases = list(reversed(user["purchases"]))
    total_spent = sum(p["price"] for p in user["purchases"])
    progress = user["progress"]
    next_level_exp = progress["level"] * LEVEL_STEP
    percent = int(min(100, progress["experience"] / max(next_level_exp, 1) * 100))
    available_stickers = unlocked_sticker_icons(progress["level"])
    upcoming_tier = next_sticker_tier(progress["level"])
    classes = load_classes()
    if cleanup_all_classes(classes):
        save_classes(classes)
    class_assignments = []
    class_name = None
    feedback_note = None
    assignment_error = session.pop("assignment_error", None)
    discord_status = session.pop("discord_oauth_status", None)
    class_data = None
    if user.get("role") == "student" and user.get("class_code"):
        class_data = classes.get(user["class_code"])
        if class_data:
            class_name = class_data.get("name")
    if request.method == "POST" and user.get("role") == "student" and class_data:
        action = request.form.get("action")
        if action == "feedback":
            assignment_id = request.form.get("assignment_id")
            message_text = request.form.get("feedback", "").strip()
            assignment = next((a for a in class_data.get("assignments", []) if a["id"] == assignment_id), None)
            if not assignment:
                feedback_note = "Aufgabe nicht gefunden."
            elif not message_text:
                feedback_note = "Feedback darf nicht leer sein."
            else:
                assignment.setdefault("feedback", []).append({
                    "student": username,
                    "message": message_text,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
                })
                save_classes(classes)
                feedback_note = "Feedback wurde gesendet."
        else:
            feedback_note = "Aktion nicht erlaubt."
    if class_data:
        for assignment in class_data.get("assignments", []):
            if not assignment_is_visible(assignment):
                continue
            deadline = assignment.get("deadline")
            deadline_label = format_deadline_display(deadline)
            open_status = is_deadline_open(deadline)
            completed = username in assignment.get("completed", [])
            started = username in assignment.get("starts", {})
            start_allowed = assignment_start_allowed(assignment, username)
            grace_msg = None
            if not completed and not started and start_allowed and not open_status:
                grace_msg = grace_remaining_display(deadline)
            if completed:
                status_label = "Abgeschlossen"
            elif open_status:
                status_label = "Offen"
            elif grace_msg:
                status_label = "Verlängert"
            else:
                status_label = "Abgelaufen"
            class_assignments.append({
                "id": assignment["id"],
                "topic": assignment["topic"],
                "subtopic": assignment["subtopic"],
                "mode": assignment["mode"],
                "mode_label": MODE_LABELS.get(assignment["mode"], assignment["mode"].title()),
                "deadline_display": deadline_label,
                "is_open": open_status,
                "status_label": status_label,
                "start_allowed": start_allowed,
                "started": started,
                "grace_message": grace_msg,
                "feedback_count": len(assignment.get("feedback", [])),
            })
    return render_template(
        "dashboard.html",
        money=user["money"],
        purchases=purchases,
        total_spent=total_spent,
        avatar=user["avatar"],
        stickers=recent_stickers(users, username),
        progress=progress,
        percent=percent,
        next_level_exp=next_level_exp,
        achievements=user["achievements"],
        last_quiz=user.get("last_quiz"),
        available_stickers=available_stickers,
        upcoming_tier=upcoming_tier,
        assignments=class_assignments,
        class_code=user.get("class_code"),
        class_name=class_name,
        feedback_note=feedback_note,
        assignment_error=assignment_error,
        discord_status=discord_status,
        mode_labels=MODE_LABELS,
    )


@app.route("/chat")
def chat():
    if "username" not in session:
        return redirect(url_for("index"))
    users = load_users()
    username = session["username"]
    ensure_user_profile(users, username)
    return render_template(
        "chat.html",
        stickers=recent_stickers(users, username),
        discord_server_id=DISCORD_SERVER_ID,
        discord_channel_id=DISCORD_CHAT_CHANNEL,
    )

@app.route("/leaderboard")
def leaderboard():
    if "username" not in session:
        return redirect(url_for("index"))
    users = load_users()
    rankings = sorted(
        [
            {
                "name": name,
                "money": data.get("money", 0),
                "badges": len(data.get("stickers", [])),
                "purchases": len(data.get("purchases", [])),
            }
            for name, data in users.items()
            if data.get("role") != "teacher"
        ],
        key=lambda entry: entry["money"],
        reverse=True,
    )
    username = session["username"]
    ensure_user_profile(users, username)
    return render_template(
        "leaderboard.html",
        rankings=rankings,
        stickers=recent_stickers(users, username),
    )

@app.route("/review")
def review():
    if "username" not in session:
        return redirect(url_for("index"))
    users = load_users()
    username = session["username"]
    user = ensure_user_profile(users, username)
    last_quiz = user.get("last_quiz")
    return render_template(
        "review.html",
        last_quiz=last_quiz,
        stickers=recent_stickers(users, username),
        mode_labels=MODE_LABELS,
    )

@app.route("/avatar", methods=["GET", "POST"])
def avatar_design():
    if "username" not in session:
        return redirect(url_for("index"))
    users = load_users()
    username = session["username"]
    ensure_user_profile(users, username)
    message = None
    user = users[username]
    collection = user.setdefault("avatar_collection", [])
    if request.method == "POST":
        equip_label = request.form.get("equip_avatar")
        if equip_label:
            selection = next((entry for entry in collection if entry.get("label") == equip_label), None)
            if selection:
                user["avatar"] = selection.copy()
                message = f"Avatar {selection['label']} ausgerüstet."
        else:
            color = request.form.get("color", "#2563eb")
            shape = request.form.get("shape", "circle")
            symbol = request.form.get("symbol", "★")
            if symbol not in AVATAR_SYMBOLS:
                symbol = AVATAR_SYMBOLS[0]
            user["avatar"].update({"color": color, "shape": shape, "symbol": symbol})
            current_label = user["avatar"].get("label")
            for entry in collection:
                if entry.get("label") == current_label:
                    entry.update(user["avatar"])
            message = "Avatar gespeichert"
        save_users(users)
    return render_template(
        "avatar.html",
        avatar=user["avatar"],
        collection=collection,
        symbols=user.get("symbol_library", AVATAR_SYMBOLS),
        message=message,
        stickers=recent_stickers(users, username),
    )


@app.route("/api/generate-question", methods=["POST"])
def api_generate_question():
    payload = request.get_json(silent=True) or {}
    topic = payload.get("topic", "Allgemein")
    subtopic = payload.get("subtopic", "Allgemein")
    mode = payload.get("mode", "leicht")
    hint = payload.get("hint")
    if not openrouter_configured():
        return jsonify(error="OpenRouter nicht konfiguriert"), 503
    try:
        question = generate_openrouter_question(topic, subtopic, mode, hint)
    except RuntimeError as exc:
        return jsonify(error=str(exc)), 502
    return jsonify(question=question)


@app.route("/api/answer", methods=["POST"])
def api_answer():
    username = session.get("username")
    if not username:
        return jsonify(error="Nicht angemeldet"), 401
    payload = request.get_json(silent=True) or {}
    topic = payload.get("topic")
    subtopic = payload.get("subtopic")
    mode = payload.get("mode")
    question = payload.get("question") or {}
    user_answer = payload.get("answer")
    skill_hint = payload.get("skill")
    if not question or user_answer is None:
        return jsonify(error="Frage oder Antwort fehlt"), 400
    skill_key = _skill_key_from_parts(topic, subtopic, skill_hint)
    if not skill_key:
        return jsonify(error="Skill oder Thema/Subthema fehlen"), 400
    correct_answer = resolve_question_answer(question)
    if correct_answer is None:
        return jsonify(error="Es fehlt die erwartete Antwort zur Frage"), 400
    signature = _normalize_signature(question.get("frage"))
    correct = is_correct(user_answer, correct_answer, question.get("aliases"))
    users = load_users()
    user = ensure_user_profile(users, username)
    skill_entry, weakness_entry, review_entry = _record_skill_answer(user, skill_key, signature, mode, correct)
    save_users(users)
    response = {
        "correct": correct,
        "mastery": skill_entry.get("mastered") if skill_entry else False,
        "skill": skill_key,
        "weakness": weakness_entry,
    }
    if review_entry:
        response["review_item"] = _serialize_review_item_state(review_entry)
    return jsonify(response)


@app.route("/api/next-question", methods=["GET"])
def api_next_question():
    username = session.get("username")
    if not username:
        return jsonify(error="Nicht angemeldet"), 401
    topic = request.args.get("topic")
    subtopic = request.args.get("subtopic")
    mode = request.args.get("mode")
    skill_hint = request.args.get("skill")
    users = load_users()
    user = ensure_user_profile(users, username)
    requested_skill = _skill_key_from_parts(topic, subtopic, skill_hint)
    target_skill, loop_reason, loop_meta = scheduleNextReview(user, requested_skill)
    if not target_skill:
        return jsonify(error="Skill/Topic/Subtopic werden benötigt"), 400
    question, signature, selected_mode, skill_entry = _fetch_question_for_skill(user, target_skill, mode)
    if not question:
        return jsonify(error="Keine passende Frage verfügbar"), 404
    skills_topic, skills_subtopic = _split_skill_key(target_skill)
    payload = _prepare_question_payload(
        question,
        topic or skills_topic,
        subtopic or skills_subtopic,
        selected_mode,
        signature,
    )
    _mark_question_assigned(skill_entry, signature)
    save_users(users)
    weakness_payload = None
    review_payload = None
    blocking = False
    if loop_reason == "weakness" and loop_meta:
        blocking = True
        weakness_payload = {
            "skillId": loop_meta.get("skillId"),
            "severity": loop_meta.get("severity"),
            "open": loop_meta.get("open"),
            "incorrect_count": loop_meta.get("incorrect_count"),
            "issue": loop_meta.get("issue"),
            "errorPattern": loop_meta.get("errorPattern"),
            "stabilityScore": loop_meta.get("stabilityScore"),
        }
    if loop_reason == "review" and loop_meta:
        review_payload = _serialize_review_item_state(loop_meta)
    response = {
        "question": payload,
        "weakness_blocking": blocking,
        "weakness": weakness_payload,
        "review_item": review_payload,
        "skill": target_skill,
        "adaptive": {
            "difficulty": selected_mode,
            "reason": loop_reason or "standard",
        },
    }
    return jsonify(response)


@app.route("/api/progress", methods=["GET"])
def api_progress():
    username = session.get("username")
    if not username:
        return jsonify(error="Nicht angemeldet"), 401
    users = load_users()
    user = ensure_user_profile(users, username)
    skills = []
    for skill_key, entry in user.get("skills", {}).items():
        skills.append(
            {
                "skill": skill_key,
                "mastered": entry.get("mastered", False),
                "mode": entry.get("last_mode", MODE_ORDER[0]),
                "consecutive_correct": entry.get("consecutive_correct", 0),
            }
        )
    weaknesses = []
    for entry in user.get("weaknesses", {}).values():
        if not (entry.get("severity") or entry.get("open")):
            continue
        weaknesses.append(
            {
                "skillId": entry.get("skillId") or entry.get("skill"),
                "severity": entry.get("severity"),
                "open": entry.get("open"),
                "incorrect_count": entry.get("incorrect_count"),
                "issue": entry.get("issue"),
                "pattern": entry.get("pattern"),
                "errorPattern": entry.get("errorPattern"),
                "stabilityScore": entry.get("stabilityScore"),
                "first_detected_at": entry.get("first_detected_at"),
                "last_wrong_at": entry.get("last_wrong_at"),
            }
        )
    review_schedule = []
    now = datetime.now()
    for entry in user.get("review_items", {}).values():
        item_state = _serialize_review_item_state(entry)
        if not item_state:
            continue
        next_review = _parse_iso_datetime(entry.get("nextReviewDate"))
        item_state["due"] = not next_review or next_review <= now
        review_schedule.append(item_state)
    review_schedule.sort(key=lambda item: item.get("nextReviewDate") or "")
    progress = {
        "experience": user["progress"].get("experience", 0),
        "level": user["progress"].get("level", 1),
        "completed_quizzes": user["progress"].get("completed_quizzes", 0),
        "skills": skills,
        "weaknesses": weaknesses,
        "review_schedule": review_schedule,
    }
    return jsonify(progress)


@app.errorhandler(TemplateNotFound)
def handle_missing_template(error):
    template_name = getattr(error, "name", "unbekannt")
    return render_template_string(
        """<!DOCTYPE html>
<html><head><title>Datei nicht gefunden</title></head><body>
<div style='font-family:Inter,system-ui,sans-serif;padding:2rem;text-align:center;'>
<h1>Template '{{ template_name }}' fehlt</h1>
<p>Bitte lege die Datei unter <code>templates/{{ template_name }}</code> ab.</p>
</div></body></html>""",
        template_name=template_name,
    ), 500

if __name__ == "__main__":
    app.run(debug=True)
