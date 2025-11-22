# card_predictor.py

"""
Card prediction logic for Joker's Telegram Bot - simplified for webhook deployment
Modified: Targets King (K) instead of Queen (Q)
"""
import re
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Any
import time
import os
import json

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# --- CONSTANTES ---
HIGH_VALUE_CARDS = ["A", "K", "Q", "J"] 
CARD_SYMBOLS = [r"♠️", r"♥️", r"♦️", r"♣️", r"❤️"]
# Cartes à suivre pour le mode INTER
INTER_SUITS = ['♠️', '♥️', '♦️', '♣️'] 
ANALYSIS_INTERVAL_MINUTES = 30 # Intervalle d'analyse pour le mode INTER
SYMBOL_MAP = {1: '✅', 2: '❌'} # Map pour les vérifications

class CardPredictor:
    """Gère la logique de prédiction de carte Roi (K) et la vérification. Intègre le Mode Intelligent (INTER)."""

    def __init__(self, telegram_message_sender: Optional[callable] = None):
        # Données de persistance (Prédictions et messages)
        self.predictions = self._load_data('predictions.json') 
        self.processed_messages = self._load_data('processed.json', is_set=True) 
        self.last_prediction_time = self._load_data('last_prediction_time.json', is_scalar=True)
        
        # Configuration dynamique des canaux
        self.config_data = self._load_data('channels_config.json')
        self.target_channel_id = self.config_data.get('target_channel_id', None)
        self.prediction_channel_id = self.config_data.get('prediction_channel_id', None)
        
        # --- Logique INTER (Nouvelles Propriétés) ---
        self.telegram_message_sender = telegram_message_sender # Référence à la fonction d'envoi de message du handler
        self.active_admin_chat_id = self._load_data('active_admin_chat_id.json', is_scalar=True) # ID pour la notification
        self.is_inter_mode_active = self._load_data('inter_mode_status.json', is_scalar=True, default_val=False)
        self.last_analysis_time = self._load_data('last_analysis_time.json', is_scalar=True, default_val=0)
        self.current_smart_rules = self._load_data('smart_rules.json', default_val=[])
        self.inter_data = self._load_data('inter_data.json', default_val=[]) # Historique des jeux pour l'analyse

    # --- Méthodes de Persistance ---
    def _load_data(self, filename: str, is_set: bool = False, is_scalar: bool = False, default_val: Any = None) -> Any:
        """Charge les données depuis un fichier JSON."""
        filepath = os.path.join(os.getcwd(), filename)
        if not os.path.exists(filepath):
            return set() if is_set else (default_val if is_scalar else ({} if filename == 'predictions.json' else []))
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
                if is_set:
                    return set(data)
                return data
        except Exception as e:
            logger.error(f"Erreur chargement {filename}: {e}")
            return set() if is_set else (default_val if is_scalar else ({} if filename == 'predictions.json' else []))

    def _save_data(self, data: Any, filename: str, is_set: bool = False, is_scalar: bool = False) -> None:
        """Sauvegarde les données dans un fichier JSON."""
        filepath = os.path.join(os.getcwd(), filename)
        try:
            data_to_save = list(data) if is_set else data
            with open(filepath, 'w') as f:
                json.dump(data_to_save, f)
        except Exception as e:
            logger.error(f"Erreur sauvegarde {filename}: {e}")
            
    def _save_all_data(self):
        """Sauvegarde toutes les données de persistance."""
        self._save_data(self.predictions, 'predictions.json')
        self._save_data(self.processed_messages, 'processed.json', is_set=True)
        self._save_data(self.last_prediction_time, 'last_prediction_time.json', is_scalar=True)
        self._save_data(self.config_data, 'channels_config.json')
        self._save_data(self.active_admin_chat_id, 'active_admin_chat_id.json', is_scalar=True)
        self._save_data(self.is_inter_mode_active, 'inter_mode_status.json', is_scalar=True)
        self._save_data(self.last_analysis_time, 'last_analysis_time.json', is_scalar=True)
        self._save_data(self.current_smart_rules, 'smart_rules.json')
        self._save_data(self.inter_data, 'inter_data.json')


    # --- Méthodes de Configuration de Canal (Conservées) ---
    def set_channel_id(self, chat_id: int, channel_type: str):
        # ... (Logique inchangée)
        str_chat_id = str(chat_id)
        if channel_type == 'source':
            self.target_channel_id = chat_id
            self.config_data['target_channel_id'] = str_chat_id
        elif channel_type == 'prediction':
            self.prediction_channel_id = chat_id
            self.config_data['prediction_channel_id'] = str_chat_id
        
        self._save_data(self.config_data, 'channels_config.json')

    # --- Logique de Prédiction et Vérification (Conservée, ajustée pour INTER) ---
    def should_predict(self, text: str) -> Tuple[bool, Optional[int], Optional[str]]:
        """Détermine si une prédiction peut être faite et si l'analyse INTER est nécessaire."""
        
        # 🚨 Appel à la vérification périodique INTER
        self.check_and_update_rules()

        # ... (Le reste de la logique de should_predict)
        match = re.search(r'JEU\s+(\d+)\s*:.*', text, re.IGNORECASE)
        if match:
            game_number = int(match.group(1))
            
            # 🚨 Enregistrement du jeu pour l'analyse INTER, AVANT la prédiction du jeu N+2
            if game_number not in [item.get('game_number') for item in self.inter_data]:
                card_match = re.search(r'([AKQJ])\s*([♠️♥️♦️♣️❤️])', text)
                if card_match:
                    card_value = card_match.group(1)
                    card_suit = card_match.group(2)
                    self.inter_data.append({'game_number': game_number, 'card_value': card_value, 'card_suit': card_suit})
                    # Conserver seulement les 50 derniers jeux pour l'analyse
                    self.inter_data = self.inter_data[-50:] 
                    self._save_data(self.inter_data, 'inter_data.json')
            
            # Logique de prédiction (cible le jeu N+2)
            predicted_game_number = game_number + 2 
            
            if predicted_game_number in self.predictions:
                return False, None, None # Déjà prédit
            
            # Logique pour déterminer la couleur à prédire (basée sur 'K')
            k_match = re.search(r'K\s*([♠️♥️♦️♣️])', text)
            predicted_suit = k_match.group(1) if k_match else None
            
            if predicted_suit:
                # 🚨 Application des règles INTER si actif
                if self.is_inter_mode_active and self.current_smart_rules:
                    for rule in self.current_smart_rules:
                        if rule['trigger_suit'] == predicted_suit:
                            predicted_suit = rule['target_suit']
                            break # On applique la première règle correspondante
                
                self.predictions[predicted_game_number] = {
                    'game_number': predicted_game_number,
                    'predicted_suit': predicted_suit,
                    'timestamp': time.time(),
                    'status': 'pending'
                }
                self._save_data(self.predictions, 'predictions.json')
                
                return True, game_number, predicted_suit
        
        return False, None, None

    # ... (_verify_prediction_common, make_prediction conservées)
    def _verify_prediction_common(self, text: str, is_edited: bool = False) -> Optional[Dict]:
        """Vérifie le résultat d'un jeu dans le canal source."""
        match = re.search(r'JEU\s+(\d+)\s*:.*', text, re.IGNORECASE)
        if not match:
            return None
        
        game_number = int(match.group(1))
        
        # Vérification du jeu N-2, où N est le jeu courant
        predicted_game = game_number - 2
        
        if predicted_game in self.predictions:
            prediction = self.predictions[predicted_game]
            
            # Extraction des informations sur la carte finale
            card_match = re.search(r'K\s*([♠️♥️♦️♣️])', text)
            k_found = bool(card_match)
            
            # Si le jeu a déjà été vérifié, ignorer l'édition sauf si c'est la première vérification
            if prediction.get('status', 'pending') not in ['pending', 'failed']:
                 return None
            
            # Logique de vérification (offset +2)
            verification_offset = 2 
            
            if k_found:
                # SUCCÈS - Le Roi (K) est trouvé au bon offset
                status_symbol = SYMBOL_MAP[verification_offset]
                updated_message = f"🔵{predicted_game}🔵:Valeur K statut :{status_symbol}"
                
                prediction['status'] = f'correct_offset_{verification_offset}'
                prediction['verification_count'] = verification_offset
                prediction['final_message'] = updated_message
                self._save_all_data()
                
                return {
                    'type': 'edit_message',
                    'predicted_game': predicted_game,
                    'new_message': updated_message,
                }
            elif verification_offset == 2 and not k_found:
                # ÉCHEC - MARQUER ❌ (RIEN TROUVÉ)
                updated_message = f"🔵{predicted_game}🔵:Valeur K statut :❌"

                prediction['status'] = 'failed'
                prediction['final_message'] = updated_message
                self._save_all_data()
                
                return {
                    'type': 'edit_message',
                    'predicted_game': predicted_game,
                    'new_message': updated_message,
                }
        return None

    def make_prediction(self, game_number: int, predicted_suit: str) -> str:
        """Crée le message de prédiction pour le jeu N+2."""
        target_game = game_number + 2
        
        if self.is_inter_mode_active:
             inter_status = "🧠 Mode INTER ACTIF"
        else:
             inter_status = "⚙️ Mode Statique"

        message = (
            f"🎯 **PRÉDICTION JEU {target_game}**\n\n"
            f"{inter_status}\n\n"
            f"**Couleur à prédire** : {predicted_suit} (pour Roi K)"
        )
        return message

    # --- Logique INTER (Nouvelles Méthodes) ---

    def _analyze_suit_data(self) -> List[Dict[str, Any]]:
        """Analyse les données pour identifier les règles INTER (Top 3 des couleurs avec le K qui suit)."""
        if len(self.inter_data) < 10:
            return []

        # 1. Identifier les occurrences où K apparaît dans le jeu (N)
        k_games = [item for item in self.inter_data if item['card_value'] == 'K']
        
        # 2. Compter la couleur qui précède (N-1) ces K
        preceding_suit_counts = defaultdict(lambda: defaultdict(int)) # {trigger_suit: {target_suit: count}}
        
        for k_game in k_games:
            k_game_number = k_game['game_number']
            
            # Trouver le jeu précédent (N-1)
            preceding_game = next((item for item in self.inter_data if item['game_number'] == k_game_number - 1), None)
            
            if preceding_game:
                trigger_suit = preceding_game['card_suit']
                target_suit = k_game['card_suit'] # La couleur du K
                preceding_suit_counts[trigger_suit][target_suit] += 1
        
        # 3. Transformer en règles (Top 3 des combinaisons les plus fréquentes)
        rules = []
        for trigger_suit, target_suits in preceding_suit_counts.items():
            # Trouver la couleur cible la plus fréquente pour ce trigger
            most_frequent_target = max(target_suits, key=target_suits.get)
            count = target_suits[most_frequent_target]
            
            # Seulement si le compte est supérieur ou égal à 2 (pour éviter le bruit)
            if count >= 2:
                rules.append({
                    'trigger_suit': trigger_suit,
                    'target_suit': most_frequent_target,
                    'count': count
                })
        
        # 4. Trier par count (du plus fréquent au moins fréquent) et prendre le Top 3
        rules.sort(key=lambda x: x['count'], reverse=True)
        return rules[:3] # Retourne les 3 règles les plus fortes

    def _did_rules_change(self, new_rules: List[Dict[str, Any]]) -> bool:
        """Vérifie si les nouvelles règles sont différentes des règles actuelles."""
        if len(self.current_smart_rules) != len(new_rules):
            return True
        
        # Comparaison des règles (en ignorant potentiellement l'ordre si les règles sont les mêmes)
        current_set = set(tuple(sorted(d.items())) for d in self.current_smart_rules)
        new_set = set(tuple(sorted(d.items())) for d in new_rules)
        
        return current_set != new_set

    def analyze_and_set_smart_rules(self, chat_id: int = None, force_activate: bool = False):
        """Déclenche l'analyse des règles, les met à jour, et envoie une notification si elles changent."""
        
        new_rules = self._analyze_suit_data()
        rules_changed = self._did_rules_change(new_rules)
        
        if rules_changed or force_activate:
            self.current_smart_rules = new_rules
            
            if force_activate:
                self.is_inter_mode_active = True
                self.active_admin_chat_id = chat_id # Enregistre l'ID pour la notification
            
            self.last_analysis_time = time.time()
            self._save_all_data() # Sauvegarde toutes les données mises à jour
            
            if self.is_inter_mode_active and self.telegram_message_sender and self.active_admin_chat_id:
                # Envoi de la notification
                notification_text = "🧠 **MISE À JOUR DES RÈGLES INTERLIGNE**\n\n"
                if rules_changed:
                    notification_text += "✅ **Nouvelles règles actives !**\n\n"
                elif force_activate:
                    notification_text += "✅ **Mode INTER ACTIVÉ.** Les règles actuelles sont :\n\n"
                    
                if new_rules:
                    for i, rule in enumerate(new_rules):
                        notification_text += f"{i+1}. Si ➡️ `{rule['trigger_suit']}` suit, prédire ➡️ `{rule['target_suit']}` (x{rule['count']})\n"
                else:
                    notification_text += "❌ Aucune règle forte détectée pour le moment."
                    
                self.telegram_message_sender(self.active_admin_chat_id, notification_text)


    def check_and_update_rules(self):
        """Vérifie si l'intervalle de 30 minutes est passé et met à jour les règles si le mode INTER est actif."""
        if not self.is_inter_mode_active:
            return

        current_time = time.time()
        time_elapsed = current_time - self.last_analysis_time
        
        if time_elapsed > ANALYSIS_INTERVAL_MINUTES * 60:
            logger.info(f"⌛ {ANALYSIS_INTERVAL_MINUTES} minutes écoulées. Déclenchement de l'analyse INTER périodique.")
            self.analyze_and_set_smart_rules()
        

    def get_inter_status(self, force_reanalyze: bool = False) -> Tuple[str, Optional[Dict]]:
        """Retourne le statut actuel du mode intelligent."""
        if force_reanalyze:
            self.analyze_and_set_smart_rules() # Force l'analyse si demandé
            
        status_message = "🧠 **STATUT MODE INTERLIGNE**\n\n"
        keyboard = None

        if self.is_inter_mode_active:
            status_message += "🟢 **Statut :** ACTIF (Mise à jour automatique toutes les 30 min)\n"
            status_message += f"🗓️ **Dernière analyse :** {datetime.fromtimestamp(self.last_analysis_time).strftime('%H:%M:%S')}\n\n"
            
            if self.current_smart_rules:
                status_message += "**Règles Top 3 actuelles :**\n"
                for i, rule in enumerate(self.current_smart_rules):
                    status_message += f"{i+1}. Si ➡️ `{rule['trigger_suit']}` suit, prédire ➡️ `{rule['target_suit']}` (x{rule['count']})\n"
            else:
                status_message += "**Règles :** ⚠️ Aucune règle forte détectée pour l'instant.\n"

            # Boutons pour désactiver
            keyboard = {
                'inline_keyboard': [
                    [{'text': "Désactiver le mode INTER", 'callback_data': 'inter_default'}],
                    [{'text': "Forcer l'analyse maintenant", 'callback_data': 'inter_apply'}]
                ]
            }

        else:
            status_message += "🔴 **Statut :** INACTIF (Mode Statique par défaut)\n\n"
            status_message += "ℹ️ Activez le mode pour un algorithme auto-apprenant (30 min)."
            
            # Boutons pour activer
            keyboard = {
                'inline_keyboard': [
                    [{'text': "Activer le mode INTER", 'callback_data': 'inter_apply'}]
                ]
            }
            
        return status_message, keyboard
        
