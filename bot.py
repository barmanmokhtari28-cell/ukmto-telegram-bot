import os
import json
import html
import time
import requests
import hashlib
from playwright.sync_api import sync_playwright
from deep_translator import GoogleTranslator

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SEEN_FILE = "seen_ids.json"
UKMTO_URL = "https://www.ukmto.org/recent-incidents"

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
    if not text:
        return ""

    input_text = text[:400]
    error_indicators = ["Error 500", "Server Error", "That’s an error", "That's an error"]

    for attempt in range(max_retries):
        try:
            translated = GoogleTranslator(source='auto', target='fa').translate(input_text)
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
    reports = []
    
    keywords = ["ADVISORY", "WARNING", "ATTACK", "HIJACK", "INCIDENT", "BOARDING", "SUSPICIOUS", "FLASH", "NOTICE", "UPDATE"]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 1000}
        )
        page = context.new_page()

        print(f"Opening UKMTO recent incidents page...")
        # Fixed: Changed wait_until to "domcontentloaded" to prevent 60-second timeouts
        page.goto(UKMTO_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        # Accept cookies if banner appears
        try:
            cookie_btn = page.query_selector("button:has-text('Accept'), .cookie-accept")
            if cookie_btn:
                cookie_btn.click()
                page.wait_for_timeout(1000)
        except Exception:
            pass

        # Scroll page down and back up to force dynamic cards to render
        page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
        page.wait_for_timeout(1500)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1500)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1000)

        all_elements = page.query_selector_all("div, tr, article, li")
        found_signatures = set()
        count = 0

        for elem in all_elements:
            try:
                text = elem.inner_text().strip()
                upper_text = text.upper()

                if "UKMTO" in upper_text and any(kw in upper_text for kw in keywords):
                    if 60 < len(text) < 1500:
                        
                        # Filter out parent containers holding multiple report cards
                        sub_matches = elem.query_selector_all("article, div, tr, li")
                        is_parent_container = False
                        for sub in sub_matches:
                            sub_text = sub.inner_text().strip()
                            if len(sub_text) > 50 and sub_text != text and "UKMTO" in sub_text.upper():
                                is_parent_container = True
                                break
                        
                        if is_parent_container:
                            continue

                        text_signature = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
                        
                        if text_signature in found_signatures:
                            continue
                        found_signatures.add(text_signature)

                        photo_filename = f"card_photo_{count}.png"
                        
                        try:
                            elem.screenshot(path=photo_filename)
                        except Exception:
                            page.screenshot(path=photo_filename, full_page=False)

                        reports.append({
                            "id": text_signature,
                            "raw_id_display": text.split("\n")[0][:60],
                            "text": text,
                            "photo_path": photo_filename,
                            "link": UKMTO_URL
                        })
                        count += 1

                        if count >= 20:
                            break

            except Exception:
                continue

        browser.close()

    return reports

def send_telegram_photo(photo_path, caption):
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

    print(f"Found {len(reports)} valid report cards on page!")

    for item in reversed(reports):
        item_id = item["id"]
        display_label = item["raw_id_display"]

        if item_id in seen_ids:
            print(f"Skipping previously posted report: {display_label} (ID: {item_id})")
            continue

        raw_text = item["text"]
        link = item["link"]
        photo_path = item["photo_path"]

        clean_text = " ".join(raw_text.split())
        persian_translation = translate_to_persian(clean_text)

        safe_persian = html.escape(persian_translation[:350])
        safe_original = html.escape(clean_text[:350])

        caption = (
            f"🚨 <b>گزارش حادثه مرکز تجارت دریایی بریتانیا (UKMTO)</b>\n\n"
            f"{safe_persian}\n\n"
            f"<tg-spoiler>{safe_original}</tg-spoiler>\n\n"
            f"🔗 <a href='{link}'>منبع گزارش رسمی</a>\n\n"
            f"{FOOTER}"
        )

        print(f"Posting report card photo to Telegram: {display_label}")
        success = send_telegram_photo(photo_path, caption)

        if success:
            print(f"Successfully posted report photo to Telegram! (ID: {item_id})")
            seen_ids.append(item_id)
        else:
            print("Failed to post photo to Telegram.")

    save_seen_ids(seen_ids)

if __name__ == "__main__":
    main()
