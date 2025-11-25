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
# Mis à jour à DEBUG pour vous aider à tracer la collecte.
logger.setLevel(logging.DEBUG) 

# --- 1. RÈGLES STATIQUES (13 Règles Exactes) ---
# Si la 1ère carte du jeu N est la clé -> On prédit la valeur pour N+2
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
    """Gère la logique de prédiction d'ENSEIGNE (Couleur) et la vérification."""

    def __init__(self, telegram_message_sender=None):
        
        # <<<<<<<<<<<<<<<< ZONE CRITIQUE À MODIFIER PAR L'UTILISATEUR >>>>>>>>>>>>>>>>
        # ⚠️ IDs DE CANAUX CONFIGURÉS
        self.HARDCODED_SOURCE_ID = -1002682552255  # <--- ID du canal SOURCE/DÉCLENCHEUR
        self.HARDCODED_PREDICTION_ID = -1003341134749 # <--- ID du canal PRÉDICTION/RÉSULTAT
        # <<<<<<<<<<<<<<<< FIN ZONE CRITIQUE >>>>>>>>>>>>>>>>

        # --- A. Chargement des Données ---
        self.predictions = self._load_data('predictions.json') 
        self.processed_messages = self._load_data('processed.json', is_set=True) 
        self.last_prediction_time = self._load_data('last_prediction_time.json', is_scalar=True) or 0
        self.last_predicted_game_number = self._load_data('last_predicted_game_number.json', is_scalar=True) or 0
        self.consecutive_fails = self._load_data('consecutive_fails.json', is_scalar=True) or 0
        self.pending_edits: Dict[int, Dict] = self._load_data('pending_edits.json')
        
        # --- B. Configuration Canaux (AVEC FALLBACK SÉCURISÉ) ---
        raw_config = self._load_data('channels_config.json')
        self.config_data = raw_config if isinstance(raw_config, dict) else {}
        
        self.target_channel_id = self.config_data.get('target_channel_id')
        if not self.target_channel_id and self.HARDCODED_SOURCE_ID != 0:
            self.target_channel_id = self.HARDCODED_SOURCE_ID
            
        self.prediction_channel_id = self.config_data.get('prediction_channel_id')
        if not self.prediction_channel_id and self.HARDCODED_PREDICTION_ID != 0:
            self.prediction_channel_id = self.HARDCODED_PREDICTION_ID
        
        # --- C. Logique INTER (Intelligente) ---
        self.telegram_message_sender = telegram_message_sender
        self.active_admin_chat_id = self._load_data('active_admin_chat_id.json', is_scalar=True)
        
        self.sequential_history: Dict[int, Dict] = self._load_data('sequential_history.json') 
        self.inter_data: List[Dict] = self._load_data('inter_data.json') 
        self.is_inter_mode_active = self._load_data('inter_mode_status.json', is_scalar=True)
        self.smart_rules = self._load_data('smart_rules.json')
        self.last_analysis_time = self._load_data('last_analysis_time.json', is_scalar=True) or 0
        
        if self.is_inter_mode_active is None:
            self.is_inter_mode_active = True
        
        self.prediction_cooldown = 30 
        
        if self.inter_data and not self.is_inter_mode_active and not self.smart_rules:
             self.analyze_and_set_smart_rules(initial_load=True)

    # --- Persistance ---
    def _load_data(self, filename: str, is_set: bool = False, is_scalar: bool = False) -> Any:
        try:
            is_dict = filename in ['channels_config.json', 'predictions.json', 'sequential_history.json', 'smart_rules.json', 'pending_edits.json']
            
            if not os.path.exists(filename):
                return set() if is_set else (None if is_scalar else ({} if is_dict else []))
            with open(filename, 'r') as f:
                content = f.read().strip()
                if not content: return set() if is_set else (None if is_scalar else ({} if is_dict else []))
                data = json.loads(content)
                if is_set: return set(data)
                if filename in ['sequential_history.json', 'predictions.json', 'pending_edits.json'] and isinstance(data, dict): 
                    return {int(k): v for k, v in data.items()}
                return data
        except Exception as e:
            logger.error(f"⚠️ Erreur chargement {filename}: {e}")
            is_dict = filename in ['channels_config.json', 'predictions.json', 'sequential_history.json', 'smart_rules.json', 'pending_edits.json']
            return set() if is_set else (None if is_scalar else ({} if is_dict else []))

    def _save_data(self, data: Any, filename: str):
        try:
            if isinstance(data, set): data = list(data)
            if filename == 'channels_config.json' and isinstance(data, dict):
                if 'target_channel_id' in data and data['target_channel_id'] is not None:
                    data['target_channel_id'] = int(data['target_channel_id'])
                if 'prediction_channel_id' in data and data['prediction_channel_id'] is not None:
                    data['prediction_channel_id'] = int(data['prediction_channel_id'])
            
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
        self._save_data(self.pending_edits, 'pending_edits.json')

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

    # --- Outils d'Extraction/Comptage ---
    
    def _extract_parentheses_content(self, text: str) -> List[str]:
        """Extrait le contenu de toutes les sections de parenthèses (non incluses)."""
        pattern = r'\(([^)]+)\)'
        return re.findall(pattern, text)

    def _count_cards_in_content(self, content: str) -> int:
        """Compte les symboles de cartes (♠️, ♥️, ♦️, ♣️) dans une chaîne, en normalisant ❤️ vers ♥️."""
        normalized_content = content.replace("❤️", "♥️")
        return len(re.findall(r'(\d+|[AKQJ])(♠️|♥️|♦️|♣️)', normalized_content, re.IGNORECASE))
        
    def has_pending_indicators(self, text: str) -> bool:
        """Vérifie si le message contient des indicateurs suggérant qu'il sera édité (temporaire)."""
        indicators = ['⏰', '▶', '🕐', '➡️']
        return any(indicator in text for indicator in indicators)

    def has_completion_indicators(self, text: str) -> bool:
        """Vérifie si le message contient des indicateurs de complétion après édition (✅ ou 🔰)."""
        completion_indicators = ['✅', '🔰']
        return any(indicator in text for indicator in completion_indicators)
        
    def is_final_result_structurally_valid(self, text: str) -> bool:
        """
        Vérifie si la structure du message correspond à un format de résultat final connu.
        Gère les messages #T, #R et les formats édités basés sur le compte de cartes.
        """
        matches = self._extract_parentheses_content(text)
        num_sections = len(matches)

        if num_sections < 2: return False

        # Règle pour les messages finalisés (#T) ou normaux (#R)
        if ('#T' in text or '🔵#R' in text) and num_sections >= 2:
            return True

        # Messages Édités (basé sur le compte de cartes)
        if num_sections == 2:
            content_1 = matches[0]
            content_2 = matches[1]
            
            count_1 = self._count_cards_in_content(content_1)
            count_2 = self._count_cards_in_content(content_2)

            # Formats acceptés: 3/2, 3/3, 2/3 (3 cartes dans le premier groupe sont supportées)
            if (count_1 == 3 and count_2 == 2) or \
               (count_1 == 3 and count_2 == 3) or \
               (count_1 == 2 and count_2 == 3):
                return True

        return False
        
    # --- Outils d'Extraction (Continuation) ---
    def extract_game_number(self, message: str) -> Optional[int]:
        match = re.search(r'#N(\d+)\.', message, re.IGNORECASE) 
        if not match: match = re.search(r'🔵(\d+)🔵', message)
        return int(match.group(1)) if match else None

    def extract_card_details(self, content: str) -> List[Tuple[str, str]]:
        # Normalise ♥️ en ❤️
        normalized_content = content.replace("♥️", "❤️")
        # Cherche Valeur + Enseigne (ex: 10♦️, A♠️)
        return re.findall(r'(\d+|[AKQJ])(♠️|❤️|♦️|♣️)', normalized_content, re.IGNORECASE)

    def get_first_card_info(self, message: str) -> Optional[Tuple[str, str]]:
        """
        Retourne la PREMIÈRE carte du PREMIER groupe (déclencheur INTER/STATIQUE).
        """
        match = re.search(r'\(([^)]*)\)', message)
        if not match: return None
        
        details = self.extract_card_details(match.group(1))
        if details:
            v, c = details[0]
            if c == "❤️": c = "♥️" 
            return f"{v.upper()}{c}", c 
        return None
        
    # --- Logique INTER (Collecte et Analyse) ---
    def collect_inter_data(self, game_number: int, message: str):
        """Collecte les données (N-2 -> N) si le message est structurellement valide."""
        info = self.get_first_card_info(message)
        if not info: return
        
        full_card, suit = info
        result_suit_normalized = suit.replace("❤️", "♥️")

        self.sequential_history[game_number] = {'carte': full_card, 'date': datetime.now().isoformat()}
        
        n_minus_2 = game_number - 2
        trigger_entry = self.sequential_history.get(n_minus_2)
        
        if trigger_entry:
            trigger_card = trigger_entry['carte']
            if not any(e.get('numero_resultat') == game_number for e in self.inter_data):
                self.inter_data.append({
                    'numero_resultat': game_number,
                    'declencheur': trigger_card, 
                    'numero_declencheur': n_minus_2,
                    'result_suit': result_suit_normalized, 
                    'date': datetime.now().isoformat()
                })
                self._save_all_data()

        limit = game_number - 50
        self.sequential_history = {k:v for k,v in self.sequential_history.items() if k >= limit}

    
    def analyze_and_set_smart_rules(self, chat_id: int = None, initial_load: bool = False, force_activate: bool = False):
        """
        Analyse les données pour trouver les Top 2 règles pour CHAQUE enseigne déclencheuse.
        """
        suit_groups = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        
        for entry in self.inter_data:
            trig = entry['declencheur'] 
            result_suit = entry['result_suit'] 
            
            trigger_suit = trig[-1].replace("❤️", "♥️")
            
            if trigger_suit in ['♠️', '♥️', '♦️', '♣️']:
                 suit_groups[trigger_suit][trig][result_suit] += 1
            
        self.smart_rules = []
        
        for trigger_suit in ['♠️', '♥️', '♦️', '♣️']:
            cards_data = suit_groups.get(trigger_suit, {})
            
            card_candidates = []
            for card, results in cards_data.items():
                
                for result_suit, count in results.items():
                    card_candidates.append({
                        'trigger': card,            
                        'predict': result_suit,     
                        'count': count,
                        'trigger_suit': trigger_suit
                    })
            
            top_2_for_suit = sorted(card_candidates, key=lambda x: x['count'], reverse=True)[:2]
            self.smart_rules.extend(top_2_for_suit)
        
        if force_activate:
            self.is_inter_mode_active = True
            if chat_id: self.active_admin_chat_id = chat_id
        elif self.smart_rules and not initial_load:
            self.is_inter_mode_active = True
        elif not initial_load:
            self.is_inter_mode_active = False
            
        self.last_analysis_time = time.time()
        self._save_all_data()

        logger.info(f"🧠 Analyse terminée. Règles trouvées: {len(self.smart_rules)}. Mode actif: {self.is_inter_mode_active}")
        
        # Notification Admin (Logique omise ici pour la concision)

    def check_and_update_rules(self):
        """Vérification périodique (30 minutes)."""
        if self.is_inter_mode_active and (time.time() - self.last_analysis_time > 1800):
            logger.info("🧠 Mise à jour INTER périodique (30 min).")
            self.analyze_and_set_smart_rules(chat_id=self.active_admin_chat_id)

    # ... (get_inter_status omis pour la concision) ...


    # --- CŒUR DU SYSTÈME : PRÉDICTION ---
    
    def should_wait_for_edit(self, text: str, message_id: int) -> bool:
        if self.has_pending_indicators(text):
            game_number = self.extract_game_number(text)
            if message_id not in self.pending_edits:
                self.pending_edits[message_id] = {
                    'game_number': game_number,
                    'original_text': text,
                    'timestamp': datetime.now().isoformat()
                }
                self._save_data(self.pending_edits, 'pending_edits.json')
            return True
        return False

    def should_predict(self, message: str) -> Tuple[bool, Optional[int], Optional[str]]:
        self.check_and_update_rules()
        
        game_number = self.extract_game_number(message)
        if not game_number: return False, None, None
        
        # Filtre TEMPORAIRE : On ne prédit pas sur un message temporaire
        if self.has_pending_indicators(message): 
            return False, None, None
        
        # Règle : Ecart de 3 jeux
        if self.last_predicted_game_number and (game_number - self.last_predicted_game_number < 3):
            return False, None, None
            
        # 3. Décision
        info = self.get_first_card_info(message)
        if not info: return False, None, None
        first_card, _ = info 
        
        predicted_suit = None

        # A. PRIORITÉ 1 : MODE INTER
        if self.is_inter_mode_active and self.smart_rules:
            for rule in self.smart_rules:
                if rule['trigger'] == first_card:
                    predicted_suit = rule['predict']
                    logger.info(f"🔮 INTER: Déclencheur {first_card} -> Prédit {predicted_suit}")
                    break
            
        # B. PRIORITÉ 2 : MODE STATIQUE
        if not predicted_suit and first_card in STATIC_RULES:
            predicted_suit = STATIC_RULES[first_card]
            logger.info(f"🔮 STATIQUE: Déclencheur {first_card} -> Prédit {predicted_suit}")

        if predicted_suit:
            if self.last_prediction_time and time.time() < self.last_prediction_time + self.prediction_cooldown:
                return False, None, None
                
            return True, game_number, predicted_suit

        return False, None, None

    def prepare_prediction_text(self, game_number_source: int, predicted_costume: str) -> str:
        target_game = game_number_source + 2
        return f"🔵{target_game}🔵:Enseigne {predicted_costume} statut :⏳"


    def make_prediction(self, game_number_source: int, suit: str, message_id_bot: int):
        target = game_number_source + 2
        txt = self.prepare_prediction_text(game_number_source, suit)
        
        self.predictions[target] = {
            'predicted_costume': suit, 
            'status': 'pending', 
            'predicted_from': game_number_source, 
            'message_text': txt, 
            'message_id': message_id_bot, 
            'is_inter': self.is_inter_mode_active
        }
        
        self.last_prediction_time = time.time()
        self.last_predicted_game_number = game_number_source
        self.consecutive_fails = 0
        self._save_all_data()

    # --- VERIFICATION LOGIQUE ---

    def verify_prediction(self, message: str) -> Optional[Dict]:
        """Vérifie une prédiction (message normal)"""
        return self._verify_prediction_common(message, is_edited=False)

    def verify_prediction_from_edit(self, message: str) -> Optional[Dict]:
        """Vérifie une prédiction (message édité)"""
        return self._verify_prediction_common(message, is_edited=True)

    def check_costume_in_first_parentheses(self, message: str, predicted_costume: str) -> bool:
        """Vérifie si le costume prédit apparaît SEULEMENT dans le PREMIER parenthèses"""
        normalized_message = message.replace("❤️", "♥️")
        normalized_costume = predicted_costume.replace("❤️", "♥️")

        pattern = r'\(([^)]+)\)'
        matches = re.findall(pattern, normalized_message)

        if not matches: return False

        first_parentheses_content = matches[0]
        costume_found = normalized_costume in first_parentheses_content
        return costume_found

    def _verify_prediction_common(self, message: str, is_edited: bool = False) -> Optional[Dict]:
        """Logique de vérification commune."""
        game_number = self.extract_game_number(message)
        if not game_number: return None
        
        # --- ÉTAPE 1 : Validation Structurelle et Collecte ---
        # Si la structure du résultat final est reconnue (y compris les formats édités 3/2, 3/3, 2/3)
        is_structurally_valid = self.is_final_result_structurally_valid(message)
        
        if not is_structurally_valid: return None
        
        # COLLECTE DE DONNÉES INTER (Uniquement pour les messages non édités pour éviter les doublons)
        if not is_edited: 
            self.collect_inter_data(game_number, message) 
            logger.info(f"🧠 Jeu {game_number} validé. Données collectées pour l'analyse INTER.")

        # --- ÉTAPE 2 : Vérification du statut de la prédiction ---
        # ATTENTION : Le filtre has_completion_indicators a été retiré ici
        # pour s'assurer que les messages édités qui ont une structure finale
        # sont vérifiés même si l'emoji final (✅/🔰) est manquant.

        if not self.predictions: return None
        
        verification_result = None

        # --- ÉTAPE 3 : Vérification du gain/perte ---
        for predicted_game in sorted(self.predictions.keys()):
            prediction = self.predictions[predicted_game]

            if prediction.get('status') != 'pending': continue

            verification_offset = game_number - predicted_game
            
            if verification_offset < 0 or verification_offset > 5: continue

            predicted_costume = prediction.get('predicted_costume')
            if not predicted_costume: continue

            # CAS A: SUCCÈS (Décalage 0, 1 ou 2)
            costume_found = self.check_costume_in_first_parentheses(message, predicted_costume)
            
            if costume_found and verification_offset <= 2:
                status_symbol = SYMBOL_MAP.get(verification_offset, f"✅{verification_offset}️⃣")
                updated_message = f"🔵{predicted_game}🔵:Enseigne {predicted_costume} statut :{status_symbol}"

                prediction['status'] = 'won'
                prediction['verification_count'] = verification_offset
                prediction['final_message'] = updated_message
                self.consecutive_fails = 0
                self._save_all_data()

                verification_result = {
                    'type': 'edit_message',
                    'predicted_game': str(predicted_game),
                    'new_message': updated_message,
                    'message_id_to_edit': prediction.get('message_id')
                }
                break 

            # CAS B: ÉCHEC (Seulement confirmé si on a dépassé l'offset 2)
            elif verification_offset >= 2:
                status_symbol = "❌" 
                updated_message = f"🔵{predicted_game}🔵:Enseigne {predicted_costume} statut :{status_symbol}"

                prediction['status'] = 'lost'
                prediction['final_message'] = updated_message
                
                if prediction.get('is_inter'):
                    self.is_inter_mode_active = False 
                    logger.info("❌ Échec INTER : Désactivation automatique.")
                else:
                    self.consecutive_fails += 1
                    if self.consecutive_fails >= 2:
                        self.analyze_and_set_smart_rules(force_activate=True) 
                        logger.info("⚠️ 2 Échecs Statiques : Activation automatique INTER.")
                
                self._save_all_data()

                verification_result = {
                    'type': 'edit_message',
                    'predicted_game': str(predicted_game),
                    'new_message': updated_message,
                    'message_id_to_edit': prediction.get('message_id')
                }
                break 

        return verification_result

# Global instance
card_predictor = CardPredictor()
