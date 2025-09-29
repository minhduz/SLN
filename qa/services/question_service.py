import random
from django.core.cache import cache
from ..models import Question

def get_random_questions_for_user(user_id, limit=10):
    """
    Return a list of random public questions for a specific user.
    Uses Redis/Django cache to maintain a 'deck' that prevents repeats
    until all questions are shown.
    """
    cache_key = f"user:{user_id}:random_questions"

    # Get deck from cache
    question_ids = cache.get(cache_key)

    if not question_ids:
        # Fetch all public question IDs
        all_ids = list(
            Question.objects.filter(is_public=True).values_list("id", flat=True)
        )
        random.shuffle(all_ids)  # shuffle deck
        question_ids = all_ids

    # Take up to `limit`
    selected_ids = question_ids[:limit]
    remaining_ids = question_ids[limit:]

    # Update cache (only if there are leftovers)
    if remaining_ids:
        cache.set(cache_key, remaining_ids, timeout=3600)  # 1 hour TTL
    else:
        cache.delete(cache_key)

    # Fetch actual questions
    return Question.objects.filter(id__in=selected_ids)

def get_random_questions_by_subject(subject_id, limit=10):
    """
    Return a list of random public questions for a specific subject.
    Works like the user-specific version: shuffled deck until exhausted.
    """
    cache_key = f"subject:{subject_id}:random_questions"

    question_ids = cache.get(cache_key)

    if not question_ids:
        all_ids = list(
            Question.objects.filter(subject_id=subject_id, is_public=True)
            .values_list("id", flat=True)
        )
        random.shuffle(all_ids)
        question_ids = all_ids

    selected_ids = question_ids[:limit]
    remaining_ids = question_ids[limit:]

    if remaining_ids:
        cache.set(cache_key, remaining_ids, timeout=3600)
    else:
        cache.delete(cache_key)

    return Question.objects.filter(id__in=selected_ids)
