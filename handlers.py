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
    # Assurez-vous d'utiliser la version de CardPredictor que j'ai corrigée (avec Top 2 par enseigne)
    from card_predictor import CardPredictor
except ImportError:
    logger.error("❌ IMPOSSIBLE D'IMPORTER CARDPREDICTOR")
    CardPredictor = None

user_message_counts = defaultdict(list)

# --- MESSAGES UTILISATEUR NETTOYÉS ---
WELCOME_MESSAGE = """
👋 **BIENVENUE SUR LE BOT ENSEIGNE !** ♠️♥️♦️♣️

Je prédis la prochaine Enseigne (Couleur) en utilisant :
1. **Règles statiques** : Patterns prédéfinis (ex: 10♦️ → ♠️)
2. **Intelligence artificielle (Mode INTER)** : Apprend des données réelles

━━━━━━━━━━━━━━━━━━━━━
📋 **COMMANDES DISPONIBLES**
━━━━━━━━━━━━━━━━━━━━━

**🔹 Informations Générales**
• `/start` - Afficher ce message d'aide
• `/stat` - Voir l'état du bot (canaux, mode actif)

**🔹 Mode Intelligent (INTER)**
• `/inter status` - Voir les règles apprises (Top 2 par enseigne)
• `/inter activate` - **Activer manuellement** le mode intelligent
• `/inter default` - Désactiver et revenir aux règles statiques

**🔹 Collecte de Données**
• `/collect` - Voir toutes les données collectées par enseigne

**🔹 Configuration**
• `/config` - Configurer les rôles des canaux (Source/Prédiction)

**🔹 Déploiement**
• `/deploy` - Télécharger le package pour Render.com

━━━━━━━━━━━━━━━━━━━━━
**💡 Comment ça marche ?**
━━━━━━━━━━━━━━━━━━━━━

1️⃣ Le bot surveille le canal SOURCE
2️⃣ Détecte les cartes et fait des prédictions
3️⃣ Envoie les prédictions dans le canal PRÉDICTION
4️⃣ Vérifie automatiquement les résultats
5️⃣ Collecte les données en continu pour apprentissage

🧠 **Mode INTER** : 
• Collecte automatique des données de jeu
• Mise à jour des règles toutes les 30 min
• **Activation MANUELLE uniquement** (commande `/inter activate`)
• Utilise les Top 2 déclencheurs par enseigne (♠️♥️♦️♣️)

━━━━━━━━━━━━━━━━━━━━━
⚠️ **Important** : Le mode INTER doit être activé manuellement avec `/inter activate`
"""

