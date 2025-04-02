import os
import sqlite3
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram import ChatMember
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# Configure logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Database setup
db_file = "registrations.db"
conn = sqlite3.connect(db_file, check_same_thread=False)
c = conn.cursor()

# Create tables if they do not exist
c.execute('''CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                edate TEXT,
                etime TEXT,
                location_name TEXT,
                level TEXT,
                location_coordinates TEXT,
                published INTEGER)''')

c.execute('''CREATE TABLE IF NOT EXISTS registrations (
                user_id INTEGER,
                event_id INTEGER,
                shortname TEXT,
                drives INTEGER,
                safety_equipment TEXT,
                car_details TEXT,
                consent_accepted BOOLEAN,
                PRIMARY KEY (user_id, event_id),
                FOREIGN KEY (event_id) REFERENCES events(event_id))''')
conn.commit()

# Function to get admin IDs from the channel
async def get_admins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> list:
    logger.debug("Getting admins for chat %s", update.message.chat_id)
    chat_id = update.message.chat_id
    admins = await context.bot.get_chat_administrators(chat_id)
    admin_ids = [admin.user.id for admin in admins]
    logger.debug("Admins retrieved: %s", admin_ids)
    return admin_ids

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    logger.info("User %s started the bot", user.full_name)
    await update.message.reply_text(f"Hello {user.full_name}, welcome to the bot! Use /help to see available commands.")

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    logger.info("User %s asked for help from bot. chatid: %d", user.full_name, chat.id)
    await update.message.reply_text(f"Hello {user.full_name}, These are the available commands: \n/events to list the currently available drives\n/register <drivename> to register for a specific drive\n")
    admins = await  get_admins(update, context)
    #admin_ids = [admin.user.id for admin in admins ]
    logger.debug("ADMINS: %s", admins)
    if user.id in admins:
        logger.info("Admin commands for user %s", user.full_name)
        await update.message.reply_text(f"Admin commands: \n/create_event <event shortname> to initiate a drive creation\n/participants <event shortname>\n/publish_event <event shortname> to make the drive selectable for registration\n/modify_event <event shortname> to initiate modification to drive details")

# Create event command (admin only)
async def create_event2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    admin_ids = await get_admins(update, context)
    user_id = update.message.from_user.id

    if user_id in admin_ids:
        try:
            name = context.args[0]
            date = context.args[1]
            time = context.args[2]
            location_name = context.args[3]
            location_coordinates = context.args[4]

            c.execute('INSERT INTO events (name, date, time, location_name, location_coordinates) VALUES (?, ?, ?, ?, ?)', 
                      (name, date, time, location_name, location_coordinates))
            conn.commit()

            await update.message.reply_text(f"Event '{name}' created successfully.")
            logger.info("Event '%s' created by admin %d", name, user_id)
        except IndexError:
            await update.message.reply_text("Usage: /create_event <name> <date> <time> <location_name> <location_coordinates>")
            logger.error("Insufficient arguments for creating event.")
    else:
        await update.message.reply_text("You do not have permission to create events.")
        logger.warning("Unauthorized attempt to create event by user %d", user_id)

async def create_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat = update.effective_chat #update.message.chat

    if context.args:
        try:
            event_name = " ".join(context.args)

            if chat.type != "private":  # If in a group chat
                member = await context.bot.get_chat_member(chat.id, user_id)
                logger.info("chat id: %d", chat.id)
                if member.status not in ["administrator", "creator"]:
                    await update.message.reply_text("🚫 Only group admins can create events.")
                    return

                # Record admin user ID
                if "allowed_admins" not in context.bot_data:
                    context.bot_data["allowed_admins"] = set()
                context.bot_data["allowed_admins"].add(user_id)

                await context.bot.send_message(
                    chat_id=user_id,
                    text="✅ You are authorized to create an event. Let's continue in private chat.\n\n"
                         "Please start by typing the event name."
                )
                context.user_data.clear()
                context.user_data["step"] = "name"
                context.user_data['flow'] = "event"
                return

            # If already in private chat
            if user_id not in context.bot_data.get("allowed_admins", set()):
                await update.message.reply_text("🚫 You are not authorized to create events.")
                return
            
        except ValueError:
            await update.message.reply_text("Invalid event name.")
            logger.error("Error with event name")
    else:
        logger.error("no event name provided in create_event")
        await update.message.reply_text("🚫 provide a short event name to create")

