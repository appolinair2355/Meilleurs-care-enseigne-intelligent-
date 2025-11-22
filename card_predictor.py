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

# --- RÈGLES STATIQUES (13 Règles Exactes) ---
STATIC_RULES = {
    "10♦️": "♠️", "10♠️": "❤️", 
    "9♣️": "❤️", "9♦️": "♠️",
    "8♣️": "♠️", "8♠️": "♣️", 
    "7♠️": "♠️", "7♣️": "♣️",
    "6♦️": "♣️", "6♣️": "♦️", 
    "A❤️": "❤️", 
    "5❤️": "❤️", "5♠️": "♠️"
}

# Symboles pour les status de vérification
SYMBOL_MAP = {0: '✅0️⃣', 1: '✅1️⃣', 2: '✅2️⃣'}

class CardPredictor:
    """
    Gère la logique de prédiction d'ENSEIGNE (Couleur).
    Inclut: Mode Statique, Mode INTER (Apprentissage N-2), Gestion 30min.
    """

    def __init__(self, telegram_message_sender=None):
        # --- Chargement Sécurisé (Anti-Crash Render) ---
        self.predictions = self._load_data('predictions.json') 
        self.processed_messages = self._load_data('processed.json', is_set=True) 
        self.last_prediction_time = self._load_data('last_prediction_time.json', is_scalar=True) or 0
        self.last_predicted_game_number = self._load_data('last_predicted_game_number.json', is_scalar=True) or 0
        self.consecutive_fails = self._load_data('consecutive_fails.json', is_scalar=True) or 0
        
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
        
        # Si données présentes mais pas de règles, on force une analyse au démarrage
        if self.inter_data and not self.smart_rules:
             self.analyze_and_set_smart_rules(initial_load=True)

    # --- Persistance Robuste ---
    def _load_data(self, filename: str, is_set: bool = False, is_scalar: bool = False) -> Any:
        """Charge les données sans faire planter le bot si le fichier manque."""
        default = set() if is_set else (None if is_scalar else ({} if filename in ['predictions.json', 'sequential_history.json'] else []))
        try:
            if not os.path.exists(filename): return default
            with open(filename, 'r') as f:
                content = f.read().strip()
                if not content: return default
                data = json.loads(content)
                
                if is_set: return set(data)
                # Conversion des clés en int pour les dictionnaires indexés par numéro de jeu
                if filename in ['sequential_history.json', 'predictions.json'] and isinstance(data, dict):
                    return {int(k): v for k, v in data.items()}
                return data
        except Exception:
            return default

    def _save_data(self, data: Any, filename: str):
        """Sauvegarde 'Best Effort' (Si ça échoue sur Render, on ignore)."""
        try:
            if isinstance(data, set): data = list(data)
            with open(filename, 'w') as f: json.dump(data, f, indent=4)
        except Exception: pass

    def _save_all_data(self):
        """Sauvegarde tout."""
        self._save_data(self.predictions, 'predictions.json')
        self._save_data(self.processed_messages, 'processed.json')
        self._save_data(self.last_prediction_time, 'last_prediction_time.json')
        self._save_data(self.last_predicted_game_number, 'last_predicted_game_number.json')
        self._save_data(self.consecutive_fails, 'consecutive_fails.json')
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

    # --- Extraction (RegEx Corrigée pour #N...) ---
    def extract_game_number(self, message: str) -> Optional[int]:
        # Supporte "#N1381" et "🔵1381🔵"
        match = re.search(r'#N(\d+)', message, re.IGNORECASE) 
        if not match: match = re.search(r'🔵(\d+)🔵', message)
        return int(match.group(1)) if match else None

    def extract_card_details(self, content: str) -> List[Tuple[str, str]]:
        normalized_content = content.replace("♥️", "❤️")
        # Cherche "10♦️", "A♠️"
        return re.findall(r'(\d+|[AKQJ])(♠️|❤️|♦️|♣️)', normalized_content, re.IGNORECASE)

    def get_first_card_info(self, message: str) -> Optional[Tuple[str, str]]:
        """Extrait la 1ère carte du 1er groupe entre parenthèses."""
        # Cherche le contenu entre parenthèses après le point ou au début
        # Ex: ". 4(10♦️...)"
        match = re.search(r'\(([^)]*)\)', message)
        if not match: return None
        
        details = self.extract_card_details(match.group(1))
        if details:
            v, c = details[0]
            return f"{v.upper()}{c}", c # ("10♦️", "♦️")
        return None

    # --- Apprentissage INTER (N-2) ---
    def collect_inter_data(self, game_number: int, message: str):
        info = self.get_first_card_info(message)
        if not info: return
        
        full_card, suit = info

        # 1. Stocker N comme futur déclencheur
        self.sequential_history[game_number] = {'carte': full_card, 'date': datetime.now().isoformat()}
        
        # 2. Chercher N-2 pour former une paire
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

        # Nettoyage (Garde 50 derniers)
        limit = game_number - 50
        self.sequential_history = {k:v for k,v in self.sequential_history.items() if k >= limit}

    def analyze_and_set_smart_rules(self, chat_id: int = None, initial_load: bool = False, force_activate: bool = False):
        """Calcule les Top 3 Règles."""
        counts = defaultdict(lambda: defaultdict(int))
        for entry in self.inter_data:
            counts[entry['declencheur']][entry['result_suit']] += 1
            
        candidates = []
        for trig, results in counts.items():
            best_suit = max(results, key=results.get)
            count = results[best_suit]
            candidates.append({'trigger': trig, 'predict': best_suit, 'count': count})
            
        # Tri par fréquence
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
        
        # Notification 30min
        if self.active_admin_chat_id and self.telegram_message_sender and (force_activate or self.is_inter_mode_active):
            msg = "🧠 **MISE À JOUR INTER (30min)**\n\n**Top 3 Règles (Carte -> Enseigne):**\n"
            if self.smart_rules:
                for r in self.smart_rules:
                    msg += f"🥇 {r['trigger']} → {r['predict']} (x{r['count']})\n"
            else:
                msg += "Aucune règle fiable pour le moment."
            self.telegram_message_sender(self.active_admin_chat_id, msg)

    def check_and_update_rules(self):
        """Vérification du délai de 30 minutes."""
        if self.is_inter_mode_active and (time.time() - self.last_analysis_time > 1800):
            self.analyze_and_set_smart_rules(chat_id=self.active_admin_chat_id)

    def get_inter_status(self) -> Tuple[str, Optional[Dict]]:
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

    # --- Prédiction ---
    def should_predict(self, message: str) -> Tuple[bool, Optional[int], Optional[str]]:
        # 1. Vérif Périodique
        self.check_and_update_rules()
        
        if not self.target_channel_id: return False, None, None
        game_number = self.extract_game_number(message)
        if not game_number: return False, None, None
        
        # 2. Collecte INTER
        self.collect_inter_data(game_number, message)
        
        # 3. Filtres
        if '🕐' in message or '⏰' in message: return False, None, None
        if '✅' not in message and '🔰' not in message: return False, None, None
        
        if self.last_predicted_game_number and (game_number - self.last_predicted_game_number < 3):
            return False, None, None

        # 4. Décision
        info = self.get_first_card_info(message)
        if not info: return False, None, None
        first_card, _ = info
        
        predicted_suit = None

        # A. INTER (Priorité)
        if self.is_inter_mode_active and self.smart_rules:
            for rule in self.smart_rules:
                if rule['trigger'] == first_card:
                    predicted_suit = rule['predict']
                    logger.info(f"🔮 INTER: {first_card} -> {predicted_suit}")
                    break
            
        # B. STATIQUE
        if not predicted_suit and first_card in STATIC_RULES:
            predicted_suit = STATIC_RULES[first_card]
            logger.info(f"🔮 STATIQUE: {first_card} -> {predicted_suit}")

        if predicted_suit:
            if self.last_prediction_time and time.time() < self.last_prediction_time + 30:
                return False, None, None
                
            self.last_prediction_time = time.time()
            self.last_predicted_game_number = game_number
            self.consecutive_fails = 0
            self._save_all_data()
            return True, game_number, predicted_suit

        return False, None, None

    def make_prediction(self, game_number: int, suit: str) -> str:
        target = game_number + 2
        txt = f"🔵{target}🔵:Enseigne {suit} statut :⏳"
        
        self.predictions[target] = {
            'predicted_costume': suit, 
            'status': 'pending', 
            'predicted_from': game_number, 
            'message_text': txt, 
            'message_id': None, 
            'is_inter': self.is_inter_mode_active
        }
        self._save_all_data()
        return txt

    def _verify_prediction_common(self, text: str, is_edited: bool = False) -> Optional[Dict]:
        game_number = self.extract_game_number(text)
        if not game_number: return None
        
        for pred_game, pred_data in list(self.predictions.items()):
            if pred_data['status'] != 'pending': continue
            
            offset = game_number - int(pred_game)
            if not (0 <= offset <= 2): continue
            
            info = self.get_first_card_info(text)
            found_suit = info[1] if info else None
            predicted = pred_data['predicted_costume']
            
            # SUCCÈS
            if found_suit == predicted:
                symbol = SYMBOL_MAP.get(offset, '✅')
                msg = f"🔵{pred_game}🔵:Enseigne {predicted} statut :{symbol}"
                pred_data['status'] = 'won'
                pred_data['final_message'] = msg
                self.consecutive_fails = 0
                self._save_all_data()
                return {'type': 'edit_message', 'predicted_game': str(pred_game), 'new_message': msg}
            
            # ÉCHEC (Après 2 tours)
            elif offset == 2:
                msg = f"🔵{pred_game}🔵:Enseigne {predicted} statut :❌"
                pred_data['status'] = 'lost'
                pred_data['final_message'] = msg
                
                # Auto-Switch
                if pred_data.get('is_inter'):
                    self.is_inter_mode_active = False 
                else:
                    self.consecutive_fails += 1
                    if self.consecutive_fails >= 2:
                        self.analyze_and_set_smart_rules(force_activate=True) 
                
                self._save_all_data()
                return {'type': 'edit_message', 'predicted_game': str(pred_game), 'new_message': msg}
                
        return None

