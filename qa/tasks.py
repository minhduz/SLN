# qa/tasks.py
from celery import shared_task
import openai
import logging
from django.conf import settings
from .models import Question

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def generate_question_embedding(self, question_id):
    """
    Celery task to generate embedding for a question
    This runs asynchronously to avoid blocking the API response
    """
    try:
        question = Question.objects.get(id=question_id)

        # Skip if embedding already exists
        if question.embedding:
            logger.info(f"Question {question_id} already has embedding")
            return f"Question {question_id} already has embedding"

        # Create embedding text from title and body
        embedding_text = f"{question.title} {question.body}".strip()

        if not embedding_text:
            logger.error(f"No text to embed for question {question_id}")
            return f"No text to embed for question {question_id}"

        # Generate embedding using OpenAI
        client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
        embedding_model = getattr(settings, 'EMBEDDING_MODEL', 'text-embedding-ada-002')

        response = client.embeddings.create(
            input=embedding_text,
            model=embedding_model
        )

        embedding = response.data[0].embedding

        # Save embedding to database
        question.embedding = embedding
        question.save(update_fields=['embedding'])

        logger.info(f"Successfully generated embedding for question {question_id}")
        return f"Successfully generated embedding for question {question_id}"

    except Question.DoesNotExist:
        logger.error(f"Question {question_id} not found")
        raise Exception(f"Question {question_id} not found")

    except Exception as e:
        logger.error(f"Error generating embedding for question {question_id}: {e}")

        # Retry the task if we haven't exceeded max_retries
        try:
            raise self.retry(exc=e)
        except self.MaxRetriesExceededError:
            logger.error(f"Max retries exceeded for question {question_id}")
            raise Exception(f"Failed to generate embedding after {self.max_retries} retries: {str(e)}")