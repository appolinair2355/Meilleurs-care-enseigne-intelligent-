# handlers.py

import logging
import time
import json
from collections import defaultdict
from typing import Dict, Any, Optional
import requests

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Importation Robuste
try:
    from card_predictor import CardPredictor
except ImportError:
    logger.error("❌ IMPOSSIBLE D'IMPORTER CARDPREDICTOR")
    CardPredictor = None

user_message_counts = defaultdict(list)

# --- MESSAGES UTILISATEUR NETTOYÉS ---
WELCOME_MESSAGE = """
👋 **BIENVENUE SUR LE BOT ENSEIGNE !** ♠️♥️♦️♣️

Je prédis la prochaine Enseigne (Couleur) en utilisant :
1. Des règles statiques (ex: 10♦️ → ♠️)
2. Une intelligence artificielle (Mode INTER)

🎯 **COMMANDES:**
• `/start` - Accueil
• `/stat` - État du bot
• `/inter` - Gérer le Mode Intelligent
• `/config` - Configurer les canaux
• `/deploy` - Télécharger le package Render.com
"""

HELP_MESSAGE = """
🤖 **AIDE COMMANDE /INTER**

• `/inter status` : Voir les règles apprises (Top 3).
• `/inter activate` : Forcer l'activation de l'IA.
• `/inter default` : Revenir aux règles statiques.
"""

