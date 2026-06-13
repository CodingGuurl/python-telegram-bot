"""Taxi dispatch bot handlers."""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

logger = logging.getLogger(__name__)

# ID du groupe chauffeurs — à remplacer après avoir trouvé l'ID
GROUPE_CHAUFFEURS_ID = -1001234567890

# Stockage temporaire des courses (en mémoire)
courses = {}
course_counter = [0]

BOT_COMMANDS = [
    ("start", "Démarrer le bot"),
    ("help", "Aide"),
]

async def set_bot_commands(app: Application):
    await app.bot.set_my_commands(BOT_COMMANDS)

async def error_handler(update, context):
    logger.error("Erreur: %s", context.error)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    await update.message.reply_text(
        "🚖 *Bot Taxi Dispatch*\n\n"
        "Envoyez les détails de la course directement ici.\n\n"
        "Exemple :\n"
        "IMMEDIAT F\n"
        "25 Rue de Paris, 75011\n"
        "Gare du Nord\n"
        "Mr Dupont\n"
        "06 12 34 56 78\n"
        "39€ / 7KM",
        parse_mode="Markdown"
    )

async def recevoir_course(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Ignorer les messages dans les groupes
    if update.effective_chat.type != "private":
        return

    texte = update.message.text
    agent_nom = update.effective_user.first_name or "Agent"

    # Créer un ID unique pour la course
    course_counter[0] += 1
    course_id = course_counter[0]

    # Sauvegarder la course
    courses[course_id] = {
        "texte": texte,
        "agent": agent_nom,
        "statut": "libre",
        "chauffeur": None,
    }

    # Bouton pour prendre la course
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚗 PRENDRE LA COURSE", callback_data=f"prendre_{course_id}")]
    ])

    # Message formaté pour les chauffeurs
    message_chauffeurs = (
        f"🚖 *NOUVELLE COURSE #{course_id}*\n"
        f"👩‍💼 Agent : {agent_nom}\n\n"
        f"{texte}\n\n"
        f"👇 Cliquez pour prendre la course"
    )

    # Publier dans le groupe chauffeurs
    await context.bot.send_message(
        chat_id=GROUPE_CHAUFFEURS_ID,
        text=message_chauffeurs,
        parse_mode="Markdown",
        reply_markup=keyboard
    )

    # Confirmer à l'agent
    await update.message.reply_text(
        f"✅ Course #{course_id} publiée dans le groupe chauffeurs !"
    )

async def prendre_course(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    course_id = int(data.split("_")[1])
    chauffeur = query.from_user.first_name or "Chauffeur"
    chauffeur_id = query.from_user.id

    if course_id not in courses:
        await query.edit_message_text("❌ Course introuvable.")
        return

    course = courses[course_id]

    if course["statut"] != "libre":
        await query.answer("❌ Cette course est déjà prise !", show_alert=True)
        return

    # Verrouiller la course
    course["statut"] = "prise"
    course["chauffeur"] = chauffeur
    course["chauffeur_id"] = chauffeur_id

    # Mettre à jour le message dans le groupe
    await query.edit_message_text(
        f"🚖 *COURSE #{course_id} — PRISE*\n\n"
        f"{course['texte']}\n\n"
        f"✅ Prise par : {chauffeur}",
        parse_mode="Markdown"
    )

    # Envoyer confirmation au chauffeur en privé
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Course effectuée", callback_data=f"done_{course_id}")],
        [InlineKeyboardButton("⚠️ Problème", callback_data=f"probleme_{course_id}")]
    ])

    await context.bot.send_message(
        chat_id=chauffeur_id,
        text=(
            f"✅ *Course #{course_id} confirmée !*\n\n"
            f"{course['texte']}\n\n"
            f"Merci de confirmer quand la course est terminée 👇"
        ),
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def valider_course(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    action = data.split("_")[0]
    course_id = int(data.split("_")[1])

    if course_id not in courses:
        await query.edit_message_text("❌ Course introuvable.")
        return

    course = courses[course_id]

    if action == "done":
        course["statut"] = "terminée"
        await query.edit_message_text(
            f"✅ *Course #{course_id} terminée et validée !*\n\n"
            f"{course['texte']}",
            parse_mode="Markdown"
        )
    elif action == "probleme":
        course["statut"] = "problème"
        await query.edit_message_text(
            f"⚠️ *Problème signalé — Course #{course_id}*\n\n"
            f"{course['texte']}\n\n"
            f"Un agent va vous contacter.",
            parse_mode="Markdown"
        )

def register_handlers(app: Application):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, recevoir_course))
    app.add_handler(CallbackQueryHandler(prendre_course, pattern=r"^prendre_"))
    app.add_handler(CallbackQueryHandler(valider_course, pattern=r"^done_|^probleme_"))
