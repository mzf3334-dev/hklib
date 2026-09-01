from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from datetime import datetime, timedelta
import html
import re
import time
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import history_store

CALL_NO_LABEL_RE = re.compile(r"索書號|call\s*number|call\s*no", re.IGNORECASE)

def get_config(key, default=None):
    """Get configuration from environment variable"""
    return os.environ.get(key, default)

# Email Configuration
EMAIL_SENDER = get_config("EMAIL_SENDER")
GMAIL_PWD = get_config("GMAIL_PWD")

def get_accounts():
    """
    Get library accounts from environment variables.
    Supports multiple accounts: LIB_USERNAME, LIB_PASSWORD, EMAIL_RECEIVER
    and LIB_USERNAME2, LIB_PASSWORD2, EMAIL_RECEIVER2, etc.
    """
    accounts = []
    
    # First account (no suffix)
    username = get_config("LIB_USERNAME", "").strip()
    password = get_config("LIB_PASSWORD", "").strip()
    email_receiver = get_config("EMAIL_RECEIVER", "").strip()
    if username and password:
        accounts.append({
            "username": username,
            "password": password,
            "email_receiver": email_receiver
        })
    
    # Check for additional accounts (2, 3, 4, ...)
    for i in range(2, 10):  # Support up to 9 accounts
        username = get_config(f"LIB_USERNAME{i}", "").strip()
        password = get_config(f"LIB_PASSWORD{i}", "").strip()
        email_receiver = get_config(f"EMAIL_RECEIVER{i}", "").strip()
        if username and password:
            accounts.append({
                "username": username,
                "password": password,
                "email_receiver": email_receiver
            })
    
    return accounts

def create_driver():
    """Create and configure Chrome WebDriver"""
    chrome_options = Options()
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    if os.environ.get("GITHUB_ACTIONS"):
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=chrome_options)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    return driver

def parse_due_date(date_str):
    """Parse different date formats from the library system"""
    try:
        date_str = "".join(date_str.split())
        formats = ["%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d", "%d-%b-%Y"]
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        return None
    except Exception:
        return None


def extract_column_index_by_header(table, *header_keywords):
    """Find the zero-based column index whose header contains any of the keywords."""
    try:
        headers = table.find_elements(By.CSS_SELECTOR, "thead th, tr th, thead td, tr td")
        for idx, th in enumerate(headers):
            header = th.text.strip().lower()
            if not header:
                continue
            for keyword in header_keywords:
                if keyword.lower() in header:
                    print(f"[debug] Matched header '{th.text.strip()}' at index {idx} for keyword '{keyword}'")
                    return idx
        # Log unmatched headers for debugging
        header_texts = [th.text.strip() for th in headers]
        if header_texts:
            print(f"[debug] Table headers found: {header_texts}")
    except Exception as e:
        print(f"[debug] Header extraction failed: {e}")
    return None


def extract_times_renewed(cols, times_renewed_index=None):
    """Extract times renewed value. Prefer the column matched by header; otherwise scan all cells."""
    pattern = re.compile(r"\d+\s*of\s*\d+", re.IGNORECASE)

    if times_renewed_index is not None and 0 <= times_renewed_index < len(cols):
        text = " ".join(cols[times_renewed_index].text.split())
        print(f"[debug] Times Renewed column {times_renewed_index} raw text: '{cols[times_renewed_index].text}'")
        match = pattern.search(text)
        if match:
            return match.group(0)

    print("[debug] Falling back to scanning all row cells for 'X of Y'")
    for idx, col in enumerate(cols):
        text = " ".join(col.text.split())
        if text:
            match = pattern.search(text)
            if match:
                print(f"[debug] Found match '{match.group(0)}' in column {idx}")
                return match.group(0)
    print("[debug] No 'X of Y' pattern found in any cell")
    return "Not available"


