#!/usr/bin/env python3
"""
Telegram Bot for Amharic Speech-to-Text Transcription.
Receives audio messages and transcribes them using AWS Lambda API.
"""

import asyncio
import base64
import logging
import os
import random
from typing import Optional

import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_URL = "https://5pinlu85tk.execute-api.us-east-1.amazonaws.com/api/v1/speech-to-text"
MAX_FILE_SIZE_MB = 10
MAX_AUDIO_DURATION_SECONDS = 60
DEFAULT_LANGUAGE = "am-ET"

# Retry configuration
MAX_RETRIES = 3
BASE_DELAY = 1  # seconds


async def exponential_backoff_retry(
    func,
    *args,
    max_retries: int = MAX_RETRIES,
    base_delay: float = BASE_DELAY,
    **kwargs,
) -> Optional[httpx.Response]:
    """Execute function with exponential backoff retry logic."""
    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except (httpx.RequestError, httpx.TimeoutException) as e:
            if attempt == max_retries - 1:
                raise e
            delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
            logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay:.2f}s...")
            await asyncio.sleep(delay)
    return None


async def transcribe_audio(audio_data: bytes, language: str = DEFAULT_LANGUAGE) -> dict:
    """Send audio to the Speech-to-Text API and return the response."""
    # Encode audio to base64
    audio_base64 = base64.b64encode(audio_data).decode("utf-8")
    
    # Prepare request payload
    payload = {
        "audioData": audio_base64,
        "language": language,
    }
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await exponential_backoff_retry(
            client.post,
            API_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        
        if response is None:
            return {"success": False, "error": "Failed to connect to API after retries"}
        
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 400:
            error_data = response.json()
            return {"success": False, "error": error_data.get("error", "Bad request")}
        elif response.status_code == 500:
            error_data = response.json()
            return {"success": False, "error": error_data.get("error", "Server error")}
        else:
            return {"success": False, "error": f"Unexpected status code: {response.status_code}"}


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""
    welcome_message = (
        "🎤 *Welcome to the Amharic Speech-to-Text Bot!*\n\n"
        "Send me a voice message or audio file, and I'll transcribe it to text.\n\n"
        "📋 *Supported formats:* MP3, OGG, WAV, M4A, WebM, FLAC\n"
        "⏱️ *Recommended:* Audio under 60 seconds\n"
        "📦 *Max size:* 10MB\n\n"
        "Just send your audio and I'll do the rest! 🇪🇹"
    )
    await update.message.reply_text(welcome_message, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /help command."""
    help_message = (
        "📖 *How to use this bot:*\n\n"
        "1. Send a voice message (tap and hold the mic icon)\n"
        "2. Or send an audio file\n"
        "3. Wait for the transcription\n\n"
        "🔧 *Commands:*\n"
        "/start - Start the bot\n"
        "/help - Show this help message\n\n"
        "⚠️ *Tips:*\n"
        "• Speak clearly for better results\n"
        "• Minimize background noise\n"
        "• Keep audio under 60 seconds for best results"
    )
    await update.message.reply_text(help_message, parse_mode="Markdown")


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming audio messages (voice messages and audio files)."""
    message = update.message

    # Determine if it's a voice message or audio file
    if message.voice:
        audio_file = message.voice
        file_type = "voice message"
        duration = message.voice.duration
    elif message.audio:
        audio_file = message.audio
        file_type = "audio file"
        duration = message.audio.duration or 0
    else:
        await message.reply_text("❌ Please send a voice message or audio file.")
        return

    # Check file size (Telegram provides size in bytes)
    file_size_mb = audio_file.file_size / (1024 * 1024) if audio_file.file_size else 0
    if file_size_mb > MAX_FILE_SIZE_MB:
        await message.reply_text(
            f"❌ File too large ({file_size_mb:.1f}MB). Maximum size is {MAX_FILE_SIZE_MB}MB."
        )
        return

    # Warn about long audio
    if duration and duration > MAX_AUDIO_DURATION_SECONDS:
        await message.reply_text(
            f"⚠️ Audio is {duration}s long. For best results, keep it under {MAX_AUDIO_DURATION_SECONDS}s.\n"
            "Processing anyway..."
        )

    # Send processing message
    processing_msg = await message.reply_text("🔄 Processing your audio... Please wait.")

    try:
        # Download the audio file
        file = await context.bot.get_file(audio_file.file_id)
        audio_data = await file.download_as_bytearray()

        logger.info(f"Downloaded {file_type}: {len(audio_data)} bytes")

        # Transcribe the audio
        result = await transcribe_audio(bytes(audio_data))

        # Handle the response
        if result.get("success"):
            transcription = result.get("data", {}).get("transcription", "")
            if transcription:
                await processing_msg.edit_text(
                    f"✅ *Transcription:*\n\n{transcription}",
                    parse_mode="Markdown"
                )
            else:
                await processing_msg.edit_text(
                    "⚠️ Transcription completed but no text was detected. "
                    "Please try speaking more clearly."
                )
        else:
            error_msg = result.get("error", "Unknown error occurred")
            await processing_msg.edit_text(f"❌ Transcription failed: {error_msg}")
            logger.error(f"Transcription error: {error_msg}")

    except httpx.TimeoutException:
        await processing_msg.edit_text(
            "❌ Request timed out. Please try again with a shorter audio."
        )
        logger.error("API request timed out")
    except Exception as e:
        await processing_msg.edit_text(
            "❌ An error occurred while processing your audio. Please try again."
        )
        logger.error(f"Error processing audio: {e}")


async def health_check(request):
    """Health check endpoint for Railway."""
    from aiohttp import web
    return web.Response(text="OK", status=200)


async def run_webhook(application: Application) -> None:
    """Run the bot with webhook for production (Railway)."""
    from aiohttp import web

    port = int(os.getenv("PORT", 8080))
    webhook_url = os.getenv("RAILWAY_PUBLIC_DOMAIN")

    if not webhook_url:
        logger.warning("RAILWAY_PUBLIC_DOMAIN not set, using polling mode")
        await run_polling(application)
        return

    webhook_url = f"https://{webhook_url}/webhook"

    # Create aiohttp app for health checks
    aiohttp_app = web.Application()
    aiohttp_app.router.add_get("/health", health_check)

    # Initialize the application
    await application.initialize()
    await application.start()

    # Set up webhook
    await application.bot.set_webhook(url=webhook_url)
    logger.info(f"Webhook set to: {webhook_url}")

    # Create webhook handler
    async def telegram_webhook(request):
        data = await request.json()
        update = Update.de_json(data, application.bot)
        await application.process_update(update)
        return web.Response(text="OK")

    aiohttp_app.router.add_post("/webhook", telegram_webhook)

    # Run the server
    runner = web.AppRunner(aiohttp_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Server started on port {port}")

    # Keep running
    while True:
        await asyncio.sleep(3600)


async def run_polling(application: Application) -> None:
    """Run the bot with polling for local development."""
    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    logger.info("Bot started in polling mode")

    # Keep running
    while True:
        await asyncio.sleep(3600)


def main() -> None:
    """Main function to start the bot."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN environment variable is not set!")
        return

    # Create application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_audio))

    # Run the bot
    if os.getenv("RAILWAY_PUBLIC_DOMAIN"):
        logger.info("Running in webhook mode (Railway)")
        asyncio.run(run_webhook(application))
    else:
        logger.info("Running in polling mode (local)")
        asyncio.run(run_polling(application))


if __name__ == "__main__":
    main()

