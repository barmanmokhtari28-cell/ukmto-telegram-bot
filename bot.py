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
UKMTO_URL = "https://www.ukmto.org/recent-incidents"

# Channel signature footer
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
    """Translates text to Persian."""
    try:
        translated = GoogleTranslator(source='auto', target='fa').translate(text)
        return translated
    except Exception as e:
        print(f"Translation error: {e}")
        return text

def scrape_ukmto_incidents():
    """
    Scrapes the official UKMTO website for recent incidents 
    and screenshots the advisory card using Playwright.
    """
    incidents = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        
        try:
            print("Navigating to UKMTO recent incidents...")
            page.goto(UKMTO_URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)  # Wait for JS elements to render
            
            # Extract incident elements
            content = page.content()
            soup = BeautifulSoup(content, "html.parser")
            
            # UKMTO incident card selectors
            cards = page.query_selector_all(".incident-card, .card, article, tr")
            
            # Fallback: grab textual blocks if cards selector differs
            blocks = soup.find_all(["div", "article", "tr"], class_=lambda x: x and ("incident" in x or "report" in x or "card" in x))
            
            print(f"Found {len(blocks)} potential incident blocks on page.")
            
            # Iterate through found incidents
            for idx, block in enumerate(blocks[:5]):
                text_content = block.get_text(strip=True)
                if len(text_content) < 20 or "UKMTO" not in text_content.upper():
                    continue

                incident_id = f"ukmto_{hash(text_content[:100])}"
                screenshot_filename = f"report_{idx}.png"

                # Capture photo/screenshot of the specific report element
                try:
                    if idx < len(cards):
                        cards[idx].screenshot(path=screenshot_filename)
                    else:
                        page.screenshot(path=screenshot_filename, full_page=False)
                except Exception as err:
                    print(f"Screenshot error: {err}")
                    page.screenshot(path=screenshot_filename, full_page=False)

                incidents.append({
                    "id": incident_id,
                    "text": text_content[:500],  # Title/summary
                    "photo_path": screenshot_filename,
                    "link": UKMTO_URL
                })

        except Exception as e:
            print(f"Error scraping UKMTO website: {e}")

        browser.close()
        
    return incidents

def send_telegram_photo(photo_path, caption):
    """Sends photo of the report with Persian translation and spoiler format to Telegram."""
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
    incidents = scrape_ukmto_incidents()

    if not incidents:
        print("No new UKMTO incidents retrieved.")
        return

    for item in reversed(incidents):
        item_id = item["id"]

        if item_id in seen_ids:
            continue

        raw_text = item["text"]
        link = item["link"]
        photo_path = item["photo_path"]

        # Translate to Persian
        persian_text = translate_to_persian(raw_text)

        # Escape HTML special characters
        safe_persian = html.escape(persian_text)
        safe_original = html.escape(raw_text)

        # Construct Rich Text Caption
        caption = (
            f"🚨 <b>گزارش حادثه مرکز تجارت دریایی بریتانیا (UKMTO)</b>\n\n"
            f"{safe_persian}\n\n"
            f"<tg-spoiler>{safe_original}</tg-spoiler>\n\n"
            f"🔗 <a href='{link}'>منبع گزارش رسمی</a>\n\n"
            f"{FOOTER}"
        )

        print(f"Sending alert for ID: {item_id}")
        success = send_telegram_photo(photo_path, caption)

        if success:
            print("Alert posted to Telegram successfully!")
            seen_ids.append(item_id)
        else:
            print("Failed to post alert to Telegram.")

    save_seen_ids(seen_ids)

if __name__ == "__main__":
    main()
