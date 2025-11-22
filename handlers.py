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
# L'importation de CardPredictor est conservée (avec un fallback en cas d'erreur)
try:
    from card_predictor import CardPredictor
except ImportError:
    # Fallback minimal pour éviter le crash
    class CardPredictor:
        def __init__(self, telegram_message_sender=None): # Ajout de l'argument pour l'initialisation
            self.target_channel_id = None
            self.prediction_channel_id = None
            self.is_inter_mode_active = False
            self.inter_data = []
            self.active_admin_chat_id = None # Ajout de la propriété
        def set_channel_id(self, *args):
            logger.error("CardPredictor non chargé, impossible de définir l'ID du canal.")
            return False
        def get_inter_status(self, *args): 
            return "Système INTER non disponible.", None
        def analyze_and_set_smart_rules(self, *args, **kwargs): 
            logger.error("CardPredictor non chargé, impossible d'analyser les règles.")
            return []
        def _save_data(self, *args, **kwargs): pass
        def _verify_prediction_common(self, *args, **kwargs): return None # Ajout de la méthode de vérification
        def should_predict(self, *args): return False, None, None # Ajout de la méthode de prédiction
        def make_prediction(self, *args): return "" # Ajout de la méthode de création de prédiction
    logger.error("❌ Échec de l'importation de CardPredictor. Les fonctionnalités de prédiction seront désactivées.")
    

# Limites de débit (Logique conservée)
user_message_counts = defaultdict(list)
MAX_MESSAGES_PER_MINUTE = 30
RATE_LIMIT_WINDOW = 60

# Messages (Mise à jour des messages pour inclure /inter)
WELCOME_MESSAGE = "👋 Bienvenue ! Je suis le Bot de Prédiction. Utilisez les commandes de configuration pour démarrer."
CONFIG_PROMPT = "⚙️ Veuillez me dire à quel canal j'ai été ajouté :\n\n- Canal de **Source** (où les résultats arrivent)\n- Canal de **Prédiction** (où j'envoie les prédictions)"
HELP_MESSAGE = "🤖 **COMMANDES DISPONIBLES :**\n\n`/config` : Configure les canaux source/prédiction.\n`/inter status` : Affiche l'état du mode intelligent (apprentissage et règles Top 3).\n`/inter activate` : Active le mode intelligent avec auto-adaptation/notification 30min.\n`/inter default` : Revient au mode statique."
CONFIG_SUCCESS = "✅ **CANAL CONFIGURÉ** : Ce canal est désormais le **{type}** pour les IDs suivants :\n\n- Source (Résultats) : `{source_id}`\n- Prédiction (Envoi) : `{prediction_id}`"


