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

# --- 1. LES RÈGLES STATIQUES EXACTES ---
# (Première carte du groupe 1 -> Enseigne à prédire)
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
    """Gère la logique de prédiction d'enseigne (suit) et la vérification."""

    def __init__(self, telegram_message_sender=None):
        # --- A. Chargement Robuste des Données ---
        self.predictions = self._load_data('predictions.json') 
        self.processed_messages = self._load_data('processed.json', is_set=True) 
        self.last_prediction_time = self._load_data('last_prediction_time.json', is_scalar=True) or 0
        self.last_predicted_game_number = self._load_data('last_predicted_game_number.json', is_scalar=True) or 0
        self.consecutive_fails = self._load_data('consecutive_fails.json', is_scalar=True) or 0
        
        # --- B. Configuration Canaux (Correction du Bug 'list object') ---
        raw_config = self._load_data('channels_config.json')
        # Sécurité : Si le fichier est corrompu ou est une liste, on remet un dict vide
        self.config_data = raw_config if isinstance(raw_config, dict) else {}
            
        self.target_channel_id = self.config_data.get('target_channel_id', None)
        self.prediction_channel_id = self.config_data.get('prediction_channel_id', None)
        
        # --- C. Logique INTER (Intelligente) ---
        self.telegram_message_sender = telegram_message_sender
        self.active_admin_chat_id = self._load_data('active_admin_chat_id.json', is_scalar=True)
        
        self.sequential_history: Dict[int, Dict] = self._load_data('sequential_history.json') 
        self.inter_data: List[Dict] = self._load_data('inter_data.json') 
        self.is_inter_mode_active = self._load_data('inter_mode_status.json', is_scalar=True)
        self.smart_rules = self._load_data('smart_rules.json')
        self.last_analysis_time = self._load_data('last_analysis_time.json', is_scalar=True) or 0
        
        self.prediction_cooldown = 30 
        
        # Analyse initiale au démarrage si nécessaire
        if self.inter_data and not self.is_inter_mode_active and not self.smart_rules:
             self.analyze_and_set_smart_rules(initial_load=True)

    # --- Persistance (Chargement/Sauvegarde) ---
    def _load_data(self, filename: str, is_set: bool = False, is_scalar: bool = False) -> Any:
        try:
            if not os.path.exists(filename):
                return set() if is_set else (None if is_scalar else ({} if filename == 'channels_config.json' else []))
            with open(filename, 'r') as f:
                content = f.read().strip()
                if not content: return set() if is_set else (None if is_scalar else {})
                data = json.loads(content)
                if is_set: return set(data)
                # Conversion des clés str -> int pour l'historique
                if filename == 'sequential_history.json' and isinstance(data, dict): 
                    return {int(k): v for k, v in data.items()}
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

    # --- Outils d'Extraction ---
    def extract_game_number(self, message: str) -> Optional[int]:
        match = re.search(r'#N(\d+)\.', message, re.IGNORECASE) 
        if not match: match = re.search(r'🔵(\d+)🔵', message)
        return int(match.group(1)) if match else None

    def extract_first_parentheses_content(self, message: str) -> Optional[str]:
        match = re.search(r'\(([^)]*)\)', message)
        return match.group(1).strip() if match else None

    def extract_card_details(self, content: str) -> List[Tuple[str, str]]:
        # Normalise ♥️ en ❤️ pour correspondre aux règles statiques
        normalized_content = content.replace("♥️", "❤️")
        return re.findall(r'(\d+|[AKQJ])(♠️|❤️|♦️|♣️)', normalized_content, re.IGNORECASE)

    def get_first_card_full(self, content: str) -> Optional[str]:
        """Récupère la première carte complète (ex: '10♦️')."""
        details = self.extract_card_details(content)
        if details:
            v, c = details[0]
            return f"{v.upper()}{c}"
        return None
        
    def get_first_card_suit(self, content: str) -> Optional[str]:
        """Récupère l'enseigne de la première carte."""
        details = self.extract_card_details(content)
        return details[0][1] if details else None

    # --- Logique INTER (Apprentissage) ---
    def collect_inter_data(self, game_number: int, message: str):
        content = self.extract_first_parentheses_content(message)
        if not content: return

        # 1. Stocker la carte du jeu actuel (N) pour qu'elle serve de déclencheur futur
        first_card = self.get_first_card_full(content)
        if first_card:
            self.sequential_history[game_number] = {'carte': first_card, 'date': datetime.now().isoformat()}
        
        # 2. Vérifier si ce jeu (N) est un résultat (Enseigne) pour un déclencheur passé (N-2)
        result_suit = self.get_first_card_suit(content)
        if result_suit:
            n_minus_2 = game_number - 2
            trigger_entry = self.sequential_history.get(n_minus_2)
            
            if trigger_entry:
                trigger_card = trigger_entry['carte']
                # Anti-doublon
                if not any(e.get('numero_resultat') == game_number for e in self.inter_data):
                    self.inter_data.append({
                        'numero_resultat': game_number,
                        'declencheur': trigger_card, # La carte unique (ex: "10♦️")
                        'numero_declencheur': n_minus_2,
                        'result_suit': result_suit, # L'enseigne résultante (ex: "♠️")
                        'date': datetime.now().isoformat()
                    })
                    self._save_all_data()

        # Nettoyage
        limit = game_number - 50
        self.sequential_history = {k:v for k,v in self.sequential_history.items() if k >= limit}

    def analyze_and_set_smart_rules(self, chat_id: int = None, initial_load: bool = False, force_activate: bool = False):
        # 1. Compter les associations: Carte Déclencheur -> Enseigne Résultat
        counts = defaultdict(lambda: defaultdict(int))
        for entry in self.inter_data:
            trig = entry['declencheur']
            res = entry['result_suit']
            counts[trig][res] += 1
            
        # 2. Trouver le meilleur résultat pour chaque déclencheur
        candidates = []
        for trig, results in counts.items():
            best_suit = max(results, key=results.get)
            count = results[best_suit]
            candidates.append({'trigger': trig, 'predict': best_suit, 'count': count})
            
        # 3. Top 3 Global
        self.smart_rules = sorted(candidates, key=lambda x: x['count'], reverse=True)[:3]
        
        # Gestion Activation
        if force_activate:
            self.is_inter_mode_active = True
            if chat_id: self.active_admin_chat_id = chat_id
        elif self.smart_rules and not initial_load:
            self.is_inter_mode_active = True
        elif not initial_load:
            self.is_inter_mode_active = False # Désactive si pas de règles
            
        self.last_analysis_time = time.time()
        self._save_all_data()
        
        # Notification Admin
        if self.active_admin_chat_id and self.telegram_message_sender and (force_activate or self.is_inter_mode_active):
            msg = "🧠 **MISE À JOUR INTER (30min)**\n\n**Top 3 Règles (Carte -> Enseigne):**\n"
            if self.smart_rules:
                for r in self.smart_rules:
                    msg += f"🥇 {r['trigger']} → {r['predict']} (x{r['count']})\n"
            else:
                msg += "Aucune règle fiable trouvée."
            self.telegram_message_sender(self.active_admin_chat_id, msg)

    def check_and_update_rules(self):
        """Vérification 30 minutes."""
        if self.is_inter_mode_active and (time.time() - self.last_analysis_time > 1800):
            self.analyze_and_set_smart_rules(chat_id=self.active_admin_chat_id)

    def get_inter_status(self, force_reanalyze: bool = False) -> Tuple[str, Optional[Dict]]:
        if force_reanalyze: self.analyze_and_set_smart_rules()
        
        msg = f"**🧠 ETAT DU MODE INTELLIGENT**\n\n"
        msg += f"**Actif :** {'✅ OUI' if self.is_inter_mode_active else '❌ NON'}\n"
        msg += f"**Données analysées :** {len(self.inter_data)}\n\n"
        
        if self.smart_rules:
            msg += "**📜 Règles Actives (Top 3):**\n"
            for r in self.smart_rules:
                msg += f"• Si **{r['trigger']}** sort (N-2) → Prédire **{r['predict']}** (x{r['count']})\n"
        else:
            msg += "⚠️ Pas assez de données pour former des règles."
            
        kb = {'inline_keyboard': [
            [{'text': '✅ Activer / Mettre à jour', 'callback_data': 'inter_apply'}],
            [{'text': '❌ Désactiver (Retour Statique)', 'callback_data': 'inter_default'}]
        ]}
        return msg, kb

    # --- CŒUR DU SYSTÈME : PRÉDICTION ---
    def should_predict(self, message: str) -> Tuple[bool, Optional[int], Optional[str]]:
        # Vérif 30 min
        self.check_and_update_rules()
        
        if not self.target_channel_id: return False, None, None
        game_number = self.extract_game_number(message)
        if not game_number: return False, None, None
        
        # Collecte des données
        self.collect_inter_data(game_number, message)
        
        # Filtres de sécurité
        if '🕐' in message or '⏰' in message: return False, None, None
        if '✅' not in message and '🔰' not in message: return False, None, None
        
        # Écart de 3 jeux
        if self.last_predicted_game_number and (game_number - self.last_predicted_game_number < 3):
            return False, None, None

        predicted_suit = None
        first_content = self.extract_first_parentheses_content(message)
        first_card = self.get_first_card_full(first_content)

        if first_card:
            # 1. PRIORITÉ : MODE INTER
            if self.is_inter_mode_active and self.smart_rules:
                for rule in self.smart_rules:
                    if rule['trigger'] == first_card:
                        predicted_suit = rule['predict']
                        logger.info(f"🔮 INTER: {first_card} -> {predicted_suit}")
                        break
            
            # 2. PRIORITÉ : MODE STATIQUE (Si Inter inactif ou pas de match)
            if not predicted_suit and first_card in STATIC_RULES:
                predicted_suit = STATIC_RULES[first_card]
                logger.info(f"🔮 STATIQUE: {first_card} -> {predicted_suit}")

        if predicted_suit:
            # Vérif Cooldown temporel (30s)
            if self.last_prediction_time and time.time() < self.last_prediction_time + 30:
                return False, None, None
                
            self.last_prediction_time = time.time()
            self.last_predicted_game_number = game_number
            self.consecutive_fails = 0 # Reset fail count
            self._save_all_data()
            return True, game_number, predicted_suit

        return False, None, None

    def make_prediction(self, game_number: int, suit: str) -> str:
        target = game_number + 2
        txt = f"🔵{target}🔵:Enseigne {suit} statut :⏳"
        self.predictions[target] = {
            'predicted_costume': suit, 'status': 'pending', 'predicted_from': game_number, 
            'message_text': txt, 'message_id': None, 'is_inter': self.is_inter_mode_active
        }
        self._save_all_data()
        return txt

    def _verify_prediction_common(self, text: str, is_edited: bool = False) -> Optional[Dict]:
        game_number = self.extract_game_number(text)
        if not game_number: return None
        
        # Vérifie les prédictions en cours
        for pred_game_num, pred_data in list(self.predictions.items()):
            # Convertir la clé en int si nécessaire (json charge en str parfois)
            pred_game_num = int(pred_game_num)
            
            if pred_data['status'] != 'pending': continue
            
            # Calcul de l'offset (0, 1, 2)
            offset = game_number - pred_game_num
            if not (0 <= offset <= 2): continue
            
            # Résultat trouvé ?
            found_suit = self.get_first_card_suit(self.extract_first_parentheses_content(text))
            predicted_suit = pred_data['predicted_costume']
            
            if found_suit == predicted_suit:
                # GAGNÉ
                symbol = f"✅{offset}️⃣" # ✅0️⃣, ✅1️⃣, ✅2️⃣
                msg = f"🔵{pred_game_num}🔵:Enseigne {predicted_suit} statut :{symbol}"
                pred_data['status'] = 'won'
                pred_data['final_message'] = msg
                self.consecutive_fails = 0
                self._save_all_data()
                return {'type': 'edit_message', 'predicted_game': str(pred_game_num), 'new_message': msg}
            
            elif offset == 2:
                # PERDU (Après 3 essais)
                msg = f"🔵{pred_game_num}🔵:Enseigne {predicted_suit} statut :❌"
                pred_data['status'] = 'lost'
                pred_data['final_message'] = msg
                
                # Gestion Auto-Activation/Désactivation
                if pred_data.get('is_inter'):
                    self.is_inter_mode_active = False # Désactive INTER si échec
                else:
                    self.consecutive_fails += 1
                    if self.consecutive_fails >= 2:
                        self.analyze_and_set_smart_rules(force_activate=True) # Active INTER si 2 échecs statiques
                
                self._save_all_data()
                return {'type': 'edit_message', 'predicted_game': str(pred_game_num), 'new_message': msg}
                
        return None
