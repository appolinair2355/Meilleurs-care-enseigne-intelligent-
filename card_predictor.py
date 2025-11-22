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

# --- 1. RÈGLES STATIQUES (13 Règles) ---
STATIC_RULES = {
    "10♦️": "♠️", "10♠️": "❤️", 
    "9♣️": "❤️", "9♦️": "♠️",
    "8♣️": "♠️", "8♠️": "♣️", 
    "7♠️": "♠️", "7♣️": "♣️",
    "6♦️": "♣️", "6♣️": "♦️", 
    "A❤️": "❤️", 
    "5❤️": "❤️", "5♠️": "♠️"
}

class CardPredictor:
    """Gère la logique de prédiction d'enseigne (suit)."""

    def __init__(self, telegram_message_sender=None):
        # Chargement sécurisé des données
        self.predictions = self._load_data('predictions.json') 
        self.processed_messages = self._load_data('processed.json', is_set=True) 
        self.last_prediction_time = self._load_data('last_prediction_time.json', is_scalar=True) or 0
        self.last_predicted_game_number = self._load_data('last_predicted_game_number.json', is_scalar=True) or 0
        
        # Config Canaux
        raw_config = self._load_data('channels_config.json')
        self.config_data = raw_config if isinstance(raw_config, dict) else {}
        self.target_channel_id = self.config_data.get('target_channel_id', None)
        self.prediction_channel_id = self.config_data.get('prediction_channel_id', None)
        
        # Logique INTER
        self.telegram_message_sender = telegram_message_sender
        self.active_admin_chat_id = self._load_data('active_admin_chat_id.json', is_scalar=True)
        self.sequential_history: Dict[int, Dict] = self._load_data('sequential_history.json') 
        self.inter_data: List[Dict] = self._load_data('inter_data.json') 
        self.is_inter_mode_active = self._load_data('inter_mode_status.json', is_scalar=True)
        self.smart_rules = self._load_data('smart_rules.json')
        self.last_analysis_time = self._load_data('last_analysis_time.json', is_scalar=True) or 0
        
        # Analyse initiale
        if self.inter_data and not self.is_inter_mode_active and not self.smart_rules:
             self.analyze_and_set_smart_rules(initial_load=True)

    # --- PERSISTANCE ---
    def _load_data(self, filename: str, is_set: bool = False, is_scalar: bool = False) -> Any:
        try:
            if not os.path.exists(filename):
                return set() if is_set else (None if is_scalar else ({} if filename == 'channels_config.json' else []))
            with open(filename, 'r') as f:
                content = f.read().strip()
                if not content: return set() if is_set else (None if is_scalar else {})
                data = json.loads(content)
                if is_set: return set(data)
                if filename == 'sequential_history.json' and isinstance(data, dict): 
                    return {int(k): v for k, v in data.items()}
                if filename == 'predictions.json' and isinstance(data, dict):
                    return {int(k): v for k, v in data.items()} # Clés en int pour predictions
                return data
        except Exception as e:
            logger.error(f"⚠️ Erreur chargement {filename}: {e}")
            return set() if is_set else (None if is_scalar else {})

    def _save_data(self, data: Any, filename: str):
        try:
            if isinstance(data, set): data = list(data)
            with open(filename, 'w') as f: json.dump(data, f, indent=4)
        except Exception as e: logger.error(f"❌ Erreur sauvegarde {filename}: {e}")

    def _save_all_data(self):
        self._save_data(self.predictions, 'predictions.json')
        self._save_data(self.processed_messages, 'processed.json')
        self._save_data(self.last_prediction_time, 'last_prediction_time.json')
        self._save_data(self.last_predicted_game_number, 'last_predicted_game_number.json')
        self._save_data(self.inter_data, 'inter_data.json')
        self._save_data(self.sequential_history, 'sequential_history.json')
        self._save_data(self.is_inter_mode_active, 'inter_mode_status.json')
        self._save_data(self.smart_rules, 'smart_rules.json')
        self._save_data(self.active_admin_chat_id, 'active_admin_chat_id.json')
        self._save_data(self.last_analysis_time, 'last_analysis_time.json')

    def set_channel_id(self, channel_id: int, channel_type: str):
        if not isinstance(self.config_data, dict): self.config_data = {}
        if channel_type == 'source':
            self.target_channel_id = channel_id
            self.config_data['target_channel_id'] = channel_id
        elif channel_type == 'prediction':
            self.prediction_channel_id = channel_id
            self.config_data['prediction_channel_id'] = channel_id
        self._save_data(self.config_data, 'channels_config.json')
        return True

    # --- EXTRACTION ---
    def extract_game_number(self, message: str) -> Optional[int]:
        match = re.search(r'#N(\d+)\.', message, re.IGNORECASE) 
        if not match: match = re.search(r'🔵(\d+)🔵', message)
        return int(match.group(1)) if match else None

    def extract_card_details(self, content: str) -> List[Tuple[str, str]]:
        content = content.replace("♥️", "❤️") # Normalisation
        return re.findall(r'(\d+|[AKQJ])(♠️|❤️|♦️|♣️)', content, re.IGNORECASE)

    def get_first_card_info(self, message: str) -> Optional[Tuple[str, str]]:
        """Retourne (CarteComplète, Enseigne) de la 1ère carte du 1er groupe."""
        match = re.search(r'\(([^)]*)\)', message)
        if not match: return None
        details = self.extract_card_details(match.group(1))
        if details:
            v, c = details[0]
            return f"{v.upper()}{c}", c
        return None

    # --- LOGIQUE INTER ---
    def collect_inter_data(self, game_number: int, message: str):
        info = self.get_first_card_info(message)
        if not info: return
        
        full_card, suit = info

        # 1. Stocker le déclencheur potentiel (N)
        self.sequential_history[game_number] = {'carte': full_card, 'date': datetime.now().isoformat()}
        
        # 2. Vérifier si c'est un résultat (Enseigne) pour N-2
        n_minus_2 = game_number - 2
        trigger_entry = self.sequential_history.get(n_minus_2)
        
        if trigger_entry:
            trigger_card = trigger_entry['carte']
            # Anti-doublon
            if not any(e.get('numero_resultat') == game_number for e in self.inter_data):
                self.inter_data.append({
                    'numero_resultat': game_number,
                    'declencheur': trigger_card, 
                    'numero_declencheur': n_minus_2,
                    'result_suit': suit,
                    'date': datetime.now().isoformat()
                })
                self._save_all_data()

        # Nettoyage
        limit = game_number - 50
        self.sequential_history = {k:v for k,v in self.sequential_history.items() if k >= limit}

    def analyze_and_set_smart_rules(self, chat_id: int = None, initial_load: bool = False, force_activate: bool = False):
        # Analyse : Quelle enseigne suit quelle carte ?
        counts = defaultdict(lambda: defaultdict(int))
        for entry in self.inter_data:
            counts[entry['declencheur']][entry['result_suit']] += 1
            
        candidates = []
        for trig, results in counts.items():
            best_suit = max(results, key=results.get)
            count = results[best_suit]
            candidates.append({'trigger': trig, 'predict': best_suit, 'count': count})
            
        # Top 3
        self.smart_rules = sorted(candidates, key=lambda x: x['count'], reverse=True)[:3]
        
        # Activation
        if force_activate:
            self.is_inter_mode_active = True
            if chat_id: self.active_admin_chat_id = chat_id
        elif self.smart_rules and not initial_load:
            self.is_inter_mode_active = True
        elif not initial_load:
            self.is_inter_mode_active = False
            
        self.last_analysis_time = time.time()
        self._save_all_data()
        
        # Notification Admin
        if self.active_admin_chat_id and self.telegram_message_sender and (force_activate or self.is_inter_mode_active):
            msg = "🧠 **MISE À JOUR INTER (30min)**\n\n"
            if self.smart_rules:
                for r in self.smart_rules:
                    msg += f"🥇 {r['trigger']} → {r['predict']} (x{r['count']})\n"
            else:
                msg += "Aucune règle fiable trouvée."
            self.telegram_message_sender(self.active_admin_chat_id, msg)

    def get_inter_status(self, force_reanalyze: bool = False) -> Tuple[str, Optional[Dict]]:
        if force_reanalyze: self.analyze_and_set_smart_rules()
        
        msg = f"**🧠 ETAT DU MODE INTELLIGENT**\n\n"
        msg += f"**Actif :** {'✅ OUI' if self.is_inter_mode_active else '❌ NON'}\n"
        msg += f"**Données :** {len(self.inter_data)}\n\n"
        
        if self.smart_rules:
            msg += "**📜 Règles Actives (Top 3):**\n"
            for r in self.smart_rules:
                msg += f"• Si **{r['trigger']}** (N-2) → Prédire **{r['predict']}** (x{r['count']})\n"
        else:
            msg += "⚠️ Pas de règles."
            
        kb = {'inline_keyboard': [
            [{'text': '✅ Activer / Update', 'callback_data': 'inter_apply'}],
            [{'text': '❌ Désactiver', 'callback_data': 'inter_default'}]
        ]}
        return msg, kb

    # --- PRÉDICTION ---
    def should_predict(self, message: str) -> Tuple[bool, Optional[int], Optional[str]]:
        # 1. Vérif Périodique
        if self.is_inter_mode_active and (time.time() - self.last_analysis_time > 1800):
            self.analyze_and_set_smart_rules(chat_id=self.active_admin_chat_id)
        
        if not self.target_channel_id: return False, None, None
        game_number = self.extract_game_number(message)
        if not game_number: return False, None, None
        
        # 2. Collecte
        self.collect_inter_data(game_number, message)
        
        # 3. Filtres (Attente, Ecart 3 jeux)
        if '🕐' in message or '⏰' in message: return False, None, None
        if '✅' not in message and '🔰' not in message: return False, None, None
        
        if self.last_predicted_game_number and (game_number - self.last_predicted_game_number < 3):
            return False, None, None

        # 4. Décision
        info = self.get_first_card_info(message)
        if not info: return False, None, None
        first_card, _ = info
        
        predicted_suit = None

        # A. INTER
        if self.is_inter_mode_active and self.smart_rules:
            for rule in self.smart_rules:
                if rule['trigger'] == first_card:
                    predicted_suit = rule['predict']
                    logger.info(f"🔮 INTER: {first_card} -> {predicted_suit}")
                    break
        
        # B. STATIQUE (Si pas de prédiction INTER)
        if not predicted_suit and first_card in STATIC_RULES:
            predicted_suit = STATIC_RULES[first_card]
            logger.info(f"🔮 STATIQUE: {first_card} -> {predicted_suit}")

        if predicted_suit:
            # Cooldown temps (30s)
            if self.last_prediction_time and time.time() < self.last_prediction_time + 30:
                return False, None, None
                
            self.last_prediction_time = time.time()
            self.last_predicted_game_number = game_number
            self._save_all_data()
            return True, game_number, predicted_suit

        return False, None, None

    def make_prediction(self, game_number: int, suit: str) -> str:
        target = game_number + 2
        txt = f"🔵{target}🔵:Enseigne {suit} statut :⏳"
        self.predictions[target] = {
            'predicted_costume': suit, 'status': 'pending', 'predicted_from': game_number, 
            'message_text': txt, 'message_id': None
        }
        self._save_all_data()
        return txt

    def _verify_prediction_common(self, text: str, is_edited: bool = False) -> Optional[Dict]:
        game_number = self.extract_game_number(text)
        if not game_number: return None
        
        # On vérifie les jeux stockés
        # On fait une copie des items pour itérer en sécurité
        for pred_game, pred_data in list(self.predictions.items()):
            if pred_data['status'] != 'pending': continue
            
            offset = game_number - int(pred_game)
            if not (0 <= offset <= 2): continue
            
            # Résultat dans le message actuel
            info = self.get_first_card_info(text)
            found_suit = info[1] if info else None
            predicted = pred_data['predicted_costume']
            
            if found_suit == predicted:
                symbol = f"✅{offset}️⃣"
                msg = f"🔵{pred_game}🔵:Enseigne {predicted} statut :{symbol}"
                pred_data['status'] = 'won'
                self._save_all_data()
                return {'type': 'edit_message', 'predicted_game': str(pred_game), 'new_message': msg}
            
            elif offset == 2:
                msg = f"🔵{pred_game}🔵:Enseigne {predicted} statut :❌"
                pred_data['status'] = 'lost'
                self._save_all_data()
                return {'type': 'edit_message', 'predicted_game': str(pred_game), 'new_message': msg}
                
        return None
