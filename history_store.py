"""Per-account borrow history persistence for HK Library renewals.

History is stored as one JSON file per account inside HISTORY_DIR
(default: "history", overridable via the HISTORY_DIR environment variable).
Each file contains a list of borrow records with the fields:
  title, author, call_no, first_seen, last_seen, returned_date
Dates are ISO formatted strings (YYYY-MM-DD), or None for returned_date
when the book is still on loan.
"""

import json
import os
import re
from datetime import date

HISTORY_DIR = os.environ.get("HISTORY_DIR", "history")

EBOOK_SOURCES = [
    "hyread", "suep", "overdrive", "libby", "ebsco", "proquest",
    "apabi", "funpark", "kado", "gale", "britannica", "worldbook",
    "naxos", "medici", "kobo", "kindle",
]


def masked_name(username):
    """Mask an account id for public display and file naming.

    Only the last 4 characters are kept (e.g. 22222017768445 -> masked8445).
    Masked names are stable: masking an already-masked name is a no-op.
    """
    name = username or ""
    if name.startswith("masked"):
        return name
    return f"masked{name[-4:]}" if len(name) > 4 else "masked"


def get_history_dir():
    """Return the directory where history files are stored."""
    return HISTORY_DIR


def history_path(username):
    """Return the history file path for an account.

    The file name uses the masked account id so card numbers never appear
    in the public repository.
    """
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", masked_name(username))
    return os.path.join(HISTORY_DIR, f"{safe}.json")


def normalize_text(value):
    """Normalize a text field for comparison."""
    return re.sub(r"\s+", " ", (value or "")).strip().lower()


def parse_author_from_title(title):
    """Split 'Title / Author' style catalogue text into (title, author)."""
    text = re.sub(r"\s+", " ", title or "").strip()
    if " / " in text:
        title_part, author_part = text.split(" / ", 1)
        return title_part.strip(), author_part.strip(" ,;/")
    return text, ""


def guess_call_no(cells, skip_texts):
    """Best-effort guess of the call number / e-book source from row cells."""
    skip_norm = {normalize_text(s) for s in skip_texts if s}
    for cell in cells:
        text = re.sub(r"\s+", " ", cell).strip()
        if not text or normalize_text(text) in skip_norm:
            continue
        if "/" in text or "@" in text:
            continue
        lowered = text.lower()
        if any(source in lowered for source in EBOOK_SOURCES):
            return text
        if re.match(r"^\d+\s+of\s+\d+$", text, re.IGNORECASE):
            continue
        if re.match(r"^[A-Za-z]{0,3}\s?\d{1,3}(\.\d+){0,2}(\s+[A-Za-z0-9.]{1,6}){0,3}$", text):
            return text
    return ""


def record_key(book):
    """Build a stable identity key for a borrowed book.

    The key uses title and author only, so a record keeps its identity even
    after the call number is backfilled from the book detail page later.
    """
    parts = [
        normalize_text(book.get("title")),
        normalize_text(book.get("author")),
    ]
    return "|".join(parts)


def load_history(username):
    """Load history for an account, returning an empty structure if absent."""
    path = history_path(username)
    if not os.path.exists(path):
        return {"account": username, "records": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("records"), list):
            return {"account": masked_name(username), "records": []}
        data.setdefault("account", masked_name(username))
        return data
    except (OSError, ValueError) as e:
        print(f"[history] Could not read {path}: {e}; starting fresh")
        return {"account": masked_name(username), "records": []}


def save_history(username, history):
    """Save history for an account atomically, storing the account id masked."""
    os.makedirs(HISTORY_DIR, exist_ok=True)
    path = history_path(username)
    payload = dict(history)
    payload["account"] = masked_name(username)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    print(f"[history] Saved {len(history['records'])} record(s) to {path}")


def update_history(username, current_books, run_date=None):
    """Record currently borrowed books into the account history.

    New books (never seen before on this account) are appended with
    first_seen set to the run date. Books already open keep their record
    and get last_seen refreshed. Open records no longer present in
    current_books are marked as returned on the run date.

    Returns (history, new_books) where new_books is the list of records
    created during this run.
    """
    run_date = run_date or date.today()
    run_date_str = run_date.isoformat()
    history = load_history(username)
    records = history["records"]

    open_by_key = {}
    for rec in records:
        if rec.get("returned_date") is None:
            open_by_key[record_key(rec)] = rec

    new_books = []
    for book in current_books:
        key = record_key(book)
        existing = open_by_key.get(key)
        if existing:
            existing["last_seen"] = run_date_str
            if not existing.get("call_no") and (book.get("call_no") or "").strip():
                existing["call_no"] = book["call_no"].strip()
                print(f"[history] Backfilled call number for '{existing['title']}': {existing['call_no']}")
            if not existing.get("author") and (book.get("author") or "").strip():
                existing["author"] = book["author"].strip()
            continue
        record = {
            "title": (book.get("title") or "").strip(),
            "author": (book.get("author") or "").strip(),
            "call_no": (book.get("call_no") or "").strip(),
            "first_seen": run_date_str,
            "last_seen": run_date_str,
            "returned_date": None,
        }
        records.append(record)
        open_by_key[key] = record
        new_books.append(record)
        print(f"[history] New borrowed book recorded: {record['title']}")

    for rec in records:
        if rec.get("returned_date") is None and rec["last_seen"] < run_date_str:
            rec["returned_date"] = run_date_str
            print(f"[history] Marked returned: {rec['title']} (last seen {rec['last_seen']})")

    records.sort(key=lambda r: (r["first_seen"], r["title"]))
    save_history(username, history)
    return history, new_books


def list_accounts():
    """List account names that have history files."""
    if not os.path.isdir(HISTORY_DIR):
        return []
    names = []
    for filename in os.listdir(HISTORY_DIR):
        if filename.endswith(".json"):
            names.append(filename[:-5])
    return sorted(names)