async def save_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.debug("event save started")
    event_name = context.user_data.get("event_name")
    event_date = context.user_data.get("event_date")
    event_time = context.user_data.get("event_time")
    level = context.user_data.get("level")
    location_name = context.user_data.get("location_name")
    location_coordinates = context.user_data.get("location_coordinates")
    logger.debug("event save with name %s date %s time %s location %s level %s and coord %s", event_name, event_date, event_time, location_name, level, location_coordinates)
    
    c.execute(
        "INSERT INTO events (name, date, time, location_name, level, location_coordinates) VALUES (?, ?, ?, ?, ?, ?)",
        (event_name, event_date, event_time, location_name, level, location_coordinates)
    )
    conn.commit()
    logger.debug("event save after commit")

    await update.message.reply_text(f"✅ Event '{event_name}' created for {event_date} at {event_time}.")
    if location_name:
        await update.message.reply_text(f"📍 Location: {location_name}")
    context.user_data.clear()


# List events command
async def list_events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

    if context.args:
        try:
            event_name = " ".join(context.args)
            c.execute("SELECT event_id, name, edate, etime, location_name, level, location_coordinates FROM events WHERE name = ?", (event_name,))
            event = c.fetchone()
            event_id, name, edate, etime, location_name, level, location_coordintates = event

            c.execute("SELECT COUNT(*) FROM registrations WHERE event_id = ?", (event_id,))
            participant_count = c.fetchone()[0]
            event_list=""
            if not location_name:
                location_name = "."
            event_list += f"{name} on {edate} at {etime} at {location_name} - {participant_count} participant(s)\n"
            if location_coordintates:
                event_list += f"{location_coordintates}\n"
            await update.message.reply_text(f"Event {event_name}:\n{event_list}")
        except ValueError:
            await update.message.reply_text("Invalid event name. Use /events to see available events.")
            logger.error("Invalid event name input.")
    else:
        try:
            c.execute("SELECT event_id, name, edate, etime FROM events WHERE edate >= date('now')")
            events = c.fetchall()
            if events:
                event_list = ""
                for event in events:
                    event_id, name, edate, etime = event
                    # Format the date to show the day of the week (e.g., Monday, 2025-03-29)
                    event_date = datetime.strptime(date, "%Y-%m-%d").strftime("%A, %Y-%m-%d")

                    # Count the number of participants registered for the event
                    c.execute("SELECT COUNT(*) FROM registrations WHERE event_id = ?", (event_id,))
                    participant_count = c.fetchone()[0]

                    event_list += f"{name} on {event_date} at {etime} - {participant_count} participant(s)\n"

                await update.message.reply_text(f"Upcoming events:\n{event_list}")
            else:
                await update.message.reply_text("No upcoming events found.")
        except ValueError:
            await update.message.reply_text("Error in events. Use /events to see available events.")
            logger.error("Error in events.")

# Register command
async def register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.message.from_user
    logger.debug("User %s started registration", user.id)

    if context.args:
        try:
            event_name = " ".join(context.args)
            c.execute("SELECT event_id, name FROM events WHERE name = ?", (event_name,))
            event = c.fetchone()

            if event:
                event_id = event[0]
                logger.debug("Event found: %s (ID: %d)", event_name, event_id)

                c.execute("SELECT * FROM registrations WHERE user_id = ? AND event_id = ?", (user.id, event_id))
                registration = c.fetchone()

                if registration:
                    current_drives = registration[3]
                    await update.message.reply_text(f"You are already registered for the {event_name} drive.")
                    logger.debug("User %s is already registered for %s drive", user.id, event_id)
                    #await update.message.reply_text("Would you like to update the number of drives? (Reply with the new number of drives or type 'no' to cancel)")
                    #context.user_data['awaiting_event_id'] = event_id
                    #context.user_data['flow'] = "reg"
                    #context.user_data['step'] = 'reg_update_drives'
                    context.user_data.clear()
                else:
                    c.execute("SELECT shortname FROM registrations WHERE user_id = ?", (user.id,))
                    profile = c.fetchone()

                    if profile:
                        # If profile exists, just ask for the shortname.
                        await update.message.reply_text("Please provide your short name for the registration.")
                        context.user_data['awaiting_event_id'] = event_id
                        context.user_data['flow'] = "reg"
                        context.user_data['step'] = 'reg_shortname'
                        logger.debug("User %s profile found. Proceeding with shortname registration.", user.id)
                    else:
                        # If no profile, ask for the full details.
                        await update.message.reply_text("Please provide your short name for the registration.")
                        context.user_data['awaiting_event_id'] = event_id
                        context.user_data['flow'] = "reg"
                        context.user_data['step'] = 'reg_shortname_new'
                        logger.debug("User %s is a new participant. Asking for full registration details.", user.id)
            else:
                await update.message.reply_text("Event not found. Please provide a valid event name.")
                logger.debug("Event '%s' not found in the database.", event_name)

        except ValueError:
            await update.message.reply_text("Invalid event name. Use /events to see available events.")
            logger.error("Invalid event name input.")
    else:
        await update.message.reply_text("Please specify an event name: /register <event_name>")