def map_checkout_columns(table):
    """Map checkout table columns to title/author/call number/due date indexes."""
    indexes = {"title": 1, "author": None, "call_no": None, "due": 4}
    try:
        headers = table.find_elements(By.CSS_SELECTOR, "thead th, tr th")
        header_texts = [h.text.strip() for h in headers]
    except Exception as e:
        print(f"[debug] Could not read table headers: {e}")
        return indexes

    if not header_texts:
        print("[debug] No table headers found, using default column indexes")
        return indexes

    keyword_map = {
        "title": ("title", "書名"),
        "author": ("author", "作者"),
        "call_no": ("call", "索書號", "source", "電子"),
        "due": ("due", "到期"),
    }
    for field, keywords in keyword_map.items():
        for idx, header in enumerate(header_texts):
            lowered = header.lower()
            if header and any(keyword.lower() in lowered for keyword in keywords):
                indexes[field] = idx
                break
    print(f"[debug] Checkout column mapping: {indexes} from headers {header_texts}")
    return indexes


def find_renew_button(driver, wait):
    """Find the renew button using multiple selector strategies."""
    selectors = [
        (By.CSS_SELECTOR, "#renew"),
        (By.CSS_SELECTOR, "button.renew"),
        (By.CSS_SELECTOR, "input[type='submit'][name='renew']"),
        (By.CSS_SELECTOR, "button[name='renew']"),
        (By.XPATH, "//input[contains(translate(@value, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'renew')]"),
        (By.XPATH, "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'renew')]"),
        (By.XPATH, "//a[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'renew')]"),
    ]

    for by, selector in selectors:
        try:
            elements = driver.find_elements(by, selector)
            for elem in elements:
                if elem.is_displayed() and elem.is_enabled():
                    return elem
        except Exception:
            continue

    # Final fallback: wait for any clickable renew-like element
    return wait.until(EC.element_to_be_clickable(
        (By.XPATH, "//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'renew')]")
    ))


def get_checkout_table(driver, username):
    """Locate the checkout table, refreshing if the page shows an internal error."""
    short_wait = WebDriverWait(driver, 10)
    for attempt in range(1, 4):
        try:
            if "Internal Error" in driver.title:
                print(f"[{username}] Account page shows internal error (attempt {attempt}), refreshing...")
                driver.refresh()
                time.sleep(3)
                continue

            table = short_wait.until(EC.presence_of_element_located((By.ID, "checkout")))
            return table
        except Exception as e:
            print(f"[{username}] Checkout table not ready (attempt {attempt}): {type(e).__name__}")
            if attempt < 3:
                try:
                    driver.refresh()
                    time.sleep(3)
                except Exception as refresh_err:
                    print(f"[{username}] Refresh failed: {refresh_err}")
                    raise
            else:
                raise RuntimeError(f"Checkout table not found after {attempt} attempts: {type(e).__name__}")

    raise RuntimeError("Checkout table not found")


def looks_like_call_no(text):
    """Check whether a text snippet is plausibly a call number / e-book source."""
    t = re.sub(r"\s+", " ", text or "").strip(" :：-–—|")
    if not t or len(t) > 40:
        return False
    for word in ("館藏地", "條碼", "狀態", "應還", "到期", "館別", "架位", "索書號",
                 "Call No", "Call Number", "Collection", "Status"):
        if word.lower() in t.lower():
            return False
    if "/" in t:
        return False
    if not re.search(r"\d", t):
        return any(source in t.lower() for source in history_store.EBOOK_SOURCES)
    return bool(re.search(r"[A-Za-z.]", t) or " " in t)


def clean_call_no_candidate(text, label_text=""):
    """Remove the label text and stray separators from a candidate snippet."""
    t = re.sub(r"\s+", " ", text or "").strip()
    if label_text:
        t = re.sub(re.escape(re.sub(r"\s+", " ", label_text).strip()), " ", t, count=1)
    t = re.sub(r"(索書號|call\s*no\.?|call\s*number)\s*[:：]?", " ", t, flags=re.IGNORECASE, count=1)
    return t.strip(" :：|")


