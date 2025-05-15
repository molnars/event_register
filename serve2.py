import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, ConversationHandler,
    MessageHandler, ContextTypes, filters
)
from pymongo import MongoClient
from datetime import datetime
import os
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN','')
GROUPID = os.getenv('GROUPID','')
MONGO_URI = os.getenv('MONGO_URI','')

# --- MongoDB Setup ---
#MONGO_URI = "YOUR_MONGODB_URI"
client = MongoClient(MONGO_URI)
db = client['eventbot']
users_col = db['users']
events_col = db['events']
registrations_col = db['registrations']

# --- States for ConversationHandler ---
(ASK_DATE, ASK_LOCATION, ASK_LEVEL, ASK_PUBLISH,
 ASK_SCREEN, ASK_CAR, ASK_DRIVES) = range(7)

# --- Helper Functions ---
async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        #member = await update.effective_chat.get_member(update.effective_user.id)
        print(f"[DEBUG] chatid: {update.effective_chat} vs master {GROUPID}")
        #prepend - or -100 infront of supergroup chat id
        member = await context.bot.get_chat_member(f"-{GROUPID}", update.effective_user.id)
        return member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]
    except Exception as e:
        print(e)
        return False

def get_next_event_id():
    last = events_col.find_one(sort=[("event_id", -1)])
    return (last["event_id"] + 1) if last else 1

# --- Inline Keyboards ---
def admin_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Create Event", callback_data="admin_create_event")],
        [InlineKeyboardButton("📍 Add template location", callback_data="admin_new_location_template")],
        [InlineKeyboardButton("👥 List Registrations", callback_data="admin_list_events")],
        [InlineKeyboardButton("👥 Promote user", callback_data="admin_promote_driver")]

    ])

def user_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Upcoming Events", callback_data="user_list_upcoming")],
        [InlineKeyboardButton("✅ My Registrations", callback_data="user_my_registrations")],
        [InlineKeyboardButton("✅ Introduce myself", callback_data="user_intro")]
    ])

def event_registration_buttons(event_id, is_registered):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "❌ Unregister" if is_registered else "✅ Register",
            callback_data=f"user_toggle_reg_{event_id}"
        )]
    ])

def admin_event_buttons(event_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 View Registrations", callback_data=f"admin_view_regs_{event_id}")]
    ])

# --- Start/Help ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users_col.find_one({"user_id": user_id})
    if not user:
        await update.message.reply_text(
            "Welcome! Let's create your profile.\n"
            "Please enter your screen name:"
        )
        return ASK_SCREEN
    await update.message.reply_text("Welcome! Use /menu for event options.")

