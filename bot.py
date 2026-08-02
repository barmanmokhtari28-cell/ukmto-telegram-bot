import os
import json
import html
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from deep_translator import GoogleTranslator

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SEEN_FILE = "seen_ids.json"

# UKMTO Page URLs
URLS_TO_SCRAPE = [
    "https://www.ukmto.org/recent-incidents",
    "https://www.ukmto.org/ukmto-products/advisories",
    "https://www.ukmto.org/ukmto-products/warnings"
]

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
        json.dump(seen_ids[-100:], f, indent=2)

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
    Scrapes UKMTO recent incidents, warnings, and advisories from the past weeks.
    Screenshots each advisory card and returns structured reports.
    """
    reports = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900}
        )
        page = context.new_page()

        for target_url in URLS_TO_SCRAPE:
            try:
                print(f"Connecting to: {target_url}...")
                # Use domcontentloaded instead of networkidle to prevent timeout
                page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(4000)  # Allow JS content/map to render

                # Accept cookies if banner appears
                try:
                    cookie_btn = page.query_selector("button:has-text('Accept'), .cookie-accept")
                    if cookie_btn:
                        cookie_btn.click()
                        page.wait_for_timeout(1000)
                except Exception:
                    pass

                # Locate report elements
                elements = page.query_selector_all("tr, .card, article, div.row, div.grid-item, div.incident")
                print(f"Found {len(elements)} items on {target_url}")

                valid_in_page = 0
                for idx, el in enumerate(elements):
                    text = el.inner_text().strip()

                    # Filter for legitimate UKMTO report text
                    if "UKMTO" in text.upper() and len(text) > 25:
                        report_id = f"ukmto_{hash(text[:150])}"
                        screenshot_file = f"report_photo_{len(reports)}.png"

                        # Capture screenshot of the report container
                        try:
                            el.screenshot(path=screenshot_file)
                        except Exception:
                            page.screenshot(path=screenshot_file, full_page=False)

                        reports.append({
                            "id": report_id,
                            "text": text,
                            "photo_path": screenshot_file,
                            "link": target_url
                        })
                        valid_in_page += 1

                        # Cap max items per page to avoid spamming
                        if valid_in_page >= 8:
                            break

            except Exception as e:
                print(f"Error fetching {target_url}: {e}")

        browser.close()

    return reports

def send_telegram_photo(photo_path, caption):
    """Sends report photo with Persian translation & spoiler text to Telegram."""
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
        print("No UKMTO reports retrieved. Will try again next run.")
        return

    print(f"Total reports collected: {len(reports)}")

    # Process from oldest to newest
    for item in reversed(reports):
        item_id = item["id"]

        if item_id in seen_ids:
            print(f"Skipping previously posted report: {item_id}")
            continue

        raw_text = item["text"]
        link = item["link"]
        photo_path = item["photo_path"]

        # Translate to Persian
        persian_translation = translate_to_persian(raw_text)

        # HTML escape special characters
        safe_persian = html.escape(persian_translation)
        safe_original = html.escape(raw_text)

        # Build Rich Text Caption
        caption = (
            f"🚨 <b>گزارش حادثه مرکز تجارت دریایی بریتانیا (UKMTO)</b>\n\n"
            f"{safe_persian}\n\n"
            f"<tg-spoiler>{safe_original}</tg-spoiler>\n\n"
            f"🔗 <a href='{link}'>منبع گزارش رسمی</a>\n\n"
            f"{FOOTER}"
        )

        print(f"Posting report photo to Telegram channel...")
        success = send_telegram_photo(photo_path, caption)

        if success:
            print("Successfully posted to Telegram!")
            seen_ids.append(item_id)
        else:
            print("Failed to send photo to Telegram.")

    save_seen_ids(seen_ids)

if __name__ == "__main__":
    main()