def _call_no_from_tables(page):
    """Scan HTML tables for a 索書號/Call Number column and read its first value."""
    soup = None
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(page, "html.parser")
    except Exception:
        return ""
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        header_cells = rows[0].find_all(["th", "td"])
        col_idx = None
        for idx, cell in enumerate(header_cells):
            if CALL_NO_LABEL_RE.search(cell.get_text(" ", strip=True)):
                col_idx = idx
                break
        if col_idx is None:
            continue
        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if col_idx < len(cells):
                value = clean_call_no_candidate(cells[col_idx].get_text(" ", strip=True))
                if looks_like_call_no(value):
                    return value
    return ""


def _call_no_from_labels(page):
    """Scan HTML for label text nodes and read the value beside them."""
    soup = None
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(page, "html.parser")
    except Exception:
        return ""
    for text_node in soup.find_all(string=CALL_NO_LABEL_RE):
        parent = text_node.parent
        if parent is None:
            continue
        label_text = re.sub(r"\s+", " ", text_node.strip())
        if not label_text or len(label_text) > 30:
            continue
        value = clean_call_no_candidate(parent.get_text(" ", strip=True), label_text)
        if looks_like_call_no(value):
            return value
        sibling = parent.find_next_sibling()
        if sibling is not None:
            value = clean_call_no_candidate(sibling.get_text(" ", strip=True), "")
            if looks_like_call_no(value):
                return value
    return ""


def extract_call_no(driver):
    """Extract the call number (索書號) from a catalogue detail page.

    Tries, in order: label elements in the live DOM, structured HTML table
    columns, generic HTML label/value pairs, and finally a text-flow scan of
    the page source. Returns '' when nothing plausible is found.
    """
    label_xpaths = [
        "//*[contains(text(), '索書號')]",
        "//*[contains(text(), 'Call Number')]",
        "//*[contains(text(), 'Call No')]",
    ]
    for xpath in label_xpaths:
        try:
            labels = driver.find_elements(By.XPATH, xpath)
        except Exception:
            continue
        for label in labels:
            try:
                label_text = label.text.strip()
                if not label_text or len(label_text) > 30:
                    continue
                candidates = []
                try:
                    row = label.find_element(By.XPATH, "ancestor::tr[1]")
                    if row is not label:
                        candidates.append(row.text)
                except Exception:
                    pass
                if not candidates:
                    try:
                        candidates.append(label.find_element(By.XPATH, "..").text)
                    except Exception:
                        pass
                try:
                    candidates.append(
                        label.find_element(By.XPATH, "following-sibling::*[1]").text
                    )
                except Exception:
                    pass
                for candidate in candidates:
                    value = clean_call_no_candidate(candidate, label_text)
                    if looks_like_call_no(value):
                        return value
            except Exception:
                continue

    try:
        page = driver.page_source or ""
    except Exception:
        return ""
    if not page:
        return ""

    value = _call_no_from_tables(page)
    if value:
        return value
    value = _call_no_from_labels(page)
    if value:
        return value

    text = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", page, flags=re.S | re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "\n", text))
    lines = [line.strip() for line in text.splitlines()]
    for i, line in enumerate(lines):
        if not line or not CALL_NO_LABEL_RE.search(line):
            continue
        remainder = clean_call_no_candidate(line, "")
        if looks_like_call_no(remainder):
            return remainder
        for j in range(i + 1, min(i + 13, len(lines))):
            nxt = lines[j]
            if not nxt:
                continue
            if CALL_NO_LABEL_RE.search(nxt):
                break
            if looks_like_call_no(nxt):
                return nxt
    return ""


def fetch_call_no(driver, wait, detail_url, username, title):
    """Open a book's detail page and extract its call number (索書號)."""
    try:
        print(f"[{username}] Fetching call number from detail page: {title}")
        driver.get(detail_url)
        wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
        time.sleep(1)
        value = extract_call_no(driver)
        if value:
            print(f"[{username}] Call number found: {value}")
        else:
            print(f"[{username}] Call number not found on detail page")
        return value
    except Exception as e:
        print(f"[{username}] Failed to fetch call number for '{title}': {e}")
        return ""


