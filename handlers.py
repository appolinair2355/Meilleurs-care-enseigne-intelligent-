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

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Importation de CardPredictor
try:
    from card_predictor import CardPredictor
except ImportError:
    # Fallback minimal pour éviter le crash
    class CardPredictor:
        def __init__(self, telegram_message_sender=None): 
            self.target_channel_id = None
            self.prediction_channel_id = None
            self.is_inter_mode_active = False
            self.predictions = {}
            self.active_admin_chat_id = None 
            self.prediction_channel_id = None
        def set_channel_id(self, *args): return False
        def get_inter_status(self, *args): return "Système INTER non disponible.", None
        def analyze_and_set_smart_rules(self, *args, **kwargs): pass
        def _save_data(self, *args, **kwargs): pass
        def _verify_prediction_common(self, *args, **kwargs): return None
        def should_predict(self, *args): return False, None, None
        def make_prediction(self, *args): return ""
    logger.error("❌ Échec de l'importation de CardPredictor. Les fonctionnalités de prédiction seront désactivées.")
    
# --- CONSTANTES ---
user_message_counts = defaultdict(list)
MAX_MESSAGES_PER_MINUTE = 30
RATE_LIMIT_WINDOW = 60
WELCOME_MESSAGE = "👋 Bienvenue ! Je suis le Bot de Prédiction. Utilisez les commandes de configuration pour démarrer."
CONFIG_PROMPT = "⚙️ Veuillez me dire à quel canal j'ai été ajouté :\n\n- Canal de **Source** (où les résultats arrivent)\n- Canal de **Prédiction** (où j'envoie les prédictions)"
HELP_MESSAGE = "🤖 **COMMANDES DISPONIBLES :**\n\n`/config` : Configure les canaux source/prédiction.\n`/inter status` : Affiche l'état du mode intelligent (apprentissage et règles Top 3).\n`/inter activate` : Active le mode intelligent avec auto-adaptation/notification 30min.\n`/inter default` : Revient au mode statique."
CONFIG_SUCCESS = "✅ **CANAL CONFIGURÉ** : Ce canal est désormais le **{type}** pour les IDs suivants :\n\n- Source (Résultats) : `{source_id}`\n- Prédiction (Envoi) : `{prediction_id}`"


