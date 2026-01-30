import os
import json
import logging
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any

# Third-party imports
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters
)
from groq import Groq
from keep_alive import keep_alive

# --- CONFIGURATION & SETUP ---

# Load environment variables from .env file
load_dotenv()

# Constants
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
BASE_DIR = Path(__file__).resolve().parent
RESOURCES_PATH = BASE_DIR / "resources" / "texts.json"

# Validate keys
if not TELEGRAM_TOKEN or not GROQ_API_KEY:
    raise ValueError("Missing API keys in .env file.")

# Logging Configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize Groq Client
client = Groq(api_key=GROQ_API_KEY)

# --- UTILITY FUNCTIONS ---

def load_texts() -> Dict[str, Any]:
    """Loads the JSON file containing all static texts and prompts."""
    try:
        with open(RESOURCES_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"Resource file not found at {RESOURCES_PATH}")
        raise
    except json.JSONDecodeError:
        logger.error("Error decoding the JSON resource file.")
        raise

# Load texts once at startup
TEXTS = load_texts()

# --- CORE LOGIC ---

async def generate_jungian_response(user_text: str, update: Update) -> None:
    """
    Core function that handles the interaction with the LLM (Groq/Llama).
    Includes a fallback mechanism: if Markdown parsing fails, sends plain text.
    """
    try:
        # Prepare the prompt using the template from JSON
        wrapped_input = TEXTS["prompts"]["user_input_wrapper"].format(user_input=user_text)

        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": TEXTS["prompts"]["system_prompt"]
                },
                {
                    "role": "user",
                    "content": wrapped_input
                }
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.7,
        )

        analysis = chat_completion.choices[0].message.content
        
        # Append safety footer
        full_response = f"{analysis}{TEXTS['messages']['footer_disclaimer']}"
        
        # --- SAFE SENDING BLOCK ---
        try:
            await update.message.reply_text(full_response, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Markdown parsing failed, falling back to plain text. Error: {e}")
            await update.message.reply_text(full_response, parse_mode=None)

    except Exception as e:
        logger.error(f"LLM Generation Error: {e}")
        await update.message.reply_text(TEXTS["errors"]["generic_error"])

# --- TELEGRAM HANDLERS ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /start command and sends the welcome guide."""
    await update.message.reply_text(TEXTS["messages"]["welcome"], parse_mode="Markdown")

async def privacy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /privacy command."""
    await update.message.reply_text(TEXTS["messages"]["privacy"], parse_mode="Markdown")

async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Processes voice notes:
    1. Downloads the OGG file.
    2. Transcribes it using Groq (Whisper).
    3. Sends the transcription to the LLM for analysis.
    """
    await update.message.reply_text(TEXTS["messages"]["processing_audio"])
    
    # Create a temporary file path
    temp_ogg_path = BASE_DIR / "temp_voice.ogg"
    
    try:
        # Download file from Telegram
        voice_file = await context.bot.get_file(update.message.voice.file_id)
        await voice_file.download_to_drive(custom_path=temp_ogg_path)

        # Transcribe using Groq Whisper
# Transcribe using Groq Whisper
        with open(temp_ogg_path, "rb") as file:
            transcription = client.audio.transcriptions.create(
                file=(str(temp_ogg_path), file.read()), 
                model="whisper-large-v3",
                language="it", 
                response_format="json"
            )
        
        transcribed_text = transcription.text
        
        # Feedback to user with the transcription
        feedback_msg = TEXTS["messages"]["transcription_done"].format(text=transcribed_text)
        await update.message.reply_text(feedback_msg, parse_mode="Markdown")
        
        # Proceed to analysis
        await generate_jungian_response(transcribed_text, update)

    except Exception as e:
        logger.error(f"Audio Processing Error: {e}")
        await update.message.reply_text(TEXTS["errors"]["audio_error"])
    
    finally:
        # Cleanup: Ensure temporary file is removed
        if temp_ogg_path.exists():
            os.remove(temp_ogg_path)

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles standard text messages."""
    # Send 'typing' action for better UX
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    
    user_input = update.message.text
    await generate_jungian_response(user_input, update)

# --- APPLICATION ENTRY POINT ---

if __name__ == '__main__':

    # Mock a web server to fool Render
    keep_alive()

    # Build the application
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Register Handlers
    application.add_handler(CommandHandler('start', start_command))
    application.add_handler(CommandHandler('privacy', privacy_command))
    
    # Handle Voice Messages
    application.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
    
    # Handle Text Messages (excluding commands)
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_message))
    
    logger.info("Dr. Jung Bot is running professionally. Press Ctrl+C to stop.")
    application.run_polling()