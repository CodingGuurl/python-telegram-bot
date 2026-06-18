"""DispatchPro - Generic task dispatch bot handlers."""

import logging
import os
from datetime import datetime, timedelta, timezone
from supabase import create_client
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

logger = logging.getLogger(__name__)

GROUPE_AGENTS_TERRAIN_ID = int(os.getenv("GROUPE_TERRAIN_ID", "0"))
NOM_ENTREPRISE = os.getenv("NOM_ENTREPRISE", "Dispatch")
NOM_UNITE = os.getenv("NOM_UNITE", "Tache")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
RELANCE_MINUTES = int(os.getenv("RELANCE_MINUTES", "30"))

STEPS_RAW = os.getenv("STEPS", "En route,En cours")
STEPS = [s.strip() for s in STEPS_RAW.split(",") if s.strip()]

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

BOT_COMMANDS = [
    ("start", "Demarrer le bot"),
    ("taches", "Voir les taches en attente"),
    ("mestaches", "Voir mes taches en cours"),
]

async def set_bot_commands(app: Application):
    await app.bot.set_my_commands(BOT_COMMANDS)

async def error_handler(update, context):
    logger.error("Erreur: %s", context.error)

def get_utilisateur(user_id):
    result = supabase.table("utilisateurs").select("*").eq("user_id", user_id).execute()
    if result.data:
        return result.data[0]
    return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text(f"ID de ce groupe : {update.effective_chat.id}")
        return

    user_id = update.effective_user.id
    nom = update.effective_user.first_name or "Utilisateur"

    utilisateur = get_utilisateur(user_id)

    if utilisateur and utilisateur["statut"] == "approuve":
        await update.message.reply_text(
            f"🤖 Bot {NOM_ENTREPRISE} actif.\n\n"
            f"Envoyez les details de la {NOM_UNITE.lower()} ici.\n\n"
            f"Commandes:\n"
            f"/taches - Voir les taches en attente\n"
            f"/mestaches - Voir mes taches en cours"
        )
        return

    if utilisateur and utilisateur["statut"] == "en_attente":
        await update.message.reply_text(
            "⏳ Votre demande est en cours de validation. Vous serez notifie."
        )
        return

    if utilisateur and utilisateur["statut"] == "refuse":
        await update.message.reply_text(
            "❌ Votre demande a ete refusee. Contactez l'administrateur."
        )
        return

    supabase.table("utilisateurs").insert({
        "user_id": user_id,
        "nom": nom,
        "statut": "en_attente",
        "role": None
    }).execute()

    await update.message.reply_text(
        "⏳ Bienvenue! Votre demande d'acces a ete envoyee a l'administrateur.\n\n"
        "Vous serez notifie une fois valide."
    )

    if ADMIN_ID:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Approuver - Agent", callback_data=f"approve_agent_{user_id}")],
            [InlineKeyboardButton("✅ Approuver - Executant", callback_data=f"approve_executant_{user_id}")],
            [InlineKeyboardButton("❌ Refuser", callback_data=f"refuse_{user_id}")]
        ])
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🆕 Nouvelle demande d'acces\n\nNom: {nom}\nID: {user_id}\n\nChoisir un role:",
            reply_markup=keyboard
        )

async def gerer_validation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        await query.answer("Vous n'etes pas autorise.", show_alert=True)
        return

    data = query.data

    if data.startswith("refuse_"):
        user_id = int(data.split("_")[1])
        supabase.table("utilisateurs").update({"statut": "refuse"}).eq("user_id", user_id).execute()
        await query.edit_message_text(f"❌ Demande refusee pour l'utilisateur {user_id}")
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ Votre demande a ete refusee."
            )
        except Exception:
            pass
        return

    if data.startswith("approve_agent_"):
        user_id = int(data.split("_")[2])
        role = "agent"
    elif data.startswith("approve_executant_"):
        user_id = int(data.split("_")[2])
        role = "executant"
    else:
        return

    supabase.table("utilisateurs").update({"statut": "approuve", "role": role}).eq("user_id", user_id).execute()
    await query.edit_message_text(f"✅ Utilisateur {user_id} approuve comme {role}")

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ Votre demande a ete approuvee en tant que {role}!\n\nVous pouvez maintenant utiliser le bot. Tapez /start"
        )
    except Exception:
        pass

async def liste_taches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    utilisateur = get_utilisateur(update.effective_user.id)
    if not utilisateur or utilisateur["statut"] != "approuve":
        await update.message.reply_text("⏳ Vous n'etes pas encore autorise. Tapez /start")
        return

    result = supabase.table("tasks").select("*").eq("statut", "libre").execute()
    if not result.data:
        await update.message.reply_text("✅ Aucune tache en attente.")
        return
    msg = "📋 TACHES EN ATTENTE:\n\n"
    for t in result.data:
        msg += f"🔹 {NOM_UNITE} #{t['id']} — Agent: {t['agent']}\n{t['texte']}\n\n"
    await update.message.reply_text(msg)

