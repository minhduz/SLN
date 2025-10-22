import random
from django.core.cache import cache
from ..models import Question


def get_random_questions_for_user(user_id, limit=10):
    """
    Return random public questions without duplicates.
    Maintains a deck and tracks shown questions across multiple calls (pagination).
    """
    deck_key = f"user:{user_id}:question_deck"
    shown_key = f"user:{user_id}:shown_questions"

    # Get current state
    question_ids = cache.get(deck_key)
    shown_ids = cache.get(shown_key, set())

    # If deck is empty, rebuild it
    if not question_ids:
        all_ids = list(
            Question.objects.filter(is_public=True)
            .exclude(user_id=user_id)
            .values_list("id", flat=True)
        )

        # CRITICAL: Exclude already shown questions when rebuilding deck
        available_ids = [qid for qid in all_ids if qid not in shown_ids]

        # If all questions shown, reset the cycle
        if not available_ids or len(available_ids) < limit:
            available_ids = all_ids
            shown_ids = set()  # Fresh start

        random.shuffle(available_ids)
        question_ids = available_ids

    # Serve next batch
    selected_ids = question_ids[:limit]
    remaining_ids = question_ids[limit:]

    # Track what we just served
    shown_ids.update(selected_ids)

    # Update cache
    if remaining_ids:
        cache.set(deck_key, remaining_ids, timeout=3600)
    else:
        # Deck exhausted - delete so it rebuilds on next call
        cache.delete(deck_key)

    cache.set(shown_key, shown_ids, timeout=3600)

    # Return questions in selected order
    questions = Question.objects.filter(id__in=selected_ids)
    questions_dict = {q.id: q for q in questions}
    return [questions_dict[qid] for qid in selected_ids if qid in questions_dict]


def get_random_questions_by_subject(subject_id, user_id, limit=10):
    """
    Return random questions by subject without duplicates.
    """
    deck_key = f"user:{user_id}:subject:{subject_id}:question_deck"
    shown_key = f"user:{user_id}:subject:{subject_id}:shown_questions"

    question_ids = cache.get(deck_key)
    shown_ids = cache.get(shown_key, set())

    if not question_ids:
        all_ids = list(
            Question.objects.filter(subject_id=subject_id, is_public=True)
            .exclude(user_id=user_id)
            .values_list("id", flat=True)
        )

        available_ids = [qid for qid in all_ids if qid not in shown_ids]

        if not available_ids or len(available_ids) < limit:
            available_ids = all_ids
            shown_ids = set()

        random.shuffle(available_ids)
        question_ids = available_ids

    selected_ids = question_ids[:limit]
    remaining_ids = question_ids[limit:]

    shown_ids.update(selected_ids)

    if remaining_ids:
        cache.set(deck_key, remaining_ids, timeout=3600)
    else:
        cache.delete(deck_key)

    cache.set(shown_key, shown_ids, timeout=3600)

    questions = Question.objects.filter(id__in=selected_ids)
    questions_dict = {q.id: q for q in questions}
    return [questions_dict[qid] for qid in selected_ids if qid in questions_dict]