# Handle user messages during the registration process
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.message.from_user
    event_id = context.user_data.get('awaiting_event_id')
    step = context.user_data.get('step')
    flow = context.user_data.get('flow')

    #if event_id:
    if user.id:
        logger.debug("User %s is in flow %s step %s", user.id, flow, step)
        if flow == "reg":
            if step == 'reg_shortname' or step == 'reg_shortname_new':
                context.user_data['shortname'] = update.message.text
                if step == 'reg_shortname_new':
                    await update.message.reply_text("How many drives have you had as experience? (Reply with a number)")
                    context.user_data['step'] = 'reg_drives'
                    context.user_data['flow'] = "reg"
                    logger.debug("User %s with new profile: %s", user.id, context.user_data['shortname'])
                else:
                    #await update.message.reply_text("You are already registered. Please provide the shortname.")
                    await update.message.reply_text("Please read and accept the consent form: 'I consent to participating in this event and follow all safety regulations.' (Reply with 'yes' to accept)")
                    context.user_data['step'] = 'event_consent'
                    context.user_data['flow'] = "reg"

            elif step == 'reg_drives':
                try:
                    drives = int(update.message.text)
                    context.user_data['drives'] = drives
                    await update.message.reply_text("Do you have safety equipment in your car? (Reply with 'yes' or 'no')")
                    context.user_data['step'] = 'reg_safety_equipment'
                    context.user_data['flow'] = "reg"
                    logger.debug("User %s provided drives: %d", user.id, drives)
                except ValueError:
                    await update.message.reply_text("Please enter a valid number of drives.")

            elif step == 'reg_safety_equipment':
                safety_equipment = update.message.text
                context.user_data['safety_equipment'] = safety_equipment
                context.user_data['flow'] = "reg"
                await update.message.reply_text("Please provide your car details (make, model, year, etc.)")
                context.user_data['step'] = 'reg_car_details'
                logger.debug("User %s provided safety equipment: %s", user.id, safety_equipment)

            elif step == 'reg_car_details':
                car_details = update.message.text
                context.user_data['car_details'] = car_details
                context.user_data['flow'] = "reg"
                await update.message.reply_text("Please read and accept the consent form: 'I consent to participating in this event and follow all safety regulations.' (Reply with 'yes' to accept)")
                context.user_data['step'] = 'event_consent'
                logger.debug("User %s provided car details: %s", user.id, car_details)

            elif step == 'event_consent':
                consent = update.message.text
                if consent.lower() == 'yes':
                    c.execute("REPLACE INTO registrations (user_id, event_id, shortname, drives, safety_equipment, car_details, consent_accepted) VALUES (?, ?, ?, ?, ?, ?, ?)", 
                              (user.id, event_id, context.user_data['shortname'], context.user_data['drives'], context.user_data['safety_equipment'], context.user_data['car_details'], True))
                    conn.commit()

                    # Increment the number of drives by 1 after successful registration.
                    c.execute("UPDATE registrations SET drives = drives + 1 WHERE user_id = ? AND event_id = ?", (user.id, event_id))
                    conn.commit()

                    await update.message.reply_text(f"{user.full_name}, you have been successfully registered for {context.user_data['drives']} drive(s) in event {event_id}!")
                    logger.info("User %s successfully registered for event %d", user.id, event_id)
                else:
                    await update.message.reply_text("You must accept the consent to register.")
                    logger.warning("User %s did not accept consent", user.id)
                context.user_data.clear()  # Clear user data after registration process is complete

            elif step == 'reg_update_drives':
                try:
                    new_drives = int(update.message.text)
                    if new_drives >= 0:
                        c.execute("UPDATE registrations SET drives = ? WHERE user_id = ? AND event_id = ?", 
                                  (new_drives, user.id, event_id))
                        conn.commit()
                        await update.message.reply_text(f"Your number of drives has been updated to {new_drives}.")
                        logger.info("User %s updated drives for event %d to %d", user.id, event_id, new_drives)
                    else:
                        await update.message.reply_text("Please enter a valid number of drives.")
                except ValueError:
                    if update.message.text.lower() == 'no':
                        await update.message.reply_text("No changes have been made to your registration.")
                        logger.info("User %s canceled drive update for event %d", user.id, event_id)
                    else:
                        await update.message.reply_text("Please enter a valid number.")
                context.user_data.clear()  # Clear user data after handling the update
            else: 
                logger.info("unknown step %s in flow %s", step, flow)
                context.user_data.clear()  # Clear user data after handling the update

        elif flow == "event":
            if step == "name":
               context.user_data["event_name"] = update.message.text
               await update.message.reply_text("Now, provide the event date (YYYY-MM-DD).")
               context.user_data['flow'] = "event"
               context.user_data["step"] = "event_date"
               
               name = update.message.text
               logger.info("Event %s is being created", name)
            elif step == "event_date":
                event_date = update.message.text
                try:
                    datetime.strptime(event_date, "%Y-%m-%d")
                    context.user_data["event_date"] = event_date
                    await update.message.reply_text("Provide the event time (HH:MM, 24-hour format).")
                    context.user_data['flow'] = "event"
                    context.user_data["step"] = "event_time"
                except ValueError:
                    await update.message.reply_text("Invalid date format. Use YYYY-MM-DD.")
            elif step == "event_time":
                event_time = update.message.text
                try:
                    datetime.strptime(event_time, "%H:%M")
                    context.user_data["event_time"] = event_time
                    await update.message.reply_text(
                        "Optionally, provide the location name. Type '.' to skip."
                    )
                    context.user_data['flow'] = "event"
                    context.user_data["step"] = "location_name"
                except ValueError:
                    await update.message.reply_text("Invalid time format. Use HH:MM.")

            elif step == "location_name":
                location_name = update.message.text
                if location_name.lower() == ".":
                    context.user_data["location_name"] = None

                context.user_data['flow'] = "event"
                await update.message.reply_text(
                    "Optionally, provide location coordinates (e.g., google map link or '12.34, 56.78'). Type '.' to skip."
                )
                context.user_data["step"] = "location_coordinates"

            elif step == "location_coordinates":
                location_coordinates = update.message.text
                if location_coordinates.lower() == ".":
                    context.user_data["location_coordinates"] = None
                else:
                    context.user_data["location_coordinates"] = location_coordinates
                await save_event(update, context)

            else: 
                logger.info("unknown step %s in flow %s", step, flow)
                context.user_data.clear()  # Clear user data after handling the update
            
        else:
            #await update.message.reply_text("unknown flow.")
            logger.debug("Unknown flow")

    else:
        await update.message.reply_text("unknown event.")
        logger.debug("Unknown event for user %s", user.id)