class TelegramHandlers:
    
    def __init__(self, token: str):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
        
        # 🚨 MISE À JOUR CRITIQUE : Initialisation du prédicteur en lui donnant la fonction d'envoi de message
        self.card_predictor = CardPredictor(telegram_message_sender=self._send_message) 

    def _check_rate_limit(self, user_id):
        now = time.time()
        user_message_counts[user_id] = [t for t in user_message_counts[user_id] if now - t < RATE_LIMIT_WINDOW]
        user_message_counts[user_id].append(now)
        if len(user_message_counts[user_id]) > MAX_MESSAGES_PER_MINUTE:
            logger.warning(f"⚠️ Limite de débit atteinte pour l'utilisateur {user_id}")
            return False
        return True

    def _send_message(self, chat_id: int, text: str, reply_to_message_id: Optional[int] = None, reply_markup: Optional[Dict] = None) -> Optional[int]:
        """Sends a message via the Telegram API (utilisé par CardPredictor pour les notifications)."""
        if not chat_id or not text: return None
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}
            if reply_to_message_id: payload['reply_to_message_id'] = reply_to_message_id
            if reply_markup: payload['reply_markup'] = reply_markup
            
            response = requests.post(url, json=payload, timeout=5)
            result = response.json()
            if result.get('ok'):
                message_id = result.get('result', {}).get('message_id')
                return message_id
            else:
                logger.error(f"❌ Échec envoi message à {chat_id}: {result.get('description')}")
                return None
        except Exception as e:
            logger.error(f"❌ Erreur réseau lors de l'envoi du message: {e}")
            return None
    
    def _edit_message(self, chat_id: int, message_id: int, text: str, reply_markup: Optional[Dict] = None):
        """Edite un message existant."""
        if not chat_id or not message_id or not text: return
        try:
            url = f"{self.base_url}/editMessageText"
            payload = {'chat_id': chat_id, 'message_id': message_id, 'text': text, 'parse_mode': 'Markdown'}
            if reply_markup: payload['reply_markup'] = reply_markup
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            logger.error(f"❌ Erreur réseau lors de l'édition du message {message_id}: {e}")

    def _send_config_prompt(self, chat_id: int, chat_title: str):
        """Envoie le message de configuration avec les boutons inline."""
        keyboard = {
            'inline_keyboard': [
                [{'text': "1️⃣ Canal SOURCE (Résultats)", 'callback_data': 'config_source'}],
                [{'text': "2️⃣ Canal PRÉDICTION (Bot envoie)", 'callback_data': 'config_prediction'}],
                [{'text': "❌ Annuler la configuration", 'callback_data': 'config_cancel'}]
            ]
        }
        self._send_message(chat_id, f"🚨 **CONFIGURATION** : Vous m'avez ajouté à **{chat_title}**.\n\n{CONFIG_PROMPT}", reply_markup=keyboard)


    def _handle_command_config(self, message: Dict[str, Any]):
        """Gère la commande /config"""
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

    # 🚨 NOUVELLE FONCTION : Gestion de la commande /inter
    def _handle_command_inter(self, chat_id: int, text: str):
        """Gère la commande /inter pour le mode intelligent (activate, status, default)."""
        command_parts = text.lower().split()
        command = command_parts[0]
        
        if command == '/inter':
            
            action = command_parts[1] if len(command_parts) > 1 else 'status'
            
            if action == 'activate':
                logger.info(f"🧠 Commande /inter activate reçue de {chat_id}. Déclenchement de l'analyse et activation.")
                
                # Active le mode, stocke l'ID admin, et force l'analyse + notification
                self.card_predictor.analyze_and_set_smart_rules(chat_id=chat_id, force_activate=True)
                self._send_message(chat_id, "✅ **MODE INTERLIGNE ACTIF** : L'algorithme se mettra à jour et vous notifiera toutes les 30 minutes des changements de règles.")
                
            elif action == 'status':
                logger.info(f"🧠 Commande /inter status reçue de {chat_id}.")
                status_text, keyboard = self.card_predictor.get_inter_status(force_reanalyze=False) 
                self._send_message(chat_id, status_text, reply_markup=keyboard)

            elif action == 'default':
                logger.info(f"🧠 Commande /inter default reçue de {chat_id}. Désactivation du mode intelligent.")
                self.card_predictor.is_inter_mode_active = False
                # Sauvegarder la désactivation
                self.card_predictor._save_data(self.card_predictor.is_inter_mode_active, 'inter_mode_status.json') 
                self._send_message(chat_id, "❌ **MODE INTERLIGNE DÉSACTIVÉ** : Retour aux règles statiques par défaut.")

            else:
                self._send_message(chat_id, HELP_MESSAGE, reply_to_message_id=None)

            return True

        return False

    def _handle_callback_query(self, callback_query: Dict[str, Any]):
        """Gère les actions après un clic sur un bouton (callback)."""
        data = callback_query['data']
        chat_id = callback_query['message']['chat']['id']
        message_id = callback_query['message']['message_id']
        
        # 🚨 Gestion des actions INTERLIGNE venant des boutons de status
        if data == 'inter_apply':
            self.card_predictor.analyze_and_set_smart_rules(chat_id=chat_id, force_activate=True)
            self._edit_message(chat_id, message_id, "✅ **MODE INTERLIGNE ACTIVÉ** : L'algorithme se mettra à jour et vous notifiera toutes les 30 minutes des changements de règles.")
            return
        elif data == 'inter_default':
            self.card_predictor.is_inter_mode_active = False
            self.card_predictor._save_data(self.card_predictor.is_inter_mode_active, 'inter_mode_status.json')
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
            logger.info(f"⚙️ Configuration mise à jour: {channel_type} = {chat_id}")

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
            if self._handle_command_inter(chat_id, text): return # 🚨 Gestion de la commande /inter
            if self._handle_basic_commands(chat_id, text): return
            
        # 2. Logique de Prédiction/Vérification (Seulement dans les canaux)
        if chat_id == self.card_predictor.target_channel_id:
            # a. Vérification des prédictions précédentes
            verification_result = self.card_predictor._verify_prediction_common(text)
            if verification_result and verification_result['type'] == 'edit_message':
                # On édite le message envoyé par le bot (via le message_id stocké)
                predicted_game = verification_result['predicted_game']
                prediction_message_id = self.card_predictor.predictions.get(predicted_game, {}).get('message_id')
                
                if prediction_message_id and self.card_predictor.prediction_channel_id:
                    self._edit_message(
                        self.card_predictor.prediction_channel_id,
                        prediction_message_id,
                        verification_result['new_message']
                    )
                else:
                    logger.warning(f"⚠️ Échec édition message: ID de prédiction ou canal non trouvé pour le jeu {predicted_game}")
                    
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
        """Gère les messages/posts de canal édités."""
        chat_id = message['chat']['id']
        text = message.get('text', '') or message.get('caption', '')
        
        if chat_id == self.card_predictor.target_channel_id:
            # Logique de vérification pour les messages édités
            verification_result = self.card_predictor._verify_prediction_common(text, is_edited=True)
            if verification_result and verification_result['type'] == 'edit_message':
                 # On édite le message envoyé par le bot (via le message_id stocké)
                predicted_game = verification_result['predicted_game']
                prediction_message_id = self.card_predictor.predictions.get(predicted_game, {}).get('message_id')
                
                if prediction_message_id and self.card_predictor.prediction_channel_id:
                    self._edit_message(
                        self.card_predictor.prediction_channel_id,
                        prediction_message_id,
                        verification_result['new_message']
                    )
                else:
                    logger.warning(f"⚠️ Échec édition message édité: ID de prédiction ou canal non trouvé pour le jeu {predicted_game}")
                    

    def _handle_basic_commands(self, chat_id: int, text: str):
        """Gère les commandes simples."""
        text = text.lower().split()[0]
        if text == '/start':
            self._send_message(chat_id, WELCOME_MESSAGE)
            return True
        elif text == '/help':
            self._send_message(chat_id, HELP_MESSAGE)
            return True
        return False

    def handle_update(self, update: Dict[str, Any]) -> None:
        """Point d'entrée principal pour traiter les updates du webhook."""
        try:
            # 1. GESTION DES CALLBACKS (clics sur boutons)
            if 'callback_query' in update:
                self._handle_callback_query(update['callback_query'])
                
            # 2. GESTION DES STATUTS DE MEMBRE (ajout/promotion du bot)
            elif 'my_chat_member' in update:
                my_chat_member = update['my_chat_member']
                # Si le statut change vers 'member' ou 'administrator'
                new_status = my_chat_member['new_chat_member']['status']
                
                # Le token est dans self.token, la partie bot_id est avant le ":"
                bot_id = int(self.token.split(':')[0]) 
                
                if new_status in ['member', 'administrator']:
                    # Vérifie que c'est bien notre bot
                    if my_chat_member['new_chat_member']['user']['id'] == bot_id:
                        chat_id = my_chat_member['chat']['id']
                        chat_title = my_chat_member['chat'].get('title', f'Chat ID: {chat_id}')
                        chat_type = my_chat_member['chat'].get('type', 'private')
                        
                        # Déclenche le prompt de configuration si c'est un groupe ou un canal
                        if chat_type in ['channel', 'group', 'supergroup']:
                            logger.info(f"✨ BOT AJOUTÉ/PROMU : Envoi du prompt de configuration à {chat_title} ({chat_id})")
                            self._send_config_prompt(chat_id, chat_title)
            
            # 3. GESTION DES MESSAGES/POSTS
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
