"""Taxi dispatch bot handlers."""

import logging
import os
from supabase import create_client
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

logger = logging.getLogger(__name__)

GROUPE_CHAUFFEURS_ID = -1003468031320

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

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

    result = supabase.table("courses").insert({
        "agent": agent_nom,
        "texte": texte,
        "statut": "libre"
    }).execute()

    course_id = result.data[0]["id"]

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚗 PRENDRE LA COURSE", callback_data=f"prendre_{course_id}")]
    ])
    await context.bot.send_message(
        chat_id=GROUPE_CHAUFFEURS_ID,
        text=f"🚖 NOUVELLE COURSE #{course_id}\n👩‍💼 Agent: {agent_nom}\n\n{texte}",
        reply_markup=keyboard
    )
    await update.message.reply_text(f"✅ Course #{course_id} publiee dans le groupe chauffeurs!")

async def prendre_course(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    course_id = int(query.data.split("_")[1])
    chauffeur = query.from_user.first_name or "Chauffeur"
    chauffeur_id = query.from_user.id

    result = supabase.table("courses").select("*").eq("id", course_id).execute()
    if not result.data:
        await query.answer("Course introuvable.", show_alert=True)
        return

    course = result.data[0]
    if course["statut"] != "libre":
        await query.answer("Course deja prise!", show_alert=True)
        return

    supabase.table("courses").update({
        "statut": "prise",
        "chauffeur": chauffeur,
        "chauffeur_id": chauffeur_id
    }).eq("id", course_id).execute()

    await query.edit_message_text(
        f"🚖 COURSE #{course_id} PRISE par {chauffeur}\n\n{course['texte']}"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Course effectuee", callback_data=f"done_{course_id}")],
        [InlineKeyboardButton("⚠️ Probleme", callback_data=f"probleme_{course_id}")]
    ])
    await context.bot.send_message(
        chat_id=chauffeur_id,
        text=f"✅ Course #{course_id} confirmee!\n\n{course['texte']}\n\nConfirmez quand termine:",
        reply_markup=keyboard
    )

async def valider_course(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data.split("_")[0]
    course_id = int(query.data.split("_")[1])

    result = supabase.table("courses").select("*").eq("id", course_id).execute()
    if not result.data:
        return
    course = result.data[0]

    if action == "done":
        supabase.table("courses").update({"statut": "terminee"}).eq("id", course_id).execute()
        await query.edit_message_text(
            f"✅ Course #{course_id} terminee!\n\n{course['texte']}"
        )
    elif action == "probleme":
        supabase.table("courses").update({"statut": "probleme"}).eq("id", course_id).execute()
        await query.edit_message_text(
            f"⚠️ Probleme - Course #{course_id}\n\n{course['texte']}"
        )

def register_handlers(app: Application):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, recevoir_course))
    app.add_handler(CallbackQueryHandler(prendre_course, pattern=r"^prendre_"))
    app.add_handler(CallbackQueryHandler(valider_course, pattern=r"^done_|^probleme_"))
