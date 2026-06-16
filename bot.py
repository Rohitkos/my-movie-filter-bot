import os
import re
import time
from pyrogram import Client, filters

# ==================== CONFIGURATION ====================
API_ID = 35493210
API_HASH = "9dbbafd97493ad43740a10fa4b24c201"

# NO HARDCODED TOKENS OR DB LINKS HERE!
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URL = os.environ.get("MONGO_URL")
MONETAG_LINK = os.environ.get("MONETAG_LINK")

# Database and Clients Setup
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["MovieDatabase"]
files_col = db["files"]
users_col = db["users"] 

app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Map for filename language shortcodes
LANGUAGE_MAP = {
    "telugu": "tel",
    "tamil": "tam",
    "hindi": "hin",
    "english": "eng"
}

# ==================== HELPERS ====================
async def has_active_token(user_id):
    """Checks if user completed the ad in the last 2 hours (7200 seconds)"""
    user = await users_col.find_one({"user_id": user_id})
    if user and (time.time() - user.get("token_time", 0)) < 7200:
        return True
    return False

def generate_pages(results, page, query, lang=None):
    """Generates text layout for 6 items per page with menus"""
    items_per_page = 6
    total_items = len(results)
    total_pages = (total_items + items_per_page - 1) // items_per_page
    
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    paginated_items = results[start_idx:end_idx]
    
    text = f"» **TITLE** : {query.upper()}\n"
    if lang:
        text += f"» **FILTER** : {lang.upper()}\n"
    text += f"» **TOTAL FILES** : {total_items}\n\n» **Requested Files** 👇\n\n"
    
    for item in paginated_items:
        # Format human-readable file sizes
        size_gb = round(item['file_size'] / (1024 * 1024 * 1024), 2)
        size_str = f"{size_gb} GB" if size_gb >= 1 else f"{round(item['file_size']/(1024*1024), 2)} MB"
        
        # Deep links back to the bot
        text += f"📁 [{size_str} ▷ {item['file_name']}](t.me/{app.me.username}?start=dl_{item['file_id']})\n\n"
        
    lang_str = lang if lang else "none"
    filter_buttons = [
        InlineKeyboardButton("QUALITY", callback_data="nop"),
        InlineKeyboardButton("LANGUAGE", callback_data=f"openlang_{query}"),
        InlineKeyboardButton("SEASON", callback_data="nop")
    ]
    
    nav_buttons = [
        InlineKeyboardButton("PAGE", callback_data="nop"),
        InlineKeyboardButton(f"{page}/{total_pages}", callback_data="nop"),
        InlineKeyboardButton("NEXT ＞" if page < total_pages else "LAST ■", 
                             callback_data=f"page_{page+1}_{query}_{lang_str}" if page < total_pages else "nop")
    ]
    
    return text, InlineKeyboardMarkup([filter_buttons, nav_buttons])

# ==================== HANDLERS ====================

@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    user_id = message.from_user.id
    cmd_args = message.text.split()
    
    if len(cmd_args) > 1:
        data = cmd_args[1]
        
        # Verification callback from Monetag
        if data.startswith("verify_"):
            await users_col.update_one({"user_id": user_id}, {"$set": {"token_time": time.time()}}, upsert=True)
            await message.reply_text("✅ **Access Granted! You can download files without ads for 2 hours.**")
            return
            
        # File download request via deep link
        if data.startswith("dl_"):
            file_id = data.replace("dl_", "")
            if await has_active_token(user_id):
                await message.reply_document(document=file_id, caption="Thank you for using our bot! Enjoy your movie.")
            else:
                bypass_url = f"{MONETAG_LINK}?token_verify={user_id}&redirect=t.me/{client.me.username}?start=verify_{user_id}"
                btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔓 Unlock Download Link (Watch Ad)", url=bypass_url)]])
                await message.reply_text("⚠️ **Your 2-Hour Download Session has expired or is invalid.**\n\nPlease click the button below to reactivate your access.", reply_markup=btn)
            return

    await message.reply_text(f"Hello {message.from_user.mention},\n\nWelcome to our bot we can download any movie hear. Just type the movie name to search!")

