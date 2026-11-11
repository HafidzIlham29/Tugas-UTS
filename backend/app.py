#!/usr/bin/env python3
"""Backend REST API - Papan Pengumuman Kampus (Campus Announcement Board).

Dibangun hanya dengan standard library Python (tanpa framework).

Endpoint:
    GET    /health                      -> status layanan (dipakai Health Check Jenkins)
    GET    /announcements               -> daftar semua pengumuman
    POST   /announcements               -> tambah pengumuman baru (body JSON)
    DELETE /announcements?index=X       -> hapus pengumuman pada posisi X (mulai dari 0)

Seluruh data disimpan di file JSON pada DATA_DIR. Di dalam container, DATA_DIR
di-mount dari Docker Named Volume `announcement-data`, sehingga data tetap ada
walaupun container dihapus (docker rm -f).
"""

import json
import os
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

DATA_DIR = os.environ.get("DATA_DIR", "/var/lib/backend_data")
DATA_FILE = os.path.join(DATA_DIR, "announcements.json")
PORT = int(os.environ.get("PORT", "8000"))

MAX_BODY_BYTES = 16 * 1024
CATEGORIES = ("Umum", "Akademik", "Ormawa", "Kegiatan", "Beasiswa")
LIMITS = {"title": 120, "content": 2000, "author": 60}

# Lock supaya baca-tulis file aman ketika ada beberapa request bersamaan.
LOCK = threading.Lock()


# --------------------------------------------------------------------------- #
# Penyimpanan data (file JSON di dalam Named Volume)
# --------------------------------------------------------------------------- #
def load_data():
    """Baca daftar pengumuman dari file JSON. File belum ada -> list kosong."""
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[WARN] Gagal membaca {DATA_FILE}: {exc}", flush=True)
        return []


def save_data(items):
    """Tulis data secara atomik: tulis ke file sementara, lalu ganti file utama."""
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp_path = DATA_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, DATA_FILE)


# --------------------------------------------------------------------------- #
# Validasi input
# --------------------------------------------------------------------------- #
def validate_announcement(payload):
    """Kembalikan (data_bersih, None) bila valid, atau (None, pesan_error)."""
    if not isinstance(payload, dict):
        return None, "Body harus berupa objek JSON"

    clean = {}
    for field in ("title", "content"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            return None, f"Field '{field}' wajib diisi (teks tidak kosong)"
        value = value.strip()
        if len(value) > LIMITS[field]:
            return None, f"Field '{field}' maksimal {LIMITS[field]} karakter"
        clean[field] = value

    author = payload.get("author", "Admin")
    if author is None or author == "":
        author = "Admin"
    if not isinstance(author, str):
        return None, "Field 'author' harus berupa teks"
    author = author.strip() or "Admin"
    if len(author) > LIMITS["author"]:
        return None, f"Field 'author' maksimal {LIMITS['author']} karakter"
    clean["author"] = author

    category = payload.get("category", "Umum")
    if category is None or category == "":
        category = "Umum"
    if category not in CATEGORIES:
        return None, "Field 'category' harus salah satu dari: " + ", ".join(CATEGORIES)
    clean["category"] = category

    return clean, None


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    server_version = "AnnouncementAPI/1.0"

    # ---- helper ----------------------------------------------------------- #
    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status, message):
        self._send_json(status, {"error": message})

    def _route(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        return path, parse_qs(parsed.query)

    def _read_json_body(self):
        """Kembalikan (payload, None) atau (None, (status, pesan))."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None, (400, "Header Content-Length tidak valid")
        if length <= 0:
            return None, (400, "Body request kosong, kirim JSON")
        if length > MAX_BODY_BYTES:
            return None, (413, f"Body terlalu besar (maksimal {MAX_BODY_BYTES} byte)")
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8")), None
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, (400, "Body bukan JSON yang valid")

    # ---- metode HTTP ------------------------------------------------------ #
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path, _ = self._route()

        if path == "/health":
            with LOCK:
                total = len(load_data())
            self._send_json(200, {"status": "ok", "service": "announcement-backend", "total": total})
        elif path == "/announcements":
            with LOCK:
                items = load_data()
            self._send_json(200, items)
        else:
            self._error(404, "Endpoint tidak ditemukan")

    def do_POST(self):
        path, _ = self._route()
        if path != "/announcements":
            self._error(404, "Endpoint tidak ditemukan")
            return

        payload, err = self._read_json_body()
        if err:
            self._error(*err)
            return

        clean, message = validate_announcement(payload)
        if message:
            self._error(400, message)
            return

        clean["created_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

        with LOCK:
            items = load_data()
            items.append(clean)
            save_data(items)
            index = len(items) - 1

        self._send_json(201, {"message": "Pengumuman berhasil ditambahkan", "index": index, "announcement": clean})

    def do_DELETE(self):
        path, query = self._route()
        if path != "/announcements":
            self._error(404, "Endpoint tidak ditemukan")
            return

        raw_index = query.get("index", [None])[0]
        if raw_index is None or raw_index == "":
            self._error(400, "Parameter 'index' wajib diisi, contoh: /announcements?index=0")
            return
        try:
            index = int(raw_index)
        except ValueError:
            self._error(400, "Parameter 'index' harus berupa bilangan bulat")
            return

        with LOCK:
            items = load_data()
            if index < 0 or index >= len(items):
                self._error(404, f"Pengumuman dengan index {index} tidak ditemukan")
                return
            removed = items.pop(index)
            save_data(items)

        self._send_json(200, {"message": "Pengumuman berhasil dihapus", "deleted": removed})

    def _method_not_allowed(self):
        path, _ = self._route()
        if path in ("/health", "/announcements"):
            self._error(405, "Method tidak diizinkan untuk endpoint ini")
        else:
            self._error(404, "Endpoint tidak ditemukan")

    do_PUT = _method_not_allowed
    do_PATCH = _method_not_allowed

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {self.address_string()} {fmt % args}", flush=True)


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Backend berjalan di port {PORT}, data disimpan di {DATA_FILE}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Server dihentikan", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