# --- Profile Creation ---
async def ask_car(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['profile'] = {'screen_name': update.message.text}
    await update.message.reply_text("What car do you drive?")
    return ASK_CAR

async def ask_drives(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['profile']['car'] = update.message.text
    await update.message.reply_text("How many drives have you done so far?")
    return ASK_DRIVES

async def save_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    profile = context.user_data.pop('profile')
    profile['user_id'] = user_id
    try:
        profile['drives'] = int(update.message.text)
    except ValueError:
        profile['drives'] = 0
    users_col.insert_one(profile)
    await update.message.reply_text("Profile created! Use /menu to see event options.")
    return ConversationHandler.END

# --- Menus ---
async def show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_admin(update, context):
        await update.message.reply_text("Admin Menu:", reply_markup=admin_menu())
    else:
        await update.message.reply_text("You are not an admin.")

async def show_user_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Event Menu:", reply_markup=user_menu())

# --- Admin: Create Event Conversation ---
async def admin_create_event_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['event'] = {}
    await query.message.reply_text("Enter event date (YYYY-MM-DD):")
    return ASK_DATE

async def ask_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['event']['date'] = update.message.text
    await update.message.reply_text("Enter event location:")
    return ASK_LOCATION

async def ask_level(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['event']['location'] = update.message.text
    await update.message.reply_text("Enter minimum level required:")
    return ASK_LEVEL

async def ask_publish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['event']['min_level'] = update.message.text
    event = context.user_data['event']
    keyboard = [
        [InlineKeyboardButton("Publish", callback_data="admin_publish_event"),
         InlineKeyboardButton("Cancel", callback_data="admin_cancel_event")]
    ]
    await update.message.reply_text(
        f"Event details:\nDate: {event['date']}\nLocation: {event['location']}\n"
        f"Min Level: {event['min_level']}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ASK_PUBLISH

async def admin_publish_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    event = context.user_data.pop('event')
    event_id = get_next_event_id()
    event['event_id'] = event_id
    event['published'] = True
    event['publish_date'] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    events_col.insert_one(event)
    await query.edit_message_text(
        f"Event #{event_id} published!\n"
        f"Date: {event['date']}\nLocation: {event['location']}\nMin Level: {event['min_level']}"
    )
    return ConversationHandler.END

async def admin_cancel_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop('event', None)
    await query.edit_message_text("Event creation cancelled.")
    return ConversationHandler.END

# --- Admin: List Events for Registration View ---
async def admin_list_events_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    events = list(events_col.find().sort("date", 1))
    if not events:
        await query.message.reply_text("No events available.")
        return
    buttons = [
        [InlineKeyboardButton(
            f"{ev['date']} - {ev['location']}",
            callback_data=f"admin_view_regs_{ev['event_id']}"
        )]
        for ev in events
    ]
    await query.message.reply_text("Select event to view registrations:", reply_markup=InlineKeyboardMarkup(buttons))

# --- Admin: View Registrations for Event ---
async def admin_view_regs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    event_id = int(query.data.split("_")[-1])
    regs = list(registrations_col.find({"event_id": event_id}))
    if not regs:
        await query.edit_message_text("No registrations for this event.")
        return
    user_ids = [r["user_id"] for r in regs]
    users = list(users_col.find({"user_id": {"$in": user_ids}}))
    user_map = {u["user_id"]: u for u in users}
    text = f"Registrations for Event #{event_id}:\n"
    for r in regs:
        u = user_map.get(r["user_id"])
        if u:
            text += f"\n👤 {u['screen_name']} - 🚗 {u['car']} - 🛣️ {u['drives']} drives"
    await query.edit_message_text(text)

# --- User: List Upcoming Events ---
async def user_list_upcoming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    events = list(events_col.find({
        "published": True,
        "date": {"$gte": today}
    }).sort("date", 1))
    if not events:
        await query.edit_message_text("No upcoming events.")
        return
    buttons = [
        [InlineKeyboardButton(
            f"{ev['date']} - {ev['location']}",
            callback_data=f"user_event_detail_{ev['event_id']}"
        )]
        for ev in events
    ]
    await query.edit_message_text("Upcoming Events:", reply_markup=InlineKeyboardMarkup(buttons))

# --- User: Event Detail and Registration ---
async def user_event_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    event_id = int(query.data.split("_")[-1])
    event = events_col.find_one({"event_id": event_id})
    if not event:
        await query.edit_message_text("Event not found.")
        return
    user_id = query.from_user.id
    is_registered = registrations_col.find_one({"event_id": event_id, "user_id": user_id}) is not None
    text = (
        f"Event #{event_id}\n"
        f"Date: {event['date']}\n"
        f"Location: {event['location']}\n"
        f"Min Level: {event['min_level']}\n"
        f"Status: {'✅ Registered' if is_registered else '❌ Not Registered'}"
    )
    await query.edit_message_text(
        text,
        reply_markup=event_registration_buttons(event_id, is_registered)
    )

# --- User: Toggle Registration ---
async def user_toggle_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    event_id = int(query.data.split("_")[-1])
    user_id = query.from_user.id

    # Check profile exists
    if not users_col.find_one({"user_id": user_id}):
        await query.message.reply_text("Please create a profile first using /start")
        return

    reg = registrations_col.find_one({"event_id": event_id, "user_id": user_id})
    if reg:
        registrations_col.delete_one({"_id": reg["_id"]})
        action = "unregistered"
        is_registered = False
    else:
        registrations_col.insert_one({
            "event_id": event_id,
            "user_id": user_id,
            "registered_at": datetime.utcnow()
        })
        action = "registered"
        is_registered = True

    await query.edit_message_text(
        f"You have been {action} for event #{event_id}.",
        reply_markup=event_registration_buttons(event_id, is_registered)
    )

# --- User: My Registrations ---
async def user_my_registrations(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    today = datetime.utcnow().strftime("%Y-%m-%d")
    regs = list(registrations_col.find({"user_id": user_id}))
    if not regs:
        await query.edit_message_text("You have no upcoming registrations.")
        return
    event_ids = [r["event_id"] for r in regs]
    events = list(events_col.find({
        "event_id": {"$in": event_ids},
        "published": True,
        "date": {"$gte": today}
    }).sort("date", 1))
    if not events:
        await query.edit_message_text("You have no upcoming registrations.")
        return
    text = "Your Upcoming Registrations:\n"
    for ev in events:
        text += f"\nID: {ev['event_id']} - {ev['date']} at {ev['location']}"
    await query.edit_message_text(text)

# --- Admin: Start Event (increments drive count) ---
async def start_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can start events.")
        return
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /start_event <event_id>")
        return
    event_id = int(args[0])
    regs = registrations_col.find({"event_id": event_id})
    for reg in regs:
        users_col.update_one({"user_id": reg["user_id"]}, {"$inc": {"drives": 1}})
    await update.message.reply_text("Event started and drive counts updated.")

# --- Conversation Handlers for Profile and Event Creation ---
profile_conv = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        ASK_SCREEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_car)],
        ASK_CAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_drives)],
        ASK_DRIVES: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_profile)],
    },
    fallbacks=[]
)

admin_event_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(admin_create_event_entry, pattern="^admin_create_event$")],
    states={
        ASK_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_location)],
        ASK_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_level)],
        ASK_LEVEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_publish)],
        ASK_PUBLISH: [
            CallbackQueryHandler(admin_publish_event, pattern="^admin_publish_event$"),
            CallbackQueryHandler(admin_cancel_event, pattern="^admin_cancel_event$")
        ],
    },
    fallbacks=[]
)

# --- Main ---
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(profile_conv)
    app.add_handler(admin_event_conv)

    app.add_handler(CommandHandler("admin", show_admin_menu))
    app.add_handler(CommandHandler("menu", show_user_menu))
    app.add_handler(CommandHandler("start_event", start_event))

    app.add_handler(CallbackQueryHandler(admin_list_events_entry, pattern="^admin_list_events$"))
    app.add_handler(CallbackQueryHandler(admin_view_regs, pattern="^admin_view_regs_"))
    app.add_handler(CallbackQueryHandler(user_list_upcoming, pattern="^user_list_upcoming$"))
    app.add_handler(CallbackQueryHandler(user_event_detail, pattern="^user_event_detail_"))
    app.add_handler(CallbackQueryHandler(user_toggle_registration, pattern="^user_toggle_reg_"))
    app.add_handler(CallbackQueryHandler(user_my_registrations, pattern="^user_my_registrations$"))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