async def mes_taches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    user_id = update.effective_user.id
    utilisateur = get_utilisateur(user_id)
    if not utilisateur or utilisateur["statut"] != "approuve":
        await update.message.reply_text("⏳ Vous n'etes pas encore autorise. Tapez /start")
        return

    if utilisateur["role"] == "executant":
        # Toutes les taches prises par cet executant, pas encore terminees
        statuts_actifs = ["prise"] + [f"etape_{i}" for i in range(len(STEPS))]
        result = supabase.table("tasks").select("*").eq("chauffeur_id", user_id).in_("statut", statuts_actifs).execute()

        if not result.data:
            await update.message.reply_text("✅ Vous n'avez aucune tache en cours.")
            return

        msg = f"📋 VOS {NOM_UNITE.upper()}S EN COURS:\n\n"
        for t in result.data:
            etape_idx = t.get("etape_index", -1)
            if etape_idx >= 0 and etape_idx < len(STEPS):
                statut_label = STEPS[etape_idx]
            else:
                statut_label = "Assignee"
            msg += f"🔹 {NOM_UNITE} #{t['id']} — {statut_label}\n{t['texte']}\n\n"
        await update.message.reply_text(msg)

    elif utilisateur["role"] == "agent":
        # Toutes les taches postees par cet agent, pas encore terminees/annulees
        statuts_actifs = ["libre", "prise"] + [f"etape_{i}" for i in range(len(STEPS))]
        result = supabase.table("tasks").select("*").eq("agent_id", user_id).in_("statut", statuts_actifs).execute()

        if not result.data:
            await update.message.reply_text("✅ Vous n'avez aucune tache active.")
            return

        msg = f"📋 VOS {NOM_UNITE.upper()}S ACTIVES:\n\n"
        for t in result.data:
            statut = t.get("statut", "libre")
            if statut == "libre":
                statut_label = "En attente"
            elif statut == "prise":
                statut_label = f"Prise par {t.get('chauffeur', '?')}"
            elif statut.startswith("etape_"):
                idx = int(statut.split("_")[1])
                statut_label = f"{STEPS[idx]} ({t.get('chauffeur', '?')})"
            else:
                statut_label = statut
            msg += f"🔹 {NOM_UNITE} #{t['id']} — {statut_label}\n{t['texte']}\n\n"
        await update.message.reply_text(msg)

async def recevoir_tache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    if context.user_data.get("attente_rendu") or context.user_data.get("attente_probleme"):
        await recevoir_rendu(update, context)
        return

    utilisateur = get_utilisateur(update.effective_user.id)
    if not utilisateur or utilisateur["statut"] != "approuve":
        await update.message.reply_text("⏳ Vous n'etes pas encore autorise a utiliser ce bot. Tapez /start")
        return

    if utilisateur["role"] != "agent":
        await update.message.reply_text("❌ Seuls les agents peuvent publier des taches.")
        return

    texte = update.message.text
    agent_nom = update.effective_user.first_name or "Agent"
    agent_id = update.effective_user.id
    now = datetime.now()
    label = f"{now.strftime('%d/%m %Hh%M')} - {agent_nom}"

    result = supabase.table("tasks").insert({
        "agent": agent_nom,
        "agent_id": agent_id,
        "texte": texte,
        "statut": "libre",
        "etape_index": -1,
        "relance_envoyee": False
    }).execute()

    task_id = result.data[0]["id"]

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ PRENDRE LA {NOM_UNITE.upper()}", callback_data=f"prendre_{task_id}")],
        [InlineKeyboardButton("❌ ANNULER", callback_data=f"annuler_{task_id}")]
    ])
    sent = await context.bot.send_message(
        chat_id=GROUPE_AGENTS_TERRAIN_ID,
        text=f"🔹 {NOM_UNITE.upper()} {label}\n\n{texte}\n\n📍 Statut: Libre",
        reply_markup=keyboard
    )

    sent_agent = await update.message.reply_text(
        f"📍 Statut: En attente\n\n{texte}\n\nVous serez notifie quand quelqu'un la prend."
    )

    supabase.table("tasks").update({
        "agent_msg_id": sent.message_id,
        "agent_notif_msg_id": sent_agent.message_id
    }).eq("id", task_id).execute()

