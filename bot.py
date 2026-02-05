#!/usr/bin/env python3
"""
Telegram Bot for Amharic Speech-to-Text Transcription.
Receives audio messages and transcribes them using AWS Lambda API.
"""

import base64
import logging
import os
import random
import asyncio
from typing import Optional

import httpx
from dotenv import load_dotenv
from urllib.parse import quote_plus

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
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

# Retry configuration
MAX_RETRIES = 3
BASE_DELAY = 1  # seconds

# Language configurations
LANGUAGES = {
    "am": {
        "code": "am-ET",
        "flag": "🇪🇹",
        "name_en": "Amharic",
        "name_native": "አማርኛ",
    },
    "en": {
        "code": "en-US",
        "flag": "🇺🇸",
        "name_en": "English",
        "name_native": "English",
    },
}

# UI Strings for both languages
STRINGS = {
    "am": {
        "welcome": (
            "🎤 *ወደ ፊደል ስክራይብ ቦት እንኳን በደህና መጡ!*\n\n"
            "የድምጽ መልእክት ወይም የድምጽ ፋይል ይላኩልኝ፣ ወደ ጽሑፍ እቀይረዋለሁ።\n\n"
            "📋 *የሚደገፉ ቅርጸቶች:* MP3, OGG, WAV, M4A, WebM, FLAC\n"
            "⏱️ *የሚመከር:* ከ60 ሰከንድ በታች ድምጽ\n"
            "📦 *ከፍተኛ መጠን:* 10MB\n\n"
            "ድምጽዎን ይላኩ እና እኔ የተቀረውን አደርጋለሁ!"
        ),
        "help": (
            "📖 *ይህን ቦት እንዴት መጠቀም እንደሚቻል:*\n\n"
            "1. የድምጽ መልእክት ይላኩ\n"
            "2. ወይም የድምጽ ፋይል ይላኩ\n"
            "3. ግልባጩን ይጠብቁ\n\n"
            "🗣️ /language - ቋንቋ ይቀይሩ\n\n"
            "⚠️ *ምክሮች:*\n"
            "• ለተሻለ ውጤት በግልጽ ይናገሩ\n"
            "• የጀርባ ድምጽን ይቀንሱ\n"
            "• ድምጽ ከ60 ሰከንድ በታች ያድርጉ"
        ),
        "choose_language": "🌍 ቋንቋ ይምረጡ / Choose language:",
        "language_set": "✅ ቋንቋ ወደ አማርኛ ተቀይሯል",
        "processing": "🔄 ድምጽዎን በማስኬድ ላይ... እባክዎ ይጠብቁ።",
        "transcription_success": "✅ *ግልባጭ:*\n\n",
        "no_text_detected": "⚠️ ግልባጭ ተጠናቋል ግን ምንም ጽሑፍ አልተገኘም። እባክዎ በግልጽ ለመናገር ይሞክሩ።",
        "error_failed": "❌ ግልባጭ አልተሳካም: ",
        "error_timeout": "❌ ጊዜው አልፏል። እባክዎ በአጭር ድምጽ እንደገና ይሞክሩ።",
        "error_generic": "❌ ድምጽዎን በማስኬድ ላይ ስህተት ተፈጥሯል። እባክዎ እንደገና ይሞክሩ።",
        "error_no_audio": "❌ እባክዎ የድምጽ መልእክት ወይም የድምጽ ፋይል ይላኩ።",
        "error_file_too_large": "❌ ፋይሉ በጣም ትልቅ ነው ({size}MB)። ከፍተኛው መጠን {max}MB ነው።",
        "warning_long_audio": "⚠️ ድምጽ {duration} ሰከንድ ነው። ለተሻለ ውጤት ከ{max} ሰከንድ በታች ያድርጉ።\nቢሆንም በማስኬድ ላይ...",
    },
    "en": {
        "welcome": (
            "🎤 *Welcome to Fidel Scribe Bot!*\n\n"
            "Send me a voice message or audio file, and I'll transcribe it to text.\n\n"
            "📋 *Supported formats:* MP3, OGG, WAV, M4A, WebM, FLAC\n"
            "⏱️ *Recommended:* Audio under 60 seconds\n"
            "📦 *Max size:* 10MB\n\n"
            "Just send your audio and I'll do the rest!"
        ),
        "help": (
            "📖 *How to use this bot:*\n\n"
            "1. Send a voice message\n"
            "2. Or send an audio file\n"
            "3. Wait for the transcription\n\n"
            "🗣️ /language - Change language\n\n"
            "⚠️ *Tips:*\n"
            "• Speak clearly for better results\n"
            "• Minimize background noise\n"
            "• Keep audio under 60 seconds"
        ),
        "choose_language": "🌍 ቋንቋ ይምረጡ / Choose language:",
        "language_set": "✅ Language set to English",
        "processing": "🔄 Processing your audio... Please wait.",
        "transcription_success": "✅ *Transcription:*\n\n",
        "no_text_detected": "⚠️ Transcription completed but no text was detected. Please try speaking more clearly.",
        "error_failed": "❌ Transcription failed: ",
        "error_timeout": "❌ Request timed out. Please try again with shorter audio.",
        "error_generic": "❌ An error occurred while processing your audio. Please try again.",
        "error_no_audio": "❌ Please send a voice message or audio file.",
        "error_file_too_large": "❌ File too large ({size}MB). Maximum size is {max}MB.",
        "warning_long_audio": "⚠️ Audio is {duration}s long. For best results, keep it under {max}s.\nProcessing anyway...",
    },
}

