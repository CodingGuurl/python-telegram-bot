"""Taxi dispatch bot handlers."""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

logger = logging.getLogger(__name__)

courses = {}
course_counter = [0]

BOT_COMMANDS = [("start", "Demarrer le bot")]

async def set_bot_commands(app: Application):
    await app.bot.set_my_commands(BOT_COMMANDS)

async def error_handler(update, context):
    logger.error("Erreur: %s", context.error)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text(f"ID de ce groupe : {update.effective_chat.id}")
        return
    await update.message.reply_text("🚖 Bot Taxi actif.\n\nEnvoyez les details de la course ici.")

async def recevoir_course(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    texte = update.message.text
    agent_nom = update.effective_user.first_name or "Agent"
    course_counter[0] += 1
    course_id = course_counter[0]
    courses[course_id] = {"texte": texte, "agent": agent_nom, "statut": "libre", "chauffeur": None}
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🚗 PRENDRE LA COURSE", callback_data=f"prendre_{course_id}")]])
    await update.message.reply_text(f"✅ Course #{course_id} publiee!")

async def prendre_course(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    course_id = int(query.data.split("_")[1])
    chauffeur = query.from_user.first_name or "Chauffeur"
    chauffeur_id = query.from_user.id
    if course_id not in courses:
        await query.answer("Course introuvable.", show_alert=True)
        return
    course = courses[course_id]
    if course["statut"] != "libre":
        await query.answer("Course deja prise!", show_alert=True)
        return
    course["statut"] = "prise"
    course["chauffeur"] = chauffeur
    course["chauffeur_id"] = chauffeur_id
    await query.edit_message_text(f"🚖 COURSE #{course_id} PRISE par {chauffeur}\n\n{course['texte']}")
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Course effectuee", callback_data=f"done_{course_id}")],
        [InlineKeyboardButton("⚠️ Probleme", callback_data=f"probleme_{course_id}")]
    ])
    await context.bot.send_message(chat_id=chauffeur_id, text=f"✅ Course #{course_id} confirmee!\n\n{course['texte']}\n\nConfirmez quand termine:", reply_markup=keyboard)

async def valider_course(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data.split("_")[0]
    course_id = int(query.data.split("_")[1])
    if course_id not in courses:
        return
    course = courses[course_id]
    if action == "done":
        course["statut"] = "terminee"
        await query.edit_message_text(f"✅ Course #{course_id} terminee!\n\n{course['texte']}")
    elif action == "probleme":
        course["statut"] = "probleme"
        await query.edit_message_text(f"⚠️ Probleme - Course #{course_id}\n\n{course['texte']}")

def register_handlers(app: Application):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, recevoir_course))
    app.add_handler(CallbackQueryHandler(prendre_course, pattern=r"^prendre_"))
    app.add_handler(CallbackQueryHandler(val
