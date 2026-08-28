# HK Library Book Renewal Automation

## Description
An automated Python script that helps users manage their Hong Kong Public Library borrowed books by:
- Automatically logging into the HKPL account
- Checking due dates of borrowed books
- Identifying books that are due within 2 days
- Automatically renewing books that are near their due date
- Reporting each book's **Times Renewed** count (e.g., `1 of 5`) in the notification email
- Detecting books that have already been renewed or are no longer eligible for renewal
- Providing detailed console output of the renewal process
- Saving error logs and screenshots if issues occur

## Features
- Automated login handling
- Multi-format date parsing
- Near-due book detection (<= 2 days)
- Automatic book renewal for eligible items only
- **Times Renewed** reporting in notification emails (e.g., `1 of 5`)
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

## Notification Email
After each run, the script sends an email summarizing your borrowed books. Each book entry includes:

- **Title**
- **Due Date**
- **Times Renewed** — the current renewal count shown by the library, for example `1 of 5`. If the value cannot be read, it will show `Not available`.
- **Renewal result** — shown only for books that were near due and selected for renewal (`Renewal successful` or `Renewal failed`).

## Author
Developed by Tony Mok
Last Updated: 2025.07