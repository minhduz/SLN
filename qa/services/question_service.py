import random
from django.core.cache import cache
from ..models import Question

import logging

logger = logging.getLogger(__name__)


def get_random_questions_for_user(user_id, page=1, page_size=10):
    deck_key = f"user:{user_id}:question_deck"
    shown_key = f"user:{user_id}:shown_questions"

    # Get current state from cache
    question_ids = cache.get(deck_key)
    shown_ids = cache.get(shown_key, set())

    # If deck is empty, rebuild it
    if not question_ids:
        logger.info(f"Rebuilding question deck for user {user_id}")

        # Get all available questions (exclude user's own questions)
        all_question_ids = list(
            Question.objects.filter(is_public=True)
            .exclude(user_id=user_id)
            .values_list("id", flat=True)
        )

        # Exclude already shown questions
        available_ids = [qid for qid in all_question_ids if qid not in shown_ids]

        # If all questions shown or not enough questions, reset the cycle
        if not available_ids or len(available_ids) < page_size:
            logger.info(f"Resetting shown questions for user {user_id}")
            available_ids = all_question_ids
            shown_ids = set()  # Fresh start

        if not available_ids:
            logger.warning(f"No public questions available for user {user_id}")
            return []

        # Build a deck for multiple pages (~10 pages worth)
        deck_size = min(len(available_ids), page_size * 10)

        # Randomly sample from available questions
        if len(available_ids) >= deck_size:
            question_ids = random.sample(available_ids, deck_size)
        else:
            question_ids = available_ids.copy()
            random.shuffle(question_ids)

        logger.info(f"Built deck of {len(question_ids)} questions for user {user_id}")

    # Calculate offset for pagination
    offset = (page - 1) * page_size

    # Check if we have enough questions in deck
    if offset >= len(question_ids):
        logger.warning(
            f"Page {page} exceeds available questions. "
            f"Offset: {offset}, Deck size: {len(question_ids)}"
        )
        # Return empty list if page exceeds available questions
        return []

    # Serve current page
    selected_ids = question_ids[offset:offset + page_size]
    remaining_ids = question_ids[offset + page_size:]

    # Track what we just served
    shown_ids.update(selected_ids)

    # Update cache
    if remaining_ids:
        cache.set(deck_key, question_ids, timeout=3600)  # Keep full deck
    else:
        # Deck exhausted - delete so it rebuilds on next call
        cache.delete(deck_key)
        logger.info(f"Deck exhausted for user {user_id}, will rebuild on next request")

    cache.set(shown_key, shown_ids, timeout=3600)

    logger.info(
        f"Served page {page} for user {user_id}: "
        f"{len(selected_ids)} questions (offset: {offset})"
    )

    # Fetch and return questions in selected order
    questions = Question.objects.filter(id__in=selected_ids)
    questions_dict = {q.id: q for q in questions}

    # Maintain the randomized order
    return [questions_dict[qid] for qid in selected_ids if qid in questions_dict]


def get_random_questions_by_subject(subject_id, user_id, page=1, page_size=10):
    deck_key = f"user:{user_id}:subject:{subject_id}:question_deck"
    shown_key = f"user:{user_id}:subject:{subject_id}:shown_questions"

    # Get current state from cache
    question_ids = cache.get(deck_key)
    shown_ids = cache.get(shown_key, set())

    # If deck is empty, rebuild it
    if not question_ids:
        logger.info(f"Rebuilding question deck for user {user_id}, subject {subject_id}")

        # Get all available questions for this subject
        all_question_ids = list(
            Question.objects.filter(subject_id=subject_id, is_public=True)
            .exclude(user_id=user_id)
            .values_list("id", flat=True)
        )

        # Exclude already shown questions
        available_ids = [qid for qid in all_question_ids if qid not in shown_ids]

        # If all questions shown or not enough questions, reset the cycle
        if not available_ids or len(available_ids) < page_size:
            logger.info(f"Resetting shown questions for user {user_id}, subject {subject_id}")
            available_ids = all_question_ids
            shown_ids = set()  # Fresh start

        if not available_ids:
            logger.warning(f"No public questions available for user {user_id} in subject {subject_id}")
            return []

        # Build a deck for multiple pages (~10 pages worth)
        deck_size = min(len(available_ids), page_size * 10)

        # Randomly sample from available questions
        if len(available_ids) >= deck_size:
            question_ids = random.sample(available_ids, deck_size)
        else:
            question_ids = available_ids.copy()
            random.shuffle(question_ids)

        logger.info(f"Built deck of {len(question_ids)} questions for user {user_id}, subject {subject_id}")

    # Calculate offset for pagination
    offset = (page - 1) * page_size

    # Check if we have enough questions in deck
    if offset >= len(question_ids):
        logger.warning(
            f"Page {page} exceeds available questions for subject {subject_id}. "
            f"Offset: {offset}, Deck size: {len(question_ids)}"
        )
        # Return empty list if page exceeds available questions
        return []

    # Serve current page
    selected_ids = question_ids[offset:offset + page_size]
    remaining_ids = question_ids[offset + page_size:]

    # Track what we just served
    shown_ids.update(selected_ids)

    # Update cache
    if remaining_ids:
        cache.set(deck_key, question_ids, timeout=3600)  # Keep full deck
    else:
        # Deck exhausted - delete so it rebuilds on next call
        cache.delete(deck_key)
        logger.info(f"Deck exhausted for user {user_id}, subject {subject_id}, will rebuild on next request")

    cache.set(shown_key, shown_ids, timeout=3600)

    logger.info(
        f"Served page {page} for user {user_id}, subject {subject_id}: "
        f"{len(selected_ids)} questions (offset: {offset})"
    )

    # Fetch and return questions in selected order
    questions = Question.objects.filter(id__in=selected_ids)
    questions_dict = {q.id: q for q in questions}

    # Maintain the randomized order
    return [questions_dict[qid] for qid in selected_ids if qid in questions_dict]