import logging
import re
from typing import Dict, Optional, List
from datetime import datetime
import time

# --- Configuration du Logger (à adapter) ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('CardPredictor')

# --- Constantes (à adapter si nécessaire) ---
# NOTE: Vous devez définir la liste des combinaisons valides si get_card_combination est utilisée
VALID_CARD_COMBINATIONS = [
    # Exemple: toutes les 3 cartes sont valides
    # ['♠️', '♥️', '♦️'], ['♠️', '♥️', '♣️'], etc.
]

class CardPredictor:
    """Gère la prédiction des cartes et la vérification des résultats échelonnés."""

    def __init__(self):
        self.predictions: Dict[int, Dict] = {}  # Stocke {num_jeu: {status, predicted_costume, message_id_bot, ...}}
        self.pending_edits: Dict[int, Dict] = {}  # Stocke les messages temporaires en attente d'édition
        self.processed_messages = set()
        self.prediction_cooldown = 60
        self.last_prediction_time = 0
        logger.info("CardPredictor initialisé.")

    # =========================================================================
    # --- Méthodes d'Analyse et de Comptage ---
    # =========================================================================

    def extract_game_number(self, text: str) -> Optional[int]:
        """Extrait le numéro du jeu à partir du format #NXXX."""
        match = re.search(r'#N(\d+)', text)
        return int(match.group(1)) if match else None

    def has_pending_indicators(self, text: str) -> bool:
        """Vérifie si le message contient des indicateurs suggérant qu'il sera édité (temporaire)."""
        indicators = ['⏰', '▶', '🕐', '➡️']
        return any(indicator in text for indicator in indicators)

    def has_completion_indicators(self, text: str) -> bool:
        """Vérifie si le message contient des indicateurs de complétion après édition (✅ ou 🔰)."""
        completion_indicators = ['✅', '🔰']
        return any(indicator in text for indicator in completion_indicators)

    def _extract_parentheses_content(self, text: str) -> List[str]:
        """Extrait le contenu de toutes les sections de parenthèses (non incluses)."""
        pattern = r'\(([^)]+)\)'
        return re.findall(pattern, text)

    def _count_cards_in_content(self, content: str) -> int:
        """Compte les symboles de cartes (♠️, ♥️, ♦️, ♣️) dans une chaîne, en normalisant ❤️ vers ♥️."""
        normalized_content = content.replace("❤️", "♥️")
        card_count = 0
        for symbol in ["♠️", "♥️", "♦️", "♣️"]:
            card_count += normalized_content.count(symbol)
        return card_count

    # =========================================================================
    # --- Logique de Classification et de Structure (MODIFIÉ) ---
    # =========================================================================

    def is_final_result_structurally_valid(self, text: str) -> bool:
        """Vérifie si la structure du message correspond à un format de résultat final connu (Normal ou Édité)."""
        matches = self._extract_parentheses_content(text)
        num_sections = len(matches)

        if num_sections < 2:
            return False

        # --- Message Normal (Règle 1) ---
        # Le format doit contenir 2 sections de parenthèses et le marqueur de fin 🔵#R
        if '🔵#R' in text and num_sections == 2:
            logger.info("🔍 VALIDATION STRUCTURALE: Normal (🔵#R).")
            return True

        # --- Messages Édités (Règles 2, 3, 4) ---
        # Si le message n'est pas "Normal", on vérifie s'il correspond aux formats de victoire édités.
        if num_sections == 2:
            content_1 = matches[0]
            content_2 = matches[1]
            
            count_1 = self._count_cards_in_content(content_1)
            count_2 = self._count_cards_in_content(content_2)

            # Format 3/2 : 3 cartes (1ère) / 2 cartes (2ème)
            if count_1 == 3 and count_2 == 2:
                logger.info("🔍 VALIDATION STRUCTURALE: Édité (3 cartes / 2 cartes).")
                return True

            # Format 3/3 : 3 cartes (1ère) / 3 cartes (2ème)
            if count_1 == 3 and count_2 == 3:
                logger.info("🔍 VALIDATION STRUCTURALE: Édité (3 cartes / 3 cartes).")
                return True

            # Format 2/3 : 2 cartes (1ère) / 3 cartes (2ème)
            if count_1 == 2 and count_2 == 3:
                logger.info("🔍 VALIDATION STRUCTURALE: Édité (2 cartes / 3 cartes).")
                return True

        logger.info(f"🔍 VALIDATION STRUCTURALE: Échec. Sections: {num_sections}.")
        return False
        
    def check_costume_in_first_parentheses(self, message: str, predicted_costume: str) -> bool:
        """Vérifie si le costume prédit apparaît dans le PREMIER parenthèses trouvé."""
        normalized_message = message.replace("❤️", "♥️")
        normalized_costume = predicted_costume.replace("❤️", "♥️")

        # Extrait SEULEMENT le contenu du PREMIER parenthèses
        pattern = r'\(([^)]+)\)'
        match = re.search(pattern, normalized_message)

        if not match:
            logger.info(f"🔍 Aucun parenthèses trouvé dans le message")
            return False

        first_parentheses_content = match.group(1)
        
        costume_found = normalized_costume in first_parentheses_content
        logger.info(f"🔍 Recherche costume {normalized_costume} dans PREMIER parenthèses: {costume_found}")
        return costume_found

    # =========================================================================
    # --- Méthodes de Prédiction et d'Attente ---
    # =========================================================================

    def should_wait_for_edit(self, text: str, message_id: int) -> bool:
        """Détermine si on doit attendre l'édition de ce message (temporaire)."""
        if self.has_pending_indicators(text):
            # Stocke ce message comme en attente d'édition
            if message_id not in self.pending_edits:
                game_number = self.extract_game_number(text)
                self.pending_edits[message_id] = {
                    'game_number': game_number,
                    'original_text': text,
                    'timestamp': datetime.now()
                }
                logger.info(f"⏳ MESSAGE TEMPORAIRE DÉTECTÉ: Jeu {game_number}, en attente d'édition.")
            return True
        return False

    def make_prediction(self, game_number: int, predicted_costume: str, message_id_bot: int) -> str:
        """Crée une prédiction et la stocke."""
        target_game = game_number + 2

        prediction_text = f"🔵{target_game}🔵:{predicted_costume}statut :⏳"

        # Store the prediction for later verification
        self.predictions[target_game] = {
            'predicted_costume': predicted_costume,
            'status': 'pending',
            'predicted_from': game_number,
            'verification_count': 0,
            'message_text': prediction_text,
            'message_id_bot': message_id_bot # CLÉ CRUCIALE POUR L'ÉDITION
        }

        self.last_prediction_time = time.time() # Mettre à jour le cooldown
        logger.info(f"🔮 PRÉDICTION FAITE - Jeu {target_game} avec costume {predicted_costume}. ID du message stocké: {message_id_bot}")
        return prediction_text

    # =========================================================================
    # --- Vérification Centrale (MODIFIÉ) ---
    # =========================================================================

    def _verify_prediction_common(self, text: str, is_edited: bool = False) -> Optional[Dict]:
        """Logique de vérification échelonnée des prédictions en attente."""
        game_number = self.extract_game_number(text)
        if not game_number:
            return None

        # --- ÉTAPE 1 : Filtrage des messages non terminés ---
        has_success_symbol = self.has_completion_indicators(text)
        is_structurally_valid = self.is_final_result_structurally_valid(text)

        # Le message doit être final (✅/🔰) ET avoir une structure de victoire connue.
        if not has_success_symbol or not is_structurally_valid:
            logger.info("🔍 ⏸️ Filtrage: Symbole de succès OU structure de résultat final manquante. Ignoré.")
            return None
        
        # --- ÉTAPE 2 : Vérification des prédictions en attente ---
        
        # VÉRIFICATION SÉQUENTIELLE: offset 0 → +1 → +2 → +3 → ❌
        for predicted_game in sorted(self.predictions.keys()):
            prediction = self.predictions[predicted_game]

            if prediction.get('status') != 'pending':
                continue # Passe aux prédictions déjà traitées

            verification_offset = game_number - predicted_game
            predicted_costume = prediction.get('predicted_costume')

            # Définir le statut par défaut et le symbole de succès
            status_symbol = None
            should_fail = False
            
            # --- Détermination du statut par Offset ---
            if 0 <= verification_offset <= 3:
                status_symbol = f"✅{verification_offset}️⃣"
            elif verification_offset > 3:
                status_symbol = "❌"
                should_fail = True
            else:
                continue # Offset négatif ou autre cas non pertinent

            
            # --- Vérification du Costume ---
            costume_found = False
            if not should_fail:
                costume_found = self.check_costume_in_first_parentheses(text, predicted_costume)

            
            if costume_found:
                # SUCCÈS (Offset 0, 1, 2 ou 3)
                updated_message = f"🔵{predicted_game}🔵:{predicted_costume}statut :{status_symbol}"

                prediction['status'] = 'correct'
                prediction['verification_count'] = verification_offset

                logger.info(f"🔍 ✅ SUCCÈS OFFSET {verification_offset} - Costume {predicted_costume} trouvé")
                
                # Supprimer le message traité pour éviter une nouvelle vérification
                del self.predictions[predicted_game] 

                return {
                    'type': 'edit_message',
                    'new_message': updated_message,
                    'message_id_to_edit': prediction['message_id_bot'] # ID du message du bot
                }
            
            elif should_fail:
                # ÉCHEC FINAL (Offset > 3)
                updated_message = f"🔵{predicted_game}🔵:{predicted_costume}statut :❌"

                prediction['status'] = 'failed'

                logger.info(f"🔍 ❌ ÉCHEC FINAL - Offset {verification_offset} dépassé, prédiction marquée: ❌")
                
                # Supprimer le message traité
                del self.predictions[predicted_game] 

                return {
                    'type': 'edit_message',
                    'new_message': updated_message,
                    'message_id_to_edit': prediction['message_id_bot']
                }
            else:
                # ÉCHEC à l'offset actuel (continue d'attendre le prochain jeu)
                logger.info(f"🔍 ❌ ÉCHEC OFFSET {verification_offset} - Costume non trouvé, attente du prochain jeu...")
                continue
                
        return None # Aucune prédiction éligible ou terminée

    def verify_prediction(self, message: str) -> Optional[Dict]:
        """Vérification pour un nouveau message non édité."""
        return self._verify_prediction_common(message, is_edited=False)

    def verify_prediction_from_edit(self, message: str) -> Optional[Dict]:
        """Vérification pour un message édité."""
        return self._verify_prediction_common(message, is_edited=True)
