# Dhanu Telegram AutoFilter

Telegram file receiver with optional SD MOVIE ADDA metadata publishing.

## Optional website integration
Set WEBSITE_WEBHOOK_URL to the SD MOVIE ADDA endpoint, for example https://YOUR-VERCEL-DOMAIN/api/movies, and WEBSITE_WEBHOOK_SECRET to the same random secret configured in Vercel. After a media upload succeeds, the bot publishes parsed metadata only. It does not upload the media file to the website. If the variables are empty, the website publisher is skipped and the existing receiver workflow continues.

Keep API credentials, session strings, and webhook secrets private. Only process and publish content you are authorized to distribute.
