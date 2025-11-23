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
            if not os.path.exists(filename):
                return set() if is_set else (None if is_scalar else ({} if filename in ['channels_config.json', 'predictions.json', 'sequential_history.json', 'smart_rules.json'] else []))
            with open(filename, 'r') as f:
                content = f.read().strip()
                if not content: return set() if is_set else (None if is_scalar else ({} if filename in ['channels_config.json', 'predictions.json', 'sequential_history.json', 'smart_rules.json'] else []))
                data = json.loads(content)
                if is_set: return set(data)
                # Conversion des clés str -> int pour les dictionnaires indexés par ID jeu
                if filename in ['sequential_history.json', 'predictions.json'] and isinstance(data, dict): 
                    return {int(k): v for k, v in data.items()}
                return data
        except Exception as e:
            logger.error(f"⚠️ Erreur chargement {filename}: {e}")
            return set() if is_set else (None if is_scalar else ({} if filename in ['channels_config.json', 'predictions.json', 'sequential_history.json', 'smart_rules.json'] else []))

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

    # --- Outils d'Extraction ---
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
            return f"{v.upper()}{c}", c 
        return None

    # --- Logique INTER (Apprentissage N-2) ---
    def collect_inter_data(self, game_number: int, message: str):
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

    def analyze_and_set_smart_rules(self, chat_id: Optional[int] = None, initial_load: bool = False, force_activate: bool = False):
        """Analyse les données pour trouver les Top 3 règles Enseignes."""
        counts = defaultdict(lambda: defaultdict(int))
        for entry in self.inter_data:
            trig = entry['declencheur']
            res = entry['result_suit']
            counts[trig][res] += 1
            
        candidates = []
        for trig, results in counts.items():
            if results:
                best_suit = max(results, key=lambda x: results[x])
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
        
        # Aperçu des derniers déclencheurs collectés
        if self.inter_data:
            msg += "**🎯 Derniers déclencheurs collectés:**\n"
            recent = sorted(self.inter_data, key=lambda x: x.get('date', ''), reverse=True)[:5]
            for entry in recent:
                msg += f"• N{entry['numero_declencheur']} ({entry['declencheur']}) → {entry['result_suit']}\n"
            msg += "\n"
        
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

    # --- CŒUR DU SYSTÈME : PRÉDICTION ---
    def should_predict(self, message: str) -> Tuple[bool, Optional[int], Optional[str]]:
        # 1. Vérif Périodique
        self.check_and_update_rules()
        
        # VÉRIF CRITIQUE : Maintenant que les IDs sont forcés, ceci devrait toujours être vrai.
        if not self.target_channel_id: 
            logger.warning("❌ target_channel_id non défini. Impossible de prédire.")
            return False, None, None
            
        game_number = self.extract_game_number(message)
        if not game_number: 
            return False, None, None
        
        # 2. Filtres : ignorer les messages de timing
        if '🕐' in message or '⏰' in message: 
            return False, None, None
        
        # 3. Extraire la première carte AVANT de vérifier ✅/🔰
        info = self.get_first_card_info(message)
        if not info: 
            return False, None, None
        first_card, suit = info
        
        # 4. Collecte INTER (Démarre la collecte puisque l'ID est connu)
        self.collect_inter_data(game_number, message)
        
        # 5. Vérifier que le message est finalisé (✅ ou 🔰)
        if '✅' not in message and '🔰' not in message: 
            return False, None, None
        
        # 6. Règle : Ecart de 3 jeux minimum
        if self.last_predicted_game_number and (game_number - self.last_predicted_game_number < 3):
            logger.info(f"⏭️ Skip prédiction : Écart trop court (dernier: {self.last_predicted_game_number}, actuel: {game_number})")
            return False, None, None

        # 7. Décision de prédiction
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

        # 8. Si une prédiction est trouvée, vérifier le cooldown
        if predicted_suit:
            time_since_last = time.time() - self.last_prediction_time if self.last_prediction_time else 999
            if self.last_prediction_time and time.time() < self.last_prediction_time + 30:
                logger.warning(f"⏳ COOLDOWN ACTIF: {int(30 - time_since_last)}s restantes | Jeu {game_number} ({first_card}) → {predicted_suit} IGNORÉ")
                return False, None, None
            
            # Vérification supplémentaire de l'écart
            if self.last_predicted_game_number and (game_number - self.last_predicted_game_number < 3):
                logger.warning(f"⏭️ ÉCART INSUFFISANT: Dernier={self.last_predicted_game_number}, Actuel={game_number}, Diff={game_number - self.last_predicted_game_number} | Jeu {game_number} ({first_card}) → {predicted_suit} IGNORÉ")
                return False, None, None
                
            self.last_prediction_time = time.time()
            self.last_predicted_game_number = game_number
            self.consecutive_fails = 0
            self._save_all_data()
            logger.info(f"✅ PRÉDICTION CRÉÉE: Jeu {game_number} ({first_card}) → Prédire {predicted_suit} pour jeu {game_number + 2}")
            return True, game_number, predicted_suit

        logger.info(f"❌ Aucune règle trouvée pour {first_card}")
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
        """
        🔄 Séquence de Vérification :
        1. Si Numéro prédit (offset 0) reçoit la carte prédite → statut = ✅0️⃣ et ARRÊT
        2. Sinon, vérifier Prédit +1 (offset 1) → statut = ✅1️⃣ et ARRÊT
        3. Sinon, vérifier Prédit +2 (offset 2) → statut = ✅2️⃣ et ARRÊT
        4. Si offset 2 atteint sans correspondance → statut = ❌ et ARRÊT
        """
        game_number = self.extract_game_number(text)
        if not game_number: return None
        
        # --- Extraction de l'enseigne GAGNANTE (fait UNE SEULE FOIS) ---
        # Format: #N490. ✅9(J♠️3♦️6♣️) - 1(J♦️K♠️A♠️)
        # RÈGLE: L'enseigne gagnante est celle du PREMIER groupe (celui de gauche)
        first_group_match = re.search(r'#N\d+\.\s*[✅🔰]?\d*\(([^)]+)\)', text)
        found_suit = None
        
        if first_group_match:
            winner_cards = first_group_match.group(1)
            card_details = self.extract_card_details(winner_cards)
            if card_details:
                found_suit = card_details[0][1]  # L'enseigne de la première carte
        
        # Si aucune enseigne trouvée, on ne peut pas vérifier
        if not found_suit:
            return None
        
        # 🔄 SÉQUENCE DE VÉRIFICATION : offset 0 → 1 → 2
        # Vérifier d'abord offset 0, puis 1, puis 2 dans l'ordre
        for check_offset in [0, 1, 2]:
            # Calculer le numéro de prédiction correspondant à cet offset
            pred_game = game_number - check_offset
            
            # Vérifier si une prédiction existe pour ce numéro
            pred_data = self.predictions.get(pred_game)
            if not pred_data or pred_data['status'] != 'pending':
                continue  # Pas de prédiction pending pour cet offset, passer au suivant
            
            predicted = pred_data['predicted_costume']
            
            # ✅ SUCCÈS : L'enseigne correspond
            if found_suit == predicted:
                symbol = SYMBOL_MAP.get(check_offset, '✅')
                msg = f"🔵{pred_game}🔵:Enseigne {predicted} statut :{symbol}"
                pred_data['status'] = 'won'
                pred_data['final_message'] = msg
                self.consecutive_fails = 0
                self._save_all_data()
                logger.info(f"✅ Prédiction {pred_game} validée à offset {check_offset} avec {predicted}")
                return {'type': 'edit_message', 'predicted_game': str(pred_game), 'new_message': msg}
            
            # ❌ ÉCHEC : Offset 2 atteint sans correspondance → ARRÊT
            elif check_offset == 2:
                msg = f"🔵{pred_game}🔵:Enseigne {predicted} statut :❌"
                pred_data['status'] = 'lost'
                pred_data['final_message'] = msg
                
                # Gestion Automatique
                if pred_data.get('is_inter'):
                    self.is_inter_mode_active = False 
                    logger.info("❌ Échec INTER : Désactivation automatique.")
                else:
                    self.consecutive_fails += 1
                    if self.consecutive_fails >= 2:
                        self.analyze_and_set_smart_rules(force_activate=True) 
                        logger.info("⚠️ 2 Échecs Statiques : Activation automatique INTER.")
                
                self._save_all_data()
                logger.info(f"❌ Prédiction {pred_game} échouée à offset 2 (prédit: {predicted}, trouvé: {found_suit})")
                return {'type': 'edit_message', 'predicted_game': str(pred_game), 'new_message': msg}
                
        return None
