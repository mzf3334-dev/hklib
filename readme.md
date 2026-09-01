# HK Library Book Renewal Automation

## Description
An automated Python script that helps users manage their Hong Kong Public Library borrowed books by:
- Automatically logging into the HKPL account
- Checking due dates of borrowed books
- Identifying books that are due within 3 days
- Automatically renewing books that are near their due date
- Reporting each book's **Times Renewed** count (e.g., `1 of 5`) in the notification email
- Detecting books that have already been renewed or are no longer eligible for renewal
- Keeping a **borrow history per account**: every newly borrowed book is recorded the first time the script sees it, and books are marked returned once they disappear from the loans list
- Generating a **printable borrowed history report** for any period (10 books per A4 page, sized for cutting and pasting into a record book)
- Providing detailed console output of the renewal process
- Saving error logs and screenshots if issues occur

## Features
- Automated login handling
- Multi-format date parsing
- Near-due book detection (<= 3 days)
- Automatic book renewal for eligible items only
- Times Renewed reporting in notification emails (e.g., `1 of 5`)
- Skips already-renewed or non-renewable items
- Resilient account-page loading with retry on internal errors
- Error handling with debug information
- Chrome WebDriver automation

## Technical Implementation
Built using:
- Selenium WebDriver for browser automation
- Python datetime for date handling
- Environment variables for credentials management

## Configuration Setup
The script uses environment variables for configuration. You can set these in your local environment or as GitHub Secrets.

### Required Variables
- `LIB_USERNAME`: Your library card number.
- `LIB_PASSWORD`: Your library password.
- `EMAIL_SENDER`: Your Gmail address.
- `EMAIL_RECEIVER`: The recipient email address.
- `GMAIL_PWD`: Your Gmail app password (Generate from Google Account settings).

### Gmail Setup for `EMAIL_SENDER`
To use a Gmail account as the sender, you must use an **App Password** because standard password login is disabled for security.
1. Enable **2-Step Verification** in your [Google Account Security settings](https://myaccount.google.com/security).
2. Search for "App Passwords" in the search bar or go to the [App Passwords page](https://myaccount.google.com/apppasswords).
3. Create a new app password (e.g., name it "Library Renewal").
4. Use the generated **16-character code** as your `GMAIL_PWD`.

## Local Usage

### Prerequisites
- Python 3.10 or higher
- Chrome Browser installed

### Installation
1. Install the required dependencies:
```bash
pip install -r requirements.txt
```

### Running the Script
1. Ensure you have completed the [Configuration Setup](#configuration-setup).
2. Run the script:
```bash
python hk_library_renew.py
```

## GitHub Actions Automation
This project is configured to run automatically using GitHub Actions.

### Setup Instructions
1. Go to your GitHub repository.
2. Navigate to **Settings** > **Secrets and variables** > **Actions**.
3. Create the following **Repository secrets**:
    - `LIB_USERNAME`: Your library card number.
    - `LIB_PASSWORD`: Your library password.
    - `EMAIL_SENDER`: Your Gmail address.
    - `EMAIL_RECEIVER`: The recipient email address.
    - `GMAIL_PWD`: Your Gmail App Password.
    
    To support multiple accounts, you can add:
    - `LIB_USERNAME2`, `LIB_PASSWORD2`, `EMAIL_RECEIVER2`
    - `LIB_USERNAME3`, `LIB_PASSWORD3`, `EMAIL_RECEIVER3`
    - (Up to 9 accounts supported)

    **Note:** The script will automatically skip any account if the `LIB_USERNAME` or `LIB_PASSWORD` is not set or is an empty string.

4. The script is scheduled to run daily at 6 PM HKT. You can also trigger it manually from the **Actions** tab.

## Borrow History

The script keeps a borrowing history for each library account so past loans are never lost:

- Every book the script sees on loan **for the first time** is recorded in `history/<account>.json` with its title, author and call number (or e-book source), plus the date it was first seen.
- A book that stays on loan keeps its record and has its `last_seen` date refreshed on every run.
- When a book no longer appears in the loans list, its record is marked as returned (`returned_date` = the run date when the return was first noticed).
- The notification email lists any books newly added to the history.

History files are committed back to the repository automatically after each GitHub Actions run, so the history survives between scheduled runs.

### History file format

```json
{
  "account": "LIB_USERNAME",
  "records": [
    {
      "title": "The Hobbit",
      "author": "J. R. R. Tolkien",
      "call_no": "823.912 TOL",
      "first_seen": "2025-09-01",
      "last_seen": "2025-09-20",
      "returned_date": "2025-09-21"
    }
  ]
}
```

## Borrowed History Report

Generate a printable report of all books borrowed within a period:

```bash
# Interactive (asks for the period)
python history_report.py

# Explicit period
python history_report.py --period "2025.09.01 - 2026.08.31"

# Equivalent start/end options, one specific account only
python history_report.py --from 2025.09.01 --to 2026.08.31 --account LIB_USERNAME2
```

The report is written to `reports/` as an HTML file. Open it in a browser and print to A4 (Ctrl+P / Cmd+P).

Layout is designed for cutting out rows and pasting them into a record book:

- **10 books per page**
- Each row is **1.5 cm high** (last page padded with empty rows for hand-written entries)
- First column (Title of Book and Author 書名及作者): **5 cm wide**
- Second column (Call No. / Source of Electronic Book (索書號)): **2.5 cm wide**

All layout values can be adjusted:

| Option | Default | Description |
| --- | --- | --- |
| `--rows-per-page` | 10 | Books per page |
| `--row-height` | 1.5 | Row height in cm |
| `--col1-width` | 5 | First column width in cm |
| `--col2-width` | 2.5 | Second column width in cm |
| `--font-size` | 9 | Data font size in pt |
| `--with-dates` | off | Adds a Borrowed/Returned date column |
| `--no-empty-rows` | off | Do not pad the last page with empty rows |
| `--output` | reports | Output directory |
| `--history-dir` | history | Directory containing history files |

## Notification Email
After each run, the script sends an email summarizing your borrowed books. Each book entry includes:

- **Title**
- **Due Date**
- **Times Renewed** — the current renewal count shown by the library, for example `1 of 5`. If the value cannot be read, it will show `Not available`.
- **Renewal result** — shown only for books that were near due and selected for renewal (`Renewal successful` or `Renewal failed`).

## Author
Developed by Tony Mok
Last Updated: 2026.09
