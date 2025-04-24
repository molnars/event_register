import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, ConversationHandler,
    MessageHandler, ContextTypes, filters
)
from pymongo import MongoClient
from datetime import datetime
import os

logging.basicConfig(level=logging.INFO)

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
templates_col = db['templates']

# --- States ---
(ASK_DATE, ASK_LOCATION, ASK_LEVEL, ASK_PUBLISH,
 ASK_SCREEN, ASK_CAR, ASK_DRIVES, ASK_TEMPLATE_NAME) = range(8)

# --- Helpers ---
async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    member = await update.effective_chat.get_member(update.effective_user.id)
    return member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]

def get_next_event_id():
    last = events_col.find_one(sort=[("event_id", -1)])
    return (last["event_id"] + 1) if last else 1

def get_next_template_id():
    last = templates_col.find_one(sort=[("template_id", -1)])
    return (last["template_id"] + 1) if last else 1

# --- Event Creation ---
async def create_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can create events.")
        return ConversationHandler.END
    context.user_data['event'] = {}
    await update.message.reply_text("Enter event date (YYYY-MM-DD):")
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
        [InlineKeyboardButton("Publish", callback_data="publish_event"),
         InlineKeyboardButton("Save as Template", callback_data="save_template"),
         InlineKeyboardButton("Cancel", callback_data="cancel_event")]
    ]
    await update.message.reply_text(
        f"Event details:\nDate: {event['date']}\nLocation: {event['location']}\n"
        f"Min Level: {event['min_level']}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ASK_PUBLISH

async def publish_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    event = context.user_data.pop('event')
    event_id = get_next_event_id()
    event['event_id'] = event_id
    events_col.insert_one(event)
    # Post event with registration button
    keyboard = [[InlineKeyboardButton("Register", callback_data=f"register|{event_id}")]]
    await query.edit_message_text(
        f"Event #{event_id}\nDate: {event['date']}\nLocation: {event['location']}\n"
        f"Min Level: {event['min_level']}\n\nClick below to register:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END

async def save_template(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Enter template name:")
    return ASK_TEMPLATE_NAME

async def store_template(update: Update, context: ContextTypes.DEFAULT_TYPE):
    template_name = update.message.text
    template = context.user_data.get('event', {})
    template['template_name'] = template_name
    template['template_id'] = get_next_template_id()
    templates_col.insert_one(template)
    await update.message.reply_text(f"Template '{template_name}' saved.")
    context.user_data.pop('event', None)
    return ConversationHandler.END

async def cancel_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop('event', None)
    await query.edit_message_text("Event creation cancelled.")
    return ConversationHandler.END

# --- Registration ---
async def register_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    _, event_id = query.data.split("|")
    event_id = int(event_id)
    user = users_col.find_one({"user_id": user_id})
    if not user:
        context.user_data['register_event_id'] = event_id
        await query.message.reply_text("Let's create your profile!\nEnter your screen name:")
        return ASK_SCREEN
    # Check if already registered
    reg = registrations_col.find_one({"event_id": event_id, "user_id": user_id})
    if reg:
        await query.message.reply_text("You are already registered.")
        return ConversationHandler.END
    # Register
    order = registrations_col.count_documents({"event_id": event_id}) + 1
    registrations_col.insert_one({
        "event_id": event_id,
        "user_id": user_id,
        "registered_at": datetime.utcnow(),
        "order": order
    })
    await query.message.reply_text("You are registered for the event!")
    return ConversationHandler.END

# --- Profile Creation ---
async def ask_car(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['profile'] = {'screen_name': update.message.text}
    await update.message.reply_text("What car do you drive?")
    return ASK_CAR

async def ask_drives(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['profile']['car'] = update.message.text
    await update.message.reply_text("How many drives have you done so far?")
    return ASK_DRIVES

async def save_profile_and_register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    profile = context.user_data.pop('profile')
    profile['user_id'] = user_id
    profile['drives'] = int(update.message.text)
    users_col.insert_one(profile)
    event_id = context.user_data.pop('register_event_id')
    order = registrations_col.count_documents({"event_id": event_id}) + 1
    registrations_col.insert_one({
        "event_id": event_id,
        "user_id": user_id,
        "registered_at": datetime.utcnow(),
        "order": order
    })
    await update.message.reply_text("Profile created and registered for the event!")

# --- List Events ---
async def list_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    events = list(events_col.find())
    if not events:
        await update.message.reply_text("No events available.")
        return
    msg = "Events:\n"
    for ev in events:
        msg += f"ID: {ev['event_id']}, Date: {ev['date']}, Location: {ev['location']}, Min Level: {ev['min_level']}\n"
    await update.message.reply_text(msg)

# --- Start Event (increments drive count) ---
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

# --- Main ---
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    event_conv = ConversationHandler(
        entry_points=[CommandHandler("create_event", create_event)],
        states={
            ASK_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_location)],
            ASK_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_level)],
            ASK_LEVEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_publish)],
            ASK_PUBLISH: [
                CallbackQueryHandler(publish_event, pattern="^publish_event$"),
                CallbackQueryHandler(save_template, pattern="^save_template$"),
                CallbackQueryHandler(cancel_event, pattern="^cancel_event$")
            ],
            ASK_TEMPLATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, store_template)],
        },
        fallbacks=[]
    )
    profile_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(register_callback, pattern="^register\\|")],
        states={
            ASK_SCREEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_car)],
            ASK_CAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_drives)],
            ASK_DRIVES: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_profile_and_register)],
        },
        fallbacks=[]
    )

    app.add_handler(event_conv)
    app.add_handler(profile_conv)
    app.add_handler(CommandHandler("events", list_events))
    app.add_handler(CommandHandler("start_event", start_event))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
