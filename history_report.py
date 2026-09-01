"""Generate a printable A4 borrowed-history report for a chosen period.

Example:
    python history_report.py --period "2025.09.01 - 2026.08.31"
    python history_report.py --from 2025.09.01 --to 2026.08.31 --account LIB_USERNAME2

The report is written as an HTML file (reports/ by default) laid out for A4
printing: 10 books per page, each row 1.5 cm high, first column 5 cm wide
(Title of Book and Author), second column 2.5 cm wide (Call No. / Source of
Electronic Book). Print it from any browser with Ctrl+P / Cmd+P.
"""

import argparse
import html
import os
import re
import sys
from datetime import date, datetime

import history_store

DATE_FORMATS = ["%Y.%m.%d", "%Y-%m-%d", "%Y/%m/%d"]
PERIOD_PATTERN = re.compile(
    r"(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})\s*(?:-|–|—|to|至)\s*(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})"
)
DATE_TOKEN_PATTERN = re.compile(r"\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2}")


def parse_date(text):
    """Parse a date in YYYY.MM.DD, YYYY-MM-DD or YYYY/MM/DD format."""
    text = text.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date '{text}'. Use e.g. 2025.09.01 or 2025-09-01")


def parse_period(text):
    """Parse a period from a range string or from one or two standalone dates.

    Accepts '2025.09.01 - 2026.08.31' (separators: -, to, 至), a single date
    like '2025.09.01' (reported for that day only), or two dates in any
    order, e.g. '2026.09.01 2027.08.31'.
    """
    match = PERIOD_PATTERN.search(text or "")
    if match:
        start = parse_date(match.group(1))
        end = parse_date(match.group(2))
    else:
        tokens = DATE_TOKEN_PATTERN.findall(text or "")
        try:
            dates = [parse_date(token) for token in tokens]
        except ValueError as e:
            raise ValueError(f"Invalid date in period: {e}")
        if not dates:
            raise ValueError(
                "No date found. Enter a period like '2025.09.01 - 2026.08.31' "
                "(separators: -, to, 至), a single date like '2025.09.01', "
                "or two dates like '2025.09.01 2026.08.31'"
            )
        start, end = min(dates), max(dates)
    if start > end:
        raise ValueError("Period start date is after the end date")
    return start, end


def record_in_period(record, start, end):
    """True if the borrow interval of the record overlaps [start, end]."""
    try:
        first_seen = datetime.strptime(record["first_seen"], "%Y-%m-%d").date()
    except (KeyError, ValueError):
        return False
    returned = record.get("returned_date")
    if returned:
        try:
            returned = datetime.strptime(returned, "%Y-%m-%d").date()
        except ValueError:
            returned = None
    return first_seen <= end and (returned is None or returned >= start)


def select_records(history, start, end):
    """Return the records of a history that fall inside the period, sorted."""
    records = [r for r in history["records"] if record_in_period(r, start, end)]
    records.sort(key=lambda r: (r.get("first_seen", ""), r.get("title", "")))
    return records


def display_title(record):
    """Combine title and author for the report's first column."""
    title = (record.get("title") or "").strip()
    author = (record.get("author") or "").strip()
    return f"{title} / {author}" if author else title


def mask_account(account):
    """Mask an account id, keeping only the last 4 characters."""
    return f"****{account[-4:]}" if len(account) > 4 else "****"


def display_account(account, options):
    """Return the account label to show in reports and filenames."""
    return mask_account(account) if options.mask_account else account


def safe_account_label(account, options):
    """Return a filesystem-safe account label for output filenames.

    Masked filenames avoid '*' because artifact uploads reject it;
    only the last 4 characters of the card number are kept.
    """
    if not options.mask_account:
        return os.path.basename(history_store.history_path(account))[:-5]
    return f"masked{account[-4:]}" if len(account) > 4 else "masked"


def fmt_cm(value):
    """Format a cm value without trailing zeros (5.0 -> '5', 2.5 -> '2.5')."""
    return f"{value:g}"


def fmt_date(value):
    """Format an ISO date string as YYYY.MM.DD, or a status text."""
    if not value:
        return "on loan 借閱中"
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y.%m.%d")
    except ValueError:
        return value


