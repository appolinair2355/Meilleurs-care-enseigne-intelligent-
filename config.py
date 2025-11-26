# config.py

"""
Configuration settings for the Telegram bot
"""
import os
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# --- IDS DE CANAUX FIXES (Mis à jour avec tes valeurs) ---
# Canal source : Baccarat Kouamé
DEFAULT_TARGET_CHANNEL_ID = -1002682552255 
# Canal prédiction : Bot hyper Intelligent carte enseigne confiance 99%
DEFAULT_PREDICTION_CHANNEL_ID = -1003341134749 

# --- CONSTANTES POUR LES CALLBACKS DE CONFIGURATION ---
CALLBACK_SOURCE = "config_source"
CALLBACK_PREDICTION = "config_prediction"
CALLBACK_CANCEL = "config_cancel"

class Config:
    """Configuration class for bot settings"""
    
    def __init__(self):
        # BOT_TOKEN - OBLIGATOIRE
        self.BOT_TOKEN = self._get_bot_token()
        
        # Détermination de l'URL du Webhook
        self.WEBHOOK_URL = self._determine_webhook_url()
        logger.info(f"🔗 Webhook URL configuré: {self.WEBHOOK_URL}")

        # Port pour le serveur (utilise PORT env ou 10000 par défaut pour Render)
        self.PORT = int(os.getenv('PORT') or 10000)
        
        # --- CORRECTION ICI : Utilisation des IDs fournis ---
        # On essaie de lire les variables d'environnement, sinon on prend les valeurs par défaut codées en dur
        env_target = os.getenv('TARGET_CHANNEL_ID')
        self.TARGET_CHANNEL_ID = int(env_target) if env_target else DEFAULT_TARGET_CHANNEL_ID

        env_pred = os.getenv('PREDICTION_CHANNEL_ID')
        self.PREDICTION_CHANNEL_ID = int(env_pred) if env_pred else DEFAULT_PREDICTION_CHANNEL_ID
        
        # Log pour confirmer au démarrage
        logger.info(f"✅ ID Source configuré: {self.TARGET_CHANNEL_ID}")
        logger.info(f"✅ ID Prédiction configuré: {self.PREDICTION_CHANNEL_ID}")

        # Mode Debug
        self.DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
        
        # Validation finale
        self._validate_config()
    
    def _get_bot_token(self) -> str:
        """Récupère et valide le token du bot depuis les variables d'environnement."""
        token = os.getenv('BOT_TOKEN')
        if not token:
            raise ValueError("BOT_TOKEN environment variable not set.")
        if ':' not in token or not token.split(':')[0].isdigit():
            # Petite tolérance si le format change, mais warning
            logger.warning("Format du BOT_TOKEN potentiellement incorrect")

        logger.info(f"✅ BOT_TOKEN configuré: {token[:10]}...")
        return token
    
    def _determine_webhook_url(self) -> str:
        """Détermine l'URL du webhook avec priorité à l'ENV."""
        webhook_url = os.getenv('WEBHOOK_URL')
        
        if not webhook_url:
            if os.getenv('RENDER'):
                logger.warning("⚠️ Sur Render.com, WEBHOOK_URL doit être défini manuellement dans les variables d'environnement")
        
        return webhook_url or ""
    
    def _validate_config(self) -> None:
        """Valide les paramètres de configuration."""
        if self.WEBHOOK_URL and not self.WEBHOOK_URL.startswith('https://'):
            logger.warning("⚠️ L'URL du webhook devrait utiliser HTTPS pour la production.")
        
        if not self.PREDICTION_CHANNEL_ID or not self.TARGET_CHANNEL_ID:
             logger.error("⚠️ ATTENTION : Les IDs des canaux ne sont pas configurés corrects !")

        logger.info("✅ Configuration validée avec succès.")
    
    def get_webhook_url(self) -> str:
        """Renvoie l'URL complète du webhook (y compris /webhook)."""
        if self.WEBHOOK_URL:
            return f"{self.WEBHOOK_URL}/webhook"
        return ""
    
    def __str__(self) -> str:
        """Représentation textuelle de la configuration (sans données sensibles)."""
        return (
            f"Config(\n"
            f"  WEBHOOK_URL: {self.WEBHOOK_URL},\n"
            f"  PORT: {self.PORT},\n"
            f"  TARGET_CHANNEL_ID: {self.TARGET_CHANNEL_ID},\n"
            f"  PREDICTION_CHANNEL_ID: {self.PREDICTION_CHANNEL_ID},\n"
            f"  DEBUG: {self.DEBUG}\n"
            f")"
            )
        
