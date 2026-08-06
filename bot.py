import os
import json
import html
import time
import requests
from playwright.sync_api import sync_playwright
from deep_translator import GoogleTranslator

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SEEN_FILE = "seen_ids.json"
UKMTO_URL = "https://www.ukmto.org/recent-incidents"

# Channel Footer
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

def translate_to_persian(text, max_retries=3):
    """Translates summary into Persian with retry logic and error detection."""
    if not text:
        return ""

    input_text = text[:400]
    error_indicators = ["Error 500", "Server Error", "That’s an error", "That's an error"]

    for attempt in range(max_retries):
        try:
            translated = GoogleTranslator(source='auto', target='fa').translate(input_text)
            
            # Check if Google returned an error response page instead of a translation
            if translated and any(indicator in translated for indicator in error_indicators):
                print(f"[DEBUG] Translation attempt {attempt + 1} returned Google Error page text. Retrying...")
                time.sleep(2)
                continue

            if translated:
                return translated
        except Exception as e:
            print(f"[DEBUG] Translation attempt {attempt + 1} error: {e}")
            time.sleep(2)

    print("[DEBUG] Translation failed after max retries. Using original text as fallback.")
    return input_text

def scrape_ukmto_report_cards():
    """
    Finds all UKMTO report cards on the webpage and takes 
    an element screenshot of each card.
    """
    reports = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 1000}
        )
        page = context.new_page()

        print(f"Opening UKMTO recent incidents page...")
        page.goto(UKMTO_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        # Accept cookies
        try:
            cookie_btn = page.query_selector("button:has-text('Accept'), .cookie-accept")
            if cookie_btn:
                cookie_btn.click()
                page.wait_for_timeout(1000)
        except Exception:
            pass

        # Query all elements on page
        all_elements = page.query_selector_all("div, tr, article, li")
        
        found_keys = set()
        count = 0

        for elem in all_elements:
            try:
                text = elem.inner_text().strip()
                
                # Target UKMTO report card elements
                if "UKMTO" in text and ("ADVISORY" in text or "WARNING" in text or "ATTACK" in text or "HIJACK" in text):
                    # Filter for element length of a report card
                    if 60 < len(text) < 1200:
                        
                        # Generate unique ID from the report text
                        first_line = text.split("\n")[0] if "\n" in text else text[:60]
                        report_key = f"ukmto_{hash(first_line)}"
                        
                        if report_key in found_keys:
                            continue
                        found_keys.add(report_key)

                        photo_filename = f"card_photo_{count}.png"
                        
                        # Screenshot the exact report card element on screen
                        try:
                            elem.screenshot(path=photo_filename)
                        except Exception:
                            page.screenshot(path=photo_filename, full_page=False)

                        reports.append({
                            "id": first_line,
                            "text": text,
                            "photo_path": photo_filename,
                            "link": UKMTO_URL
                        })
                        count += 1
                        
                        if count >= 15:
                            break

            except Exception:
                continue

        browser.close()

    return reports

def send_telegram_photo(photo_path, caption):
    """Sends report photo with Persian translation & spoiler formatting to Telegram."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    data = {
        "chat_id": CHAT_ID,
        "caption": caption[:1024],
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
    reports = scrape_ukmto_report_cards()

    if not reports:
        print("No report cards found on UKMTO page.")
        return

    print(f"Found {len(reports)} report cards on page!")

    # Process from oldest to newest
    for item in reversed(reports):
        item_id = item["id"]

        if item_id in seen_ids:
            print(f"Skipping previously posted report: {item_id}")
            continue

        raw_text = item["text"]
        link = item["link"]
        photo_path = item["photo_path"]

        # Clean text formatting
        clean_text = " ".join(raw_text.split())

        # Translate summary to Persian
        persian_translation = translate_to_persian(clean_text)

        # HTML escape
        safe_persian = html.escape(persian_translation[:350])
        safe_original = html.escape(clean_text[:350])

        caption = (
            f"🚨 <b>گزارش حادثه مرکز تجارت دریایی بریتانیا (UKMTO)</b>\n\n"
            f"{safe_persian}\n\n"
            f"<tg-spoiler>{safe_original}</tg-spoiler>\n\n"
            f"🔗 <a href='{link}'>منبع گزارش رسمی</a>\n\n"
            f"{FOOTER}"
        )

        print(f"Posting report card photo to Telegram: {item_id}")
        success = send_telegram_photo(photo_path, caption)

        if success:
            print("Successfully posted report photo to Telegram!")
            seen_ids.append(item_id)
        else:
            print("Failed to post photo to Telegram.")

    save_seen_ids(seen_ids)

if __name__ == "__main__":
    main()
