# card_predictor.py

"""
Card prediction logic for Joker's Telegram Bot - Prediction des Enseignes (Suits)
Intégration du mode INTER intelligent avec vérification périodique.
"""
import re
import logging
import time
import json
from datetime import datetime
from typing import Optional, Dict, List, Tuple, Any
from collections import defaultdict
import os # Ajout de os pour les chemins

# --- CONSTANTES ---
# Note: Les IDs de canaux par défaut doivent être définis dans config.py ou dans ce fichier si nécessaire, 
# mais ici, on suppose qu'ils sont gérés par la configuration dynamique.
STATIC_RULES = {
    "10♦️": "♠️", "10♠️": "❤️", "9♣️": "❤️", "9♦️": "♠️",
    "8♣️": "♠️", "8♠️": "♣️", "7♠️": "♠️", "7♣️": "♣️",
    "6♦️": "♣️", "6♣️": "♦️", "A❤️": "❤️", "5❤️": "❤️", 
    "5♠️": "♠️"
}

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class CardPredictor:
    """Gère la logique de prédiction d'enseigne (suit), la vérification et l'adaptation INTER."""

    def __init__(self, telegram_message_sender=None):
        # Données de persistance
        self.predictions = self._load_data('predictions.json') 
        self.processed_messages = self._load_data('processed.json', is_set=True) 
        self.last_prediction_time = self._load_data('last_prediction_time.json', is_scalar=True)
        self.last_predicted_game_number = self._load_data('last_predicted_game_number.json', is_scalar=True)
        self.consecutive_fails = self._load_data('consecutive_fails.json', is_scalar=True) 
        
        # Configuration dynamique des canaux
        self.config_data = self._load_data('channels_config.json')
        # Utilisation de None par défaut car les IDs sont dynamiques
        self.target_channel_id = self.config_data.get('target_channel_id', None)
        self.prediction_channel_id = self.config_data.get('prediction_channel_id', None)
        
        # --- Logique INTER (Mise à jour pour le suivi du temps et de l'admin) ---
        self.sequential_history: Dict[int, Dict] = self._load_data('sequential_history.json') 
        self.inter_data: List[Dict] = self._load_data('inter_data.json') 
        
        self.is_inter_mode_active = self._load_data('inter_mode_status.json', is_scalar=True)
        self.smart_rules = self._load_data('smart_rules.json') 
        self.previous_smart_rules = self._load_data('previous_smart_rules.json') or [] 
        self.last_analysis_time = self._load_data('last_analysis_time.json', is_scalar=True) or 0
        self.active_admin_chat_id = self._load_data('admin_chat_id.json', is_scalar=True) or None
        self.prediction_cooldown = 30 
        
        # Communication helper (via handlers.py)
        self.send_telegram_message = telegram_message_sender if telegram_message_sender else self._default_send_message
        
        if self.inter_data and not self.is_inter_mode_active and not self.smart_rules:
             self.analyze_and_set_smart_rules(initial_load=True) 

    def _default_send_message(self, chat_id, text, reply_markup=None):
        logger.warning(f"⚠️ Message d'alerte INTER pour Chat ID {chat_id} non envoyé (Mock).")
        return True

    def _load_data(self, filename: str, is_set: bool = False, is_scalar: bool = False) -> Any:
        try:
            # Pour gérer les IDs de canaux stockés en JSON
            if filename == 'channels_config.json' and not os.path.exists(filename):
                 return {}

            with open(filename, 'r') as f:
                data = json.load(f)
                if is_set: return set(data)
                if is_scalar:
                    if filename == 'inter_mode_status.json': return data.get('active', False)
                    if filename == 'consecutive_fails.json': return data.get('count', 0)
                    if filename in ['last_analysis_time.json', 'admin_chat_id.json', 'last_prediction_time.json']: return data
                    return int(data) if filename == 'last_predicted_game_number.json' else data
                if filename == 'sequential_history.json': return {int(k): v for k, v in data.items()}
                return data
        except (FileNotFoundError, json.JSONDecodeError):
            if is_set: return set()
            if is_scalar and filename == 'inter_mode_status.json': return False
            if is_scalar and filename in ['admin_chat_id.json']: return None
            if is_scalar and filename in ['last_analysis_time.json', 'last_prediction_time.json']: return 0
            if is_scalar: return 0
            if filename in ['inter_data.json', 'smart_rules.json', 'previous_smart_rules.json']: return []
            if filename == 'sequential_history.json': return {}
            return {}
        except Exception as e:
             logger.error(f"❌ Erreur chargement {filename}: {e}")
             return {} if not is_set and not is_scalar else (0 if is_scalar else set())

    def _save_data(self, data: Any, filename: str):
        # La sauvegarde de 'channels_config.json' est gérée séparément
        if filename == 'channels_config.json':
            data_to_save = data
        elif filename == 'inter_mode_status.json': 
            data_to_save = {'active': self.is_inter_mode_active}
        elif filename == 'consecutive_fails.json': 
            data_to_save = {'count': self.consecutive_fails}
        elif isinstance(data, set): 
            data_to_save = list(data)
        else: 
            # Gère les scalaires (time, chat_id, int) et les listes/dictionnaires normaux
            data_to_save = data
            
        try:
            with open(filename, 'w') as f: 
                json.dump(data_to_save, f, indent=4)
        except Exception as e: 
            logger.error(f"❌ Erreur sauvegarde {filename}: {e}")

    def _save_channels_config(self):
        self.config_data['target_channel_id'] = self.target_channel_id
        self.config_data['prediction_channel_id'] = self.prediction_channel_id
        self._save_data(self.config_data, 'channels_config.json')

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
        self._save_data(self.previous_smart_rules, 'previous_smart_rules.json')
        self._save_data(self.last_analysis_time, 'last_analysis_time.json')
        self._save_data(self.active_admin_chat_id, 'admin_chat_id.json')

    def _did_rules_change(self, new_rules: List[Dict]) -> bool:
        """Compare les nouvelles règles avec les règles précédentes (sans la fréquence)."""
        if len(new_rules) != len(self.previous_smart_rules):
            return True
        for i, rule in enumerate(new_rules):
            old_rule = self.previous_smart_rules[i]
            # Vérifie les cartes et la prédiction, ignore le 'count' (fréquence)
            if rule.get('cards') != old_rule.get('cards') or \
               rule.get('predicted_suit') != old_rule.get('predicted_suit'):
                return True
        return False
        
    def set_channel_id(self, channel_id: int, channel_type: str):
        if channel_type == 'source': self.target_channel_id = channel_id
        elif channel_type == 'prediction': self.prediction_channel_id = channel_id
        else: return False
        self._save_channels_config()
        return True

    def extract_game_number(self, message: str) -> Optional[int]:
        match = re.search(r'#N(\d+)\.', message, re.IGNORECASE) 
        if not match: match = re.search(r'🔵(\d+)🔵', message)
        if match:
            try: return int(match.group(1))
            except ValueError: return None
        return None

    def extract_first_parentheses_content(self, message: str) -> Optional[str]:
        pattern = r'\(([^)]*)\)' 
        match = re.search(pattern, message)
        if match: return match.group(1).strip()
        return None

    def extract_card_details(self, content: str) -> List[Tuple[str, str]]:
        card_details = []
        normalized_content = content.replace("❤️", "♥️") 
        card_pattern = r'(\d+|[AKQJ])(♠️|♥️|♦️|♣️)'
        matches = re.findall(card_pattern, normalized_content, re.IGNORECASE)
        for value, costume in matches:
            final_costume = "❤️" if costume == "♥️" else costume
            card_details.append((value.upper(), final_costume))
        return card_details

    def get_first_card(self, content: str) -> Optional[str]:
        card_details = self.extract_card_details(content)
        if card_details:
            v, c = card_details[0]
            return f"{v}{c}" 
        return None
        
    def get_first_card_suit(self, content: str) -> Optional[str]:
        card_details = self.extract_card_details(content)
        if card_details: return card_details[0][1]
        return None

    def collect_inter_data(self, game_number: int, message: str):
        first_group_content = self.extract_first_parentheses_content(message)
        if not first_group_content: return
        first_card = self.get_first_card(first_group_content)
        if first_card:
            self.sequential_history[game_number] = {'carte': first_card, 'date': datetime.now().isoformat()}
        
        result_suit = self.get_first_card_suit(first_group_content)
        if result_suit:
            n_minus_2_game = game_number - 2
            trigger_entry = self.sequential_history.get(n_minus_2_game)
            if trigger_entry:
                trigger_card = trigger_entry['carte']
                is_duplicate = any(e.get('numero_resultat') == game_number for e in self.inter_data)
                if is_duplicate: return 
                new_entry = {
                    'numero_resultat': game_number,
                    'declencheur': [trigger_card], 
                    'numero_declencheur': n_minus_2_game,
                    'carte_q': result_suit, 
                    'date_resultat': datetime.now().isoformat()
                }
                self.inter_data.append(new_entry)
                self._save_all_data() 
        obsolete_game_limit = game_number - 50 
        self.sequential_history = {k: v for k, v in self.sequential_history.items() if k >= obsolete_game_limit}

    def analyze_and_set_smart_rules(self, chat_id: Optional[int] = None, initial_load: bool = False, force_activate: bool = False) -> List[Dict]:
        
        self.previous_smart_rules = list(self.smart_rules) 
        
        association_counts = defaultdict(int) 
        for data in self.inter_data:
            declencheur_card = data['declencheur'][0]
            result_suit = data['carte_q']
            association_counts[(declencheur_card, result_suit)] += 1
        best_rules = {} 
        for (card, suit), count in association_counts.items():
            current_best_suit, current_best_count = best_rules.get(card, ('', 0))
            if count > current_best_count: best_rules[card] = (suit, count)
        sorted_rules = sorted(
            [{'cards': [card], 'predicted_suit': suit, 'count': count} for card, (suit, count) in best_rules.items()],
            key=lambda item: item['count'], reverse=True
        )
        self.smart_rules = sorted_rules[:3]
        
        rules_changed = self._did_rules_change(self.smart_rules)

        if force_activate: 
            self.is_inter_mode_active = True
            if chat_id: self.active_admin_chat_id = chat_id
        elif self.smart_rules and not initial_load: 
            self.is_inter_mode_active = True
            if chat_id and not self.active_admin_chat_id: self.active_admin_chat_id = chat_id 
        elif not initial_load: 
            self.is_inter_mode_active = False 

        self.last_analysis_time = time.time()
        self._save_all_data()

        if self.active_admin_chat_id:
            target_chat = chat_id if chat_id else self.active_admin_chat_id
            
            if rules_changed and self.smart_rules:
                status_message = "🔄 **MISE À JOUR ALGORITHME INTERLIGNE** (Règles modifiées) :\n"
                status_message += "\n".join([f"{['🥇', '🥈', '🥉'][i]} **{rule['cards'][0]}** → **{rule['predicted_suit']}** (x{rule['count']})" for i, rule in enumerate(self.smart_rules)])
            elif self.smart_rules:
                status_message = "✅ **VERIFICATION INTERLIGNE** (Aucun changement majeur) : Les Top 3 règles restent valides."
            else:
                status_message = "⚠️ **VERIFICATION INTERLIGNE** : Historique insuffisant ou peu cohérent. Le mode intelligent est désactivé."
            
            self.send_telegram_message(target_chat, status_message)

        return self.smart_rules

    def check_and_update_rules(self):
        """Vérifie si 30 minutes (1800s) se sont écoulées et déclenche l'analyse si nécessaire."""
        if self.is_inter_mode_active and (time.time() - self.last_analysis_time) > 1800:
            logger.info("⏱️ Déclenchement de l'analyse périodique de 30 minutes...")
            self.analyze_and_set_smart_rules(chat_id=self.active_admin_chat_id, force_activate=True)
            return True
        return False
        
    def get_full_trigger_list_grouped(self) -> str:
        if not self.inter_data: return "\n❌ Aucun historique collecté."
        grouped_data = {r"❤️": [], r"♠️": [], r"♣️": [], r"♦️": []}
        suit_pattern = r'(♠️|♥️|♦️|♣️)' 
        for entry in self.inter_data:
            trigger_card = entry['declencheur'][0]
            match = re.search(suit_pattern, trigger_card)
            trigger_suit = match.group(1) if match else '?'
            if trigger_suit == "♥️": trigger_suit = r"❤️"
            line = f"• **N{entry['numero_declencheur']}** ({trigger_card}) → Résultat à **N{entry['numero_resultat']}** ({entry['carte_q']})"
            if trigger_suit in grouped_data: grouped_data[trigger_suit].append(line)
        output_lines = [f"\n📜 **LISTE COMPLÈTE DES DÉCLENCHEURS** (Total: {len(self.inter_data)})"]
        for suit in [r"❤️", r"♠️", r"♣️", r"♦️"]:
            entries = grouped_data.get(suit, [])
            if entries:
                output_lines.append(f"\n### 🃏 DÉCLENCHEURS **{suit}** ({len(entries)} entrées)")
                output_lines.extend(entries[:10]) 
                if len(entries) > 10: output_lines.append(f"... {len(entries) - 10} entrées masquées.")
        return "\n".join(output_lines)
    
    def get_inter_status(self, force_reanalyze: bool = False) -> Tuple[str, Optional[Dict]]:
        if force_reanalyze or (not self.smart_rules and self.inter_data):
             self.analyze_and_set_smart_rules(initial_load=False, force_activate=force_reanalyze)
        status = '✅ OUI (Top 3 Règles appliquées)' if self.is_inter_mode_active else '❌ NON (Règles Statiques par Défaut)'
        source_status = '💡 Règle Intelligente' if self.is_inter_mode_active else '📏 Règle Statique'
        status_lines = [
            "# ♠️♥️♦️♣️ GESTION DU MODE INTERLIGNE 🧠", "***", "### ⚙️ STATUT ACTUEL",
            f"**Mode Intelligent Actif:** {status}",
            f"**Source de la Prédiction :** {source_status}",
            f"**Historique d'Apprentissage :** **{len(self.inter_data)} jeux analysés.**", "***"
        ]
        if self.smart_rules:
            section_title = "RÈGLES ACTIVES (TOP 3)" if self.is_inter_mode_active else "ÉVOLUTION DES RÈGLES (TOP 3)"
            status_lines.append(f"### 🎯 {section_title}")
            if not self.is_inter_mode_active: status_lines.append("*Le bot continue d'apprendre. Vous pouvez activer ces règles.*")
            medals = ["🥇", "🥈", "🥉"]
            for i, rule in enumerate(self.smart_rules):
                status_lines.append(f"{medals[i]} **Déclencheur : {rule['cards'][0]}** → **{rule['predicted_suit']}** (Fréquence: **x{rule['count']}**)")
            status_lines.append("\n***")
        if self.inter_data:
             status_lines.append("### 📊 BILAN DES DERNIERS ENREGISTREMENTS")
             status_lines.append("*Les 5 dernières associations (N-2 → Enseigne à N) :*")
             for entry in self.inter_data[-5:]:
                 status_lines.append(f"• **N{entry['numero_resultat']}** ({entry['carte_q']}) ← **N{entry['numero_declencheur']}** ({entry['declencheur'][0]})")
             status_lines.append("***")
        status_lines.append(self.get_full_trigger_list_grouped())
        status_lines.append("\n***")
        keyboard = None
        if self.inter_data:
            apply_text = "🔄 Re-analyser et appliquer (Actif)" if self.is_inter_mode_active else f"✅ Activer Règle Intelligente ({len(self.inter_data)} entrées)"
            keyboard = {'inline_keyboard': [[{'text': apply_text, 'callback_data': 'inter_apply'}],[{'text': "➡️ Passer à la Règle Statique par Défaut", 'callback_data': 'inter_default'}]]}
        else: status_lines.append("*Aucune action disponible. Attendez plus de données.*")
        return "\n".join(status_lines), keyboard

    def can_make_prediction(self) -> bool:
        if self.last_prediction_time and time.time() < (self.last_prediction_time + self.prediction_cooldown): return False
        return True

    def is_cooldown_by_game_number(self, current_game_number: int) -> bool:
        if self.last_predicted_game_number == 0: return False
        return current_game_number - self.last_predicted_game_number < 3

    def has_pending_indicators(self, message: str) -> bool: return '🕐' in message or '⏰' in message
    def has_completion_indicators(self, message: str) -> bool: return '✅' in message or '🔰' in message

    def should_predict(self, message: str) -> Tuple[bool, Optional[int], Optional[str]]:
        if self.is_inter_mode_active:
             self.check_and_update_rules() # Vérification périodique ici

        if not self.target_channel_id: return False, None, None
        game_number = self.extract_game_number(message)
        if not game_number: return False, None, None
        self.collect_inter_data(game_number, message) 
        if self.has_pending_indicators(message): return False, None, None 
        if not self.has_completion_indicators(message): return False, None, None
        if self.is_cooldown_by_game_number(game_number):
            logger.warning(f"⏳ PRÉDICTION ÉVITÉE: Écart minimum de 3 jeux non respecté.")
            return False, None, None
        predicted_suit = None
        first_group_content = self.extract_first_parentheses_content(message)
        first_card = self.get_first_card(first_group_content)
        if first_card:
            if self.is_inter_mode_active and self.smart_rules:
                for rule in self.smart_rules:
                    if rule['cards'][0] == first_card:
                        predicted_suit = rule['predicted_suit']
                        logger.info(f"🔮 INTER: Déclencheur {first_card} -> Prédit {predicted_suit}.")
                        break
            if not predicted_suit and first_card in STATIC_RULES:
                predicted_suit = STATIC_RULES[first_card]
                logger.info(f"🔮 STATIQUE: Carte {first_card} -> Prédit {predicted_suit}.")
        if predicted_suit and not self.can_make_prediction(): return False, None, None
        if predicted_suit:
            message_hash = hash(message)
            if message_hash not in self.processed_messages:
                self.processed_messages.add(message_hash)
                self.last_prediction_time = time.time()
                self.last_predicted_game_number = game_number
                self.consecutive_fails = 0 
                self._save_all_data()
                return True, game_number, predicted_suit
        return False, None, None
        
    def make_prediction(self, game_number: int, predicted_suit: str) -> str:
        target_game = game_number + 2
        prediction_text = f"🔵{target_game}🔵:Enseigne {predicted_suit} statut :⏳"
        self.predictions[target_game] = {
            'predicted_costume': predicted_suit, 'status': 'pending', 'predicted_from': game_number,
            'verification_count': 0, 'message_text': prediction_text, 'message_id': None, 'is_inter_rule': self.is_inter_mode_active
        }
        self._save_all_data()
        return prediction_text
        
    def _verify_prediction_common(self, text: str, is_edited: bool = False) -> Optional[Dict]:
        if self.has_pending_indicators(text) or not self.has_completion_indicators(text): return None
        game_number = self.extract_game_number(text)
        if not game_number or not self.predictions: return None
        for predicted_game in sorted(self.predictions.keys()):
            prediction = self.predictions[predicted_game]
            if prediction.get('status') != 'pending': continue
            predicted_suit = prediction.get('predicted_costume')
            verification_offset = game_number - predicted_game
            if 0 <= verification_offset <= 2:
                status_symbol_map = {0: "✅0️⃣", 1: "✅1️⃣", 2: "✅2️⃣"}
                first_group_content = self.extract_first_parentheses_content(text)
                first_card_suit_found = self.get_first_card_suit(first_group_content)
                is_correct = first_card_suit_found == predicted_suit
                if is_correct:
                    updated_message = f"🔵{predicted_game}🔵:Enseigne {predicted_suit} statut :{status_symbol_map[verification_offset]}"
                    prediction['status'] = f'correct_offset_{verification_offset}'
                    prediction['final_message'] = updated_message
                    self.consecutive_fails = 0
                    self._save_all_data()
                    return {'type': 'edit_message', 'predicted_game': predicted_game, 'new_message': updated_message}
                elif verification_offset == 2 and not is_correct:
                    updated_message = f"🔵{predicted_game}🔵:Enseigne {predicted_suit} statut :❌"
                    prediction['status'] = 'failed'
                    if prediction.get('is_inter_rule'):
                        self.is_inter_mode_active = False
                        self.consecutive_fails = 0 
                        logger.warning("🧠 ❌ INTER DÉSACTIVÉ après échec.")
                    else:
                        self.consecutive_fails += 1
                        logger.warning(f"❌ ÉCHEC STATIQUE. Total: {self.consecutive_fails}")
                        if self.consecutive_fails >= 2:
                            self.analyze_and_set_smart_rules(force_activate=True)
                            logger.info("🧠 ✅ INTER ACTIVÉ après 2 échecs.")
                    self._save_all_data()
                    return {'type': 'edit_message', 'predicted_game': predicted_game, 'new_message': updated_message}
        return None
