from django.apps import AppConfig


class LearningConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'learning'
    verbose_name = 'Learning & Quizzes'

    def ready(self):
        """
        Import signal handlers when the app is ready.

        This ensures signal handlers are registered before any models are used.
        Called automatically by Django during initialization.
        """
        import learning.signals  # noqa - Import signals to register handlers
