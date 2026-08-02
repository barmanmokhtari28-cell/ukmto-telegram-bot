import os
import json
import html
import requests
from playwright.sync_api import sync_playwright
from deep_translator import GoogleTranslator
import fitz  # PyMuPDF to convert PDF to the official map poster image

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SEEN_FILE = "seen_ids.json"

UKMTO_URLS = [
    "https://www.ukmto.org/ukmto-products/warnings",
    "https://www.ukmto.org/ukmto-products/advisories",
    "https://www.ukmto.org/recent-incidents"
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
    """Translates summary to Persian."""
    try:
        translated = GoogleTranslator(source='auto', target='fa').translate(text[:450])
        return translated
    except Exception as e:
        print(f"Translation error: {e}")
        return text[:450]

def render_pdf_poster(pdf_bytes, output_image_path):
    """
    Renders Page 1 of the official UKMTO PDF at 200 DPI resolution.
    Produces the exact official poster with satellite map, markers, and header.
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if len(doc) > 0:
            page = doc[0]
            
            # Render at high-definition 200 DPI
            zoom = 200 / 72
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            pix.save(output_image_path)
            
            extracted_text = page.get_text()
            return output_image_path, extracted_text
    except Exception as e:
        print(f"Error rendering PDF poster: {e}")
    return None, ""

def scrape_and_render_ukmto_posters():
    """
    Finds UKMTO PDF downloads, converts them into full map posters,
    and returns report items ready for Telegram.
    """
    reports = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            accept_downloads=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1400, "height": 900}
        )
        page = context.new_page()

        for page_url in UKMTO_URLS:
            try:
                print(f"Connecting to UKMTO: {page_url}")
                page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(4000)

                # Accept cookie prompt if present
                try:
                    cookie_btn = page.query_selector("button:has-text('Accept'), .cookie-accept")
                    if cookie_btn:
                        cookie_btn.click()
                        page.wait_for_timeout(1000)
                except Exception:
                    pass

                # Select active month tabs (August, July, etc.)
                tabs = page.query_selector_all("li, button, div, span")
                for tab in tabs:
                    try:
                        tab_text = tab.inner_text().strip()
                        if any(m in tab_text for m in ["August", "July", "June", "May"]) and "(" in tab_text and ")" in tab_text:
                            if "(0)" not in tab_text:
                                tab.click(timeout=1500)
                                page.wait_for_timeout(1500)
                    except Exception:
                        pass

                # Intercept download buttons (the download arrow icons)
                download_btns = page.query_selector_all("button, svg, i, a, [class*='download']")
                print(f"Found {len(download_btns)} download triggers on {page_url}")

                download_count = 0
                for btn in download_btns:
                    try:
                        with page.expect_download(timeout=2500) as download_info:
                            btn.click(timeout=1000)

                        download = download_info.value
                        filename = download.suggested_filename or f"ukmto_report_{download_count}.pdf"
                        
                        # Read PDF stream into memory
                        pdf_path = download.path()
                        with open(pdf_path, "rb") as f:
                            pdf_bytes = f.read()

                        poster_png = f"poster_{len(reports)}.png"
                        
                        # Render the PDF into the official Map Poster Image
                        photo_file, extracted_text = render_pdf_poster(pdf_bytes, poster_png)

                        if photo_file and len(extracted_text) > 15:
                            reports.append({
                                "id": filename,
                                "text": extracted_text.strip(),
                                "photo_path": photo_file,
                                "link": page_url
                            })
                            download_count += 1

                    except Exception:
                        continue

            except Exception as e:
                print(f"Error reading {page_url}: {e}")

        browser.close()

    return reports

def send_telegram_photo(photo_path, caption):
    """Sends the official map poster photo to Telegram."""
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
    reports = scrape_and_render_ukmto_posters()

    if not reports:
        print("No new PDF posters rendered.")
        return

    print(f"Successfully created {len(reports)} official UKMTO Map Posters!")

    # Post from oldest to newest
    for item in reversed(reports):
        item_id = item["id"]

        if item_id in seen_ids:
            print(f"Skipping already posted poster: {item_id}")
            continue

        raw_text = item["text"]
        link = item["link"]
        photo_path = item["photo_path"]

        # Clean text
        clean_text = " ".join(raw_text.split())

        # Translate summary to Persian
        persian_translation = translate_to_persian(clean_text)

        # HTML Escape
        safe_persian = html.escape(persian_translation[:350])
        safe_original = html.escape(clean_text[:350])

        # Caption
        caption = (
            f"🚨 <b>گزارش حادثه مرکز تجارت دریایی بریتانیا (UKMTO)</b>\n\n"
            f"{safe_persian}\n\n"
            f"<tg-spoiler>{safe_original}</tg-spoiler>\n\n"
            f"🔗 <a href='{link}'>منبع گزارش رسمی</a>\n\n"
            f"{FOOTER}"
        )

        print(f"Posting official Map Poster photo to Telegram for {item_id}...")
        success = send_telegram_photo(photo_path, caption)

        if success:
            print("Posted official UKMTO Map Poster to Telegram successfully!")
            seen_ids.append(item_id)
        else:
            print("Failed to post photo to Telegram.")

    save_seen_ids(seen_ids)

if __name__ == "__main__":
    main()
