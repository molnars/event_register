from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackContext, CallbackQueryHandler, MessageHandler, Filters
import os
import sqlite3

# Database setup
db_file = "registrations.db"

conn = sqlite3.connect(db_file, check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                date TEXT,
                time TEXT,
                location_name TEXT,
                location_coordinates TEXT)''')
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


# Helper functions
def register(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    if context.args:
        try:
            event_id = int(context.args[0])
            c.execute("SELECT name FROM events WHERE event_id = ?", (event_id,))
            event = c.fetchone()
            if event:
                c.execute("SELECT drives FROM registrations WHERE user_id = ? AND event_id = ?", (user.id, event_id))
                registration = c.fetchone()
                
                if registration:
                    current_drives = registration[0]
                    update.message.reply_text(f"You are already registered for {current_drives} drive(s) in this event.")
                    update.message.reply_text("Would you like to update the number of drives? (Reply with the new number of drives or type 'no' to cancel)")
                    context.user_data['awaiting_event_id'] = event_id
                    context.user_data['step'] = 'update_drives'
                else:
                    update.message.reply_text("Please provide your shortname for the registration.")
                    context.user_data['awaiting_event_id'] = event_id
                    context.user_data['step'] = 'shortname'
            else:
                update.message.reply_text("Invalid event ID. Use /events to see available events.")
        except ValueError:
            update.message.reply_text("Invalid event ID. Use /events to see available events.")
    else:
        update.message.reply_text("Please specify an event ID: /register <event_id>")

def handle_message(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    event_id = context.user_data.get('awaiting_event_id')
    step = context.user_data.get('step')

    if event_id:
        if step == 'shortname':
            context.user_data['shortname'] = update.message.text
            update.message.reply_text("How many drives would you like to register for? (Reply with a number)")
            context.user_data['step'] = 'drives'

        elif step == 'drives':
            try:
                drives = int(update.message.text)
                context.user_data['drives'] = drives
                update.message.reply_text("Do you have safety equipment? (Reply with 'yes' or 'no')")
                context.user_data['step'] = 'safety_equipment'
            except ValueError:
                update.message.reply_text("Please enter a valid number.")

        elif step == 'safety_equipment':
            safety_equipment = update.message.text
            context.user_data['safety_equipment'] = safety_equipment
            update.message.reply_text("Please provide your car details (make, model, year, etc.)")
            context.user_data['step'] = 'car_details'

        elif step == 'car_details':
            car_details = update.message.text
            context.user_data['car_details'] = car_details
            update.message.reply_text("Please read and accept the consent form: 'I consent to participating in this event and follow all safety regulations.' (Reply with 'yes' to accept)")
            context.user_data['step'] = 'consent'

        elif step == 'consent':
            consent = update.message.text
            if consent.lower() == 'yes':
                c.execute("REPLACE INTO registrations (user_id, event_id, shortname, drives, safety_equipment, car_details, consent_accepted) VALUES (?, ?, ?, ?, ?, ?, ?)", 
                          (user.id, event_id, context.user_data['shortname'], context.user_data['drives'], context.user_data['safety_equipment'], context.user_data['car_details'], True))
                conn.commit()
                update.message.reply_text(f"{user.full_name}, you have been successfully registered for {context.user_data['drives']} drive(s) in event {event_id}!")
            else:
                update.message.reply_text("You must accept the consent to register.")
            context.user_data.clear()  # Clear user data after registration process is complete
        
        elif step == 'update_drives':
            try:
                new_drives = int(update.message.text)
                if new_drives >= 0:
                    c.execute("UPDATE registrations SET drives = ? WHERE user_id = ? AND event_id = ?", 
                              (new_drives, user.id, event_id))
                    conn.commit()
                    update.message.reply_text(f"Your number of drives has been updated to {new_drives}.")
                else:
                    update.message.reply_text("Please enter a valid number of drives.")
            except ValueError:
                if update.message.text.lower() == 'no':
                    update.message.reply_text("No changes have been made to your registration.")
                else:
                    update.message.reply_text("Please enter a valid number.")
            context.user_data.clear()  # Clear user data after handling the update

        else:
            update.message.reply_text("An unexpected error occurred. Please try again.")
    else:
        update.message.reply_text("You have not started the registration process yet. Please use /register <event_id> to begin.")


# Helper functions
def create_event(update: Update, context: CallbackContext) -> None:
    if is_admin(update, context):
        if len(context.args) >= 3:
            event_name = " ".join(context.args[:-2])
            event_date = context.args[-2]
            event_time = context.args[-1]
            c.execute("INSERT INTO events (name, date, time) VALUES (?, ?, ?)", (event_name, event_date, event_time))
            conn.commit()
            update.message.reply_text(f"Event '{event_name}' scheduled for {event_date} at {event_time} created successfully! Users can now register using /register <event_id>.")
        else:
            update.message.reply_text("Please provide an event name, date, and time: /create_event <event_name> <YYYY-MM-DD> <HH:MM>")
    else:
        update.message.reply_text("You do not have permission to create an event.")

def get_all_events():
    c.execute("SELECT event_id, name, date, time FROM events")
    return c.fetchall()

def list_events(update: Update, context: CallbackContext) -> None:
    events = get_all_events()
    if events:
        event_list = "\n".join(f"ID: {event_id} - {name} on {date} at {time}" for event_id, name, date, time in events)
        update.message.reply_text(f"Available Events:\n{event_list}")
    else:
        update.message.reply_text("No events have been created yet.")

def register(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    if context.args:
        try:
            event_id = int(context.args[0])
            c.execute("SELECT name FROM events WHERE event_id = ?", (event_id,))
            event = c.fetchone()
            if event:
                update.message.reply_text("How many drives do you want to register for? (Reply with a number)")
                context.user_data['awaiting_drive_count'] = event_id
            else:
                update.message.reply_text("Invalid event ID. Use /events to see available events.")
        except ValueError:
            update.message.reply_text("Invalid event ID. Use /events to see available events.")
    else:
        update.message.reply_text("Please specify an event ID: /register <event_id>")

def list_participants(update: Update, context: CallbackContext) -> None:
    if context.args:
        try:
            event_id = int(context.args[0])
            c.execute("SELECT name, drives FROM registrations WHERE event_id = ?", (event_id,))
            registrations = c.fetchall()
            if registrations:
                participants = "\n".join(f"{name} - {drives} drive(s)" for name, drives in registrations)
                update.message.reply_text(f"Participants for Event {event_id}:\n{participants}")
            else:
                update.message.reply_text("No participants registered for this event yet.")
        except ValueError:
            update.message.reply_text("Invalid event ID. Use /events to see available events.")
    else:
        update.message.reply_text("Please specify an event ID: /participants <event_id>")

def main():
    bot_token = os.getenv("BOT_TOKEN")
    updater = Updater(bot_token)
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("create_event", create_event, pass_args=True))
    dp.add_handler(CommandHandler("events", list_events))
    dp.add_handler(CommandHandler("register", register, pass_args=True))
    dp.add_handler(CommandHandler("participants", list_participants, pass_args=True))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    
    updater.start_polling()
    updater.idle()
    conn.close()

if __name__ == "__main__":
    main()
