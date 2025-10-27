import random
from django.core.cache import cache
from ..models import Quiz


def get_random_quizzes_for_user(user_id, limit=10):
    """
    Return random quizzes without duplicates.
    Maintains a deck and tracks shown quizzes across multiple calls (pagination).
    """
    deck_key = f"user:{user_id}:quiz_deck"
    shown_key = f"user:{user_id}:shown_quizzes"

    # Get current state
    quiz_ids = cache.get(deck_key)
    shown_ids = cache.get(shown_key, set())

    # If deck is empty, rebuild it
    if not quiz_ids:
        all_ids = list(
            Quiz.objects.exclude(created_by_id=user_id)  # ✅ REMOVED is_public filter
            .values_list("id", flat=True)
        )

        # CRITICAL: Exclude already shown quizzes when rebuilding deck
        available_ids = [qid for qid in all_ids if qid not in shown_ids]

        # If all quizzes shown, reset the cycle
        if not available_ids or len(available_ids) < limit:
            available_ids = all_ids
            shown_ids = set()  # Fresh start

        random.shuffle(available_ids)
        quiz_ids = available_ids

    # Serve next batch
    selected_ids = quiz_ids[:limit]
    remaining_ids = quiz_ids[limit:]

    # Track what we just served
    shown_ids.update(selected_ids)

    # Update cache
    if remaining_ids:
        cache.set(deck_key, remaining_ids, timeout=3600)
    else:
        # Deck exhausted - delete so it rebuilds on next call
        cache.delete(deck_key)

    cache.set(shown_key, shown_ids, timeout=3600)

    # Return quizzes in selected order
    quizzes = Quiz.objects.filter(id__in=selected_ids).prefetch_related('questions__answer_options')
    quizzes_dict = {q.id: q for q in quizzes}
    return [quizzes_dict[qid] for qid in selected_ids if qid in quizzes_dict]


def get_random_quizzes_by_subject(subject_id, user_id, limit=10):
    """
    Return random quizzes by subject without duplicates.
    """
    deck_key = f"user:{user_id}:subject:{subject_id}:quiz_deck"
    shown_key = f"user:{user_id}:subject:{subject_id}:shown_quizzes"

    quiz_ids = cache.get(deck_key)
    shown_ids = cache.get(shown_key, set())

    if not quiz_ids:
        all_ids = list(
            Quiz.objects.filter(subject_id=subject_id)
            .exclude(created_by_id=user_id)  # ✅ REMOVED is_public filter
            .values_list("id", flat=True)
        )

        available_ids = [qid for qid in all_ids if qid not in shown_ids]

        if not available_ids or len(available_ids) < limit:
            available_ids = all_ids
            shown_ids = set()

        random.shuffle(available_ids)
        quiz_ids = available_ids

    selected_ids = quiz_ids[:limit]
    remaining_ids = quiz_ids[limit:]

    shown_ids.update(selected_ids)

    if remaining_ids:
        cache.set(deck_key, remaining_ids, timeout=3600)
    else:
        cache.delete(deck_key)

    cache.set(shown_key, shown_ids, timeout=3600)

    quizzes = Quiz.objects.filter(id__in=selected_ids).prefetch_related('questions__answer_options')
    quizzes_dict = {q.id: q for q in quizzes}
    return [quizzes_dict[qid] for qid in selected_ids if qid in quizzes_dict]