HELP_MESSAGE = """
🤖 **AIDE COMMANDE /INTER**

• `/inter status` : Voir les règles apprises (Top 2 par Enseigne).
• `/inter activate` : Forcer l'activation de l'IA et relancer l'analyse.
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
    # (Le code de _handle_command_deploy n'a pas été modifié)
    def _handle_command_deploy(self, chat_id: int):
        try:
            self.send_message(chat_id, "📦 **Génération de fin23.zip pour Replit Deployments...**")
            
            # Liste des fichiers à inclure
            files_to_include = [
                'main.py', 'bot.py', 'handlers.py', 'card_predictor.py', 
                'config.py', 'requirements.txt', 'RENDER_DEPLOYMENT_INSTRUCTIONS.md'
            ]
            
            # Créer le fichier zip directement sans tempdir
            zip_filename = 'fin23.zip'
            
            import zipfile
            import os
            
            with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for filename in files_to_include:
                    if os.path.exists(filename):
                        # Lire et modifier config.py pour le port 10000
                        if filename == 'config.py':
                            with open(filename, 'r') as f:
                                content = f.read()
                            # Remplacer le port 5000 par 10000
                            content = content.replace('int(os.getenv(\'PORT\') or 5000)', 'int(os.getenv(\'PORT\') or 10000)')
                            zipf.writestr(filename, content)
                        else:
                            zipf.write(filename, filename)
            
            # Envoyer le fichier
            url = f"{self.base_url}/sendDocument"
            with open(zip_filename, 'rb') as f:
                files = {'document': (zip_filename, f, 'application/zip')}
                data = {
                    'chat_id': chat_id,
                    'caption': '📦 **fin23.zip - Package Replit Deployment**\n\n✅ Port : 5000 (Replit)\n✅ Tous les fichiers inclus\n✅ Mode INTER disponible\n✅ Instructions incluses\n\n**Déploiement :**\n1. Utilisez Replit Deployments\n2. Variables env : BOT_TOKEN\n3. WEBHOOK_URL auto-configuré\n\nVoir RENDER_DEPLOYMENT_INSTRUCTIONS.md pour les détails',
                    'parse_mode': 'Markdown'
                }
                response = requests.post(url, data=data, files=files, timeout=60)
            
            if response.json().get('ok'):
                logger.info(f"✅ fin23.zip envoyé avec succès")
                # Supprimer le fichier local après envoi
                if os.path.exists(zip_filename):
                    os.remove(zip_filename)
            else:
                self.send_message(chat_id, f"❌ Erreur : {response.text}")
                    
        except Exception as e:
            logger.error(f"Erreur /deploy : {e}")
            self.send_message(chat_id, f"❌ Erreur : {str(e)}")


    # --- GESTION COMMANDE /collect ---
    def _handle_command_collect(self, chat_id: int):
        if not self.card_predictor: 
            self.send_message(chat_id, "❌ Le moteur de prédiction n'est pas chargé.")
            return
        
        # Récupérer les informations
        is_active = self.card_predictor.is_inter_mode_active
        total_collected = len(self.card_predictor.inter_data)
        
        # Message d'état
        message = "🧠 **ETAT DU MODE INTELLIGENT**\n\n"
        message += f"Actif : {'✅ OUI' if is_active else '❌ NON'}\n"
        message += f"Données collectées : {total_collected}\n\n"
        
        # Afficher TOUS les déclencheurs collectés par enseigne
        if self.card_predictor.inter_data:
            from collections import defaultdict
            
            # Grouper par enseigne de résultat
            by_result_suit = defaultdict(list)
            for entry in self.card_predictor.inter_data:
                result_suit = entry.get('result_suit', '?')
                trigger = entry.get('declencheur', '?').replace("♥️", "❤️")
                by_result_suit[result_suit].append(trigger)
            
            message += "📊 **TOUS LES DÉCLENCHEURS COLLECTÉS:**\n\n"
            
            for suit in ['♠️', '❤️', '♦️', '♣️']:
                if suit in by_result_suit:
                    triggers = by_result_suit[suit]
                    message += f"**Pour enseigne {suit}:**\n"
                    # Compter les occurrences
                    from collections import Counter
                    trigger_counts = Counter(triggers)
                    for trigger, count in trigger_counts.most_common():
                        message += f"  • {trigger} ({count}x)\n"
                    message += "\n"
        else:
            message += "⚠️ **Aucune donnée collectée.**\n"
        
        # Avertissement si pas assez de données
        if total_collected < 3:
            message += f"\n⚠️ Minimum 3 jeux requis pour créer des règles (actuellement: {total_collected})."
        
        # Boutons d'action
        keyboard = {'inline_keyboard': []}
        
        if total_collected >= 3:
            if is_active:
                keyboard['inline_keyboard'].append([
                    {'text': '🔄 Relancer Analyse', 'callback_data': 'inter_apply'},
                    {'text': '❌ Désactiver INTER', 'callback_data': 'inter_default'}
                ])
            else:
                keyboard['inline_keyboard'].append([
                    {'text': '✅ Activer INTER', 'callback_data': 'inter_apply'}
                ])
        else:
            keyboard['inline_keyboard'].append([
                {'text': '🔄 Analyser les données', 'callback_data': 'inter_apply'}
            ])
        
        self.send_message(chat_id, message, reply_markup=keyboard)

    # --- GESTION COMMANDE /inter ---
    def _handle_command_inter(self, chat_id: int, text: str):
        if not self.card_predictor: 
            self.send_message(chat_id, "❌ Le moteur de prédiction n'est pas chargé.")
            return
            
        parts = text.lower().split()
        
        action = parts[1] if len(parts) > 1 else 'status'
        
        if action == 'activate':
            self.card_predictor.analyze_and_set_smart_rules(chat_id=chat_id, force_activate=True)
            self.send_message(chat_id, "✅ **MODE INTER ACTIVÉ**\nL'analyse Top 2 par enseigne est en cours...")
        
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
            # Mise à jour du message pour confirmer l'action
            msg, kb = self.card_predictor.get_inter_status()
            self.send_message(chat_id, msg, message_id=msg_id, edit=True, reply_markup=kb)
        
        elif data == 'inter_default':
            self.card_predictor.is_inter_mode_active = False
            self.card_predictor._save_all_data()
            # Mise à jour du message pour confirmer l'action
            msg, kb = self.card_predictor.get_inter_status()
            self.send_message(chat_id, msg, message_id=msg_id, edit=True, reply_markup=kb)
            
        # Actions CONFIG
        elif data.startswith('config_'):
            if 'cancel' in data:
                self.send_message(chat_id, "Configuration annulée.", message_id=msg_id, edit=True)
            else:
                type_c = 'source' if 'source' in data else 'prediction'
                self.card_predictor.set_channel_id(chat_id, type_c)
                self.send_message(chat_id, f"✅ Ce canal est maintenant défini comme **{type_c.upper()}**.\n(L'ID forcé dans le code sera utilisé si le bot redémarre sans ce fichier de config)", message_id=msg_id, edit=True)

    # --- UPDATES (PARTIE CORRIGÉE) ---
    def handle_update(self, update: Dict[str, Any]):
        try:
            if not self.card_predictor: return

            if ('message' in update and 'text' in update['message']) or ('channel_post' in update and 'text' in update['channel_post']):
                
                msg = update.get('message') or update.get('channel_post')
                chat_id = msg['chat']['id']
                text = msg['text']
                user_id = msg.get('from', {}).get('id', 0)

                if not self._check_rate_limit(user_id): return
                
                # Commandes (le code des commandes reste inchangé)
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
                elif text.startswith('/collect'):
                    self._handle_command_collect(chat_id)
                
                # Traitement Canal Source
                elif str(chat_id) == str(self.card_predictor.target_channel_id):
                    
                    # A. Collecter TOUJOURS (même messages temporaires ⏰)
                    game_num = self.card_predictor.extract_game_number(text)
                    if game_num:
                        self.card_predictor.collect_inter_data(game_num, text)
                    
                    # B. Vérifier UNIQUEMENT sur messages finalisés (✅ ou 🔰)
                    if self.card_predictor.has_completion_indicators(text) or '🔰' in text:
                        res = self.card_predictor._verify_prediction_common(text)
                        
                        if res and res['type'] == 'edit_message':
                            mid_to_edit = res.get('message_id_to_edit') 
                            
                            if mid_to_edit: 
                                self.send_message(self.card_predictor.prediction_channel_id, res['new_message'], message_id=mid_to_edit, edit=True)
                    
                    # C. Prédire (même sur messages temporaires ⏰)
                    ok, num, val = self.card_predictor.should_predict(text)
                    if ok:
                        txt = self.card_predictor.prepare_prediction_text(num, val)
                        mid = self.send_message(self.card_predictor.prediction_channel_id, txt)
                        
                        if mid:
                            self.card_predictor.make_prediction(num, val, mid)

            # 2. Messages édités (CRITIQUE pour vérification)
            elif ('edited_message' in update and 'text' in update['edited_message']) or ('edited_channel_post' in update and 'text' in update['edited_channel_post']):
                
                msg = update.get('edited_message') or update.get('edited_channel_post')
                chat_id = msg['chat']['id']
                text = msg['text']
                
                # Traitement Canal Source - Vérification sur messages édités
                if str(chat_id) == str(self.card_predictor.target_channel_id):
                    # Collecter TOUJOURS
                    game_num = self.card_predictor.extract_game_number(text)
                    if game_num:
                        self.card_predictor.collect_inter_data(game_num, text)
                    
                    # Vérifier UNIQUEMENT sur messages finalisés (✅ ou 🔰)
                    if self.card_predictor.has_completion_indicators(text) or '🔰' in text:
                        res = self.card_predictor.verify_prediction_from_edit(text)
                        
                        if res and res['type'] == 'edit_message':
                            mid_to_edit = res.get('message_id_to_edit')
                            
                            if mid_to_edit:
                                self.send_message(self.card_predictor.prediction_channel_id, res['new_message'], message_id=mid_to_edit, edit=True)

            # 3. Callbacks
            elif 'callback_query' in update:
                self._handle_callback_query(update['callback_query'])
            
            # 4. Ajout au groupe (inchangé)
            elif 'my_chat_member' in update:
                m = update['my_chat_member']
                if m['new_chat_member']['status'] in ['member', 'administrator']:
                    bot_id_part = self.bot_token.split(':')[0]
                    if str(m['new_chat_member']['user']['id']).startswith(bot_id_part):
                         self.send_message(m['chat']['id'], "✨ Merci de m'avoir ajouté ! Veuillez utiliser `/config` pour définir mon rôle (Source ou Prédiction).")


        except Exception as e:
            logger.error(f"Update error: {e}")
