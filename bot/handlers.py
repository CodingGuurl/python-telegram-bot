"""Taxi dispatch bot handlers."""

import logging
import os
from datetime import datetime
from supabase import create_client
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

logger = logging.getLogger(__name__)

GROUPE_CHAUFFEURS_ID = -1003468031320

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

BOT_COMMANDS = [
    ("start", "Demarrer le bot"),
    ("courses", "Voir les courses en attente"),
]

async def set_bot_commands(app: Application):
    await app.bot.set_my_commands(BOT_COMMANDS)

async def error_handler(update, context):
    logger.error("Erreur: %s", context.error)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text(f"ID de ce groupe : {update.effective_chat.id}")
        return
    await update.message.reply_text(
        "🚖 Bot Taxi actif.\n\n"
        "Envoyez les details de la course ici.\n\n"
        "Commandes:\n"
        "/courses - Voir les courses en attente"
    )

async def liste_courses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    result = supabase.table("courses").select("*").eq("statut", "libre").execute()
    if not result.data:
        await update.message.reply_text("✅ Aucune course en attente.")
        return
    msg = "📋 COURSES EN ATTENTE:\n\n"
    for c in result.data:
        msg += f"🚖 Course #{c['id']} — Agent: {c['agent']}\n{c['texte']}\n\n"
    await update.message.reply_text(msg)

async def recevoir_course(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    if context.user_data.get("attente_rendu") or context.user_data.get("attente_probleme"):
        await recevoir_rendu(update, context)
        return

    texte = update.message.text
    agent_nom = update.effective_user.first_name or "Agent"
    agent_id = update.effective_user.id
    now = datetime.now()
    label = f"{now.strftime('%d/%m %Hh%M')} - {agent_nom}"

    result = supabase.table("courses").insert({
        "agent": agent_nom,
        "agent_id": agent_id,
        "texte": texte,
        "statut": "libre"
    }).execute()

    course_id = result.data[0]["id"]

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚗 PRENDRE LA COURSE", callback_data=f"prendre_{course_id}")],
        [InlineKeyboardButton("❌ ANNULER LA COURSE", callback_data=f"annuler_{course_id}")]
    ])
    sent = await context.bot.send_message(
        chat_id=GROUPE_CHAUFFEURS_ID,
        text=f"🚖 COURSE {label}\n\n{texte}\n\n📍 Statut: Libre",
        reply_markup=keyboard
    )

    sent_agent = await update.message.reply_text(
        f"📍 Statut: En attente\n\n{texte}\n\nVous serez notifie quand un chauffeur la prend."
    )

    supabase.table("courses").update({
        "agent_msg_id": sent.message_id,
        "agent_notif_msg_id": sent_agent.message_id
    }).eq("id", course_id).execute()

async def maj_groupe(context, course, statut_texte, keyboard=None):
    msg_id = course.get("agent_msg_id")
    if not msg_id:
        return
    try:
        await context.bot.edit_message_text(
            chat_id=GROUPE_CHAUFFEURS_ID,
            message_id=msg_id,
            text=f"🚖 COURSE\n\n{course['texte']}\n\n📍 Statut: {statut_texte}",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.warning(f"Impossible d'editer le message groupe: {e}")

async def maj_notif_agent(context, course, statut_texte):
    agent_id = course.get("agent_id")
    msg_id = course.get("agent_notif_msg_id")
    if not agent_id or not msg_id:
        return
    try:
        await context.bot.edit_message_text(
            chat_id=agent_id,
            message_id=msg_id,
            text=f"📍 Statut: {statut_texte}\n\n{course['texte']}"
        )
    except Exception as e:
        logger.warning(f"Impossible d'editer le message agent: {e}")

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
        await query.answer("Course deja prise ou annulee!", show_alert=True)
        return

    supabase.table("courses").update({
        "statut": "prise",
        "chauffeur": chauffeur,
        "chauffeur_id": chauffeur_id
    }).eq("id", course_id).execute()
    course["chauffeur"] = chauffeur

    await query.edit_message_text(
        f"🚖 COURSE\n\n{course['texte']}\n\n📍 Statut: Prise par {chauffeur}"
    )

    await maj_notif_agent(context, course, f"Prise par {chauffeur}")

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚗 En route", callback_data=f"enroute_{course_id}")]
    ])
    sent = await context.bot.send_message(
        chat_id=chauffeur_id,
        text=f"📍 Statut: Assignee\n\n{course['texte']}\n\nCliquez pour mettre a jour 👇",
        reply_markup=keyboard
    )

    supabase.table("courses").update({
        "chauffeur_msg_id": sent.message_id
    }).eq("id", course_id).execute()

async def suivi_enroute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    course_id = int(query.data.split("_")[1])

    result = supabase.table("courses").select("*").eq("id", course_id).execute()
    if not result.data:
        return
    course = result.data[0]

    supabase.table("courses").update({"statut": "en_route"}).eq("id", course_id).execute()

    await maj_notif_agent(context, course, f"En route ({course['chauffeur']})")
    await maj_groupe(context, course, f"En route ({course['chauffeur']})")

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Course en cours", callback_data=f"encours_{course_id}")]
    ])
    await query.edit_message_text(
        f"📍 Statut: En route\n\n{course['texte']}\n\nCliquez pour mettre a jour 👇",
        reply_markup=keyboard
    )