def build_book_record(username, row_index, cols, column_indexes, times_renewed_index):
    """Parse one checkout row into a detailed book record.

    Returns None when the row has no parseable due date.
    """
    raw_cells = [col.text.strip() for col in cols]

    def cell_text(key):
        idx = column_indexes.get(key)
        if idx is not None and 0 <= idx < len(raw_cells):
            return raw_cells[idx]
        return ""

    title_cell = cell_text("title") or (raw_cells[1] if len(raw_cells) > 1 else "")
    due_date_str = cell_text("due") or (raw_cells[4] if len(raw_cells) > 4 else "")

    title_idx = column_indexes.get("title")
    if title_idx is None or not (0 <= title_idx < len(cols)):
        title_idx = 1 if len(cols) > 1 else None
    detail_url = ""
    if title_idx is not None:
        try:
            for anchor in cols[title_idx].find_elements(By.CSS_SELECTOR, "a[href]"):
                href = (anchor.get_attribute("href") or "").strip()
                if href and not href.lower().startswith("javascript"):
                    detail_url = href
                    break
        except Exception:
            detail_url = ""
    due_date = parse_due_date(due_date_str)
    if not due_date:
        print(f"[{username}] Row {row_index}: could not parse due date '{due_date_str}'")
        return None

    times_renewed = extract_times_renewed(cols, times_renewed_index)
    author = cell_text("author")
    if author:
        history_title = title_cell
    else:
        history_title, author = history_store.parse_author_from_title(title_cell)

    call_no = cell_text("call_no")
    if not call_no:
        skip = {title_cell, author, due_date_str}
        if raw_cells:
            skip.add(raw_cells[0])
        call_no = history_store.guess_call_no(raw_cells, skip)

    print(f"[{username}] Row {row_index}: title='{title_cell}', author='{author}', "
          f"call_no='{call_no}', due={due_date_str}, times_renewed='{times_renewed}'")
    return {
        "title": title_cell,
        "history_title": history_title,
        "author": author,
        "call_no": call_no,
        "detail_url": detail_url,
        "due_date": due_date,
        "due_date_str": due_date_str,
        "times_renewed": times_renewed,
    }


def send_email(subject, body, receiver_email):
    """Send an email using Gmail SMTP"""
    sender_email = EMAIL_SENDER
    password = GMAIL_PWD

    if not receiver_email:
        print("No email receiver configured, skipping email")
        return

    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = receiver_email
    message["Subject"] = subject

    message.attach(MIMEText(body, "plain"))

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, password)
        server.sendmail(sender_email, receiver_email, message.as_string())
        server.quit()
        print(f"Email sent successfully to {receiver_email}")
    except Exception as e:
        print(f"Failed to send email: {str(e)}")