def build_html(account, records, start, end, options):
    """Build the full HTML document for one account's report."""
    row_height = fmt_cm(options.row_height)
    rows_per_page = options.rows_per_page
    clip_height = fmt_cm(max(options.row_height - 0.2, 0.5))
    today = date.today().strftime("%Y.%m.%d")

    pages = [records[i:i + rows_per_page] for i in range(0, len(records), rows_per_page)] or [[]]
    total_pages = len(pages)

    def row_html(record=None):
        if record is None:
            c1 = c2 = c3 = ""
        else:
            c1 = html.escape(display_title(record))
            c2 = html.escape((record.get("call_no") or "").strip())
            c3 = html.escape(
                f"{fmt_date(record.get('first_seen'))} - {fmt_date(record.get('returned_date'))}"
            )
        cells = f"<td><div class='clip'>{c1}</div></td><td><div class='clip'>{c2}</div></td>"
        if options.with_dates:
            cells += f"<td><div class='clip'>{c3}</div></td>"
        return f"<tr class='data'>{cells}</tr>"

    body_parts = []
    for page_no, page_records in enumerate(pages, start=1):
        meta = (
            f"<p class='meta'>Account: {html.escape(display_account(account, options))} | "
            f"Borrowed history 借閱紀錄 {start.strftime('%Y.%m.%d')} - {end.strftime('%Y.%m.%d')} | "
            f"Page {page_no}/{total_pages} | Generated {today}</p>"
        )
        colgroup = (
            f"<col style='width:{fmt_cm(options.col1_width)}cm'>"
            f"<col style='width:{fmt_cm(options.col2_width)}cm'>"
        )
        if options.with_dates:
            colgroup += "<col style='width:2.6cm'>"
        head_cells = (
            "<th>Title of Book and Author 書名及作者</th>"
            "<th>Call No. / Source of Electronic Book (索書號)</th>"
        )
        if options.with_dates:
            head_cells += "<th>Borrowed - Returned 借閱/歸還</th>"

        rows = [row_html(r) for r in page_records]
        if not options.no_empty_rows:
            rows.extend(row_html() for _ in range(rows_per_page - len(page_records)))

        body_parts.append(
            f"{meta}<table class='records'><colgroup>{colgroup}</colgroup>"
            f"<thead><tr>{head_cells}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
        )
        if page_no < total_pages:
            body_parts.append("<div class='pagebreak'></div>")

    css = f"""
@page {{ size: A4; margin: 1.2cm; }}
body {{ font-family: 'Noto Sans TC', 'Microsoft JhengHei', 'PingFang TC', sans-serif;
       margin: 0; color: #000; }}
p.meta {{ font-size: 7.5pt; color: #444; margin: 0 0 1.5mm 0; }}
table.records {{ border-collapse: collapse; table-layout: fixed; }}
table.records th {{ border: 0.3mm solid #000; font-size: 8.5pt; padding: 1mm;
                    background: #f0f0f0; text-align: left; }}
table.records td {{ border: 0.3mm solid #000; height: {row_height}cm;
                    font-size: {fmt_cm(options.font_size)}pt; padding: 1mm; vertical-align: top; }}
table.records td .clip {{ max-height: {clip_height}cm; overflow: hidden;
                          overflow-wrap: anywhere; }}
div.pagebreak {{ page-break-after: always; }}
"""

    title = f"Borrowed History {start.strftime('%Y.%m.%d')} - {end.strftime('%Y.%m.%d')} ({html.escape(display_account(account, options))})"
    return (
        f"<!DOCTYPE html><html lang='zh-HK'><head><meta charset='utf-8'>"
        f"<title>{title}</title><style>{css}</style></head><body>"
        + "".join(body_parts)
        + "</body></html>"
    )


def build_index(entries, start, end):
    """Build the index page listing the generated reports."""
    today = date.today().strftime("%Y.%m.%d")
    items = "".join(
        f"<li><a href='{html.escape(filename)}'>Account 帳戶: {html.escape(name)}</a> "
        f"— {count} book(s)</li>"
        for name, filename, count in entries
    )
    return (
        "<!DOCTYPE html><html lang='zh-HK'><head><meta charset='utf-8'>"
        "<title>Borrowed History Reports 借閱紀錄報告</title><style>"
        "body { font-family: 'Noto Sans TC', 'Microsoft JhengHei', 'PingFang TC', sans-serif;"
        " margin: 2cm; } h1 { font-size: 14pt; } p.meta { color: #444; font-size: 9pt; }"
        " li { margin: 3mm 0; font-size: 11pt; }</style></head><body>"
        "<h1>Borrowed History Reports 借閱紀錄報告</h1>"
        f"<p class='meta'>Period 期間: {start.strftime('%Y.%m.%d')} - {end.strftime('%Y.%m.%d')}"
        f" | Generated 製作日期: {today}</p><ul>{items}</ul></body></html>"
    )