# --- bot_handler.py ---

from card_predictor import CardPredictor
from typing import Dict, Optional
import random

# Initialisation de l'instance du Prédicteur
card_predictor = CardPredictor()

# --- SIMULATION D'API (DOIT ÊTRE REMPLACÉE PAR VOTRE API RÉELLE) ---

LAST_BOT_MESSAGE_ID = 10000 

def send_api_message(chat_id: int, text: str) -> int:
    """Simule l'envoi d'un message et retourne un ID unique."""
    global LAST_BOT_MESSAGE_ID
    LAST_BOT_MESSAGE_ID += 1
    print(f"\n[API SENT] ➡️ NOUVELLE PRÉDICTION (ID: {LAST_BOT_MESSAGE_ID}): {text}")
    return LAST_BOT_MESSAGE_ID

def send_api_edit_message(chat_id: int, message_id: int, new_text: str):
    """Simule l'édition d'un message."""
    print(f"\n[API ACTION] ✏️ ÉDITION DU MESSAGE ID {message_id}...")
    print(f"   Ancien statut: ⏳")
    print(f"   Nouveau statut: {new_text.split('statut :')[-1]}")
    print(f"   Message complet: {new_text}")
    print("-----------------------------------")
    return True 

# --- GESTION DES MESSAGES ENTRANTS ---

