# handlers.py

import logging
import os
import re
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, Any, Optional, List, Tuple
import requests 
import time
import json 

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Importation robuste de CardPredictor
try:
    from card_predictor import CardPredictor
except ImportError:
    logger.error("❌ IMPOSSIBLE D'IMPORTER CARDPREDICTOR")
    CardPredictor = None

# Limites de débit
user_message_counts = defaultdict(list)
MAX_MESSAGES_PER_MINUTE = 30
RATE_LIMIT_WINDOW = 60

# Messages
WELCOME_MESSAGE = """
👋 **BIENVENUE SUR LE BOT ENSEIGNE V2 !** ♠️♥️♦️♣️

🎯 **COMMANDES:**
• `/start` - Accueil
• `/stat` - Statistiques globales
• `/inter` - Gérer le Mode Intelligent (Apprentissage)
• `/config` - Configurer les canaux

Utilisez `/inter status` pour voir l'état de l'IA.
"""
CONFIG_PROMPT = "⚙️ Veuillez confirmer le rôle de ce canal :"
HELP_MESSAGE = "🤖 **AIDE:**\nUtilisez `/inter activate` pour activer l'IA.\nUtilisez `/inter status` pour voir les règles."
CONFIG_SUCCESS = "✅ **CANAL CONFIGURÉ** : Ce canal est désormais le **{type}**."

# Constantes Callbacks
CALLBACK_SOURCE = "config_source"
CALLBACK_PREDICTION = "config_prediction"
CALLBACK_CANCEL = "config_cancel"
CALLBACK_INTER_APPLY = "inter_apply"
CALLBACK_INTER_DEFAULT = "inter_default"


def get_config_keyboard() -> Dict:
    keyboard = [
        [{'text': "📥 Canal SOURCE (Lecture)", 'callback_data': CALLBACK_SOURCE}],
        [{'text': "📤 Canal PRÉDICTION (Écriture)", 'callback_data': CALLBACK_PREDICTION}],
        [{'text': "❌ Annuler", 'callback_data': CALLBACK_CANCEL}]
    ]
    return {'inline_keyboard': keyboard}