@app.on_message(filters.text & filters.private)
async def search(client, message):
    query = message.text.strip()
    cursor = files_col.find({"file_name": {"$regex": query, "$options": "i"}})
    results = await cursor.to_list(length=200)
    
    if not results:
        await message.reply_text("❌ No files found matching that title in our database.")
        return
        
    text, reply_markup = generate_pages(results, 1, query)
    await message.reply_text(text, reply_markup=reply_markup, disable_web_page_preview=True)

@app.on_callback_query()
async def cb_handler(client, query_msg: CallbackQuery):
    data = query_msg.data
    
    if data == "nop":
        await query_msg.answer()
        return
        
    # Open Language Popup
    if data.startswith("openlang_"):
        movie_query = data.split("_")[1]
        buttons = [
            [InlineKeyboardButton("Telugu", callback_data=f"lang_telugu_{movie_query}"),
             InlineKeyboardButton("Tamil", callback_data=f"lang_tamil_{movie_query}")],
            [InlineKeyboardButton("Hindi", callback_data=f"lang_hindi_{movie_query}"),
             InlineKeyboardButton("English", callback_data=f"lang_english_{movie_query}")]
        ]
        await query_msg.message.edit_text("Select your preferred language down below:", reply_markup=InlineKeyboardMarkup(buttons))
        
    # Filter list by selected Language
    elif data.startswith("lang_"):
        _, selected_lang, movie_query = data.split("_")
        short_tag = LANGUAGE_MAP[selected_lang]
        
        cursor = files_col.find({"file_name": {"$regex": movie_query, "$options": "i"}})
        all_files = await cursor.to_list(length=200)
        
        filtered = [f for f in all_files if re.search(r'\b' + short_tag, f['file_name'], re.IGNORECASE)]
        
        if not filtered:
            await query_msg.answer(f"No files available in {selected_lang.capitalize()}", show_alert=True)
            return
            
        text, reply_markup = generate_pages(filtered, 1, movie_query, lang=short_tag)
        await query_msg.message.edit_text(text, reply_markup=reply_markup, disable_web_page_preview=True)

    # Pagination navigation
    elif data.startswith("page_"):
        _, page, movie_query, lang_str = data.split("_")
        page = int(page)
        
        cursor = files_col.find({"file_name": {"$regex": movie_query, "$options": "i"}})
        results = await cursor.to_list(length=200)
        
        if lang_str != "none":
            results = [f for f in results if re.search(r'\b' + lang_str, f['file_name'], re.IGNORECASE)]
            
        text, reply_markup = generate_pages(results, page, movie_query, lang=None if lang_str == "none" else lang_str)
        await query_msg.message.edit_text(text, reply_markup=reply_markup, disable_web_page_preview=True)

# ==================== CHANNEL INDEXER ====================
@app.on_message(filters.command("index") & filters.private)
async def index_channel(client, message):
    if len(message.command) < 2:
        await message.reply_text("Usage: `/index @YourChannelUsername` or Chat ID")
        return
    
    target_chat = message.command[1]
    status = await message.reply_text("Indexing started... Reading your channel files.")
    count = 0
    
    async for msg in client.get_chat_history(target_chat):
        if msg.document:
            file_data = {
                "file_name": msg.document.file_name,
                "file_id": msg.document.file_id,
                "file_size": msg.document.file_size
            }
            await files_col.update_one({"file_id": msg.document.file_id}, {"$set": file_data}, upsert=True)
            count += 1
            
    await status.edit_text(f"🏁 **Indexing Completed!** Successfully cached {count} files into your database.")

print("Bot engine is online!")
app.run()
# ==================== RENDER FREE TIER PORT BINDING FIX ====================
import threading
from http.server import SimpleHTTPRequestHandler, HTTPServer

def run_dummy_server():
    # Render passes a dynamic port variable. We bind to it to keep the free tier live!
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    print(f"🌍 Dummy Web Server listening on port {port} to pass Render health check.")
    server.serve_forever()

if __name__ == "__main__":
    # Start the web server in a background thread so it doesn't block your Telegram Bot
    threading.Thread(target=run_dummy_server, daemon=True).start()
    
    # Start your Pyrogram bot engine 
    print("🚀 Bot engine is starting...")
    app.run()
