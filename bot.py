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

def render_pdf_bytes_to_png(pdf_bytes, output_png_path):
    """
    Renders Page 1 of PDF bytes at 200 DPI resolution.
    Produces the official poster with satellite map, markers, and header.
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if len(doc) > 0:
            page = doc[0]
            zoom = 200 / 72  # 200 DPI for high definition
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            pix.save(output_png_path)
            extracted_text = page.get_text()
            return output_png_path, extracted_text
    except Exception as e:
        print(f"Error rendering PDF bytes to image: {e}")
    return None, ""

def scrape_ukmto_posters():
    """
    Scrapes UKMTO pages, extracts direct PDF URLs, downloads PDFs,
    and converts them into full map posters.
    """
    reports = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1400, "height": 1000}
        )
        page = context.new_page()

        for page_url in UKMTO_URLS:
            try:
                print(f"Connecting to UKMTO: {page_url}")
                page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(4000)

                # Accept cookies
                try:
                    cookie_btn = page.query_selector("button:has-text('Accept'), .cookie-accept")
                    if cookie_btn:
                        cookie_btn.click()
                        page.wait_for_timeout(1000)
                except Exception:
                    pass

                # Select active month tab if present
                tabs = page.query_selector_all("li, button, div, span")
                for tab in tabs:
                    try:
                        tab_text = tab.inner_text().strip()
                        if any(m in tab_text for m in ["August", "July", "June"]) and "(" in tab_text and ")" in tab_text:
                            if "(0)" not in tab_text:
                                tab.click(timeout=1500)
                                page.wait_for_timeout(1500)
                    except Exception:
                        pass

                # Extract all direct PDF links / attributes from the page DOM
                pdf_urls = page.evaluate("""
                    () => {
                        const urls = [];
                        document.querySelectorAll('a, button, [data-url], [data-href], [onclick]').forEach(el => {
                            const link = el.href || el.getAttribute('data-url') || el.getAttribute('data-href') || el.getAttribute('onclick') || '';
                            if (link && (link.includes('.pdf') || link.includes('media') || link.includes('download') || link.includes('Warning') || link.includes('Advisory'))) {
                                urls.push(link);
                            }
                        });
                        return urls;
                    }
                """)

                print(f"Found {len(pdf_urls)} potential PDF links in DOM on {page_url}")

                # Download PDF files and render posters
                for idx, pdf_url in enumerate(pdf_urls[:10]):
                    try:
                        if not pdf_url.startswith("http"):
                            if pdf_url.startswith("/"):
                                pdf_url = "https://www.ukmto.org" + pdf_url
                            else:
                                continue

                        print(f"Downloading PDF file directly: {pdf_url}")
                        res = requests.get(pdf_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)

                        if res.status_code == 200 and len(res.content) > 1000 and b"%PDF" in res.content[:10]:
                            img_path = f"poster_pdf_{len(reports)}.png"
                            photo_file, text = render_pdf_bytes_to_png(res.content, img_path)

                            if photo_file and len(text) > 10:
                                reports.append({
                                    "id": pdf_url,
                                    "text": text,
                                    "photo_path": photo_file,
                                    "link": page_url
                                })
                    except Exception as err:
                        print(f"Error fetching PDF {pdf_url}: {err}")

                # Fallback: Click preview/eye icon to capture poster preview modal if direct link fails
                if len(reports) == 0:
                    eye_icons = page.query_selector_all("i, svg, button, .fa-eye, [class*='eye'], div.card")
                    print(f"Testing {len(eye_icons)} preview icons...")
                    for idx, icon in enumerate(eye_icons[:5]):
                        try:
                            icon.click(timeout=1500)
                            page.wait_for_timeout(2000)

                            modal = page.query_selector(".modal, .popup, .pdf-viewer, div[role='dialog'], iframe")
                            img_path = f"poster_preview_{len(reports)}.png"

                            if modal:
                                modal.screenshot(path=img_path)
                            else:
                                page.screenshot(path=img_path, full_page=False)

                            text = page.evaluate("() => document.body.innerText")

                            reports.append({
                                "id": f"preview_{idx}_{hash(text[:50])}",
                                "text": text[:500],
                                "photo_path": img_path,
                                "link": page_url
                            })
                            break
                        except Exception:
                            continue

            except Exception as e:
                print(f"Error processing page {page_url}: {e}")

        browser.close()

    return reports

def send_telegram_photo(photo_path, caption):
    """Sends official poster photo to Telegram."""
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
    reports = scrape_ukmto_posters()

    if not reports:
        print("No UKMTO poster reports generated.")
        return

    print(f"Successfully generated {len(reports)} UKMTO map posters!")

    for item in reversed(reports):
        item_id = item["id"]

        if item_id in seen_ids:
            print(f"Skipping already posted: {item_id}")
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
            f"🔗 <a href='{link}'>منبع گزارش رسمی</a>\n\n"
            f"{FOOTER}"
        )

        print(f"Posting official Map Poster photo to Telegram: {item_id}")
        success = send_telegram_photo(photo_path, caption)

        if success:
            print("Successfully posted official UKMTO Map Poster to Telegram!")
            seen_ids.append(item_id)
        else:
            print("Failed to post photo to Telegram.")

    save_seen_ids(seen_ids)

if __name__ == "__main__":
    main()