def generate_reports(accounts, start, end, options):
    """Generate one HTML report per account plus an index page; returns paths."""
    output_dir = options.output
    os.makedirs(output_dir, exist_ok=True)
    written = []
    entries = []
    for account in accounts:
        history = history_store.load_history(account)
        records = select_records(history, start, end)
        if not records:
            print(f"[{account}] No borrowed records in {start} - {end}")
            continue
        html_text = build_html(account, records, start, end, options)
        filename = (
            f"borrow_history_{safe_account_label(account, options)}"
            f"_{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}.html"
        )
        path = os.path.join(output_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(html_text)
        pages = (len(records) + options.rows_per_page - 1) // options.rows_per_page
        print(f"[{account}] {len(records)} book(s), {pages} page(s) -> {path}")
        written.append(path)
        entries.append((display_account(account, options), filename, len(records)))

    if entries:
        index_path = os.path.join(output_dir, "index.html")
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(build_index(entries, start, end))
        print(f"Index page -> {index_path}")
    return written


def parse_args(argv):
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate a printable A4 borrowed-history report from hklib history files."
    )
    parser.add_argument("--account", action="append",
                        help="account name(s) to report; default: all accounts with history")
    parser.add_argument("--period",
                        help="period string, e.g. '2025.09.01 - 2026.08.31', a single date, or two dates")
    parser.add_argument("--from", dest="from_date", help="period start date, e.g. 2025.09.01")
    parser.add_argument("--to", dest="to_date", help="period end date, e.g. 2026.08.31")
    parser.add_argument("--rows-per-page", type=int, default=10,
                        help="books per page (default: 10)")
    parser.add_argument("--row-height", type=float, default=1.5,
                        help="row height in cm (default: 1.5)")
    parser.add_argument("--col1-width", type=float, default=5.0,
                        help="first column width in cm (default: 5)")
    parser.add_argument("--col2-width", type=float, default=2.5,
                        help="second column width in cm (default: 2.5)")
    parser.add_argument("--font-size", type=float, default=9.0,
                        help="data font size in pt (default: 9)")
    parser.add_argument("--with-dates", action="store_true",
                        help="add a Borrowed-Returned date column")
    parser.add_argument("--mask-account", action="store_true",
                        help="mask account/card numbers (e.g. ****1234) in output and filenames")
    parser.add_argument("--no-empty-rows", action="store_true",
                        help="do not pad the last page with empty rows")
    parser.add_argument("--output", default="reports",
                        help="output directory (default: reports)")
    parser.add_argument("--history-dir", default=None,
                        help="directory containing history files (default: history)")
    return parser.parse_args(argv)


def main(argv=None):
    """Entry point for the history report tool."""
    options = parse_args(argv)

    if options.history_dir:
        history_store.HISTORY_DIR = options.history_dir

    try:
        if options.period:
            start, end = parse_period(options.period)
        elif options.from_date or options.to_date:
            start = parse_date(options.from_date) if options.from_date else None
            end = parse_date(options.to_date) if options.to_date else None
            if not start or not end:
                raise ValueError("Both --from and --to are required")
            if start > end:
                raise ValueError("Start date is after the end date")
        else:
            print("Enter report period, e.g. 2025.09.01 - 2026.08.31")
            entered = input("Period: ")
            start, end = parse_period(entered)
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    accounts = options.account or history_store.list_accounts()
    if not accounts:
        print(f"No history files found in '{history_store.HISTORY_DIR}'. "
              f"Run hk_library_renew.py first to record borrow history.")
        return 1

    print(f"Generating borrowed history report for {start} - {end}")
    written = generate_reports(accounts, start, end, options)
    if not written:
        print("No records found for the selected period; no report generated.")
        return 1
    print("Done. Open the HTML file(s) in a browser and print to A4 (Ctrl+P / Cmd+P).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
