import logging
from typing import Dict, List, Any, Optional
from django.db import transaction
from django.utils import timezone

from ..models import Quiz, QuizQuestion, QuizAnswerOption, QuizAttempt, QuizAttemptAnswer

logger = logging.getLogger(__name__)


class QuizSubmitService:
    """Service to handle quiz submission and scoring"""

    def submit_quiz(self, quiz: Quiz, user, answers_data: List[Dict[str, str]],
                   duration_seconds: Optional[int] = None) -> QuizAttempt:
        """
        Submit quiz answers and calculate score

        Args:
            quiz: Quiz object
            user: User object submitting the quiz
            answers_data: List of answer dicts with question_id and selected_option_id
            duration_seconds: Duration in seconds (from frontend). If not provided, defaults to 0

        Returns:
            QuizAttempt object with calculated score and duration
        """
        # Get all questions in the quiz
        all_questions = QuizQuestion.objects.filter(quiz=quiz)
        total_questions = all_questions.count()

        if total_questions == 0:
            raise ValueError("Quiz has no questions")

        # Create a dict of submitted answers for quick lookup
        submitted_answers = {}
        for answer_data in answers_data:
            question_id = answer_data.get('question_id')
            submitted_answers[str(question_id)] = answer_data

        with transaction.atomic():
            # Create quiz attempt
            now = timezone.now()
            attempt = QuizAttempt.objects.create(
                quiz=quiz,
                user=user,
                score=0,
                duration_seconds=duration_seconds or 0
            )

            correct_count = 0

            # Process ALL questions in the quiz
            for question in all_questions:
                question_id = str(question.id)

                # Check if this question was answered
                if question_id in submitted_answers:
                    answer_data = submitted_answers[question_id]
                    selected_option_id = answer_data.get('selected_option_id')

                    try:
                        selected_option = QuizAnswerOption.objects.get(
                            id=selected_option_id,
                            question=question
                        )

                        is_correct = selected_option.is_correct

                        # Create attempt answer record
                        QuizAttemptAnswer.objects.create(
                            attempt=attempt,
                            question=question,
                            selected_option=selected_option,
                            is_correct=is_correct
                        )

                        if is_correct:
                            correct_count += 1

                        logger.info(
                            f"Answer recorded for question {question_id}: {'correct' if is_correct else 'incorrect'}")

                    except QuizAnswerOption.DoesNotExist:
                        logger.warning(f"Invalid option {selected_option_id} for question {question_id}")
                        # Record as incorrect if option doesn't exist
                        QuizAttemptAnswer.objects.create(
                            attempt=attempt,
                            question=question,
                            selected_option=None,
                            is_correct=False
                        )

                else:
                    # Question was NOT answered - treat as incorrect
                    logger.info(f"Question {question_id} was not answered - marking as incorrect")
                    QuizAttemptAnswer.objects.create(
                        attempt=attempt,
                        question=question,
                        selected_option=None,
                        is_correct=False
                    )

            # Calculate score based on ALL questions, not just submitted ones
            score = int((correct_count / total_questions) * 100) if total_questions > 0 else 0
            attempt.score = score
            attempt.save()

            logger.info(
                f"Quiz attempt {attempt.id} scored: {correct_count}/{total_questions} ({score}%) "
                f"in {attempt.duration_seconds} seconds"
            )

            return attempt

    def get_attempt_summary(self, attempt: QuizAttempt) -> Dict[str, Any]:
        """
        Get summary of quiz attempt

        Args:
            attempt: QuizAttempt object

        Returns:
            Dictionary with attempt summary including duration
        """
        answers = attempt.answers.all()
        correct_answers = answers.filter(is_correct=True).count()
        total_questions = attempt.quiz.questions.count()

        return {
            "attempt_id": str(attempt.id),
            "quiz_id": str(attempt.quiz.id),
            "quiz_title": attempt.quiz.title,
            "score": attempt.score,
            "correct_answers": correct_answers,
            "total_questions": total_questions,
            "duration_seconds": attempt.duration_seconds,
            "created_at": attempt.created_at
        }