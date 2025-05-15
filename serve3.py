import os, datetime
from dotenv import load_dotenv
import json
from telegram import Update, InputFile,ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, PollAnswerHandler, MessageHandler, filters, ContextTypes

# Load questions from external JSON file
def load_drives(filename="questions_drive.json"):
    with open(filename, "r", encoding="utf-8") as f:
        return json.load(f)
# Load refence locations from external JSON file
def load_references(ref):
    filename=f"questions_{ref}.json"
    with open(filename, "r", encoding="utf-8") as f:
        return json.load(f)

load_dotenv()

QUESTIONS = load_drives()
Q_CONFIRM = { "question": "Publish?", "options": ["Yes", "No"]}

user_states = {}    # user_id -> {"current_q": int, "answers": list, "awaiting_text": bool}
poll_to_user = {}   # poll_id -> user_id

async def create_drive(update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_states[user_id] = {"current_q": 0, "answers": [], "awaiting_text": False, "confirmation": False}
    QUESTIONS = load_drives()
    await send_next_poll(context, user_id)

async def send_next_poll(context, user_id):
    state = user_states[user_id]
    if state["confirmation"]:
        return  # Already in confirmation phase

    q_index = state["current_q"]
    if q_index < len(QUESTIONS):
        q = QUESTIONS[q_index]
        # If this is a text-only question
        if q.get("type") == "text":
            state["awaiting_text"] = True
            await context.bot.send_message(
                chat_id=user_id,
                text=q["question"]
            )
        else:
            if q.get("reference"):
                qref = load_references(q.get("reference"))
                options = qref["options"]
                if q.get("allow_text"):
                    options.append("Other")
            else:
                options = q["options"]
            msg = await context.bot.send_poll(
                chat_id=user_id,
                question=q["question"],
                options=options,
                is_anonymous=False,
                allows_multiple_answers=False
            )
            poll_to_user[msg.poll.id] = user_id
    else:
        await show_confirmation(context, user_id)

        #answers = state["answers"]
        #await context.bot.send_message(
        #    chat_id=user_id,
        #    text=f"Drive is ready to be published. <br>{answers}\n\n Confirm publishing:"
        #)
        #del user_states[user_id]

async def receive_poll_answer(update, context: ContextTypes.DEFAULT_TYPE):
    poll_answer = update.poll_answer
    poll_id = poll_answer.poll_id
    user_id = poll_to_user.get(poll_id)
    if user_id is None or user_id not in user_states:
        return
    state = user_states[user_id]
    q_index = state["current_q"]
    question = QUESTIONS[q_index]
    
    answer_index = poll_answer.option_ids[0] if poll_answer.option_ids else None
    if question.get("allow_text") and question.get("reference"):
        references = load_references(question.get("reference"))
        len_answers = len(references["options"]) +1
    elif question.get("reference"):
        references = load_references(question.get("reference"))
        len_answers = len(references["options"])
    else:
        len_answers = len(question["options"])

    # Check if this question allows a text answer and if "Other" was selected
    if (
       question.get("allow_text") and question.get("reference") and
       answer_index == len_answers  # Last appended should be "Other", so no -1
    ):
        state["awaiting_text"] = True
        await context.bot.send_message(
            chat_id=user_id,
            text="Please type your answer:"
        )
        # Don't increment current_q yet; wait for text response
    elif (
        question.get("allow_text") and
        answer_index == len_answers - 1  # Last option is "Other"
    ):
        state["awaiting_text"] = True
        await context.bot.send_message(
            chat_id=user_id,
            text="Please type your answer:"
        )
        # Don't increment current_q yet; wait for text response
    elif question.get("reference"):
        # Save the selected answer
        answer = references["options"][answer_index] if answer_index is not None else "No answer"
        state["answers"].append(answer)
        state["current_q"] += 1
        del poll_to_user[poll_id]
        await send_next_poll(context, user_id)
    else:
        # Save the selected answer
        answer = question["options"][answer_index] if answer_index is not None else "No answer"
        state["answers"].append(answer)
        state["current_q"] += 1
        del poll_to_user[poll_id]
        await send_next_poll(context, user_id)

async def receive_text(update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_states:
        return  # Ignore messages from users not in survey
    state = user_states[user_id]
    if state.get("awaiting_text"):
        # Save the user's text answer for the current question
        state["answers"].append(update.message.text)
        state["current_q"] += 1
        state["awaiting_text"] = False
        await send_next_poll(context, user_id)

async def show_confirmation(context, user_id):
    """Show summary and confirmation buttons"""
    state = user_states[user_id]
    state["confirmation"] = True
    
    summary = ["📝 *Your Answers:*\n"]
    for idx, (q, a) in enumerate(zip(QUESTIONS, state["answers"])):
        summary.append(f"*{q['question']}*\n   ➥ {a}")
    
    # Add confirmation buttons
    markup = ReplyKeyboardMarkup([["/Confirm ✅", "/Cancel 🚫"]], one_time_keyboard=True)
    print(f"[DEBUG] show conf keyb: {summary}")
    await context.bot.send_message(
        chat_id=user_id,
        text="\n".join(summary) + "\n\nPlease confirm your answers:",
        parse_mode="Markdown",
        reply_markup=markup
    )
    print("[DEBUG] end of confirmation ask")

async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_states.get(user_id)
    print("[DEBUG]: in confirmation handler")
    if not state or not state["confirmation"]:
        print("[DEBUG]: in confirmation handler but wrong state")
        return
    
    choice = update.message.text.lower()
    print(f"[DEBUG]: in {choice}")
    if "confirm" in choice:
        # Save answers to JSON file
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"responses/{user_id}_{timestamp}.json"
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        with open(filename, "w") as f:
            json.dump({
                "user_id": user_id,
                "answers": state["answers"],
                "timestamp": timestamp
            }, f)
        
        # Send final confirmation image
        IMAGE_DIR =""
        conf_image = os.path.join(IMAGE_DIR, "confirmed.jpg")
        if os.path.exists(conf_image):
            with open(conf_image, "rb") as photo:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=InputFile(photo),
                    caption="✅ Answers confirmed and saved!"
                )
        else:
            await update.message.reply_text("✅ Answers confirmed and saved!")
        
        del user_states[user_id]
    else:
        await update.message.reply_text("Restarting survey...")
        await create_drive(update, context)


def main():
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise RuntimeError("Please set the BOT_TOKEN environment variable.")
    application = Application.builder().token(bot_token).build()
    application.add_handler(CommandHandler("new_drive", create_drive))
    application.add_handler(PollAnswerHandler(receive_poll_answer))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text))
    application.add_handler(MessageHandler(filters.Regex(r"Confirm|Restart"), handle_confirmation))
    application.run_polling()

if __name__ == "__main__":
    main()
