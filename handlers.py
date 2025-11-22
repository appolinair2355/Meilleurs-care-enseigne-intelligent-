# handlers.py

import logging
import time
import json
from collections import defaultdict
from typing import Dict, Any, Optional
import requests

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# --- IMPORT CARDPREDICTOR ---
try:
    from card_predictor import CardPredictor
except ImportError:
    logger.error("❌ IMPOSSIBLE D'IMPORTER CARDPREDICTOR")
    CardPredictor = None

user_message_counts = defaultdict(list)

class TelegramHandlers:
    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        
        if CardPredictor:
            # 🚨 ICI ON PASSE LA FONCTION POUR QUE LE BOT PUISSE ENVOYER DES NOTIFS 30MIN
            self.card_predictor = CardPredictor(telegram_message_sender=self.send_message)
        else:
            self.card_predictor = None

    # --- MESSAGERIE ---
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

    # --- GESTION COMMANDE /inter ---
    def _handle_command_inter(self, chat_id: int, text: str):
        if not self.card_predictor: return
        parts = text.lower().split()
        
        # Par défaut 'status' si pas d'argument
        action = parts[1] if len(parts) > 1 else 'status'
        
        if action == 'activate':
            self.card_predictor.analyze_and_set_smart_rules(chat_id=chat_id, force_activate=True)
            self.send_message(chat_id, "✅ **MODE INTER ACTIVÉ**\nLe bot analyse l'historique et s'adapte toutes les 30 minutes.")
        
        elif action == 'default':
            self.card_predictor.is_inter_mode_active = False
            self.card_predictor._save_all_data()
            self.send_message(chat_id, "❌ **MODE INTER DÉSACTIVÉ**\nRetour aux règles statiques (10♦️->♠️, etc).")
            
        elif action == 'status':
            msg, kb = self.card_predictor.get_inter_status()
            self.send_message(chat_id, msg, reply_markup=kb)
        
        else:
            self.send_message(chat_id, "Commande inconnue. Utilisez: `/inter status`, `/inter activate`, `/inter default`")

    # --- CALLBACKS (BOUTONS) ---
    def _handle_callback_query(self, update_obj):
        data = update_obj['data']
        chat_id = update_obj['message']['chat']['id']
        msg_id = update_obj['message']['message_id']
        
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
                self.send_message(chat_id, f"✅ Ce canal est maintenant défini comme **{type_c.upper()}**.", message_id=msg_id, edit=True)

    # --- UPDATES ---
    def handle_update(self, update: Dict[str, Any]):
        try:
            # 1. Messages Texte
            if 'message' in update and 'text' in update['message']:
                msg = update['message']
                chat_id = msg['chat']['id']
                text = msg['text']
                
                # Commandes
                if text.startswith('/inter'):
                    self._handle_command_inter(chat_id, text)
                elif text.startswith('/config'):
                    kb = {'inline_keyboard': [[{'text': 'Source', 'callback_data': 'config_source'}, {'text': 'Prediction', 'callback_data': 'config_prediction'}, {'text': 'Annuler', 'callback_data': 'config_cancel'}]]}
                    self.send_message(chat_id, "⚙️ **CONFIGURATION**\nQuel est le rôle de ce canal ?", reply_markup=kb)
                
                # Traitement Canal Source (Lecture/Prédiction)
                # Note: on convertit en str pour être sûr de la comparaison
                elif self.card_predictor and str(chat_id) == str(self.card_predictor.target_channel_id):
                    
                    # A. Vérifier les prédictions existantes
                    res = self.card_predictor._verify_prediction_common(text)
                    if res and res['type'] == 'edit_message':
                        # Récupérer l'ID du message de prédiction envoyé
                        # La clé est 'predicted_game' qui est un string dans le JSON renvoyé par _verify
                        pred_game_str = res['predicted_game']
                        pred_data = self.card_predictor.predictions.get(pred_game_str)
                        
                        # Si on ne le trouve pas avec la clé string, essayer int
                        if not pred_data:
                             pred_data = self.card_predictor.predictions.get(int(pred_game_str))

                        if pred_data:
                            mid = pred_data.get('message_id')
                            if mid: 
                                self.send_message(self.card_predictor.prediction_channel_id, res['new_message'], message_id=mid, edit=True)
                    
                    # B. Faire une nouvelle prédiction
                    ok, num, val = self.card_predictor.should_predict(text)
                    if ok:
                        txt = self.card_predictor.make_prediction(num, val)
                        mid = self.send_message(self.card_predictor.prediction_channel_id, txt)
                        if mid:
                            # Sauvegarder l'ID du message envoyé pour pouvoir l'éditer plus tard
                            # La clé doit correspondre à ce qui est utilisé dans make_prediction (num + 2)
                            target_game = str(num + 2) # Utiliser string pour cohérence JSON
                            # Si make_prediction a sauvé en int, convertir
                            if int(target_game) in self.card_predictor.predictions:
                                self.card_predictor.predictions[int(target_game)]['message_id'] = mid
                            elif target_game in self.card_predictor.predictions:
                                self.card_predictor.predictions[target_game]['message_id'] = mid
                            
                            self.card_predictor._save_all_data()

            # 2. Callbacks
            elif 'callback_query' in update:
                self._handle_callback_query(update['callback_query'])
                
        except Exception as e:
            logger.error(f"Erreur Update: {e}")
        
