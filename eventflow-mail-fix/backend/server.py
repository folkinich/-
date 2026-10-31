"""Small standard-library backend for the Sobralis event site."""

from __future__ import annotations

import hashlib
import html
import json
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen


BACKEND_DIR = Path(__file__).resolve().parent
DB_PATH = BACKEND_DIR / "data.sqlite3"


def load_env_file() -> None:
    """Load simple KEY=value settings from backend/.env without extra packages."""
    env_path = BACKEND_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


load_env_file()
PORT = int(os.environ.get("PORT", "3001"))
BASE_URL = os.environ.get("BASE_URL", f"http://localhost:{PORT}").rstrip("/")
FRONTEND_URL = os.environ.get("FRONTEND_URL", BASE_URL).rstrip("/")
SITE_DIR = Path(os.environ.get("FRONTEND_DIR", str(BACKEND_DIR.parent / "frontend")))
if not SITE_DIR.is_absolute():
    SITE_DIR = (BACKEND_DIR / SITE_DIR).resolve()
ALLOWED_ORIGINS = {BASE_URL, FRONTEND_URL}
SESSION_SECONDS = 7 * 24 * 60 * 60
VERIFY_SECONDS = 24 * 60 * 60
MAX_BODY = 20 * 1024
RATE_LIMITS: dict[tuple[str, str], list[float]] = {}
RATE_LOCK = threading.Lock()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def db_connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_db() -> None:
    with db_connect() as db:
        db.executescript("""
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('participant', 'organizer')),
                email_verified INTEGER NOT NULL DEFAULT 0,
                verification_hash TEXT,
                verification_expires TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS sessions_user_id_idx ON sessions(user_id);
        """)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def password_hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 310_000).hex()


def public_user(user: sqlite3.Row) -> dict:
    return {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "role": user["role"],
        "emailVerified": bool(user["email_verified"]),
    }


def mail_configured() -> bool:
    return bool(os.environ.get("RESEND_API_KEY") and os.environ.get("EMAIL_FROM"))


def send_email(to: str, subject: str, text: str, html_body: str, *, reply_to: str | None = None) -> None:
    api_key = os.environ.get("RESEND_API_KEY")
    sender = os.environ.get("EMAIL_FROM")
    if not api_key or not sender:
        raise RuntimeError("Отправка писем не настроена. Администратору нужно заполнить RESEND_API_KEY и EMAIL_FROM.")

    message = {
        "from": sender,
        "to": [to],
        "subject": subject,
        "text": text,
        "html": html_body,
    }
    if reply_to:
        message["reply_to"] = reply_to
    payload = json.dumps(message).encode("utf-8")
    request = Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError("Почтовый сервис не принял письмо.")
            result = json.loads(response.read())
            if not isinstance(result, dict) or not result.get("id"):
                raise RuntimeError("Почтовый сервис не подтвердил приём письма.")
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
        # Do not log recipient addresses, credentials, message text or verification links.
        print(f"Email provider request failed ({type(error).__name__}).", flush=True)
        raise RuntimeError("Не удалось отправить письмо. Попробуйте позже.") from error


def send_verification(email: str, token: str) -> None:
    link = f"{BASE_URL}/api/auth/verify?token={quote(token, safe='')}"
    send_email(email, "Подтвердите почту — Собрались",
               f"Подтвердите адрес электронной почты: {link}\nСсылка действует 24 часа. Если вы не создавали аккаунт, проигнорируйте письмо.",
               f'<p>Подтвердите адрес электронной почты в «Собрались».</p><p><a href="{html.escape(link, quote=True)}">Подтвердить почту</a></p><p>Ссылка действует 24 часа. Если вы не создавали аккаунт, проигнорируйте письмо.</p>')


def rate_allowed(bucket: str, client: str, limit: int, window_seconds: int) -> bool:
    now = time.monotonic()
    key = (bucket, client)
    with RATE_LOCK:
        recent = [stamp for stamp in RATE_LIMITS.get(key, []) if now - stamp < window_seconds]
        if len(recent) >= limit:
            RATE_LIMITS[key] = recent
            return False
        recent.append(now)
        RATE_LIMITS[key] = recent
        return True