async def maj_groupe(context, task, statut_texte, keyboard=None):
    msg_id = task.get("agent_msg_id")
    if not msg_id:
        return
    try:
        await context.bot.edit_message_text(
            chat_id=GROUPE_AGENTS_TERRAIN_ID,
            message_id=msg_id,
            text=f"🔹 {NOM_UNITE.upper()}\n\n{task['texte']}\n\n📍 Statut: {statut_texte}",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.warning(f"Impossible d'editer le message groupe: {e}")

async def maj_notif_agent(context, task, statut_texte):
    agent_id = task.get("agent_id")
    msg_id = task.get("agent_notif_msg_id")
    if not agent_id or not msg_id:
        return
    try:
        await context.bot.edit_message_text(
            chat_id=agent_id,
            message_id=msg_id,
            text=f"📍 Statut: {statut_texte}\n\n{task['texte']}"
        )
    except Exception as e:
        logger.warning(f"Impossible d'editer le message agent: {e}")

def get_keyboard_pour_etape(task_id, etape_index):
    if etape_index + 1 < len(STEPS):
        prochaine_etape = STEPS[etape_index + 1]
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(f"▶️ {prochaine_etape}", callback_data=f"etape_{task_id}_{etape_index + 1}")]
        ])
    else:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Terminee", callback_data=f"done_{task_id}")],
            [InlineKeyboardButton("⚠️ Probleme", callback_data=f"probleme_{task_id}")]
        ])

async def prendre_tache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    task_id = int(query.data.split("_")[1])
    executant = query.from_user.first_name or "Agent"
    executant_id = query.from_user.id

    utilisateur = get_utilisateur(executant_id)
    if not utilisateur or utilisateur["statut"] != "approuve" or utilisateur["role"] != "executant":
        await query.answer("Vous n'etes pas autorise a prendre des taches. Tapez /start en prive avec le bot.", show_alert=True)
        return

    result = supabase.table("tasks").select("*").eq("id", task_id).execute()
    if not result.data:
        await query.answer("Introuvable.", show_alert=True)
        return

    task = result.data[0]
    if task["statut"] != "libre":
        await query.answer("Deja prise ou annulee!", show_alert=True)
        return

    supabase.table("tasks").update({
        "statut": "prise",
        "chauffeur": executant,
        "chauffeur_id": executant_id,
        "etape_index": -1
    }).eq("id", task_id).execute()
    task["chauffeur"] = executant

    await query.edit_message_text(
        f"🔹 {NOM_UNITE.upper()}\n\n{task['texte']}\n\n📍 Statut: Prise par {executant}"
    )

    await maj_notif_agent(context, task, f"Prise par {executant}")

    keyboard = get_keyboard_pour_etape(task_id, -1)
    sent = await context.bot.send_message(
        chat_id=executant_id,
        text=f"📍 Statut: Assignee\n\n{task['texte']}\n\nCliquez pour mettre a jour 👇",
        reply_markup=keyboard
    )

    supabase.table("tasks").update({
        "chauffeur_msg_id": sent.message_id
    }).eq("id", task_id).execute()

