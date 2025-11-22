from django.apps import AppConfig


class EconomyConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'economy'

    def ready(self):
        # Load signal handlers when app is ready
        import economy.signals
