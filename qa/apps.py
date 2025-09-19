from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)

class QaConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'qa'
    verbose_name = 'Question & Answer System'

    def ready(self):
        """Initialize the chatbot when Django starts up"""
        # Only initialize in the main process, not in migration or other management commands
        import sys
        if 'runserver' in sys.argv or 'gunicorn' in sys.argv[0] or 'uvicorn' in sys.argv:
            try:
                from .services.chatbot_agent import initialize_chatbot
                success = initialize_chatbot()
                if success:
                    logger.info("✅ Smart Learning Chatbot initialized successfully")
                else:
                    logger.warning("⚠️ Failed to initialize Smart Learning Chatbot")
            except ImportError as e:
                logger.warning(f"⚠️ Could not import chatbot_agent: {e}")
            except Exception as e:
                logger.error(f"❌ Error initializing chatbot: {e}")