async def avancer_etape(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    task_id = int(parts[1])
    nouvelle_etape_index = int(parts[2])

    result = supabase.table("tasks").select("*").eq("id", task_id).execute()
    if not result.data:
        return
    task = result.data[0]

    nom_etape = STEPS[nouvelle_etape_index]

    supabase.table("tasks").update({
        "etape_index": nouvelle_etape_index,
        "statut": f"etape_{nouvelle_etape_index}"
    }).eq("id", task_id).execute()

    statut_complet = f"{nom_etape} ({task['chauffeur']})"
    await maj_notif_agent(context, task, statut_complet)
    await maj_groupe(context, task, statut_complet)

    keyboard = get_keyboard_pour_etape(task_id, nouvelle_etape_index)
    await query.edit_message_text(
        f"📍 Statut: {nom_etape}\n\n{task['texte']}\n\nCliquez pour mettre a jour 👇",
        reply_markup=keyboard
    )

async def valider_tache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data.split("_")[0]
    task_id = int(query.data.split("_")[1])

    result = supabase.table("tasks").select("*").eq("id", task_id).execute()
    if not result.data:
        return
    task = result.data[0]

    if action == "done":
        supabase.table("tasks").update({"statut": "terminee"}).eq("id", task_id).execute()
        await maj_groupe(context, task, f"✅ Terminee ({task['chauffeur']})")
        await query.edit_message_text(
            f"📍 Statut: Terminee\n\n{task['texte']}\n\n"
            f"Merci d'envoyer votre compte rendu:\n"
            f"- Une photo si necessaire\n"
            f"- Ou un message avec vos remarques"
        )
        context.user_data["attente_rendu"] = task_id
        context.user_data["agent_id"] = task.get("agent_id")

    elif action == "probleme":
        supabase.table("tasks").update({"statut": "probleme"}).eq("id", task_id).execute()
        await maj_notif_agent(context, task, f"⚠️ Probleme signale ({task['chauffeur']})")
        await maj_groupe(context, task, f"⚠️ Probleme ({task['chauffeur']})")
        await query.edit_message_text(
            f"📍 Statut: Probleme\n\n{task['texte']}\n\n"
            f"Decrivez le probleme rencontre:"
        )
        context.user_data["attente_probleme"] = task_id
        context.user_data["agent_id"] = task.get("agent_id")

async def annuler_tache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    task_id = int(query.data.split("_")[1])

    result = supabase.table("tasks").select("*").eq("id", task_id).execute()
    if not result.data:
        await query.answer("Introuvable.", show_alert=True)
        return

    task = result.data[0]
    if task["statut"] != "libre":
        await query.answer("Ne peut plus etre annulee!", show_alert=True)
        return

    supabase.table("tasks").update({"statut": "annulee"}).eq("id", task_id).execute()

    await query.edit_message_text(f"❌ ANNULEE\n\n{task['texte']}")
    await maj_notif_agent(context, task, "❌ Annulee")

async def recevoir_rendu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    agent_id = context.user_data.get("agent_id")
    executant = update.effective_user.first_name or "Agent"

    if "attente_rendu" in context.user_data:
        task_id = context.user_data.pop("attente_rendu")
        context.user_data.pop("agent_id", None)

        if update.message.photo:
            caption = update.message.caption or "Aucune remarque"
            await update.message.reply_text("✅ Compte rendu envoye. Merci!")
            if agent_id:
                await context.bot.send_photo(
                    chat_id=agent_id,
                    photo=update.message.photo[-1].file_id,
                    caption=f"✅ {NOM_UNITE} #{task_id} terminee par {executant}\nRemarque: {caption}"
                )
        else:
            texte = update.message.text or ""
            await update.message.reply_text("✅ Compte rendu envoye. Merci!")
            if agent_id:
                await context.bot.send_message(
                    chat_id=agent_id,
                    text=f"✅ {NOM_UNITE} #{task_id} terminee par {executant}\nCompte rendu: {texte}"
                )

    elif "attente_probleme" in context.user_data:
        task_id = context.user_data.pop("attente_probleme")
        context.user_data.pop("agent_id", None)
        texte = update.message.text or ""
        await update.message.reply_text("⚠️ Probleme signale. Vous serez contacte.")
        if agent_id:
            await context.bot.send_message(
                chat_id=agent_id,
                text=f"⚠️ Probleme sur {NOM_UNITE} #{task_id} signale par {executant}:\n{texte}"
            )

async def verifier_relances(context: ContextTypes.DEFAULT_TYPE):
    seuil = datetime.now(timezone.utc) - timedelta(minutes=RELANCE_MINUTES)

    result = supabase.table("tasks").select("*").eq("statut", "libre").eq("relance_envoyee", False).execute()

    for task in result.data:
        created_at_str = task.get("created_at")
        if not created_at_str:
            continue
        try:
            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        except Exception:
            continue

        if created_at < seuil:
            agent_id = task.get("agent_id")
            if agent_id:
                try:
                    await context.bot.send_message(
                        chat_id=agent_id,
                        text=(
                            f"⏰ Personne n'a encore pris votre {NOM_UNITE.lower()} "
                            f"depuis plus de {RELANCE_MINUTES} minutes.\n\n{task['texte']}"
                        )
                    )
                except Exception as e:
                    logger.warning(f"Impossible de notifier l'agent {agent_id}: {e}")

            supabase.table("tasks").update({"relance_envoyee": True}).eq("id", task["id"]).execute()

def register_handlers(app: Application):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("taches", liste_taches))
    app.add_handler(CommandHandler("mestaches", mes_taches))
    app.add_handler(CallbackQueryHandler(gerer_validation, pattern=r"^approve_|^refuse_"))
    app.add_handler(CallbackQueryHandler(prendre_tache, pattern=r"^prendre_"))
    app.add_handler(CallbackQueryHandler(annuler_tache, pattern=r"^annuler_"))
    app.add_handler(CallbackQueryHandler(avancer_etape, pattern=r"^etape_"))
    app.add_handler(CallbackQueryHandler(valider_tache, pattern=r"^done_|^probleme_"))
    app.add_handler(MessageHandler(filters.PHOTO, recevoir_rendu))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, recevoir_tache))

    if app.job_queue:
        app.job_queue.run_repeating(verifier_relances, interval=300, first=60)
