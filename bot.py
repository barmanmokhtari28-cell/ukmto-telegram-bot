import os
import json
import requests
import feedparser
from bs4 import BeautifulSoup

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SEEN_FILE = "seen_ids.json"

# RSS Feed for @UK_MTO via Nitter/RSS bridge
RSS_URL = "https://rss.app/feed/1fX90mOqgPzZ8oO"  # You can replace this with any Twitter-to-RSS URL for @UK_MTO

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
        json.dump(seen_ids[-50:], f, indent=2)  # Keep the last 50 entries

def extract_image_url(entry):
    # Try finding image in enclosures or media content
    if "media_content" in entry and len(entry.media_content) > 0:
        return entry.media_content[0]["url"]
    if "enclosures" in entry and len(entry.enclosures) > 0:
        return entry.enclosures[0]["href"]
    
    # Fallback: parse HTML summary to find img tag
    if "summary" in entry:
        soup = BeautifulSoup(entry.summary, "html.parser")
        img = soup.find("img")
        if img and img.get("src"):
            return img["src"]
            
    return None

def send_telegram_photo(photo_url, caption):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    payload = {
        "chat_id": CHAT_ID,
        "photo": photo_url,
        "caption": caption[:1024],  # Telegram max caption limit
        "parse_mode": "HTML"
    }
    response = requests.post(url, data=payload)
    return response.ok

def main():
    seen_ids = load_seen_ids()
    feed = feedparser.parse(RSS_URL)
    
    if not feed.entries:
        print("No entries found in RSS feed.")
        return

    # Process items from oldest to newest
    for entry in reversed(feed.entries):
        item_id = entry.get("id") or entry.get("link")
        
        if item_id in seen_ids:
            continue
            
        title = entry.get("title", "UKMTO Advisory/Warning")
        image_url = extract_image_url(entry)
        
        print(f"New report found: {title}")
        
        if image_url:
            caption = f"<b>🚨 UKMTO Incident Report</b>\n\n{title}\n\n🔗 <a href='{entry.link}'>View Source</a>"
            success = send_telegram_photo(image_url, caption)
            
            if success:
                print("Posted to Telegram successfully.")
                seen_ids.append(item_id)
            else:
                print("Failed to post photo to Telegram.")
        else:
            print("No photo found in this advisory, skipping photo attachment.")
            seen_ids.append(item_id)

    save_seen_ids(seen_ids)

if __name__ == "__main__":
    main()
