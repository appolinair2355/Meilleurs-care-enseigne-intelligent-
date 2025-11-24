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
        self.pending_edits: Dict[int, Dict] = self._load_data('pending_edits.json') # AJOUT: Stockage des messages temporaires
        
        # --- B. Configuration Canaux (AVEC FALLBACK SÉCURISÉ) ---
        raw_config = self._load_data('channels_config.json')
        self.config_data = raw_config if isinstance(raw_config, dict) else {}
        
        # 1. Tente de charger depuis le fichier
        self.target_channel_id = self.config_data.get('target_channel_id')
        # 2. Si le fichier est perdu (Render), utilise l'ID forcé
        if not self.target_channel_id and self.HARDCODED_SOURCE_ID != 0:
            self.target_channel_id = self.HARDCODED_SOURCE_ID
            
        # 1. Tente de charger depuis le fichier
        self.prediction_channel_id = self.config_data.get('prediction_channel_id')
        # 2. Si le fichier est perdu (Render), utilise l'ID forcé
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
        
        # Activation par défaut si l'état INTER est perdu
        if self.is_inter_mode_active is None:
            self.is_inter_mode_active = True
        
        self.prediction_cooldown = 30 
        
        # Analyse initiale au démarrage
        if self.inter_data and not self.is_inter_mode_active and not self.smart_rules:
             self.analyze_and_set_smart_rules(initial_load=True)

    # --- Persistance ---
    def _load_data(self, filename: str, is_set: bool = False, is_scalar: bool = False) -> Any:
        try:
            # AJOUT: Ajout de 'pending_edits.json' aux fichiers traités comme dict
            is_dict = filename in ['channels_config.json', 'predictions.json', 'sequential_history.json', 'smart_rules.json', 'pending_edits.json']
            
            if not os.path.exists(filename):
                return set() if is_set else (None if is_scalar else ({} if is_dict else []))
            with open(filename, 'r') as f:
                content = f.read().strip()
                if not content: return set() if is_set else (None if is_scalar else ({} if is_dict else []))
                data = json.loads(content)
                if is_set: return set(data)
                # Conversion des clés str -> int pour les dictionnaires indexés par ID jeu/message
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
            # S'assure que les IDs sont des entiers avant la sauvegarde
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
        self._save_data(self.pending_edits, 'pending_edits.json') # AJOUT: Sauvegarde des messages temporaires

    def set_channel_id(self, channel_id: int, channel_type: str):
        # Cette méthode est toujours utile si l'utilisateur change d'ID via /config
        if not isinstance(self.config_data, dict): self.config_data = {}
        if channel_type == 'source':
            self.target_channel_id = channel_id
            self.config_data['target_channel_id'] = channel_id
        elif channel_type == 'prediction':
            self.prediction_channel_id = channel_id
            self.config_data['prediction_channel_id'] = channel_id
        self._save_data(self.config_data, 'channels_config.json')
        return True

    # --- NOUVEAUX Outils d'Extraction/Comptage ---
    
    def _extract_parentheses_content(self, text: str) -> List[str]:
        """Extrait le contenu de toutes les sections de parenthèses (non incluses)."""
        pattern = r'\(([^)]+)\)'
        return re.findall(pattern, text)

    def _count_cards_in_content(self, content: str) -> int:
        """Compte les symboles de cartes (♠️, ♥️, ♦️, ♣️) dans une chaîne, en normalisant ❤️ vers ♥️."""
        # On utilise le même ensemble de symboles que extract_card_details
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
        """Vérifie si la structure du message correspond à un format de résultat final connu (Normal ou Édité)."""
        matches = self._extract_parentheses_content(text)
        num_sections = len(matches)

        if num_sections < 2:
            return False

        # --- Message Normal (Règle 1) ---
        # Le format doit contenir 2 sections de parenthèses et le marqueur de fin 🔵#R
        if '🔵#R' in text and num_sections == 2:
            logger.debug("🔍 VALIDATION STRUCTURALE: Normal (🔵#R).")
            return True

        # --- Messages Édités (Règles 2, 3, 4) ---
        if num_sections == 2:
            content_1 = matches[0]
            content_2 = matches[1]
            
            count_1 = self._count_cards_in_content(content_1)
            count_2 = self._count_cards_in_content(content_2)

            # Format 3/2 : 3 cartes (1ère) / 2 cartes (2ème)
            if count_1 == 3 and count_2 == 2:
                logger.debug("🔍 VALIDATION STRUCTURALE: Édité (3 cartes / 2 cartes).")
                return True

            # Format 3/3 : 3 cartes (1ère) / 3 cartes (2ème)
            if count_1 == 3 and count_2 == 3:
                logger.debug("🔍 VALIDATION STRUCTURALE: Édité (3 cartes / 3 cartes).")
                return True

            # Format 2/3 : 2 cartes (1ère) / 3 cartes (2ème)
            if count_1 == 2 and count_2 == 3:
                logger.debug("🔍 VALIDATION STRUCTURALE: Édité (2 cartes / 3 cartes).")
                return True

        logger.debug(f"🔍 VALIDATION STRUCTURALE: Échec. Sections: {num_sections}.")
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
        # Note: L'enseigne est le deuxième élément du tuple
        return re.findall(r'(\d+|[AKQJ])(♠️|❤️|♦️|♣️)', normalized_content, re.IGNORECASE)

    def get_first_card_info(self, message: str) -> Optional[Tuple[str, str]]:
        """
        Retourne la PREMIÈRE carte du PREMIER groupe.
        Retour: (CarteComplète, Enseigne) -> ex: ("10♦️", "♦️")
        """
        # 1. Trouve le contenu entre la première parenthèse (...)
        match = re.search(r'\(([^)]*)\)', message)
        if not match: return None
        
        # 2. Extrait les cartes à l'intérieur
        details = self.extract_card_details(match.group(1))
        if details:
            v, c = details[0]
            # Normalisation des cœurs pour la clé de règle
            if c == "❤️": c = "♥️" 
            return f"{v.upper()}{c}", c 
        return None
        
    def extract_costumes_from_second_parentheses(self, text: str) -> Optional[str]:
        """
        Extrait le contenu de la deuxième parenthèse (qui est l'input pour la prédiction)
        Exemple: #N87. 5(4♠️7❤️) - ✅9(6❤️K♠️) #T14 🔵#R -> '6❤️K♠️' (Si 2 groupes)
        """
        matches = self._extract_parentheses_content(text)
        
        # Le deuxième match ([1]) contient le contenu de la deuxième parenthèse (si elle existe)
        if len(matches) >= 2:
            return matches[1]
        return None

    # --- Logique INTER (Apprentissage N-2) (INCHANGÉE, sauf pour l'appel) ---
    def collect_inter_data(self, game_number: int, message: str):
        # ... (Logique identique à l'original) ...
        info = self.get_first_card_info(message)
        if not info: return
        
        full_card, suit = info

        # 1. Stocker la carte du jeu actuel (N) pour qu'elle serve de déclencheur futur
        self.sequential_history[game_number] = {'carte': full_card, 'date': datetime.now().isoformat()}
        
        # 2. Vérifier si ce jeu (N) est un résultat pour un déclencheur passé (N-2)
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
                    'result_suit': suit, # L'enseigne résultante (ex: "♠️")
                    'date': datetime.now().isoformat()
                })
                self._save_all_data()

        # Nettoyage (Garde les 50 derniers jeux)
        limit = game_number - 50
        self.sequential_history = {k:v for k,v in self.sequential_history.items() if k >= limit}

    # ... (analyze_and_set_smart_rules, check_and_update_rules, get_inter_status sont inchangées) ...
    def analyze_and_set_smart_rules(self, chat_id: int = None, initial_load: bool = False, force_activate: bool = False):
        """Analyse les données pour trouver les Top 3 règles Enseignes."""
        counts = defaultdict(lambda: defaultdict(int))
        for entry in self.inter_data:
            trig = entry['declencheur']
            res = entry['result_suit']
            counts[trig][res] += 1
            
        candidates = []
        for trig, results in counts.items():
            best_suit = max(results, key=results.get)
            count = results[best_suit]
            candidates.append({'trigger': trig, 'predict': best_suit, 'count': count})
            
        # Top 3 Global
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
            msg = "🧠 **MISE À JOUR INTER (30min)**\n\n**Top 3 Règles (Carte -> Enseigne):**\n"
            if self.smart_rules:
                for r in self.smart_rules:
                    msg += f"🥇 {r['trigger']} → {r['predict']} (x{r['count']})\n"
            else:
                msg += "Aucune règle fiable trouvée pour le moment."
            self.telegram_message_sender(self.active_admin_chat_id, msg)

    def check_and_update_rules(self):
        """Vérification périodique (30 minutes)."""
        if self.is_inter_mode_active and (time.time() - self.last_analysis_time > 1800):
            self.analyze_and_set_smart_rules(chat_id=self.active_admin_chat_id)

    def get_inter_status(self, force_reanalyze: bool = False) -> Tuple[str, Optional[Dict]]:
        if force_reanalyze: self.analyze_and_set_smart_rules()
        
        msg = f"**🧠 ETAT DU MODE INTELLIGENT**\n\n"
        msg += f"**Actif :** {'✅ OUI' if self.is_inter_mode_active else '❌ NON'}\n"
        msg += f"**Données collectées :** {len(self.inter_data)}\n\n"
        
        if self.smart_rules:
            msg += "**📜 Règles Actives (Top 3):**\n"
            for r in self.smart_rules:
                msg += f"• Si **{r['trigger']}** (N-2) → Prédire **{r['predict']}** (x{r['count']})\n"
        else:
            msg += "⚠️ Pas assez de données pour former des règles."
            
        kb = {'inline_keyboard': [
            [{'text': '✅ Activer / Mettre à jour', 'callback_data': 'inter_apply'}],
            [{'text': '❌ Désactiver (Retour Statique)', 'callback_data': 'inter_default'}]
        ]}
        return msg, kb


    # --- CŒUR DU SYSTÈME : PRÉDICTION (MODIFIÉ) ---
    
    def should_wait_for_edit(self, text: str, message_id: int) -> bool:
        """Détermine si on doit attendre l'édition de ce message (temporaire)."""
        if self.has_pending_indicators(text):
            game_number = self.extract_game_number(text)
            if message_id not in self.pending_edits:
                self.pending_edits[message_id] = {
                    'game_number': game_number,
                    'original_text': text,
                    'timestamp': datetime.now().isoformat()
                }
                self._save_data(self.pending_edits, 'pending_edits.json')
                logger.info(f"⏳ MESSAGE TEMPORAIRE DÉTECTÉ: Jeu {game_number}, en attente d'édition.")
            return True
        return False

    def should_predict(self, message: str) -> Tuple[bool, Optional[int], Optional[str]]:
        # 1. Vérif Périodique
        self.check_and_update_rules()
        
        game_number = self.extract_game_number(message)
        if not game_number: return False, None, None
        
        # 2. Filtres Temporaires/Completion (Empêche la prédiction basée sur un message incomplet)
        # On prédit SEULEMENT sur un résultat final (avec un symbole ✅ ou 🔰)
        if not self.has_completion_indicators(message) or self.has_pending_indicators(message): 
            return False, None, None
        
        # Règle : Ecart de 3 jeux
        if self.last_predicted_game_number and (game_number - self.last_predicted_game_number < 3):
            return False, None, None
            
        # 3. Décision
        info = self.get_first_card_info(message)
        if not info: return False, None, None
        first_card, _ = info # On ne garde que la carte complète pour le déclencheur
        
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
            # Vérification du Cooldown
            if self.last_prediction_time and time.time() < self.last_prediction_time + self.prediction_cooldown:
                return False, None, None
                
            return True, game_number, predicted_suit

        return False, None, None

        def prepare_prediction_text(self, game_number_source: int, predicted_costume: str) -> str:
        """Prépare le texte de prédiction à envoyer."""
        target_game = game_number_source + 2
        return f"🔵{target_game}🔵:Enseigne {predicted_costume} statut :⏳"


    def make_prediction(self, game_number_source: int, suit: str, message_id_bot: int):
        """Crée une prédiction et la stocke avec l'ID du message du bot."""
        target = game_number_source + 2
        txt = self.prepare_prediction_text(game_number_source, suit)
        
        self.predictions[target] = {
            'predicted_costume': suit, 
            'status': 'pending', 
            'predicted_from': game_number_source, 
            'message_text': txt, 
            'message_id': message_id_bot, # CLÉ CRUCIALE POUR L'ÉDITION
            'is_inter': self.is_inter_mode_active
        }
        
        self.last_prediction_time = time.time()
        self.last_predicted_game_number = game_number_source
        self.consecutive_fails = 0
        self._save_all_data()

    def _verify_prediction_common(self, text: str) -> Optional[Dict]:
        """Vérifie si une prédiction en attente est validée par le message actuel."""
        game_number = self.extract_game_number(text)
        if not game_number: return None
        
        # --- ÉTAPE 1 : Filtrage des messages non terminés (Critique) ---
        has_success_symbol = self.has_completion_indicators(text)
        is_structurally_valid = self.is_final_result_structurally_valid(text)

        # Le message doit être final (✅/🔰) ET avoir une structure de victoire connue.
        if not has_success_symbol or not is_structurally_valid:
            logger.debug("🔍 ⏸️ Filtrage: Symbole de succès OU structure de résultat final manquante. Ignoré.")
            return None
        
        # =========================================================================
        # >>> POINT D'INSERTION CRITIQUE POUR LA COLLECTE DE DONNÉES INTER <<<
        # L'appel est ici, après la validation structurelle et la complétion.
        self.collect_inter_data(game_number, text) 
        logger.info("🧠 Données collectées avec succès pour l'analyse INTER.")
        # =========================================================================
        
        # --- ÉTAPE 2 : Vérification des prédictions en attente ---
        
        # Copie pour itération sûre
        for pred_game, pred_data in list(self.predictions.items()):
            if pred_data['status'] != 'pending': continue
            
            # Vérifie N+2, N+3, N+4 (offset 0, 1, 2)
            offset = game_number - int(pred_game)
            if not (0 <= offset <= 2): continue 
            
            predicted = pred_data['predicted_costume']
            
            # --- Extraction de TOUTES les enseignes du premier groupe ---
            # 1. Trouve le contenu entre la première parenthèse (...)
            match = re.search(r'\(([^)]*)\)', text)
            if not match: continue 

            # 2. Extrait TOUTES les cartes/enseignes dans ce groupe
            details = self.extract_card_details(match.group(1))
            
            # Récupère la liste de TOUTES les enseignes trouvées
            all_found_suits = {suit for _, suit in details} 
            
            # Normalisation des cœurs pour la vérification
            normalized_predicted = predicted.replace("♥️", "❤️") 
            normalized_found_suits = {s.replace("♥️", "❤️") for s in all_found_suits}
            
            
            # 1. SUCCÈS : L'enseigne prédite est présente dans TOUTES les enseignes du groupe
            if normalized_predicted in normalized_found_suits:
                symbol = SYMBOL_MAP.get(offset, '✅')
                msg = f"🔵{pred_game}🔵:Enseigne {predicted} statut :{symbol}"
                pred_data['status'] = 'won'
                pred_data['final_message'] = msg
                self.consecutive_fails = 0
                self._save_all_data()
                
                # Mise à jour de la prédiction dans le dict et retour
                self.predictions[int(pred_game)] = pred_data
                return {
                    'type': 'edit_message', 
                    'predicted_game': str(pred_game), 
                    'new_message': msg, 
                    'message_id_to_edit': pred_data.get('message_id') # Ajout de l'ID du message du bot
                }
            
            # 2. ÉCHEC : Après offset 2, si l'enseigne n'a été trouvée ni en N, N+1, ni N+2
            elif offset == 2:
                msg = f"🔵{pred_game}🔵:Enseigne {predicted} statut :❌"
                pred_data['status'] = 'lost'
                pred_data['final_message'] = msg
                
                # Gestion Automatique de l'IA (INCHANGÉE)
                if pred_data.get('is_inter'):
                    self.is_inter_mode_active = False 
                    logger.info("❌ Échec INTER : Désactivation automatique.")
                else:
                    self.consecutive_fails += 1
                    if self.consecutive_fails >= 2:
                        # Force l'analyse et l'activation INTER
                        self.analyze_and_set_smart_rules(force_activate=True) 
                        logger.info("⚠️ 2 Échecs Statiques : Activation automatique INTER.")
                
                self._save_all_data()
                
                # Mise à jour de la prédiction dans le dict et retour
                self.predictions[int(pred_game)] = pred_data
                return {
                    'type': 'edit_message', 
                    'predicted_game': str(pred_game), 
                    'new_message': msg, 
                    'message_id_to_edit': pred_data.get('message_id') # Ajout de l'ID du message du bot
                }
                
        return None
    
    def verify_prediction_from_edit(self, message: str) -> Optional[Dict]:
        """Vérification pour un message édité."""
        return self._verify_prediction_common(message)

    def verify_prediction(self, message: str) -> Optional[Dict]:
        """Vérification pour un nouveau message."""
        return self._verify_prediction_common(message)