def valid_email(email: str) -> bool:
    return len(email) <= 254 and " " not in email and email.count("@") == 1 and "." in email.rsplit("@", 1)[-1]


class AppHandler(BaseHTTPRequestHandler):
    server_version = "Sobralis/1.0"

    def log_message(self, format_string: str, *args) -> None:
        # BaseHTTPRequestHandler's default request log would expose verification tokens.
        print(f"{self.address_string()} - {self.command} {urlparse(self.path).path}")

    def end_headers(self) -> None:
        self.send_header("Referrer-Policy", "no-referrer")
        origin = self.headers.get("Origin")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Vary", "Origin")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        if not self.origin_allowed():
            return self.send_json(403, {"error": "Запрос отклонён."})
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def send_json(self, status: int, payload: dict, headers: dict[str, str] | None = None) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("Некорректный размер запроса.") from error
        if length < 0:
            raise ValueError("Некорректный размер запроса.")
        if length > MAX_BODY:
            raise OverflowError("Слишком большой запрос.")
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError as error:
            raise ValueError("Проверьте формат отправленных данных.") from error
        if not isinstance(body, dict):
            raise ValueError("Некорректные данные запроса.")
        return body

    def origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        return origin in ALLOWED_ORIGINS

    def session_user(self) -> sqlite3.Row | None:
        cookie = SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        if "session" not in cookie:
            return None
        token = cookie["session"].value
        with db_connect() as db:
            return db.execute("""
                SELECT users.* FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_hash = ? AND sessions.expires_at > ?
            """, (token_hash(token), now_utc().isoformat())).fetchone()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            return self.send_json(200, {"status": "ok"})
        if parsed.path == "/api/auth/verify":
            params = parse_qs(parsed.query)
            token = params.get("token", [""])[0]
            if len(token) < 20:
                return self.send_json(400, {"error": "Ссылка подтверждения недействительна."})
            with db_connect() as db:
                changed = db.execute(
                    "UPDATE users SET email_verified = 1, verification_hash = NULL, verification_expires = NULL WHERE verification_hash = ? AND verification_expires > ? AND email_verified = 0",
                    (token_hash(token), now_utc().isoformat()),
                ).rowcount
                if not changed:
                    return self.send_json(400, {"error": "Ссылка недействительна или срок её действия закончился."})
            self.send_response(302)
            self.send_header("Location", f"{FRONTEND_URL}/login.html?verified=1")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        if parsed.path == "/api/auth/me":
            user = self.session_user()
            if not user:
                return self.send_json(401, {"error": "Вы не вошли в аккаунт."})
            return self.send_json(200, {"user": public_user(user)})
        if parsed.path == "/dashboard.html" and not self.session_user():
            self.send_response(302)
            self.send_header("Location", "/login.html")
            self.end_headers()
            return

        files = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/index.html": ("index.html", "text/html; charset=utf-8"),
            "/login": ("login.html", "text/html; charset=utf-8"),
            "/help.html": ("help.html", "text/html; charset=utf-8"),
            "/login.html": ("login.html", "text/html; charset=utf-8"),
            "/dashboard.html": ("dashboard.html", "text/html; charset=utf-8"),
            "/style.css": ("style.css", "text/css; charset=utf-8"),
            "/script.js": ("script.js", "text/javascript; charset=utf-8"),
            "/help.js": ("help.js", "text/javascript; charset=utf-8"),
            "/login.js": ("login.js", "text/javascript; charset=utf-8"),
            "/dashboard.js": ("dashboard.js", "text/javascript; charset=utf-8"),
            "/api.js": ("api.js", "text/javascript; charset=utf-8"),
            "/config.js": ("config.js", "text/javascript; charset=utf-8"),
        }
        file_info = files.get(parsed.path)
        if not file_info:
            return self.send_json(404, {"error": "Страница не найдена."})
        filename, content_type = file_info
        try:
            data = (SITE_DIR / filename).read_bytes()
        except OSError:
            return self.send_json(404, {"error": "Страница не найдена."})
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        if not self.origin_allowed():
            return self.send_json(403, {"error": "Запрос отклонён."})
        path = urlparse(self.path).path
        if path == "/api/auth/register":
            return self.register()
        if path == "/api/auth/login":
            return self.login()
        if path == "/api/auth/resend-verification":
            return self.resend_verification()
        if path == "/api/auth/logout":
            return self.logout()
        if path == "/api/support":
            return self.support()
        return self.send_json(404, {"error": "Такой адрес API не найден."})

    def register(self) -> None:
        if not rate_allowed("register", self.client_address[0], 8, 15 * 60):
            return self.send_json(429, {"error": "Слишком много попыток. Попробуйте позже."})
        try:
            body = self.read_json()
        except (ValueError, OverflowError) as error:
            return self.send_json(413 if isinstance(error, OverflowError) else 400, {"error": str(error)})
        name = body.get("name", "").strip() if isinstance(body.get("name"), str) else ""
        email = body.get("email", "").strip().lower() if isinstance(body.get("email"), str) else ""
        password = body.get("password", "") if isinstance(body.get("password"), str) else ""
        role = body.get("role")
        if not 2 <= len(name) <= 80:
            return self.send_json(400, {"error": "Имя должно содержать от 2 до 80 символов."})
        if not valid_email(email):
            return self.send_json(400, {"error": "Введите корректный адрес электронной почты."})
        if not 8 <= len(password) <= 200:
            return self.send_json(400, {"error": "Пароль должен содержать от 8 до 200 символов."})
        if role not in ("participant", "organizer"):
            return self.send_json(400, {"error": "Выберите участника или организатора."})
        if body.get("consent") is not True:
            return self.send_json(400, {"error": "Для регистрации нужно принять условия использования."})

        with db_connect() as db:
            existing_user = db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone()
        if existing_user:
            return self.send_json(409, {"error": "Аккаунт с этой почтой уже существует."})
        if not mail_configured():
            return self.send_json(503, {"error": "Отправка писем не настроена. Обратитесь к организатору."})

        user_id = secrets.token_urlsafe(18)
        salt = secrets.token_hex(16)
        verification_token = secrets.token_urlsafe(32)
        verification_expires = (now_utc() + timedelta(seconds=VERIFY_SECONDS)).isoformat()
        try:
            with db_connect() as db:
                db.execute("""
                    INSERT INTO users (id, name, email, password_salt, password_hash, role,
                        email_verified, verification_hash, verification_expires, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                """, (user_id, name, email, salt, password_hash(password, salt), role,
                      token_hash(verification_token), verification_expires, now_utc().isoformat()))
        except sqlite3.IntegrityError:
            return self.send_json(409, {"error": "Аккаунт с этой почтой уже существует."})

        try:
            send_verification(email, verification_token)
        except RuntimeError:
            return self.send_json(503, {"error": "Аккаунт создан, но письмо отправить не удалось. Перейдите ко входу, укажите почту и пароль и нажмите «Отправить письмо повторно».", "code": "verification_delivery_failed"})
        return self.send_json(201, {"message": "Аккаунт создан. Письмо с подтверждением передано почтовому сервису. Проверьте почту и папку «Спам».", "verificationRequired": True})

    def resend_verification(self) -> None:
        if not rate_allowed("resend", self.client_address[0], 5, 15 * 60):
            return self.send_json(429, {"error": "Слишком много попыток. Попробуйте позже."})
        try:
            body = self.read_json()
        except (ValueError, OverflowError) as error:
            return self.send_json(413 if isinstance(error, OverflowError) else 400, {"error": str(error)})
        email = body.get("email", "").strip().lower() if isinstance(body.get("email"), str) else ""
        password = body.get("password", "") if isinstance(body.get("password"), str) else ""
        with db_connect() as db:
            user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not user or not secrets.compare_digest(password_hash(password, user["password_salt"]), user["password_hash"]):
            return self.send_json(401, {"error": "Почта или пароль указаны неверно."})
        if user["email_verified"]:
            return self.send_json(200, {"message": "Почта уже подтверждена. Можно войти."})
        if not mail_configured():
            return self.send_json(503, {"error": "Отправка писем не настроена. Обратитесь к организатору."})
        if not rate_allowed("resend_email", email, 1, 60):
            return self.send_json(429, {"error": "Повторное письмо можно запросить через минуту."})
        token = secrets.token_urlsafe(32)
        with db_connect() as db:
            db.execute("UPDATE users SET verification_hash = ?, verification_expires = ? WHERE id = ? AND email_verified = 0",
                       (token_hash(token), (now_utc() + timedelta(seconds=VERIFY_SECONDS)).isoformat(), user["id"]))
        try:
            send_verification(email, token)
        except RuntimeError:
            return self.send_json(503, {"error": "Письмо отправить не удалось. Повторите попытку через минуту."})
        return self.send_json(200, {"message": "Письмо передано почтовому сервису. Используйте самую новую ссылку; проверьте папку «Спам»."})

    def login(self) -> None:
        if not rate_allowed("login", self.client_address[0], 12, 15 * 60):
            return self.send_json(429, {"error": "Слишком много попыток. Попробуйте позже."})
        try:
            body = self.read_json()
        except (ValueError, OverflowError) as error:
            return self.send_json(413 if isinstance(error, OverflowError) else 400, {"error": str(error)})
        email = body.get("email", "").strip().lower() if isinstance(body.get("email"), str) else ""
        password = body.get("password", "") if isinstance(body.get("password"), str) else ""
        with db_connect() as db:
            user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not user or not secrets.compare_digest(password_hash(password, user["password_salt"]), user["password_hash"]):
            return self.send_json(401, {"error": "Почта или пароль указаны неверно."})
        if not user["email_verified"]:
            return self.send_json(403, {"error": "Сначала подтвердите почту по ссылке из письма. Если письмо не пришло, отправьте его повторно.", "code": "email_not_verified"})
        session_token = secrets.token_urlsafe(32)
        expires = (now_utc() + timedelta(seconds=SESSION_SECONDS)).isoformat()
        with db_connect() as db:
            db.execute("INSERT INTO sessions (token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                       (token_hash(session_token), user["id"], expires, now_utc().isoformat()))
        secure = "; Secure" if os.environ.get("NODE_ENV") == "production" else ""
        cookie = f"session={session_token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={SESSION_SECONDS}{secure}"
        return self.send_json(200, {"user": public_user(user)}, {"Set-Cookie": cookie})

    def logout(self) -> None:
        cookie = SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        if "session" in cookie:
            with db_connect() as db:
                db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(cookie["session"].value),))
        secure = "; Secure" if os.environ.get("NODE_ENV") == "production" else ""
        clear_cookie = f"session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0{secure}"
        return self.send_json(200, {"message": "Вы вышли из аккаунта."}, {"Set-Cookie": clear_cookie})

    def support(self) -> None:
        if not rate_allowed("support", self.client_address[0], 5, 60 * 60):
            return self.send_json(429, {"error": "Слишком много обращений. Попробуйте позже."})
        try:
            body = self.read_json()
        except (ValueError, OverflowError) as error:
            return self.send_json(413 if isinstance(error, OverflowError) else 400, {"error": str(error)})
        email = body.get("email", "").strip().lower() if isinstance(body.get("email"), str) else ""
        message = body.get("message", "").strip() if isinstance(body.get("message"), str) else ""
        if not valid_email(email):
            return self.send_json(400, {"error": "Введите корректный адрес электронной почты."})
        if not 5 <= len(message) <= 5000:
            return self.send_json(400, {"error": "Сообщение должно содержать от 5 до 5000 символов."})
        support_email = os.environ.get("SUPPORT_EMAIL")
        if not support_email or not mail_configured():
            return self.send_json(503, {"error": "Почта поддержки ещё не настроена."})
        try:
            send_email(
                support_email,
                f"Обращение в поддержку от {email}",
                f"Почта пользователя: {email}\n\n{message}",
                f"<p><b>Почта пользователя:</b> {html.escape(email)}</p><p>{html.escape(message).replace(chr(10), '<br>')}</p>",
                reply_to=email,
            )
        except RuntimeError as error:
            return self.send_json(503, {"error": str(error)})
        return self.send_json(200, {"message": "Сообщение передано почтовому сервису. Спасибо, что написали нам."})


def main() -> None:
    initialize_db()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), AppHandler)
    print(f"Python-сервер запущен на порту {PORT}: {BASE_URL}", flush=True)
    print("Почта настроена." if mail_configured() else "Почта не настроена: заполните RESEND_API_KEY и EMAIL_FROM в backend/.env.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nСервер остановлен.", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