def process_account(account):
    """Process renewal for a single library account. Returns True on success, False on failure."""
    username = account["username"]
    password = account["password"]
    email_receiver = account.get("email_receiver")
    
    print(f"\n{'='*60}")
    print(f"Processing account: {username}")
    print(f"{'='*60}")
    
    driver = create_driver()
    wait = WebDriverWait(driver, 25)
    
    try:
        # Step 1: Navigate to English login page
        driver.get("https://www.hkpl.gov.hk/en/login.html")
        print(f"[{username}] Step 1: Login page loaded")

        # Step 2: Enter credentials and submit
        username_field = wait.until(EC.presence_of_element_located((By.NAME, "USER")))
        password_field = wait.until(EC.element_to_be_clickable((By.NAME, "PASSWORD")))

        username_field.clear()
        username_field.send_keys(username)
        password_field.clear()
        password_field.send_keys(password)
        password_field.submit()
        print(f"[{username}] Step 2: Credentials submitted")

        # Step 3: Wait until we have left the login page
        wait.until(lambda d: "login.html" not in d.current_url)
        print(f"[{username}] Step 3: Login successful - current URL: {driver.current_url}")
        
        # Step 4: Handle popup and overlay
        try:
            overlay = driver.find_element(By.ID, "isd-overlay")
            driver.execute_script("arguments[0].remove();", overlay)
            print(f"[{username}] Step 4: Removed overlay with JavaScript")
        except:
            print(f"[{username}] Step 4: No overlay found")

        # Step 5: Get the current window handle (original tab)
        original_window = driver.current_window_handle
        print(f"[{username}] Original window handle: {original_window}")
        
        # Step 6: Click the "Go" button which opens a new tab
        go_link = wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "a.ac_logout_btn")
        ))
        go_link.click()
        print(f"[{username}] Step 5: Clicked Go button - new tab should open")
        
        # Step 7: Wait for the new tab to open and switch to it
        WebDriverWait(driver, 10).until(EC.number_of_windows_to_be(2))
        
        for window_handle in driver.window_handles:
            if window_handle != original_window:
                driver.switch_to.window(window_handle)
                print(f"[{username}] Step 6: Switched to new window: {window_handle}")
                break
        
        # Step 8: Wait for the account page to load in the new tab
        wait.until(EC.url_contains("PatronAccountPage"))
        print(f"[{username}] Step 7: Account page loaded: {driver.current_url}")

        # Wait for the page to finish rendering
        wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
        time.sleep(2)

        # Step 9: Extract borrowed books and identify near-due items
        print(f"[{username}] Step 8: Extracting borrowed books...")

        table = get_checkout_table(driver, username)
        print(f"[{username}] Found checkout table")

        times_renewed_index = extract_column_index_by_header(table, "Times Renewed", "Renewed", "續借")
        if times_renewed_index is not None:
            print(f"[{username}] 'Times Renewed' column index: {times_renewed_index}")
        else:
            print(f"[{username}] 'Times Renewed' header not found, will scan row cells")

        rows = table.find_elements(By.CSS_SELECTOR, "tbody tr")
        today = datetime.now()
        borrowed_books = []
        near_due_books = []
        renewable_books = []
        renewal_error = None
        
        if rows:
            print(f"\n[{username}] Your Borrowed Books:")
            print("=" * 50)
            for row_index, row in enumerate(rows):
                cols = row.find_elements(By.TAG_NAME, "td")
                if len(cols) >= 5:
                    title = cols[1].text.strip()
                    due_date_str = cols[4].text.strip()
                    selection_text = cols[0].text.strip()
                    renewal_checkboxes = cols[0].find_elements(
                        By.CSS_SELECTOR, "input[type='checkbox']"
                    )
                    due_date = parse_due_date(due_date_str)
                    if due_date:
                        days_until_due = (due_date - today).days
                        book = {
                            'title': title,
                            'due_date': due_date,
                            'due_date_str': due_date_str,
                            'row_index': row_index
                        }
                        borrowed_books.append(book)
                        if 0 <= days_until_due <= 2:
                            print(f"Title: {title}")
                            print(f"Due Date: {due_date_str} ({days_until_due} days remaining)")
                            print("⚠️ Book is near due - will select for renewal")
                            near_due_books.append(book)
                            if (
                                "already renewed" not in selection_text.lower()
                                and any(
                                    checkbox.is_displayed() and checkbox.is_enabled()
                                    for checkbox in renewal_checkboxes
                                )
                            ):
                                renewable_books.append(book)
                            else:
                                status = selection_text or "no selectable checkbox"
                                print(f"Renewal unavailable ({status})")
                            print("-" * 50)
                    else:
                        print(f"Title: {title}")
                        print(f"Due Date: {due_date_str} (format not recognized)")
                        print("-" * 50)
            print(f"[{username}] Total books: {len(borrowed_books)}")
            print(f"[{username}] Books near due: {len(near_due_books)}")
        else:
            print(f"[{username}] No borrowed books found")
        
        # Step 10: Select near-due books for renewal
        if renewable_books:
            print(f"\n[{username}] Selecting near-due books for renewal...")
            try:
                selected_count = 0
                for book in renewable_books:
                    row = rows[book['row_index']]
                    cols = row.find_elements(By.TAG_NAME, "td")
                    checkboxes = cols[0].find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
                    if checkboxes:
                        checkbox = checkboxes[0]
                        if checkbox.is_displayed() and checkbox.is_enabled():
                            if not checkbox.is_selected():
                                checkbox.click()
                                print(f"[{username}] Selected: {book['title']}")
                            selected_count += 1

                if selected_count:
                    renew_button = find_renew_button(driver, wait)
                    try:
                        renew_button.click()
                    except Exception as click_err:
                        print(f"[{username}] Normal click failed ({click_err}), trying JavaScript click")
                        driver.execute_script("arguments[0].click();", renew_button)
                    print(f"[{username}] Clicked renew button")
                    time.sleep(5)  # Wait for renewal processing to complete
                    print(f"[{username}] Renewal processing completed")
                else:
                    print(f"[{username}] No selectable near-due books found")
            except Exception as e:
                renewal_error = f"{type(e).__name__}: {str(e) or 'no additional details'}"
                print(f"[{username}] Error during renewal: {renewal_error}")
        elif near_due_books:
            print(f"[{username}] No near-due books are eligible for renewal")
        else:
            print(f"[{username}] No near-due books to renew")
        
        # Re-extract current books after renewal attempt
        rows = table.find_elements(By.CSS_SELECTOR, "tbody tr")
        column_indexes = map_checkout_columns(table)
        current_books = []
        for row_index, row in enumerate(rows):
            cols = row.find_elements(By.TAG_NAME, "td")
            if len(cols) >= 5:
                book = build_book_record(username, row_index, cols, column_indexes, times_renewed_index)
                if book:
                    current_books.append(book)

        for book in current_books:
            if book["call_no"] or not book.get("detail_url"):
                continue
            book["call_no"] = fetch_call_no(driver, wait, book["detail_url"], username, book["title"])

        # Step 12: Record borrow history and send email with borrowed book status
        try:
            history_books = [
                {"title": book["history_title"], "author": book["author"], "call_no": book["call_no"]}
                for book in current_books
            ]
            history_store.update_history(username, history_books)
        except Exception as e:
            print(f"[{username}] Failed to update borrow history: {e}")

        if current_books:
            email_body = f"Library Book Renewal Status for {username}\n\n"
            email_body += f"Total borrowed books: {len(current_books)}\n\n"
            email_body += "Your currently borrowed books:\n\n"
            for book in current_books:
                email_body += f"Title: {book['title']}\n"
                if book["author"]:
                    email_body += f"Author: {book['author']}\n"
                if book["call_no"]:
                    email_body += f"Call No.: {book['call_no']}\n"
                email_body += f"Due Date: {book['due_date'].strftime('%Y-%m-%d')}\n"
                email_body += f"Times Renewed: {book['times_renewed']}\n"
                original_book = next((b for b in near_due_books if b['title'] == book['title']), None)
                if original_book:
                    if book['due_date'] > original_book['due_date']:
                        email_body += "Renewal successful\n"
                    else:
                        email_body += "Renewal failed\n"
                email_body += "\n"
        else:
            email_body = f"Account {username}: You have no borrowed books."

        if renewal_error:
            email_body += f"\nRenewal action error: {renewal_error}\n"
        
        send_email("Library Book Renewal Status", email_body, email_receiver)
        print(f"[{username}] Account processing completed successfully")
        return True

    except Exception as e:
        print(f"\n[{username}] ❌ An error occurred: {str(e)}")
        print(f"[{username}] Current URL: {driver.current_url}")
        print(f"[{username}] Page title: {driver.title}")
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        with open(f"error_page_{username}_{timestamp}.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        driver.save_screenshot(f"error_screenshot_{username}_{timestamp}.png")
        print(f"[{username}] Saved error_page_{username}_{timestamp}.html and error_screenshot_{username}_{timestamp}.png")
        return False

    finally:
        driver.quit()
        print(f"[{username}] Browser closed")

# Main execution
if __name__ == "__main__":
    accounts = get_accounts()
    
    if not accounts:
        print("No accounts configured. Please set LIB_USERNAME and LIB_PASSWORD environment variables.")
        exit(1)
    
    print(f"Found {len(accounts)} account(s) to process")
    
    failed = False
    for account in accounts:
        if not process_account(account):
            failed = True
    
    print("\n" + "="*60)
    print("All accounts processed")
    print("="*60)

    if failed:
        exit(1)
