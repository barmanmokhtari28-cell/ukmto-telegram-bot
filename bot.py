import os
import json
import html
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from deep_translator import GoogleTranslator
import fitz  # PyMuPDF for rendering PDFs to images

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SEEN_FILE = "seen_ids.json"

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
    """Translates text into Persian."""
    try:
        translated = GoogleTranslator(source='auto', target='fa').translate(text[:400])
        return translated
    except Exception as e:
        print(f"Translation error: {e}")
        return text[:400]

def convert_pdf_to_image(pdf_bytes, output_image_path):
    """
    Renders Page 1 of a PDF into a crisp PNG image screenshot.
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if len(doc) > 0:
            page = doc[0]
            # Render page to high resolution image (DPI 150)
            pix = page.get_pixmap(dpi=150)
            pix.save(output_image_path)
            extracted_text = page.get_text()
            return output_image_path, extracted_text
    except Exception as e:
        print(f"Error converting PDF to image: {e}")
    return None, ""

def find_pdf_reports():
    """Scrapes UKMTO pages for all PDF advisory links."""
    pdf_links = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900}
        )
        page = context.new_page()

        for target_url in URLS_TO_SCRAPE:
            try:
                print(f"Scanning UKMTO page: {target_url}...")
                page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(4000)

                # Extract all PDF links on page
                anchors = page.query_selector_all("a")
                for a in anchors:
                    href = a.get_attribute("href")
                    if href:
                        if href.startswith("/"):
                            href = "https://www.ukmto.org" + href
                        
                        # Filter for PDF files
                        if ".pdf" in href.lower() or "download" in href.lower():
                            pdf_links.add(href)

            except Exception as e:
                print(f"Error searching {target_url}: {e}")

        browser.close()

    print(f"Found {len(pdf_links)} total PDF documents on UKMTO.")
    return list(pdf_links)

def download_and_process_pdfs(pdf_urls):
    """Downloads PDFs, renders screenshot images, and extracts text."""
    processed_reports = []

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    for idx, pdf_url in enumerate(pdf_urls[:10]):
        try:
            print(f"Downloading PDF: {pdf_url}")
            res = requests.get(pdf_url, headers=headers, timeout=25)

            if res.status_code == 200 and len(res.content) > 1000:
                img_filename = f"pdf_screenshot_{idx}.png"
                img_path, extracted_text = convert_pdf_to_image(res.content, img_filename)

                if img_path and extracted_text:
                    processed_reports.append({
                        "id": pdf_url,
                        "text": extracted_text.strip(),
                        "photo_path": img_path,
                        "link": pdf_url
                    })
        except Exception as e:
            print(f"Error processing PDF {pdf_url}: {e}")

    return processed_reports

def send_telegram_photo(photo_path, caption):
    """Uploads the rendered PDF photo screenshot to Telegram."""
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
    pdf_urls = find_pdf_reports()

    if not pdf_urls:
        print("No PDF links found on page.")
        return

    reports = download_and_process_pdfs(pdf_urls)

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

        # HTML Escape
        safe_persian = html.escape(persian_translation[:350])
        safe_original = html.escape(clean_text[:350])

        caption = (
            f"🚨 <b>گزارش حادثه مرکز تجارت دریایی بریتانیا (UKMTO)</b>\n\n"
            f"{safe_persian}\n\n"
            f"<tg-spoiler>{safe_original}</tg-spoiler>\n\n"
            f"🔗 <a href='{link}'>دانلود PDF رسمی گزارش</a>\n\n"
            f"{FOOTER}"
        )

        print(f"Posting PDF screenshot photo to Telegram channel...")
        success = send_telegram_photo(photo_path, caption)

        if success:
            print("Posted PDF screenshot to Telegram successfully!")
            seen_ids.append(item_id)
        else:
            print("Failed to post PDF screenshot to Telegram.")

    save_seen_ids(seen_ids)

if __name__ == "__main__":
    main()
