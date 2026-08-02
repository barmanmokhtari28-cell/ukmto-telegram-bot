import os
import json
import html
import requests
from playwright.sync_api import sync_playwright
from deep_translator import GoogleTranslator

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SEEN_FILE = "seen_ids.json"
UKMTO_URL = "https://www.ukmto.org/recent-incidents"

# Required Channel Footer
FOOTER = """🌊 @secretollah
#حادثه_دریایی
#مرکز_تجارت_دریایی_بریتانیا"""

def load_seen_ids():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []

def save_seen_ids(seen_ids):
    with open(SEEN_FILE, "w") as f:
        json.dump(seen_ids[-50:], f, indent=2)

def translate_to_persian(text):
    """Translates report text to Persian."""
    try:
        translated = GoogleTranslator(source='auto', target='fa').translate(text)
        return translated
    except Exception as e:
        print(f"Translation error: {e}")
        return text

def scrape_ukmto_reports():
    """
    Launches Playwright with real browser headers, accepts UKMTO cookies,
    scrapes all recent incident reports (from past weeks), and screenshots each card.
    """
    reports = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Use a realistic User-Agent to prevent UKMTO/Cloudflare blocking
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900}
        )
        page = context.new_page()

        try:
            print("Connecting to UKMTO official recent incidents page...")
            page.goto(UKMTO_URL, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)

            # Automatically accept UKMTO cookie banner if it appears
            try:
                cookie_button = page.query_selector("button:has-text('Accept'), #btn-accept-cookies, .cookie-accept")
                if cookie_button:
                    cookie_button.click()
                    page.wait_for_timeout(1000)
            except Exception:
                pass

            # UKMTO lists reports in table rows (tr) or content blocks
            rows = page.query_selector_all("tr, article, div.card, div.incident-row")
            print(f"Scanning {len(rows)} elements on UKMTO page...")

            valid_count = 0
            for idx, row in enumerate(rows):
                text = row.inner_text().strip()

                # Filter for genuine UKMTO Advisory/Warning entries
                if "UKMTO" in text.upper() and any(k in text.upper() for k in ["WARNING", "ADVISORY", "ATTACK", "INCIDENT", "SUSPICIOUS"]):
                    
                    # Create unique ID based on report text
                    report_id = f"ukmto_{hash(text[:120])}"
                    screenshot_file = f"report_photo_{valid_count}.png"

                    # Take a screenshot of the specific report row/card
                    try:
                        row.screenshot(path=screenshot_file)
                    except Exception:
                        page.screenshot(path=screenshot_file, full_page=False)

                    reports.append({
                        "id": report_id,
                        "text": text,
                        "photo_path": screenshot_file,
                        "link": UKMTO_URL
                    })
                    valid_count += 1
                    
                    # Limit batch to top 10 recent reports per run
                    if valid_count >= 10:
                        break

            print(f"Successfully extracted {len(reports)} UKMTO reports!")

        except Exception as e:
            print(f"Scraping error: {e}")

        browser.close()

    return reports

def send_telegram_photo(photo_path, caption):
    """Posts report photo and HTML-formatted Persian/English text to Telegram."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    data = {
        "chat_id": CHAT_ID,
        "caption": caption[:1024],  # Telegram max caption limit
        "parse_mode": "HTML"
    }

    if os.path.exists(photo_path):
        with open(photo_path, "rb") as photo_file:
            files = {"photo": photo_file}
            res = requests.post(url, data=data, files=files)
            return res.json().get("ok", False)
    return False

def main():
    seen_ids = load_seen_ids()
    reports = scrape_ukmto_reports()

    if not reports:
        print("No reports found on page. Checking alternative selectors...")
        return

    # Process reports from oldest to newest so Telegram receives them in order
    for item in reversed(reports):
        item_id = item["id"]

        if item_id in seen_ids:
            print(f"Skipping already posted ID: {item_id}")
            continue

        raw_text = item["text"]
        link = item["link"]
        photo_path = item["photo_path"]

        # Translate summary to Persian
        persian_translation = translate_to_persian(raw_text)

        # HTML Escape special characters
        safe_persian = html.escape(persian_translation)
        safe_original = html.escape(raw_text)

        # Format Rich Text Caption
        caption = (
            f"🚨 <b>گزارش حادثه مرکز تجارت دریایی بریتانیا (UKMTO)</b>\n\n"
            f"{safe_persian}\n\n"
            f"<tg-spoiler>{safe_original}</tg-spoiler>\n\n"
            f"🔗 <a href='{link}'>منبع گزارش رسمی</a>\n\n"
            f"{FOOTER}"
        )

        print(f"Sending UKMTO report photo & caption to Telegram...")
        success = send_telegram_photo(photo_path, caption)

        if success:
            print("Posted to Telegram successfully!")
            seen_ids.append(item_id)
        else:
            print("Failed to post photo to Telegram.")

    save_seen_ids(seen_ids)

if __name__ == "__main__":
    main()
