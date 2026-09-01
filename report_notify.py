"""Email the report link after a GitHub Actions report run finishes.

Reads REPORT_URL, EMAIL_SENDER, EMAIL_RECEIVER (comma-separated list allowed)
and GMAIL_PWD from the environment. Skips silently when they are not set.
"""

import os
import smtplib
from email.mime.text import MIMEText


def main():
    """Send the notification email; returns a process exit code."""
    url = (os.environ.get("REPORT_URL") or "").strip()
    sender = (os.environ.get("EMAIL_SENDER") or "").strip()
    password = os.environ.get("GMAIL_PWD") or ""
    receivers = [
        r.strip() for r in (os.environ.get("EMAIL_RECEIVER") or "").split(",") if r.strip()
    ]
    if not (sender and password and receivers):
        print("Email not configured (EMAIL_SENDER / EMAIL_RECEIVER / GMAIL_PWD); skip notification")
        return 0

    body = "Your borrowed history report has been generated.\n\n"
    if url:
        body += f"View online: {url}\n\n"
    body += "Open it in a browser and print to A4 with Ctrl+P / Cmd+P if needed."

    message = MIMEText(body)
    message["From"] = sender
    message["To"] = ", ".join(receivers)
    message["Subject"] = "Borrowed history report is ready"

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, receivers, message.as_string())
        server.quit()
        print(f"Notification email sent to {message['To']}")
    except Exception as e:
        print(f"Failed to send notification email: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
