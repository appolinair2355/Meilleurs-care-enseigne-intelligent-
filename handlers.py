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
    logger.error("❌ Erreur Import CardPredictor")
    CardPredictor = None

user_message_counts = defaultdict(list)

class TelegramHandlers:
    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        
        if CardPredictor:
            # On passe la fonction d'envoi pour les notifs INTER
            self.card_predictor = CardPredictor(telegram_message_sender=self.send_message)
        else:
            self.card_predictor = None

    def send_message(self, chat_id: int, text: str, parse_mode='Markdown', message_id: Optional[int] = None, edit=False, reply_markup: Optional[Dict] = None) -> Optional[int]:
        """Envoie ou édite un message."""
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
                logger.error(f"Erreur API Telegram: {r.text}")
        except Exception as e:
            logger.error(f"Exception Telegram: {e}")
        return None

    def _handle_command_inter(self, chat_id: int, text: str):
        if not self.card_predictor: return
        parts = text.lower().split()
        action = parts[1] if len(parts) > 1 else 'status'
        
        if action == 'activate':
            self.card_predictor.analyze_and_set_smart_rules(chat_id=chat_id, force_activate=True)
            self.send_message(chat_id, "✅ **INTER ACTIVÉ** (Auto-update 30min)")
        elif action == 'default':
            self.card_predictor.is_inter_mode_active = False
            self.card_predictor._save_all_data()
            self.send_message(chat_id, "❌ **INTER DÉSACTIVÉ**")
        else:
            msg, kb = self.card_predictor.get_inter_status()
            self.send_message(chat_id, msg, reply_markup=kb)

    def _handle_callback_query(self, update_obj):
        data = update_obj['data']
        chat_id = update_obj['message']['chat']['id']
        
        if data == 'inter_apply':
            self.card_predictor.analyze_and_set_smart_rules(chat_id=chat_id, force_activate=True)
            self.send_message(chat_id, "✅ Mode Intelligent Appliqué!")
        elif data == 'inter_default':
            self.card_predictor.is_inter_mode_active = False
            self.card_predictor._save_all_data()
            self.send_message(chat_id, "❌ Mode Défaut activé.")
        elif data.startswith('config_'):
            # Logique simplifiée configuration
            type_c = 'source' if 'source' in data else 'prediction'
            if 'cancel' in data:
                self.send_message(chat_id, "Annulé.")
            else:
                self.card_predictor.set_channel_id(chat_id, type_c)
                self.send_message(chat_id, f"✅ Canal {type_c.upper()} configuré!")

    def handle_update(self, update: Dict[str, Any]):
        try:
            if 'message' in update and 'text' in update['message']:
                msg = update['message']
                chat_id = msg['chat']['id']
                text = msg['text']
                
                # Commandes
                if text.startswith('/inter'):
                    self._handle_command_inter(chat_id, text)
                elif text.startswith('/config'):
                    kb = {'inline_keyboard': [[{'text': 'Source', 'callback_data': 'config_source'}, {'text': 'Pred', 'callback_data': 'config_prediction'}]]}
                    self.send_message(chat_id, "Config?", reply_markup=kb)
                
                # Traitement canal source
                elif self.card_predictor and chat_id == self.card_predictor.target_channel_id:
                    # Vérif
                    res = self.card_predictor._verify_prediction_common(text)
                    if res and res['type'] == 'edit_message':
                        mid = self.card_predictor.predictions[res['predicted_game']].get('message_id')
                        if mid: self.send_message(self.card_predictor.prediction_channel_id, res['new_message'], message_id=mid, edit=True)
                    
                    # Prédiction
                    ok, num, val = self.card_predictor.should_predict(text)
                    if ok:
                        txt = self.card_predictor.make_prediction(num, val)
                        mid = self.send_message(self.card_predictor.prediction_channel_id, txt)
                        if mid:
                            self.card_predictor.predictions[num+2]['message_id'] = mid
                            self.card_predictor._save_all_data()

            elif 'callback_query' in update:
                self._handle_callback_query(update['callback_query'])
                
        except Exception as e:
            logger.error(f"Update error: {e}")
