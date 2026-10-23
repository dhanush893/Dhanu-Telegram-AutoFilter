import json, os, re, urllib.request
from pathlib import Path

def publish_movie_metadata(name, size_mb, source_message_id, parsed):
    """Publish metadata only; the media file itself is not uploaded to the website."""
    endpoint = os.getenv("WEBSITE_WEBHOOK_URL", "").strip()
    secret = os.getenv("WEBSITE_WEBHOOK_SECRET", "").strip()
    if not endpoint or not secret:
        return
    title = parsed.get("title") or Path(name).stem
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:160] or f"movie-{source_message_id}"
    payload = {"slug": slug, "title": title, "year": parsed.get("year", ""), "language": parsed.get("language") or "Unknown", "quality": parsed.get("quality") or "Not specified", "file_name": name, "file_size_mb": round(float(size_mb), 2), "source_message_id": str(source_message_id)}
    req = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json", "X-Webhook-Secret": secret}, method="POST")
    with urllib.request.urlopen(req, timeout=8) as response:
        if response.status >= 300: raise RuntimeError(f"Website API returned HTTP {response.status}")
    print(f"Published movie metadata to SD MOVIE ADDA: {slug}")