def simulate_prediction_logic(game_number: int) -> Optional[str]:
    """
    SIMULE la logique de votre commande interne qui décide QUOI prédire.
    (Remplacez par votre propre logique ou appel à la commande /predic)
    """
    if time.time() - card_predictor.last_prediction_time < card_predictor.prediction_cooldown:
        # Respect du Cooldown
        return None 
        
    # Logique simplifiée: Prédire un costume aléatoire (♠️, ♥️, ♦️, ♣️)
    costumes = ["♠️", "♥️", "♦️", "♣️"]
    return random.choice(costumes)


def handle_incoming_message(message_data: Dict, is_edited: bool = False):
    """
    Point d'entrée unique pour traiter les messages entrants.
    
    :param message_data: Doit contenir 'text', 'chat_id', 'message_id'.
    :param is_edited: True si le message est une mise à jour d'un message existant.
    """
    text = message_data.get('text', '')
    chat_id = message_data.get('chat_id', 12345)
    message_id = message_data.get('message_id', 99999)
    game_number = card_predictor.extract_game_number(text)

    if not text or not game_number:
        return

    # A. Gestion des Messages Temporaires (Étape 5 - Filtrage)
    if not is_edited and card_predictor.should_wait_for_edit(text, message_id):
        # Le message a été stocké, on arrête le traitement pour l'instant.
        return 

    # B. Vérification des Prédictions (Étape 6 & 7)
    if is_edited:
        action = card_predictor.verify_prediction_from_edit(text)
    else:
        action = card_predictor.verify_prediction(text)

    # C. Exécution de l'Action (Édition) (Étape 8)
    if action and action.get('type') == 'edit_message':
        send_api_edit_message(
            chat_id=chat_id,
            message_id=action.get('message_id_to_edit'), 
            new_text=action.get('new_message')
        )
        return # Arrêt après une action d'édition réussie

    # D. Génération de Nouvelle Prédiction (Cycle 1 - Étape 2 & 3)
    # Cette étape ne doit se faire que si le message est un résultat final pour le jeu précédent.
    
    # 1. Simplification: Utilisons le même message de résultat pour potentiellement prédire le jeu N+2
    predicted_costume = simulate_prediction_logic(game_number) 
    
    if predicted_costume:
        # Envoi de la prédiction
        prediction_text = f"🔵{game_number + 2}🔵:{predicted_costume}statut :⏳"
        
        # Le bot envoie le message via l'API
        sent_id = send_api_message(chat_id, prediction_text)
        
        # Stockage de la prédiction avec l'ID du message que nous venons d'envoyer
        card_predictor.make_prediction(game_number, predicted_costume, sent_id)


