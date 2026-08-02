import os
import json
import html
import requests
from playwright.sync_api import sync_playwright
from deep_translator import GoogleTranslator
import fitz  # PyMuPDF to convert PDF into PNG photo

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
        translated = GoogleTranslator(source='auto', target='fa').translate(text[:400])
        return translated
    except Exception as e:
        print(f"Translation error: {e}")
        return text[:400]

def convert_pdf_to_image(pdf_path, output_image_path):
    """Renders page 1 of a PDF into a high-resolution PNG image."""
    try:
        doc = fitz.open(pdf_path)
        if len(doc) > 0:
            page = doc[0]
            pix = page.get_pixmap(dpi=150)
            pix.save(output_image_path)
            extracted_text = page.get_text()
            return output_image_path, extracted_text
    except Exception as e:
        print(f"Error converting PDF to image: {e}")
    return None, ""

def scrape_and_download_ukmto_pdfs():
    """
    Navigates UKMTO pages, clicks active month tabs, intercepts 
    file downloads from JS buttons, and converts PDFs to PNG images.
    """
    reports = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            accept_downloads=True,  # Crucial for intercepting JS downloads
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1400, "height": 900}
        )
        page = context.new_page()

        for page_url in UKMTO_URLS:
            try:
                print(f"Opening UKMTO page: {page_url}")
                page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(4000)

                # Accept cookies if banner appears
                try:
                    cookie_btn = page.query_selector("button:has-text('Accept'), .cookie-accept")
                    if cookie_btn:
                        cookie_btn.click()
                        page.wait_for_timeout(1000)
                except Exception:
                    pass

                # Click month tabs with active reports (e.g., August, July)
                tabs = page.query_selector_all("li, button, div, span")
                for tab in tabs:
                    try:
                        tab_text = tab.inner_text().strip()
                        if any(m in tab_text for m in ["August", "July", "June", "May"]) and "(" in tab_text and ")" in tab_text:
                            if "(0)" not in tab_text:
                                print(f"Clicking month tab: {tab_text}")
                                tab.click(timeout=2000)
                                page.wait_for_timeout(2000)
                    except Exception:
                        pass

                # Find all clickable elements (buttons, SVGs, download icons)
                clickable_elements = page.query_selector_all("button, svg, i, a, [class*='download']")
                print(f"Scanning {len(clickable_elements)} interactive elements on page...")

                download_count = 0
                for elem in clickable_elements:
                    try:
                        # Intercept browser download triggered by clicking JS download button
                        with page.expect_download(timeout=3000) as download_info:
                            elem.click(timeout=1000)

                        download = download_info.value
                        filename = download.suggested_filename or f"ukmto_report_{download_count}.pdf"
                        temp_pdf_path = f"temp_{download_count}.pdf"
                        download.save_as(temp_pdf_path)

                        print(f"Downloaded PDF file: {filename}")

                        # Render PDF page to PNG photo
                        output_png = f"photo_{download_count}.png"
                        photo_path, extracted_text = convert_pdf_to_image(temp_pdf_path, output_png)

                        if photo_path and len(extracted_text) > 10:
                            reports.append({
                                "id": filename,
                                "text": extracted_text,
                                "photo_path": photo_path,
                                "link": page_url
                            })
                            download_count += 1

                    except Exception:
                        # Element was not a download trigger, proceed to next
                        continue

            except Exception as e:
                print(f"Error scraping {page_url}: {e}")

        browser.close()

    return reports

def send_telegram_photo(photo_path, caption):
    """Posts rendered PDF photo with Persian translation and spoiler text to Telegram."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    data = {
        "chat_id": CHAT_ID,
        "caption": caption[:1024],  # Telegram 1024 max caption limit
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
    reports = scrape_and_download_ukmto_pdfs()

    if not reports:
        print("No new PDF reports downloaded.")
        return

    print(f"Successfully processed {len(reports)} UKMTO PDF reports!")

    for item in reports:
        item_id = item["id"]

        if item_id in seen_ids:
            print(f"Skipping already posted PDF: {item_id}")
            continue

        raw_text = item["text"]
        link = item["link"]
        photo_path = item["photo_path"]

        # Clean whitespace
        clean_text = " ".join(raw_text.split())

        # Translate summary to Persian
        persian_translation = translate_to_persian(clean_text)

        # Escape HTML special characters
        safe_persian = html.escape(persian_translation[:350])
        safe_original = html.escape(clean_text[:350])

        # Format Caption
        caption = (
            f"🚨 <b>گزارش حادثه مرکز تجارت دریایی بریتانیا (UKMTO)</b>\n\n"
            f"{safe_persian}\n\n"
            f"<tg-spoiler>{safe_original}</tg-spoiler>\n\n"
            f"🔗 <a href='{link}'>منبع گزارش رسمی</a>\n\n"
            f"{FOOTER}"
        )

        print(f"Posting PDF photo to Telegram channel for {item_id}...")
        success = send_telegram_photo(photo_path, caption)

        if success:
            print("Successfully posted report photo to Telegram!")
            seen_ids.append(item_id)
        else:
            print("Failed to post photo to Telegram.")

    save_seen_ids(seen_ids)

if __name__ == "__main__":
    main()
