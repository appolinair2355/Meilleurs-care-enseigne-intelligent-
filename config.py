# config.py
import os

class Config:
    def __init__(self):
        self.BOT_TOKEN = os.getenv('BOT_TOKEN')
        self.WEBHOOK_URL = os.getenv('WEBHOOK_URL')
        self.PORT = int(os.getenv('PORT', 5000))
        self.DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
        
        # IDs par défaut (A remplacer par les vôtres si la config saute)
        self.DEFAULT_SOURCE = -1002682552255  
        self.DEFAULT_PREDICTION = -1003341134749

    def get_webhook_url(self):
        return f"{self.WEBHOOK_URL}/webhook" if self.WEBHOOK_URL else ""