# --- EXEMPLE D'UTILISATION (SIMULATION DE FLUX) ---

if __name__ == '__main__":
    CHAT_ID = 123
    
    print("--- DÉBUT DE LA SIMULATION ---")
    
    # 1. MESSAGE INITIAL (Normal) - Pas d'indicateurs de succès, non utilisé pour l'édition
    # Il sert ici d'INPUT pour la première prédiction (Jeu 100)
    msg_input = {'text': '#N98. 5(4♠️7❤️) - 9(6❤️K♠️) #T14 🔵#R', 'chat_id': CHAT_ID, 'message_id': 20098}
    print("\n[IN] 1. Message de référence N98 (INPUT pour prédire le jeu 100)")
    handle_incoming_message(msg_input)
    
    # Vérification de la prédiction stockée
    print(f"\n[ÉTAT] Prédictions en attente: {card_predictor.predictions}")

    # 2. MESSAGE TEMPORAIRE (Nouveau message)
    # Le bot le stocke et l'ignore
    msg_temp = {'text': '⏰#N99. ▶️ 2(2♥️10♠️) - 3(A♦️2♥️)', 'chat_id': CHAT_ID, 'message_id': 20099}
    print("\n[IN] 2. Message N99 Temporaire (à ignorer)")
    handle_incoming_message(msg_temp)
    print(f"[ÉTAT] Messages temporaires en attente: {card_predictor.pending_edits.keys()}")

    # 3. MESSAGE DE RÉSULTAT DU JEU 100 (qui vérifie la prédiction faite à l'étape 1)
    # Supposons que le costume prédit à l'étape 1 était ♥️. Ce message contient ♥️ (SUCCÈS OFFSET 0)
    msg_result_success = {'text': '#N100. 5(5♣️10♥️Q♦️) 🔰 5(10♠️Q♦️5♠️) #T10 🟣#X', 'chat_id': CHAT_ID, 'message_id': 20100}
    print("\n[IN] 3. Message N100 (Résultat 3/3, contient ♥️)")
    handle_incoming_message(msg_result_success)

    # 4. MESSAGE ÉDITÉ (pour vérifier l'attente)
    # Le message N99 est édité et contient le résultat final N99. Costume (♦️) non trouvé (ÉCHEC OFFSET 1 si elle existait)
    msg_edited_fail = {'text': '#N99. 5(4♠️A♦️) - ✅9(9♦️K♠️7♣️) #T14 🔵#', 'chat_id': CHAT_ID, 'message_id': 20099}
    print("\n[IN] 4. Message N99 ÉDITÉ (Doit être vérifié et retiré des pending_edits)")
    handle_incoming_message(msg_edited_fail, is_edited=True)
    
    print(f"\n[FIN ÉTAT] Prédictions restantes: {card_predictor.predictions}")
    print(f"[FIN ÉTAT] Messages temporaires (doit être vide ou géré): {card_predictor.pending_edits}")
    print("--- FIN DE LA SIMULATION ---")
        
