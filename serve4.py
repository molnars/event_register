from telegram import Update, BotCommand, BotCommandScopeChat
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Define commands for admins and non-admins
ADMIN_COMMANDS = [
    BotCommand("manage_members", "Manage group members"),
    BotCommand("view_reports", "View group reports"),
]

NON_ADMIN_COMMANDS = [
    BotCommand("request_support", "Request support"),
    BotCommand("view_rules", "View group rules"),
]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    # We only want to handle this inside groups/supergroups
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("Please use this bot inside a group.")
        return

    # Get the user's status in the chat
    member = await context.bot.get_chat_member(chat.id, user.id)
    is_admin = member.status in ['administrator', 'creator']

    # Set commands based on role
    if is_admin:
        commands = ADMIN_COMMANDS
        commands += NON_ADMIN_COMMANDS
        await update.message.reply_text("Hello Admin! Your menu commands have been updated.")
    else:
        commands = NON_ADMIN_COMMANDS
        await update.message.reply_text("Hello! Your menu commands have been updated.")

    # Set commands *for this chat* (scope: this group)
    # This sets commands for all users in this chat, but we want per-user menus
    # Telegram Bot API currently does NOT support per-user command menus in groups
    # So we set commands for the whole group based on the current user role (best effort)
    # Alternatively, you can set commands globally or per user in private chat

    # To simulate context-sensitive menus, we can set commands globally for the bot
    # or per chat. Per user in groups is not supported yet.

    # Here we set commands globally (for all users)
    # To have different menus per user, you would need to handle commands inside handlers.

    await context.bot.set_my_commands(commands=commands)

if __name__ == '__main__':
    import os

    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        print("Please set the TELEGRAM_TOKEN environment variable.")
        exit(1)

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    print("Bot is running...")
    app.run_polling()