DEFAULT_LANGUAGE = "am"


def get_user_language(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Get user's preferred language from context."""
    return context.user_data.get("language", DEFAULT_LANGUAGE)


def get_string(key: str, context: ContextTypes.DEFAULT_TYPE, **kwargs) -> str:
    """Get localized string for user's language."""
    lang = get_user_language(context)
    text = STRINGS.get(lang, STRINGS[DEFAULT_LANGUAGE]).get(key, STRINGS[DEFAULT_LANGUAGE][key])
    if kwargs:
        text = text.format(**kwargs)
    return text


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


async def transcribe_audio(audio_data: bytes, language_code: str = "am-ET") -> dict:
    """Send audio to the Speech-to-Text API and return the response."""
    # Encode audio to base64
    audio_base64 = base64.b64encode(audio_data).decode("utf-8")

    # Prepare request payload
    payload = {
        "audioData": audio_base64,
        "language": language_code,
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
    # Show language selection on first start
    keyboard = [
        [
            InlineKeyboardButton(
                f"{LANGUAGES['am']['flag']} {LANGUAGES['am']['name_native']}",
                callback_data="lang_am"
            ),
            InlineKeyboardButton(
                f"{LANGUAGES['en']['flag']} {LANGUAGES['en']['name_native']}",
                callback_data="lang_en"
            ),
        ]
    ]
    await update.message.reply_text(
        get_string("choose_language", context),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /help command."""
    await update.message.reply_text(
        get_string("help", context),
        parse_mode="Markdown"
    )


async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /language command."""
    keyboard = [
        [
            InlineKeyboardButton(
                f"{LANGUAGES['am']['flag']} {LANGUAGES['am']['name_native']}",
                callback_data="lang_am"
            ),
            InlineKeyboardButton(
                f"{LANGUAGES['en']['flag']} {LANGUAGES['en']['name_native']}",
                callback_data="lang_en"
            ),
        ]
    ]
    await update.message.reply_text(
        get_string("choose_language", context),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle language selection callback."""
    query = update.callback_query
    await query.answer()

    # Extract language from callback data (lang_am or lang_en)
    lang = query.data.replace("lang_", "")
    context.user_data["language"] = lang

    # Send confirmation and welcome message
    await query.edit_message_text(get_string("language_set", context))
    await query.message.reply_text(
        get_string("welcome", context),
        parse_mode="Markdown"
    )


def create_transcription_keyboard(transcription: str, context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    """Create inline keyboard with YouTube, Google, and text buttons."""
    # URL-encode the transcription for searches
    query_text = quote_plus(transcription[:100])  # Limit query length
    youtube_url = f"https://www.youtube.com/results?search_query={query_text}"
    google_url = f"https://www.google.com/search?q={query_text}"

    # Clean, minimal buttons with recognizable icons
    keyboard = [
        [
            InlineKeyboardButton("📝", callback_data="text"),  # Get plain text
            InlineKeyboardButton("🔍", url=google_url),        # Google search
            InlineKeyboardButton("🎬", url=youtube_url),       # YouTube search
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def handle_text_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the text button callback - send transcription as plain text."""
    query = update.callback_query
    await query.answer()

    # Extract transcription from the original message
    original_text = query.message.text
    # Remove the header prefix (works for both languages)
    if "\n\n" in original_text:
        transcription = original_text.split("\n\n", 1)[1].strip()
    else:
        transcription = original_text

    # Send as plain text - easy to copy or forward
    await query.message.reply_text(transcription)


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
        await message.reply_text(get_string("error_no_audio", context))
        return

    # Check file size (Telegram provides size in bytes)
    file_size_mb = audio_file.file_size / (1024 * 1024) if audio_file.file_size else 0
    if file_size_mb > MAX_FILE_SIZE_MB:
        await message.reply_text(
            get_string("error_file_too_large", context, size=f"{file_size_mb:.1f}", max=MAX_FILE_SIZE_MB)
        )
        return

    # Warn about long audio
    if duration and duration > MAX_AUDIO_DURATION_SECONDS:
        await message.reply_text(
            get_string("warning_long_audio", context, duration=duration, max=MAX_AUDIO_DURATION_SECONDS)
        )

    # Send processing message
    processing_msg = await message.reply_text(get_string("processing", context))

    try:
        # Download the audio file
        file = await context.bot.get_file(audio_file.file_id)
        audio_data = await file.download_as_bytearray()

        logger.info(f"Downloaded {file_type}: {len(audio_data)} bytes")

        # Get user's language code for transcription
        user_lang = get_user_language(context)
        language_code = LANGUAGES.get(user_lang, LANGUAGES[DEFAULT_LANGUAGE])["code"]

        # Transcribe the audio
        result = await transcribe_audio(bytes(audio_data), language_code)

        # Handle the response
        if result.get("success"):
            transcription = result.get("data", {}).get("transcription", "")
            if transcription:
                # Create inline keyboard with action buttons
                keyboard = create_transcription_keyboard(transcription, context)
                await processing_msg.edit_text(
                    f"{get_string('transcription_success', context)}{transcription}",
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )
            else:
                await processing_msg.edit_text(get_string("no_text_detected", context))
        else:
            error_msg = result.get("error", "Unknown error occurred")
            await processing_msg.edit_text(f"{get_string('error_failed', context)}{error_msg}")
            logger.error(f"Transcription error: {error_msg}")

    except httpx.TimeoutException:
        await processing_msg.edit_text(get_string("error_timeout", context))
        logger.error("API request timed out")
    except Exception as e:
        await processing_msg.edit_text(get_string("error_generic", context))
        logger.error(f"Error processing audio: {e}")


async def post_init(application: Application) -> None:
    """Delete any existing webhook to ensure clean polling mode."""
    await application.bot.delete_webhook(drop_pending_updates=True)
    logger.info("Webhook deleted, ready for polling")


def main() -> None:
    """Main function to start the bot."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN environment variable is not set!")
        return

    # Create application with post_init to clear webhooks
    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("language", language_command))
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_audio))
    application.add_handler(CallbackQueryHandler(handle_language_callback, pattern="^lang_"))
    application.add_handler(CallbackQueryHandler(handle_text_callback, pattern="^text$"))

    # Run the bot in polling mode
    logger.info("Starting bot in polling mode...")
    application.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