class TelegramHandlers:
    """Gère les interactions Telegram via Webhook."""

    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        
        # Initialisation du prédicteur avec la fonction d'envoi pour les notifications 30min
        if CardPredictor:
            self.card_predictor = CardPredictor(telegram_message_sender=self.send_message)
        else:
            self.card_predictor = None

    # --- MÉTHODES TELEGRAM ---

    def _check_rate_limit(self, user_id):
        now = time.time()
        user_message_counts[user_id] = [t for t in user_message_counts[user_id] if now - t < RATE_LIMIT_WINDOW]
        user_message_counts[user_id].append(now)
        return len(user_message_counts[user_id]) <= MAX_MESSAGES_PER_MINUTE

    def send_message(self, chat_id: int, text: str, parse_mode='Markdown', message_id: Optional[int] = None, edit=False, reply_markup: Optional[Dict] = None) -> Optional[int]:
        if not chat_id or not text: return None
        method = 'editMessageText' if (message_id or edit) else 'sendMessage'
        payload = {'chat_id': chat_id, 'text': text, 'parse_mode': parse_mode}
        if message_id: payload['message_id'] = message_id
        if reply_markup: payload['reply_markup'] = json.dumps(reply_markup) if isinstance(reply_markup, dict) else reply_markup

        try:
            r = requests.post(f"{self.base_url}/{method}", json=payload, timeout=10)
            if r.status_code == 200:
                return r.json().get('result', {}).get('message_id')
            else:
                logger.error(f"Erreur Telegram {r.status_code}: {r.text}")
        except Exception as e:
            logger.error(f"Exception envoi message: {e}")
        return None

    def edit_message(self, chat_id: int, message_id: int, text: str, parse_mode='Markdown', reply_markup: Optional[Dict] = None) -> bool:
        res = self.send_message(chat_id, text, parse_mode, message_id, edit=True, reply_markup=reply_markup)
        return res is not None

    # --- GESTION COMMANDES ---

    def _handle_start_command(self, chat_id: int):
        self.send_message(chat_id, WELCOME_MESSAGE)

    def _handle_stat_command(self, chat_id: int):
        if not self.card_predictor: return
        sid = self.card_predictor.target_channel_id or "❌ Non défini"
        pid = self.card_predictor.prediction_channel_id or "❌ Non défini"
        mode = "🧠 INTELLIGENT" if self.card_predictor.is_inter_mode_active else "⚙️ STATIQUE"
        self.send_message(chat_id, f"**📊 STATISTIQUES**\n\n📥 Source: `{sid}`\n📤 Prédiction: `{pid}`\n🎛 Mode: {mode}")

    def _handle_inter_command(self, chat_id: int, text: str):
        """Gère la commande /inter (activate, status, default)."""
        if not self.card_predictor: return
        parts = text.lower().split()
        # Par défaut 'status' si pas d'argument
        action = parts[1] if len(parts) > 1 else 'status'
        
        if action == 'activate':
            # Force l'analyse immédiate et active le mode
            self.card_predictor.analyze_and_set_smart_rules(chat_id=chat_id, force_activate=True)
            self.send_message(chat_id, "✅ **MODE INTER ACTIVÉ**\nL'IA analyse l'historique et s'adaptera toutes les 30 minutes.")
        
        elif action == 'default':
            # Désactive le mode
            self.card_predictor.is_inter_mode_active = False
            self.card_predictor._save_all_data()
            self.send_message(chat_id, "❌ **MODE INTER DÉSACTIVÉ**\nRetour aux règles statiques (10♦️->♠️, etc).")
            
        elif action == 'status':
            msg, kb = self.card_predictor.get_inter_status()
            self.send_message(chat_id, msg, reply_markup=kb)
        
        else:
            self.send_message(chat_id, "Commande inconnue. Utilisez: `/inter status`, `/inter activate`, `/inter default`")

    def _handle_config_command(self, chat_id: int, title: str):
        self.send_message(chat_id, f"🚨 **CONFIGURATION**\nPour le chat `{title}` (ID: `{chat_id}`)\n{CONFIG_PROMPT}", reply_markup=get_config_keyboard())

    # --- GESTION CALLBACKS ---

    def _handle_callback_query(self, update_obj):
        data = update_obj['data']
        chat_id = update_obj['message']['chat']['id']
        msg_id = update_obj['message']['message_id']
        
        if not self.card_predictor: return

        if data == CALLBACK_INTER_APPLY:
            self.card_predictor.analyze_and_set_smart_rules(chat_id=chat_id, force_activate=True)
            self.edit_message(chat_id, msg_id, "✅ **IA ACTIVÉE & MISE À JOUR**")
        
        elif data == CALLBACK_INTER_DEFAULT:
            self.card_predictor.is_inter_mode_active = False
            self.card_predictor._save_all_data()
            self.edit_message(chat_id, msg_id, "❌ **MODE STATIQUE ACTIVÉ**")
            
        elif data == CALLBACK_SOURCE:
            self.card_predictor.set_channel_id(chat_id, 'source')
            self.edit_message(chat_id, msg_id, CONFIG_SUCCESS.format(type="SOURCE"))
            
        elif data == CALLBACK_PREDICTION:
            self.card_predictor.set_channel_id(chat_id, 'prediction')
            self.edit_message(chat_id, msg_id, CONFIG_SUCCESS.format(type="PRÉDICTION"))
            
        elif data == CALLBACK_CANCEL:
            self.edit_message(chat_id, msg_id, "❌ Configuration annulée.")

    # --- CŒUR DU SYSTÈME (UPDATES) ---

    def _process_channel_message(self, message: Dict[str, Any], is_edited: bool = False):
        """Traite les messages du canal source pour vérifier et prédire."""
        if not self.card_predictor: return
        text = message.get('text', '')
        if not text: return

        # 1. Vérification des prédictions passées
        res = self.card_predictor._verify_prediction_common(text)
        if res and res['type'] == 'edit_message':
            # Récupérer l'ID du message de prédiction original
            # Note: On utilise int() ou str() selon comment c'est stocké, ici on gère les deux
            pred_game = res['predicted_game']
            pred_data = self.card_predictor.predictions.get(str(pred_game)) or self.card_predictor.predictions.get(int(pred_game))
            
            if pred_data:
                mid = pred_data.get('message_id')
                if mid and self.card_predictor.prediction_channel_id:
                    self.send_message(self.card_predictor.prediction_channel_id, res['new_message'], message_id=mid, edit=True)

        # 2. Nouvelle Prédiction (Seulement si pas édité)
        if not is_edited:
            ok, num, suit = self.card_predictor.should_predict(text)
            if ok and self.card_predictor.prediction_channel_id:
                txt = self.card_predictor.make_prediction(num, suit)
                # Envoi et stockage de l'ID
                mid = self.send_message(self.card_predictor.prediction_channel_id, txt)
                if mid:
                    # Stocker l'ID pour pouvoir éditer plus tard (Cible = num + 2)
                    target = num + 2
                    if target in self.card_predictor.predictions:
                        self.card_predictor.predictions[target]['message_id'] = mid
                    # Sauvegarder immédiatement
                    self.card_predictor._save_all_data()

    def handle_update(self, update: Dict[str, Any]):
        try:
            # 1. Messages Texte
            if 'message' in update:
                msg = update['message']
                chat_id = msg['chat']['id']
                text = msg.get('text', '')
                user_id = msg.get('from', {}).get('id', 0)

                if not self._check_rate_limit(user_id): return

                # Commandes
                if text.startswith('/'):
                    if text.startswith('/start'): self._handle_start_command(chat_id)
                    elif text.startswith('/stat'): self._handle_stat_command(chat_id)
                    elif text.startswith('/config'): self._handle_config_command(chat_id, msg['chat'].get('title', 'Chat'))
                    elif text.startswith('/inter'): self._handle_inter_command(chat_id, text)
                
                # Traitement Canal Source
                elif self.card_predictor and str(chat_id) == str(self.card_predictor.target_channel_id):
                    self._process_channel_message(msg)

            # 2. Messages Édités
            elif 'edited_message' in update:
                msg = update['edited_message']
                chat_id = msg['chat']['id']
                if self.card_predictor and str(chat_id) == str(self.card_predictor.target_channel_id):
                    self._process_channel_message(msg, is_edited=True)

            # 3. Callbacks
            elif 'callback_query' in update:
                self._handle_callback_query(update['callback_query'])
            
            # 4. Ajout au groupe
            elif 'my_chat_member' in update:
                m = update['my_chat_member']
                if m['new_chat_member']['status'] in ['member', 'administrator']:
                    # Vérifie si c'est bien le bot qui est ajouté
                    if str(m['new_chat_member']['user']['id']) in self.bot_token: 
                        self._handle_config_command(m['chat']['id'], m['chat'].get('title', ''))

        except Exception as e:
            logger.error(f"Erreur Update: {e}")
