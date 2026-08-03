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
    "https://www.ukmto.org/ukmto-products/advisories"
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

def render_pdf_bytes_to_png(pdf_bytes, output_png_path):
    """
    Renders Page 1 of the PDF bytes into a 200 DPI high-definition map poster image.
    Contains the official header, report text, and satellite map with location pin.
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if len(doc) > 0:
            page = doc[0]
            zoom = 200 / 72  # 200 DPI high definition
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            pix.save(output_png_path)
            extracted_text = page.get_text()
            return output_png_path, extracted_text
    except Exception as e:
        print(f"Error rendering PDF bytes: {e}")
    return None, ""

def scrape_ukmto_pdf_urls():
    """
    Clicks 2026 -> Clicks August -> Scrapes all direct /-/media/...pdf href links.
    """
    pdf_urls = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1400, "height": 1000}
        )
        page = context.new_page()

        for page_url in UKMTO_URLS:
            try:
                print(f"Navigating to UKMTO page: {page_url}")
                page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)

                # Accept cookies
                try:
                    cookie_btn = page.query_selector("button:has-text('Accept'), .cookie-accept")
                    if cookie_btn:
                        cookie_btn.click()
                        page.wait_for_timeout(1000)
                except Exception:
                    pass

                # Step 1: Click "2026" product card
                print("Clicking '2026' year product card...")
                year_cards = page.query_selector_all("div, button, a, h3, h2, p")
                for yc in year_cards:
                    try:
                        txt = yc.inner_text().strip()
                        if "2026" in txt and ("Report" in txt or "10" in txt or txt == "2026"):
                            yc.click(timeout=2000)
                            page.wait_for_timeout(2500)
                            break
                    except Exception:
                        pass

                # Step 2: Click "August" month tab
                print("Clicking 'August' month tab...")
                month_tabs = page.query_selector_all("li, button, div, span, a")
                for mt in month_tabs:
                    try:
                        txt = mt.inner_text().strip()
                        if "August" in txt and "(" in txt and ")" in txt:
                            mt.click(timeout=2000)
                            page.wait_for_timeout(2000)
                            break
                    except Exception:
                        pass

                # Step 3: Extract all direct <a> href attributes containing /-/media/ or .pdf
                anchors = page.query_selector_all("a")
                found_on_page = 0
                for a in anchors:
                    try:
                        href = a.get_attribute("href")
                        if href and ("/-/media/" in href or ".pdf" in href.lower()):
                            if href.startswith("/"):
                                href = "https://www.ukmto.org" + href
                            pdf_urls.add(href)
                            found_on_page += 1
                    except Exception:
                        pass

                print(f"Extracted {found_on_page} direct PDF URLs from {page_url}!")

            except Exception as e:
                print(f"Error navigating {page_url}: {e}")

        browser.close()

    return list(pdf_urls)

def download_and_render_reports(pdf_urls):
    """Downloads PDF files directly and renders Page 1 into map poster PNG photos."""
    reports = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    for idx, pdf_url in enumerate(pdf_urls):
        try:
            print(f"Downloading PDF report: {pdf_url}")
            res = requests.get(pdf_url, headers=headers, timeout=25)

            if res.status_code == 200 and len(res.content) > 1000 and b"%PDF" in res.content[:10]:
                png_path = f"poster_{idx}.png"
                photo_file, extracted_text = render_pdf_bytes_to_png(res.content, png_path)

                if photo_file and len(extracted_text) > 15:
                    reports.append({
                        "id": pdf_url,
                        "text": extracted_text.strip(),
                        "photo_path": photo_file,
                        "link": pdf_url
                    })
                    print(f"Successfully rendered map poster for: {pdf_url}")
        except Exception as e:
            print(f"Error downloading PDF {pdf_url}: {e}")

    return reports

def send_telegram_photo(photo_path, caption):
    """Sends official map poster photo to Telegram."""
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
    pdf_urls = scrape_ukmto_pdf_urls()

    if not pdf_urls:
        print("No direct PDF URLs extracted.")
        return

    print(f"Collected {len(pdf_urls)} direct UKMTO PDF links!")
    reports = download_and_render_reports(pdf_urls)

    for item in reversed(reports):
        item_id = item["id"]

        if item_id in seen_ids:
            print(f"Skipping already posted PDF: {item_id}")
            continue

        raw_text = item["text"]
        link = item["link"]
        photo_path = item["photo_path"]

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
            f"🔗 <a href='{link}'>دانلود PDF گزارش رسمی</a>\n\n"
            f"{FOOTER}"
        )

        print(f"Posting official Map Poster photo to Telegram for {item_id}...")
        success = send_telegram_photo(photo_path, caption)

        if success:
            print("Successfully posted official UKMTO Map Poster to Telegram!")
            seen_ids.append(item_id)
        else:
            print("Failed to post photo to Telegram.")

    save_seen_ids(seen_ids)

if __name__ == "__main__":
    main()
