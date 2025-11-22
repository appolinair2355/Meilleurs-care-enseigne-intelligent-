# card_predictor.py

import re
import logging
import time
import os
import json
from datetime import datetime
from typing import Optional, Dict, List, Tuple, Any
from collections import defaultdict

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# --- CONSTANTES ---
HIGH_VALUE_CARDS = ["A", "K", "Q", "J"] 
CARD_SYMBOLS = [r"♠️", r"♥️", r"♦️", r"♣️", r"❤️"]
INTER_SUITS = ['♠️', '♥️', '♦️', '♣️'] 
SYMBOL_MAP = {1: '✅', 2: '✅'}

class CardPredictor:
    """Gère la logique de prédiction de carte Roi (K) et la vérification."""

    def __init__(self, telegram_message_sender=None):
        # 1. Données de persistance
        self.predictions = self._load_data('predictions.json') 
        self.processed_messages = self._load_data('processed.json', is_set=True) 
        self.last_prediction_time = self._load_data('last_prediction_time.json', is_scalar=True)
        
        # 2. Configuration des canaux (CORRECTION DU BUG 'list object has no attribute get')
        self.config_data = self._load_data('channels_config.json')
        if not isinstance(self.config_data, dict):
            self.config_data = {} # Force le type dictionnaire si le fichier est corrompu ou vide
            
        self.target_channel_id = self.config_data.get('target_channel_id', None)
        self.prediction_channel_id = self.config_data.get('prediction_channel_id', None)
        
        # 3. Logique INTER et Notification
        self.telegram_message_sender = telegram_message_sender
        self.active_admin_chat_id = self._load_data('active_admin_chat_id.json', is_scalar=True)
        
        self.sequential_history: Dict[int, Dict] = self._load_data('sequential_history.json') 
        self.inter_data: List[Dict] = self._load_data('inter_data.json') 
        self.is_inter_mode_active = self._load_data('inter_mode_status.json', is_scalar=True)
        self.smart_rules = self._load_data('smart_rules.json')
        self.last_analysis_time = self._load_data('last_analysis_time.json', is_scalar=True) or 0
        self.prediction_cooldown = 30 
        
        # Analyse initiale si nécessaire
        if self.inter_data and not self.is_inter_mode_active and not self.smart_rules:
             self.analyze_and_set_smart_rules(initial_load=True)

    # --- Persistance des Données ---
    def _load_data(self, filename: str, is_set: bool = False, is_scalar: bool = False) -> Any:
        try:
            if not os.path.exists(filename):
                return set() if is_set else (None if is_scalar else ({} if filename == 'channels_config.json' else []))
                
            with open(filename, 'r') as f:
                content = f.read().strip()
                if not content: 
                    return set() if is_set else (None if is_scalar else {})
                data = json.loads(content)
                
                if is_set: return set(data)
                
                # Conversion spéciale pour l'historique séquentiel (clés int)
                if filename == 'sequential_history.json' and isinstance(data, dict): 
                    return {int(k): v for k, v in data.items()}
                
                return data
        except Exception as e:
            logger.error(f"⚠️ Erreur chargement {filename}: {e}. Utilisation valeur par défaut.")
            return set() if is_set else (None if is_scalar else {})

    def _save_data(self, data: Any, filename: str):
        try:
            if isinstance(data, set): data = list(data)
            with open(filename, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logger.error(f"❌ Erreur sauvegarde {filename}: {e}")

    def _save_all_data(self):
        self._save_data(self.predictions, 'predictions.json')
        self._save_data(self.processed_messages, 'processed.json')
        self._save_data(self.last_prediction_time, 'last_prediction_time.json')
        self._save_data(self.inter_data, 'inter_data.json')
        self._save_data(self.sequential_history, 'sequential_history.json')
        self._save_data(self.is_inter_mode_active, 'inter_mode_status.json')
        self._save_data(self.smart_rules, 'smart_rules.json')
        self._save_data(self.active_admin_chat_id, 'active_admin_chat_id.json')
        self._save_data(self.last_analysis_time, 'last_analysis_time.json')

    def _save_channels_config(self):
        # Assure que config_data est un dictionnaire avant sauvegarde
        if not isinstance(self.config_data, dict): self.config_data = {}
        self.config_data['target_channel_id'] = self.target_channel_id
        self.config_data['prediction_channel_id'] = self.prediction_channel_id
        self._save_data(self.config_data, 'channels_config.json')

    def set_channel_id(self, channel_id: int, channel_type: str):
        if channel_type == 'source':
            self.target_channel_id = channel_id
        elif channel_type == 'prediction':
            self.prediction_channel_id = channel_id
        self._save_channels_config()
        return True

    # --- Extraction ---
    def extract_game_number(self, message: str) -> Optional[int]:
        match = re.search(r'#N(\d+)\.', message, re.IGNORECASE) 
        if not match: match = re.search(r'🔵(\d+)🔵', message)
        return int(match.group(1)) if match else None

    def extract_first_parentheses_content(self, message: str) -> Optional[str]:
        match = re.search(r'\(([^)]*)\)', message)
        return match.group(1).strip() if match else None

    def extract_card_details(self, content: str) -> List[Tuple[str, str]]:
        normalized_content = content.replace("❤️", "♥️")
        return re.findall(r'(\d+|[AKQJ])(♠️|♥️|♦️|♣️)', normalized_content, re.IGNORECASE)

    def get_first_two_cards(self, content: str) -> List[str]:
        card_details = self.extract_card_details(content)
        return [f"{v.upper()}{c}" for v, c in card_details[:2]]

    def check_value_K_in_first_parentheses(self, message: str) -> Optional[Tuple[str, str]]:
        content = self.extract_first_parentheses_content(message)
        if not content: return None
        for v, c in self.extract_card_details(content):
            if v.upper() == "K": return (v.upper(), c)
        return None

    # --- Logique INTER ---
    def collect_inter_data(self, game_number: int, message: str):
        content = self.extract_first_parentheses_content(message)
        if not content: return

        # 1. Enregistrer le déclencheur (N)
        first_two = self.get_first_two_cards(content)
        if len(first_two) >= 1: # On accepte même une seule carte
            self.sequential_history[game_number] = {'cartes': first_two, 'date': datetime.now().isoformat()}
        
        # 2. Vérifier résultat (K)
        k_card = self.check_value_K_in_first_parentheses(message)
        if k_card:
            n_minus_2 = game_number - 2
            trigger = self.sequential_history.get(n_minus_2)
            if trigger:
                # Anti-doublon
                if not any(e.get('numero_resultat') == game_number for e in self.inter_data):
                    self.inter_data.append({
                        'numero_resultat': game_number,
                        'declencheur': trigger['cartes'],
                        'numero_declencheur': n_minus_2,
                        'carte_k': f"{k_card[0]}{k_card[1]}",
                        'date_resultat': datetime.now().isoformat()
                    })
                    self._save_all_data()

        # Nettoyage
        limit = game_number - 50
        self.sequential_history = {k:v for k,v in self.sequential_history.items() if k >= limit}

    def analyze_and_set_smart_rules(self, chat_id: int = None, initial_load: bool = False, force_activate: bool = False):
        # 1. Analyse simple: trouver les déclencheurs les plus fréquents qui donnent K
        counts = defaultdict(int)
        for entry in self.inter_data:
            # Utilise la première carte du déclencheur comme clé simple
            if entry['declencheur']:
                key = entry['declencheur'][0]
                counts[key] += 1
        
        # Top 3
        sorted_rules = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:3]
        self.smart_rules = [{'cards': [card], 'count': count} for card, count in sorted_rules]
        
        # Gestion activation
        if force_activate:
            self.is_inter_mode_active = True
            if chat_id: self.active_admin_chat_id = chat_id
        elif self.smart_rules and not initial_load:
            self.is_inter_mode_active = True
        elif not initial_load:
            self.is_inter_mode_active = False
            
        self.last_analysis_time = time.time()
        self._save_all_data()
        
        # Notification
        if self.active_admin_chat_id and self.telegram_message_sender and (force_activate or self.is_inter_mode_active):
            msg = "🧠 **MISE À JOUR INTER**\nRègles Top 3 (Déclencheur -> K):\n"
            for r in self.smart_rules:
                msg += f"- {r['cards'][0]} (x{r['count']})\n"
            self.telegram_message_sender(self.active_admin_chat_id, msg)

    def get_inter_status(self, force_reanalyze: bool = False) -> Tuple[str, Optional[Dict]]:
        if force_reanalyze: self.analyze_and_set_smart_rules()
        
        msg = f"**STATUT INTER**\nActif: {'✅' if self.is_inter_mode_active else '❌'}\nHistorique: {len(self.inter_data)}"
        if self.smart_rules:
            msg += "\n\n**Top Règles:**\n" + "\n".join([f"- {r['cards'][0]} (x{r['count']})" for r in self.smart_rules])
            
        kb = {'inline_keyboard': [[{'text': 'Activer/Update', 'callback_data': 'inter_apply'}, {'text': 'Désactiver', 'callback_data': 'inter_default'}]]}
        return msg, kb

    # --- Prédiction ---
    def should_predict(self, message: str) -> Tuple[bool, Optional[int], Optional[str]]:
        if not self.target_channel_id: return False, None, None
        game_number = self.extract_game_number(message)
        if not game_number: return False, None, None
        
        self.collect_inter_data(game_number, message)
        
        # Vérification 30 min
        if self.is_inter_mode_active and (time.time() - (self.last_analysis_time or 0) > 1800):
            self.analyze_and_set_smart_rules(chat_id=self.active_admin_chat_id)

        if '🕐' in message or '⏰' in message: return False, None, None
        if '✅' not in message and '🔰' not in message: return False, None, None
        
        if self.last_prediction_time and time.time() < self.last_prediction_time + 30:
            return False, None, None

        # Logique simple: si règle correspond -> Prédire K
        first_content = self.extract_first_parentheses_content(message)
        if first_content:
            cards = self.get_first_two_cards(first_content)
            if cards:
                # Si Inter actif, vérifier si carte match une règle
                if self.is_inter_mode_active and self.smart_rules:
                    if any(cards[0] == r['cards'][0] for r in self.smart_rules):
                        self.last_prediction_time = time.time()
                        self._save_all_data()
                        return True, game_number, "K"
                
                # Règle Statique simple (Ex: Valet J)
                if "J" in first_content:
                     self.last_prediction_time = time.time()
                     self._save_all_data()
                     return True, game_number, "K"

        return False, None, None

    def make_prediction(self, game_number: int, value: str) -> str:
        target = game_number + 2
        txt = f"🔵{target}🔵:Valeur K statut :⏳"
        self.predictions[target] = {
            'predicted_costume': 'K', 'status': 'pending', 'predicted_from': game_number, 
            'message_text': txt, 'message_id': None
        }
        self._save_all_data()
        return txt

    def _verify_prediction_common(self, text: str, is_edited: bool = False) -> Optional[Dict]:
        game_number = self.extract_game_number(text)
        if not game_number: return None
        
        pred_game = game_number - 2
        if pred_game in self.predictions:
            pred = self.predictions[pred_game]
            if pred['status'] != 'pending': return None
            
            k_found = self.check_value_K_in_first_parentheses(text)
            if k_found:
                msg = f"🔵{pred_game}🔵:Valeur K statut :✅"
                pred['status'] = 'correct'
                pred['final_message'] = msg
                self._save_all_data()
                return {'type': 'edit_message', 'predicted_game': pred_game, 'new_message': msg}
            
            # Échec simple si pas trouvé (à affiner si vous voulez attendre +2 offsets)
            # Ici on assume échec immédiat pour simplifier le fix
            msg = f"🔵{pred_game}🔵:Valeur K statut :❌"
            pred['status'] = 'failed'
            pred['final_message'] = msg
            self._save_all_data()
            return {'type': 'edit_message', 'predicted_game': pred_game, 'new_message': msg}
            
        return None
