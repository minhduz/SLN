import tiktoken
import logging
from typing import List, Dict, Any

# Configure logging
logger = logging.getLogger(__name__)

# Token limits configuration - can be overridden by Django settings
DEFAULT_TOKEN_LIMITS = {
    'MAX_CONVERSATION_TOKENS': 12000,  # Maximum tokens in a conversation
    'WARNING_TOKENS': 10000,           # Warning threshold
    'CRITICAL_TOKENS': 11500,          # Critical threshold - force new chat
    'MAX_SINGLE_MESSAGE_TOKENS': 2000, # Maximum tokens in a single message
}

def get_token_limits() -> Dict[str, Any]:
    """Get token limits from Django settings if available, otherwise defaults"""
    try:
        from django.conf import settings
        if hasattr(settings, 'CHATBOT_CONFIG') and 'TOKEN_LIMITS' in settings.CHATBOT_CONFIG:
            return settings.CHATBOT_CONFIG['TOKEN_LIMITS']
    except Exception:
        pass
    return DEFAULT_TOKEN_LIMITS

TOKEN_LIMITS = get_token_limits()


class TokenCounter:
    """Helper class to count tokens using tiktoken"""

    def __init__(self, model_name: str = "gpt-4o"):
        try:
            # Get the encoding for the specific model
            self.encoding = tiktoken.encoding_for_model(model_name)
        except KeyError:
            # Fallback to cl100k_base encoding (used by GPT-4)
            self.encoding = tiktoken.get_encoding("cl100k_base")

    def count_tokens(self, text: str) -> int:
        """Count tokens in a text string"""
        if not text:
            return 0
        return len(self.encoding.encode(text))

    def count_message_tokens(self, messages: List) -> int:
        """Count tokens in a list of messages"""
        total = 0
        for message in messages:
            if hasattr(message, 'content'):
                total += self.count_tokens(str(message.content))
                # Add tokens for message formatting (role, etc.)
                total += 4  # Approximate overhead per message
        return total

    def truncate_text_to_tokens(self, text: str, max_tokens: int) -> str:
        """Truncate text to fit within token limit"""
        if not text:
            return text

        tokens = self.encoding.encode(text)
        if len(tokens) <= max_tokens:
            return text

        # Truncate tokens and decode back to text
        truncated_tokens = tokens[:max_tokens]
        return self.encoding.decode(truncated_tokens)
