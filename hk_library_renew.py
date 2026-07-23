from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from datetime import datetime, timedelta
import time
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# HKPL UI markers used to detect when the login flow and account page have completed.
POST_LOGIN_SELECTOR = "a.ac_logout_btn"
ACCOUNT_PAGE_URL_FRAGMENT = "PatronAccountPage"
CHECKOUT_TABLE_ID = "checkout"
LOGIN_PAGE_URL_FRAGMENT = "login.html"


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
        formats = ["%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d", "%d-%b-%Y"]
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        return None
    except Exception:
        return None


def has_element(driver, by, value):
    """Return True when an element is present on the current page; otherwise return False for a missing element."""
    return bool(driver.find_elements(by, value))


def login_flow_ready(driver):
    """Return True when the account page URL is detected or the post-login button is visible."""
    return (
        ACCOUNT_PAGE_URL_FRAGMENT in driver.current_url
        or has_element(driver, By.CSS_SELECTOR, POST_LOGIN_SELECTOR)
    )


def account_page_ready(driver):
    """Return True when either the account page URL is detected or the checkout table appears on a non-login page."""
    return ACCOUNT_PAGE_URL_FRAGMENT in driver.current_url or (
        has_element(driver, By.ID, CHECKOUT_TABLE_ID)
        and LOGIN_PAGE_URL_FRAGMENT not in driver.current_url
    )


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

        # Step 3: Wait until the login flow completes or the post-login account link appears
        try:
            wait.until(login_flow_ready)
            print(f"[{username}] Step 3: Login flow progressed - current URL: {driver.current_url}")
        except Exception:
            print(
                f"[{username}] Step 3: Timed out waiting for the login flow to complete "
                f"(URL change or post-login link). Current URL: {driver.current_url}"
            )
            raise
        
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
        try:
            wait.until(account_page_ready)
            print(f"[{username}] Step 7: Account page loaded: {driver.current_url}")
        except Exception:
            print(
                f"[{username}] Step 7: Timed out waiting for the account page "
                f"(URL containing 'PatronAccountPage' or checkout table). Current URL: {driver.current_url}"
            )
            raise
        
        # Step 9: Extract borrowed books and identify near-due items
        print(f"[{username}] Step 8: Extracting borrowed books...")
        
        table = wait.until(EC.presence_of_element_located((By.ID, "checkout")))
        print(f"[{username}] Found checkout table")
        
        rows = table.find_elements(By.CSS_SELECTOR, "tbody tr")
        today = datetime.now()
        borrowed_books = []
        near_due_books = []
        
        if rows:
            print(f"\n[{username}] Your Borrowed Books:")
            print("=" * 50)
            for row_index, row in enumerate(rows):
                cols = row.find_elements(By.TAG_NAME, "td")
                if len(cols) >= 5:
                    title = cols[1].text.strip()
                    due_date_str = cols[4].text.strip()
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
        if near_due_books:
            print(f"\n[{username}] Selecting near-due books for renewal...")
            for book in near_due_books:
                row = rows[book['row_index']]
                cols = row.find_elements(By.TAG_NAME, "td")
                if cols:
                    checkbox = cols[0].find_element(By.TAG_NAME, "input")
                    if checkbox.get_attribute("type") == "checkbox" and not checkbox.is_selected():
                        checkbox.click()
                        print(f"[{username}] Selected: {book['title']}")
            
            # Step 11: Click the renew button and wait for processing
            try:
                renew_button = wait.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "#renew, button.renew, input[type='submit'][name='renew'], button[name='renew']")
                ))
                renew_button.click()
                print(f"[{username}] Clicked renew button")
                time.sleep(5)  # Wait for renewal processing to complete
                print(f"[{username}] Renewal processing completed")
            except Exception as e:
                print(f"[{username}] Error during renewal: {str(e)}")
        else:
            print(f"[{username}] No near-due books to renew")
        
        # Re-extract current books after renewal attempt
        rows = table.find_elements(By.CSS_SELECTOR, "tbody tr")
        current_books = {}
        for row in rows:
            cols = row.find_elements(By.TAG_NAME, "td")
            if len(cols) >= 5:
                title = cols[1].text.strip()
                due_date_str = cols[4].text.strip()
                due_date = parse_due_date(due_date_str)
                if due_date:
                    current_books[title] = due_date
        
        # Step 12: Send email with borrowed book status
        if current_books:
            email_body = f"Library Book Renewal Status for {username}\n\n"
            email_body += "Your currently borrowed books:\n\n"
            for title, current_due_date in current_books.items():
                email_body += f"Title: {title}\n"
                email_body += f"Due Date: {current_due_date.strftime('%Y-%m-%d')}\n"
                original_book = next((book for book in near_due_books if book['title'] == title), None)
                if original_book:
                    if current_due_date > original_book['due_date']:
                        email_body += "Renewal successful\n"
                    else:
                        email_body += "Renewal failed\n"
                email_body += "\n"
        else:
            email_body = f"Account {username}: You have no borrowed books."
        
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