class TelegramHandlers:
    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

        if CardPredictor:
            # On passe la fonction d'envoi pour les notifs INTER
            self.card_predictor = CardPredictor(telegram_message_sender=self.send_message)
        else:
            self.card_predictor = None

    # --- MESSAGERIE ---
    def _check_rate_limit(self, user_id):
        now = time.time()
        user_message_counts[user_id] = [t for t in user_message_counts[user_id] if now - t < 60]
        user_message_counts[user_id].append(now)
        return len(user_message_counts[user_id]) <= 30

    def send_message(self, chat_id: int, text: str, parse_mode='Markdown', message_id: Optional[int] = None, edit=False, reply_markup: Optional[Dict] = None) -> Optional[int]:
        if not chat_id or not text: return None

        method = 'editMessageText' if (message_id or edit) else 'sendMessage'
        payload = {'chat_id': chat_id, 'text': text, 'parse_mode': parse_mode}

        if message_id: payload['message_id'] = message_id
        if reply_markup: 
            payload['reply_markup'] = json.dumps(reply_markup) if isinstance(reply_markup, dict) else reply_markup

        try:
            r = requests.post(f"{self.base_url}/{method}", json=payload, timeout=10)
            if r.status_code == 200:
                return r.json().get('result', {}).get('message_id')
            else:
                logger.error(f"Erreur Telegram {r.status_code}: {r.text}")
        except Exception as e:
            logger.error(f"Exception envoi message: {e}")
        return None

    # --- GESTION COMMANDE /deploy ---
    def _handle_command_deploy(self, chat_id: int):
        import zipfile
        import os
        import shutil

        try:
            self.send_message(chat_id, "📦 **Génération du package de déploiement Render.com (colu200.zip)...**")

            # Créer le dossier de déploiement dans le répertoire courant
            deploy_dir = 'telegram-bot-deploy-temp'
            if os.path.exists(deploy_dir):
                shutil.rmtree(deploy_dir)
            os.makedirs(deploy_dir)

            # Fichiers à inclure
            files_to_copy = [
                'main.py', 'bot.py', 'handlers.py', 'card_predictor.py', 
                'config.py', 'requirements.txt', 'render.yaml'
            ]

            # Copier les fichiers
            for filename in files_to_copy:
                if os.path.exists(filename):
                    shutil.copy(filename, deploy_dir)

            # Modifier config.py pour le port 10000
            config_path = os.path.join(deploy_dir, 'config.py')
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    content = f.read()
                content = content.replace('int(os.getenv(\'PORT\') or 5000)', 'int(os.getenv(\'PORT\') or 10000)')
                with open(config_path, 'w') as f:
                    f.write(content)

            # Créer le fichier ZIP
            zip_filename = 'colu200.zip'

            with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(deploy_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, deploy_dir)
                        zipf.write(file_path, arcname)

            # Envoyer le fichier
            url = f"{self.base_url}/sendDocument"
            with open(zip_filename, 'rb') as f:
                files = {'document': (zip_filename, f, 'application/zip')}
                data = {
                    'chat_id': chat_id,
                    'caption': '📦 Package de déploiement Render.com - COLU200\n\n✅ Port configuré : 10000\n✅ Dernières modifications incluses\n✅ Fichiers : main.py, bot.py, handlers.py, card_predictor.py, config.py, requirements.txt, render.yaml\n\nInstructions :\n1. Uploadez colu200.zip sur Render.com\n2. Configurez vos variables environnement (BOT_TOKEN, WEBHOOK_URL, etc.)\n3. Déployez !\n\nNote : Toutes les dernières modifications de prédiction et vérification sont incluses.'
                }
                response = requests.post(url, data=data, files=files, timeout=60)

            # Nettoyer les fichiers temporaires
            shutil.rmtree(deploy_dir)
            if os.path.exists(zip_filename):
                os.remove(zip_filename)

            if response.json().get('ok'):
                logger.info(f"✅ Package de déploiement colu200.zip envoyé avec succès")
            else:
                self.send_message(chat_id, f"❌ Erreur lors de l'envoi du package : {response.text}")

        except Exception as e:
            logger.error(f"Erreur lors de la création du package de déploiement : {e}")
            self.send_message(chat_id, f"❌ Erreur : {str(e)}")

    # --- GESTION COMMANDE /inter ---
    def _handle_command_inter(self, chat_id: int, text: str):
        if not self.card_predictor: 
            self.send_message(chat_id, "❌ Le moteur de prédiction n'est pas chargé.")
            return

        parts = text.lower().split()

        # Par défaut 'status' si pas d'argument
        action = parts[1] if len(parts) > 1 else 'status'

        if action == 'activate':
            self.card_predictor.analyze_and_set_smart_rules(chat_id=chat_id, force_activate=True)
            self.send_message(chat_id, "✅ **MODE INTER ACTIVÉ**\nAnalyse des Enseignes (♠️♥️♦️♣️) en cours...")

        elif action == 'default':
            self.card_predictor.is_inter_mode_active = False
            self.card_predictor._save_all_data()
            self.send_message(chat_id, "❌ **MODE INTER DÉSACTIVÉ**\nRetour aux règles statiques.")

        elif action == 'status':
            msg, kb = self.card_predictor.get_inter_status()
            self.send_message(chat_id, msg, reply_markup=kb)

        else:
            self.send_message(chat_id, HELP_MESSAGE)

    # --- CALLBACKS (BOUTONS) ---
    def _handle_callback_query(self, update_obj):
        data = update_obj['data']
        chat_id = update_obj['message']['chat']['id']
        msg_id = update_obj['message']['message_id']

        if not self.card_predictor: return

        # Actions INTER
        if data == 'inter_apply':
            self.card_predictor.analyze_and_set_smart_rules(chat_id=chat_id, force_activate=True)
            self.send_message(chat_id, "✅ Mode Intelligent Appliqué !", message_id=msg_id, edit=True)

        elif data == 'inter_default':
            self.card_predictor.is_inter_mode_active = False
            self.card_predictor._save_all_data()
            self.send_message(chat_id, "❌ Mode Statique réactivé.", message_id=msg_id, edit=True)

        # Actions CONFIG
        elif data.startswith('config_'):
            if 'cancel' in data:
                self.send_message(chat_id, "Configuration annulée.", message_id=msg_id, edit=True)
            else:
                type_c = 'source' if 'source' in data else 'prediction'
                self.card_predictor.set_channel_id(chat_id, type_c)
                self.send_message(chat_id, f"✅ Ce canal est maintenant défini comme **{type_c.upper()}**.\n(L'ID forcé dans le code sera utilisé si le bot redémarre sans ce fichier de config)", message_id=msg_id, edit=True)

    # --- UPDATES ---
    def handle_update(self, update: Dict[str, Any]):
        try:
            if not self.card_predictor: return # Sortie rapide si le moteur de prédiction n'est pas là

            # 1. Messages Texte / Channel Post
            if ('message' in update and 'text' in update['message']) or ('channel_post' in update and 'text' in update['channel_post']):

                msg = update.get('message') or update.get('channel_post')
                chat_id = msg['chat']['id']
                text = msg['text']
                user_id = msg.get('from', {}).get('id', 0)

                if not self._check_rate_limit(user_id): return

                # Commandes
                if text.startswith('/inter'):
                    self._handle_command_inter(chat_id, text)
                elif text.startswith('/config'):
                    kb = {'inline_keyboard': [[{'text': 'Source', 'callback_data': 'config_source'}, {'text': 'Prediction', 'callback_data': 'config_prediction'}, {'text': 'Annuler', 'callback_data': 'config_cancel'}]]}
                    self.send_message(chat_id, "⚙️ **CONFIGURATION**\nQuel est le rôle de ce canal ?", reply_markup=kb)
                elif text.startswith('/start'):
                    self.send_message(chat_id, WELCOME_MESSAGE)
                elif text.startswith('/stat'):
                    sid = self.card_predictor.target_channel_id or self.card_predictor.HARDCODED_SOURCE_ID or "Non défini"
                    pid = self.card_predictor.prediction_channel_id or self.card_predictor.HARDCODED_PREDICTION_ID or "Non défini"
                    mode = "IA" if self.card_predictor.is_inter_mode_active else "Statique"
                    self.send_message(chat_id, f"📊 **STATUS**\nSource (Input): `{sid}`\nPrédiction (Output): `{pid}`\nMode: {mode}")
                elif text.startswith('/deploy'):
                    self._handle_command_deploy(chat_id)

                # Traitement Canal Source
                elif str(chat_id) == str(self.card_predictor.target_channel_id):

                    # A. Vérifier
                    res = self.card_predictor._verify_prediction_common(text)
                    if res and res['type'] == 'edit_message':
                        pred_game_str = res['predicted_game']
                        # Récupère la prédiction par clé string ou int (pour plus de robustesse)
                        pred_data = self.card_predictor.predictions.get(int(pred_game_str)) or self.card_predictor.predictions.get(pred_game_str)

                        if pred_data:
                            mid = pred_data.get('message_id')
                            if mid: 
                                self.send_message(self.card_predictor.prediction_channel_id, res['new_message'], message_id=mid, edit=True)

                    # B. Prédire
                    ok, num, val = self.card_predictor.should_predict(text)
                    if ok:
                        txt = self.card_predictor.make_prediction(num, val)
                        mid = self.send_message(self.card_predictor.prediction_channel_id, txt)
                        if mid:
                            target_game = int(num + 2)
                            # Assurez-vous que la clé est mise à jour après la sauvegarde/lecture
                            if target_game in self.card_predictor.predictions:
                                self.card_predictor.predictions[target_game]['message_id'] = mid
                                self.card_predictor._save_all_data()

            # 2. Callbacks
            elif 'callback_query' in update:
                self._handle_callback_query(update['callback_query'])

            # 3. Ajout au groupe
            elif 'my_chat_member' in update:
                # Logique pour déclencher le /config quand le bot est ajouté
                m = update['my_chat_member']
                if m['new_chat_member']['status'] in ['member', 'administrator']:
                    # Simple vérification pour s'assurer que c'est bien l'ID du bot
                    bot_id_part = self.bot_token.split(':')[0]
                    if str(m['new_chat_member']['user']['id']).startswith(bot_id_part):
                         self.send_message(m['chat']['id'], "✨ Merci de m'avoir ajouté ! Veuillez utiliser `/config` pour définir mon rôle (Source ou Prédiction).")


        except Exception as e:
            logger.error(f"Update error: {e}")