async def suivi_encours(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    course_id = int(query.data.split("_")[1])

    result = supabase.table("courses").select("*").eq("id", course_id).execute()
    if not result.data:
        return
    course = result.data[0]

    supabase.table("courses").update({"statut": "en_cours"}).eq("id", course_id).execute()

    await maj_notif_agent(context, course, f"En cours ({course['chauffeur']})")
    await maj_groupe(context, course, f"En cours ({course['chauffeur']})")

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Course effectuee", callback_data=f"done_{course_id}")],
        [InlineKeyboardButton("⚠️ Signaler un probleme", callback_data=f"probleme_{course_id}")]
    ])
    await query.edit_message_text(
        f"📍 Statut: En cours\n\n{course['texte']}\n\nCliquez quand la course est terminee 👇",
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
        await maj_groupe(context, course, f"✅ Terminee ({course['chauffeur']})")
        await query.edit_message_text(
            f"📍 Statut: Terminee\n\n{course['texte']}\n\n"
            f"Merci d'envoyer votre compte rendu:\n"
            f"- Une photo de la confirmation de paiement\n"
            f"- Ou un message avec vos remarques"
        )
        context.user_data["attente_rendu"] = course_id
        context.user_data["agent_id"] = course.get("agent_id")

    elif action == "probleme":
        supabase.table("courses").update({"statut": "probleme"}).eq("id", course_id).execute()
        await maj_notif_agent(context, course, f"⚠️ Probleme signale ({course['chauffeur']})")
        await maj_groupe(context, course, f"⚠️ Probleme ({course['chauffeur']})")
        await query.edit_message_text(
            f"📍 Statut: Probleme\n\n{course['texte']}\n\n"
            f"Decrivez le probleme rencontre:"
        )
        context.user_data["attente_probleme"] = course_id
        context.user_data["agent_id"] = course.get("agent_id")

async def annuler_course(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    course_id = int(query.data.split("_")[1])

    result = supabase.table("courses").select("*").eq("id", course_id).execute()
    if not result.data:
        await query.answer("Course introuvable.", show_alert=True)
        return

    course = result.data[0]
    if course["statut"] != "libre":
        await query.answer("Cette course ne peut plus etre annulee!", show_alert=True)
        return

    supabase.table("courses").update({"statut": "annulee"}).eq("id", course_id).execute()

    await query.edit_message_text(
        f"❌ COURSE ANNULEE\n\n{course['texte']}"
    )

    await maj_notif_agent(context, course, "❌ Annulee")

async def recevoir_rendu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    agent_id = context.user_data.get("agent_id")
    chauffeur = update.effective_user.first_name or "Chauffeur"

    if "attente_rendu" in context.user_data:
        course_id = context.user_data.pop("attente_rendu")
        context.user_data.pop("agent_id", None)

        if update.message.photo:
            caption = update.message.caption or "Aucune remarque"
            await update.message.reply_text("✅ Compte rendu envoye a l'agent. Merci et bonne route!")
            if agent_id:
                await context.bot.send_photo(
                    chat_id=agent_id,
                    photo=update.message.photo[-1].file_id,
                    caption=f"✅ Course #{course_id} terminee par {chauffeur}\nRemarque: {caption}"
                )
        else:
            texte = update.message.text or ""
            await update.message.reply_text("✅ Compte rendu envoye a l'agent. Merci et bonne route!")
            if agent_id:
                await context.bot.send_message(
                    chat_id=agent_id,
                    text=f"✅ Course #{course_id} terminee par {chauffeur}\nCompte rendu: {texte}"
                )

    elif "attente_probleme" in context.user_data:
        course_id = context.user_data.pop("attente_probleme")
        context.user_data.pop("agent_id", None)
        texte = update.message.text or ""
        await update.message.reply_text("⚠️ Probleme signale a l'agent. Il vous contactera.")
        if agent_id:
            await context.bot.send_message(
                chat_id=agent_id,
                text=f"⚠️ Probleme sur course #{course_id} signale par {chauffeur}:\n{texte}"
            )

def register_handlers(app: Application):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("courses", liste_courses))
    app.add_handler(CallbackQueryHandler(prendre_course, pattern=r"^prendre_"))
    app.add_handler(CallbackQueryHandler(annuler_course, pattern=r"^annuler_"))
    app.add_handler(CallbackQueryHandler(suivi_enroute, pattern=r"^enroute_"))
    app.add_handler(CallbackQueryHandler(suivi_encours, pattern=r"^encours_"))
    app.add_handler(CallbackQueryHandler(valider_course, pattern=r"^done_|^probleme_"))
    app.add_handler(MessageHandler(filters.PHOTO, recevoir_rendu))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, recevoir_course))
