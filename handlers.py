import logging
import time
import json
import os
from collections import defaultdict
from typing import Dict, Any, Optional
import requests
import shutil
import zipfile # Ajouté pour le déploiement

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Importation Robuste
try:
    from card_predictor import CardPredictor
except ImportError:
    logger.error("❌ IMPOSSIBLE D'IMPORTER CARDPREDICTOR. Assurez-vous que le fichier est présent.")
    CardPredictor = None

user_message_counts = defaultdict(list)

# --- MESSAGES UTILISATEUR NETTOYÉS (inchangés) ---
WELCOME_MESSAGE = """
👋 **BIENVENUE SUR LE BOT ENSEIGNE !** ♠️♥️♦️♣️
...
"""

HELP_MESSAGE = """
🤖 **AIDE COMMANDE /INTER**
...
"""

class TelegramHandlers:
    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        
        if CardPredictor:
            # On passe la fonction d'envoi pour les notifs INTER
            # NOTE: La méthode send_message ci-dessous est utilisée pour les commandes/notifs, 
            # mais l'édition est gérée directement dans le handler.
            self.card_predictor = CardPredictor(telegram_message_sender=self.send_message) 
        else:
            self.card_predictor = None

    # --- MESSAGERIE (inchangée) ---
    def _check_rate_limit(self, user_id):
        # ... (Logique inchangée)
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
                # Retourne l'ID si c'est un NOUVEAU message (sendMessage)
                if method == 'sendMessage':
                    return r.json().get('result', {}).get('message_id')
                return message_id # Retourne l'ID si c'est une édition
            else:
                logger.error(f"Erreur Telegram {r.status_code}: {r.text}")
        except Exception as e:
            logger.error(f"Exception envoi message: {e}")
        return None

    # --- GESTION COMMANDE /deploy (inchangée) ---
    def _handle_command_deploy(self, chat_id: int):
        # ... (Logique inchangée)
        try:
            self.send_message(chat_id, "📦 **Génération du package de déploiement Render.com...**")
            
            # Créer un dossier temporaire
            with tempfile.TemporaryDirectory() as tmpdir:
                deploy_dir = os.path.join(tmpdir, 'telegram-bot-deploy')
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
                zip_filename = 'render_deployment.zip'
                zip_path = os.path.join(tmpdir, zip_filename)
                
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for root, dirs, files in os.walk(deploy_dir):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arcname = os.path.relpath(file_path, deploy_dir)
                            zipf.write(file_path, arcname)
                
                # Envoyer le fichier
                url = f"{self.base_url}/sendDocument"
                with open(zip_path, 'rb') as f:
                    files = {'document': (zip_filename, f, 'application/zip')}
                    data = {
                        'chat_id': chat_id,
                        'caption': '📦 **Package de déploiement Render.com**\n\n✅ Port configuré : 10000\n✅ Fichiers inclus : main.py, bot.py, handlers.py, card_predictor.py, config.py, requirements.txt, render.yaml\n\n**Instructions :**\n1. Uploadez ce fichier sur Render.com\n2. Configurez vos variables d\'environnement (BOT_TOKEN, etc.)\n3. Déployez !',
                        'parse_mode': 'Markdown'
                    }
                    response = requests.post(url, data=data, files=files, timeout=60)
                
                if response.json().get('ok'):
                    logger.info(f"✅ Package de déploiement envoyé avec succès")
                else:
                    self.send_message(chat_id, f"❌ Erreur lors de l'envoi du package : {response.text}")
                    
        except Exception as e:
            logger.error(f"Erreur lors de la création du package de déploiement : {e}")
            self.send_message(chat_id, f"❌ Erreur lors de la génération du package : {str(e)}")


    # --- GESTION COMMANDE /inter (inchangée) ---
    def _handle_command_inter(self, chat_id: int, text: str):
        if not self.card_predictor: 
            self.send_message(chat_id, "❌ Le moteur de prédiction n'est pas chargé.")
            return
            
        parts = text.lower().split()
        
        # Par défaut 'status' si pas d'argument
        action = parts[1] if len(parts) > 1 else 'status'
        
        # NOTE: Logique /inter inchangée
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

    # --- CALLBACKS (BOUTONS - inchangés) ---
    def _handle_callback_query(self, update_obj):
        data = update_obj['data']
        chat_id = update_obj['message']['chat']['id']
        msg_id = update_obj['message']['message_id']
        
        if not self.card_predictor: return

        # Actions INTER (inchangées)
        if data == 'inter_apply':
            self.card_predictor.analyze_and_set_smart_rules(chat_id=chat_id, force_activate=True)
            self.send_message(chat_id, "✅ Mode Intelligent Appliqué !", message_id=msg_id, edit=True)
        
        elif data == 'inter_default':
            self.card_predictor.is_inter_mode_active = False
            self.card_predictor._save_all_data()
            self.send_message(chat_id, "❌ Mode Statique réactivé.", message_id=msg_id, edit=True)
            
        # Actions CONFIG (inchangées)
        elif data.startswith('config_'):
            if 'cancel' in data:
                self.send_message(chat_id, "Configuration annulée.", message_id=msg_id, edit=True)
            else:
                type_c = 'source' if 'source' in data else 'prediction'
                self.card_predictor.set_channel_id(chat_id, type_c)
                self.send_message(chat_id, f"✅ Ce canal est maintenant défini comme **{type_c.upper()}**.\n(L'ID forcé dans le code sera utilisé si le bot redémarre sans ce fichier de config)", message_id=msg_id, edit=True)

    # --- UPDATES (MODIFIÉES) ---
    def _process_prediction_action(self, action: Optional[Dict], chat_id: int):
        """Exécute l'édition du message de prédiction si l'action est valide."""
        if action and action.get('type') == 'edit_message':
            # Récupération des IDs nécessaires pour l'édition
            message_id_to_edit = action.get('message_id_to_edit')
            new_message = action.get('new_message')
            
            if message_id_to_edit:
                # Utilise le canal de prédiction défini pour envoyer l'édition
                self.send_message(
                    chat_id=self.card_predictor.prediction_channel_id,
                    text=new_message, 
                    message_id=message_id_to_edit, 
                    edit=True
                )
                logger.info(f"✅ Édition du message de prédiction {message_id_to_edit} envoyée.")
            return True
        return False
        
    def handle_update(self, update: Dict[str, Any]):
        try:
            if not self.card_predictor: return 

            # Déterminer si le message est nouveau, édité ou un callback
            is_edited = 'edited_message' in update or 'edited_channel_post' in update
            
            if is_edited:
                msg = update.get('edited_message') or update.get('edited_channel_post')
            elif 'message' in update or 'channel_post' in update:
                msg = update.get('message') or update.get('channel_post')
            elif 'callback_query' in update:
                self._handle_callback_query(update['callback_query'])
                return
            elif 'my_chat_member' in update:
                # Logique d'ajout au groupe (inchangée)
                m = update['my_chat_member']
                if m['new_chat_member']['status'] in ['member', 'administrator']:
                    bot_id_part = self.bot_token.split(':')[0]
                    if str(m['new_chat_member']['user']['id']).startswith(bot_id_part):
                         self.send_message(m['chat']['id'], "✨ Merci de m'avoir ajouté ! Veuillez utiliser `/config` pour définir mon rôle (Source ou Prédiction).")
                return
            else:
                return # Ignorer les autres types d'update

            # --- Extraction des données ---
            chat_id = msg['chat']['id']
            text = msg.get('text')
            user_id = msg.get('from', {}).get('id', 0)
            message_id = msg['message_id'] # ID du message du canal source
            
            if not text: return
            if not self._check_rate_limit(user_id): return
            
            # --- Commandes (inchangées) ---
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
            
            # --- Traitement Canal Source ---
            elif str(chat_id) == str(self.card_predictor.target_channel_id):
                
                # A. Gestion Temporaire et Vérification (Cycle de Vérification)
                
                # 1. Message Temporaire (Nouveau message seulement)
                if not is_edited and self.card_predictor.should_wait_for_edit(text, message_id):
                    # Le message est stocké dans pending_edits, le traitement s'arrête ici.
                    return 
                    
                # 2. Lancement de la Vérification
                if is_edited:
                    # Le message édité peut être la finalisation d'un message temporaire.
                    res = self.card_predictor.verify_prediction_from_edit(text)
                else:
                    # Message nouveau (non temporaire) ou message qui n'a pas d'indicateurs temporaires
                    res = self.card_predictor.verify_prediction(text)

                # 3. Exécuter l'édition si la vérification a eu lieu
                if self._process_prediction_action(res, chat_id):
                    # Si une prédiction a été éditée (gagnée ou perdue), on sort.
                    
                    # On retire également le message des pending_edits si c'était une édition
                    if is_edited and message_id in self.card_predictor.pending_edits:
                         del self.card_predictor.pending_edits[message_id]
                         logger.info(f"✅ Message temporaire {message_id} retiré des pending_edits après édition.")
                    return
                
                # B. Nouvelle Prédiction (Cycle de Prédiction)
                
                # Le bot ne prédit que si le message est un résultat final (non temporaire).
                # Note: Vous devez définir la logique 'should_predict' dans card_predictor.py
                ok, num, val = self.card_predictor.should_predict(text) 
                
                if ok:
                    txt = self.card_predictor.prepare_prediction_text(num, val) # prepare_prediction_text doit retourner le texte brut
                    
                    # Envoi du message (Étape 3)
                    mid = self.send_message(self.card_predictor.prediction_channel_id, txt)
                    
                    # Stockage de l'ID du message envoyé pour l'édition future
                    if mid:
                        self.card_predictor.make_prediction(num, val, mid)
                        self.card_predictor._save_all_data()

        except Exception as e:
            logger.error(f"Update error: {e}", exc_info=True)