class TelegramHandlers:
    
    def __init__(self, token: str):
        self.bot_token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
        
        # 🚨 Initialisation du prédicteur avec la fonction d'envoi de message
        self.card_predictor = CardPredictor(telegram_message_sender=self._send_message) 

    # --- Méthodes d'envoi/édition de message ---
    def _check_rate_limit(self, user_id):
        now = time.time()
        user_message_counts[user_id] = [t for t in user_message_counts[user_id] if now - t < RATE_LIMIT_WINDOW]
        user_message_counts[user_id].append(now)
        if len(user_message_counts[user_id]) > MAX_MESSAGES_PER_MINUTE:
            return False
        return True

    def _send_message(self, chat_id: int, text: str, reply_to_message_id: Optional[int] = None, reply_markup: Optional[Dict] = None) -> Optional[int]:
        if not chat_id or not text: return None
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}
            if reply_to_message_id: payload['reply_to_message_id'] = reply_to_message_id
            if reply_markup: payload['reply_markup'] = reply_markup
            
            response = requests.post(url, json=payload, timeout=5)
            result = response.json()
            if result.get('ok'):
                return result.get('result', {}).get('message_id')
            else:
                logger.error(f"❌ Échec envoi message à {chat_id}: {result.get('description')}")
                return None
        except Exception as e:
            logger.error(f"❌ Erreur réseau lors de l'envoi du message: {e}")
            return None
    
    def _edit_message(self, chat_id: int, message_id: int, text: str, reply_markup: Optional[Dict] = None):
        if not chat_id or not message_id or not text: return
        try:
            url = f"{self.base_url}/editMessageText"
            payload = {'chat_id': chat_id, 'message_id': message_id, 'text': text, 'parse_mode': 'Markdown'}
            if reply_markup: payload['reply_markup'] = reply_markup
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            logger.error(f"❌ Erreur réseau lors de l'édition du message {message_id}: {e}")

    def _send_config_prompt(self, chat_id: int, chat_title: str):
        keyboard = {
            'inline_keyboard': [
                [{'text': "1️⃣ Canal SOURCE (Résultats)", 'callback_data': 'config_source'}],
                [{'text': "2️⃣ Canal PRÉDICTION (Bot envoie)", 'callback_data': 'config_prediction'}],
                [{'text': "❌ Annuler la configuration", 'callback_data': 'config_cancel'}]
            ]
        }
        self._send_message(chat_id, f"🚨 **CONFIGURATION** : Vous m'avez ajouté à **{chat_title}**.\n\n{CONFIG_PROMPT}", reply_markup=keyboard)


    def _handle_command_config(self, message: Dict[str, Any]):
        text = message.get('text', '').lower()
        chat_id = message['chat']['id']
        
        if text.startswith('/config'):
            if chat_id > 0:
                self._send_message(chat_id, "⚠️ **ATTENTION** : La configuration des canaux doit être faite dans le canal de discussion où le bot est administrateur.")
                return True
            
            chat_title = message['chat'].get('title', f"Chat ID {chat_id}")
            self._send_config_prompt(chat_id, chat_title)
            return True
        return False
    
    def _handle_basic_commands(self, chat_id: int, text: str):
        text = text.lower().split()[0]
        if text == '/start':
            self._send_message(chat_id, WELCOME_MESSAGE)
            return True
        elif text == '/help':
            self._send_message(chat_id, HELP_MESSAGE)
            return True
        return False

    # 🚨 CORRECTION INDEXERROR
    def _handle_command_inter(self, chat_id: int, text: str):
        """Gère la commande /inter pour le mode intelligent (activate, status, default)."""
        command_parts = text.lower().split()
        
        if not command_parts or command_parts[0] != '/inter':
            return False
            
        # Extraction sécurisée de l'action (Le défaut est 'status')
        action = 'status' 
        if len(command_parts) > 1:
            action = command_parts[1]
            
        logger.info(f"🧠 Commande /inter reçue de {chat_id} avec action: {action}")

        if action == 'activate':
            logger.info(f"🧠 Déclenchement de l'analyse et activation du mode INTER.")
            
            self.card_predictor.analyze_and_set_smart_rules(chat_id=chat_id, force_activate=True)
            self._send_message(chat_id, "✅ **MODE INTERLIGNE ACTIF** : L'algorithme se mettra à jour et vous notifiera toutes les 30 minutes des changements de règles.")
            
        elif action == 'status':
            logger.info(f"🧠 Affichage du status INTER.")
            status_text, keyboard = self.card_predictor.get_inter_status(force_reanalyze=False) 
            self._send_message(chat_id, status_text, reply_markup=keyboard)

        elif action == 'default':
            logger.info(f"🧠 Désactivation du mode intelligent.")
            self.card_predictor.is_inter_mode_active = False
            self.card_predictor._save_data(self.card_predictor.is_inter_mode_active, 'inter_mode_status.json', is_scalar=True) 
            self._send_message(chat_id, "❌ **MODE INTERLIGNE DÉSACTIVÉ** : Retour aux règles statiques par défaut.")

        else:
            self._send_message(chat_id, "⚠️ **Action /inter non reconnue.** Utilisez : `/inter activate`, `/inter status` ou `/inter default`.")

        return True

    # 🚨 MISE À JOUR : Gestion des callbacks INTER
    def _handle_callback_query(self, callback_query: Dict[str, Any]):
        """Gère les actions après un clic sur un bouton (callback)."""
        data = callback_query['data']
        chat_id = callback_query['message']['chat']['id']
        message_id = callback_query['message']['message_id']
        
        # Gestion des actions INTERLIGNE venant des boutons de status
        if data == 'inter_apply':
            self.card_predictor.analyze_and_set_smart_rules(chat_id=chat_id, force_activate=True)
            self._edit_message(chat_id, message_id, "✅ **MODE INTERLIGNE ACTIVÉ** : L'algorithme se mettra à jour et vous notifiera toutes les 30 minutes des changements de règles.")
            return
        elif data == 'inter_default':
            self.card_predictor.is_inter_mode_active = False
            self.card_predictor._save_data(self.card_predictor.is_inter_mode_active, 'inter_mode_status.json', is_scalar=True)
            self._edit_message(chat_id, message_id, "❌ **MODE INTERLIGNE DÉSACTIVÉ** : Retour aux règles statiques par défaut.")
            return

        # Gère les actions de configuration des canaux
        is_source = data == 'config_source'
        is_prediction = data == 'config_prediction'

        if is_source or is_prediction:
            channel_type = 'source' if is_source else 'prediction'
            self.card_predictor.set_channel_id(chat_id, channel_type)

            source_id = self.card_predictor.target_channel_id
            prediction_id = self.card_predictor.prediction_channel_id
            
            success_message = CONFIG_SUCCESS.format(
                type='SOURCE' if is_source else 'PRÉDICTION',
                source_id=source_id if source_id else 'Non défini',
                prediction_id=prediction_id if prediction_id else 'Non défini'
            )
            
            self._edit_message(chat_id, message_id, success_message, reply_markup=None)

        elif data == 'config_cancel':
            self._edit_message(chat_id, message_id, "❌ Configuration annulée.", reply_markup=None)


    def _handle_message(self, message: Dict[str, Any]):
        """Gère les nouveaux messages et posts de canal."""
        user_id = message.get('from', {}).get('id', 0)
        chat_id = message['chat']['id']
        text = message.get('text', '') or message.get('caption', '')
        
        if not self._check_rate_limit(user_id): return

        # 1. Gère les Commandes
        if text.startswith('/'):
            if self._handle_command_config(message): return
            if self._handle_command_inter(chat_id, text): return 
            if self._handle_basic_commands(chat_id, text): return
            
        # 2. Logique de Prédiction/Vérification
        if str(chat_id) == str(self.card_predictor.target_channel_id):
            
            # a. Vérification des prédictions précédentes
            verification_result = self.card_predictor._verify_prediction_common(text)
            if verification_result and verification_result['type'] == 'edit_message':
                predicted_game = verification_result['predicted_game']
                prediction_message_id = self.card_predictor.predictions.get(predicted_game, {}).get('message_id')
                
                if prediction_message_id and self.card_predictor.prediction_channel_id:
                    self._edit_message(
                        self.card_predictor.prediction_channel_id,
                        prediction_message_id,
                        verification_result['new_message']
                    )
            
            # b. Nouvelle prédiction
            can_predict, game_number, predicted_suit = self.card_predictor.should_predict(text)
            
            if can_predict and self.card_predictor.prediction_channel_id:
                prediction_text = self.card_predictor.make_prediction(game_number, predicted_suit)
                
                # Envoi et stockage de l'ID du message
                message_id = self._send_message(self.card_predictor.prediction_channel_id, prediction_text)
                target_game = game_number + 2
                if message_id and target_game in self.card_predictor.predictions:
                    self.card_predictor.predictions[target_game]['message_id'] = message_id
                    self.card_predictor._save_data(self.card_predictor.predictions, 'predictions.json')


    def _handle_edited_message(self, message: Dict[str, Any]):
        chat_id = message['chat']['id']
        text = message.get('text', '') or message.get('caption', '')
        
        if str(chat_id) == str(self.card_predictor.target_channel_id):
            verification_result = self.card_predictor._verify_prediction_common(text, is_edited=True)
            if verification_result and verification_result['type'] == 'edit_message':
                predicted_game = verification_result['predicted_game']
                prediction_message_id = self.card_predictor.predictions.get(predicted_game, {}).get('message_id')
                
                if prediction_message_id and self.card_predictor.prediction_channel_id:
                    self._edit_message(
                        self.card_predictor.prediction_channel_id,
                        prediction_message_id,
                        verification_result['new_message']
                    )

    def handle_update(self, update: Dict[str, Any]) -> None:
        try:
            if 'callback_query' in update:
                self._handle_callback_query(update['callback_query'])
            elif 'my_chat_member' in update:
                my_chat_member = update['my_chat_member']
                new_status = my_chat_member['new_chat_member']['status']
                bot_id = int(self.bot_token.split(':')[0]) 
                
                if new_status in ['member', 'administrator']:
                    if my_chat_member['new_chat_member']['user']['id'] == bot_id:
                        chat_id = my_chat_member['chat']['id']
                        chat_title = my_chat_member['chat'].get('title', f'Chat ID: {chat_id}')
                        chat_type = my_chat_member['chat'].get('type', 'private')
                        
                        if chat_type in ['channel', 'group', 'supergroup']:
                            logger.info(f"✨ BOT AJOUTÉ/PROMU : Envoi du prompt de configuration à {chat_title} ({chat_id})")
                            self._send_config_prompt(chat_id, chat_title)
            
            elif 'message' in update:
                self._handle_message(update['message'])
            elif 'edited_message' in update:
                self._handle_edited_message(update['edited_message'])
            elif 'channel_post' in update:
                self._handle_message(update['channel_post'])
            elif 'edited_channel_post' in update:
                self._handle_edited_message(update['edited_channel_post'])

        except Exception as e:
            logger.error(f"❌ Erreur critique lors du traitement de l'update: {e}")