# List participants command
async def list_participants(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.args:
        try:
            event_name = " ".join(context.args)
            c.execute("SELECT event_id FROM events WHERE name = ?", (event_name,))
            event = c.fetchone()

            if event:
                event_id = event[0]
                c.execute("SELECT shortname, drives FROM registrations WHERE event_id = ? ORDER BY rowid", (event_id,))
                registrations = c.fetchall()

                if registrations:
                    participants = "\n".join(f"{shortname} - {drives} drive(s)" for shortname, drives in registrations)
                    await update.message.reply_text(f"Participants for Event '{event_name}':\n{participants}")
                    logger.debug("Participants for event '%s': %s", event_name, registrations)
                else:
                    await update.message.reply_text("No participants registered for this event yet.")
                    logger.debug("No participants for event '%s'", event_name)
            else:
                await update.message.reply_text("Event not found. Please provide a valid event name.")
                logger.debug("Event '%s' not found", event_name)
        except ValueError:
            await update.message.reply_text("Invalid event name. Use /events to see available events.")
            logger.error("Invalid event name input")
    else:
        await update.message.reply_text("Please specify an event name: /participants <event_name>")
        logger.debug("No event name specified for participants listing")

# Main function to run the bot
def main():
    bot_token = os.getenv("BOT_TOKEN")
    app = ApplicationBuilder().token(bot_token).build()

    # Add handlers for commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help))
    app.add_handler(CommandHandler("create_event", create_event))
    app.add_handler(CommandHandler("events", list_events))
    app.add_handler(CommandHandler("register", register))
    app.add_handler(CommandHandler("participants", list_participants))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Start the bot and handle updates
    logger.info("Bot started")
    app.run_polling()

# If running in an environment that already has a running loop, use this method:
if __name__ == "__main__":
    main()
