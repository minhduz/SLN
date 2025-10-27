import json
import random
import logging
from typing import Dict, List, Any
from django.conf import settings
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field

from qa.models import Subject
from ..models import Quiz, QuizQuestion, QuizAnswerOption
from accounts.models import User

logger = logging.getLogger(__name__)


class QuizQuestionSchema(BaseModel):
    """Schema for a single quiz question with options"""
    question: str = Field(description="The quiz question text")
    correct_answers: List[str] = Field(description="List of correct answer(s)")
    incorrect_answers: List[str] = Field(description="List of incorrect answer options")


class QuizSchema(BaseModel):
    """Schema for complete quiz"""
    title: str = Field(description="Quiz title based on subject")
    description: str = Field(description="Brief quiz description")
    questions: List[QuizQuestionSchema] = Field(
        description="List of quiz questions"
    )


class AIQuizGenerator:
    """Service to generate quizzes using OpenAI and LangChain"""

    def __init__(
            self,
            num_questions: int = 10,
            language: str = 'English',
            custom_description: str = None,
            options_per_question: int = 4,
            correct_answers_per_question: int = 1
    ):
        """
        Initialize the quiz generator

        Args:
            num_questions: Number of questions to generate (default: 10, max: 20)
            language: Language for the quiz (default: 'English')
            custom_description: Optional custom description for the quiz
            options_per_question: Number of answer options per question (default: 4, min: 2, max: 10)
            correct_answers_per_question: Number of correct answers per question (default: 1, min: 1)
        """
        if num_questions < 1 or num_questions > 20:
            raise ValueError("Number of questions must be between 1 and 20")

        if options_per_question < 2 or options_per_question > 10:
            raise ValueError("Options per question must be between 2 and 10")

        if correct_answers_per_question < 1 or correct_answers_per_question >= options_per_question:
            raise ValueError(f"Correct answers must be between 1 and {options_per_question - 1}")

        self.num_questions = num_questions
        self.language = language
        self.custom_description = custom_description
        self.options_per_question = options_per_question
        self.correct_answers_per_question = correct_answers_per_question

        self.llm = ChatOpenAI(
            model=settings.OPENAI_MODEL,
            temperature=0.7,
            max_tokens=4000,
            api_key=settings.OPENAI_API_KEY
        )
        # Create dynamic schema based on number of questions
        self.QuizSchema = self._create_quiz_schema(num_questions, options_per_question, correct_answers_per_question)
        self.parser = JsonOutputParser(pydantic_object=self.QuizSchema)

    def _create_quiz_schema(self, num_questions: int, options_per_question: int, correct_answers_per_question: int):
        """Dynamically create quiz schema based on number of questions and options"""

        incorrect_answers_count = options_per_question - correct_answers_per_question

        class DynamicQuizQuestionSchema(BaseModel):
            question: str = Field(description="The quiz question text")
            correct_answers: List[str] = Field(
                description=f"List of {correct_answers_per_question} correct answer(s)",
                min_length=correct_answers_per_question,
                max_length=correct_answers_per_question
            )
            incorrect_answers: List[str] = Field(
                description=f"List of {incorrect_answers_count} incorrect answer options",
                min_length=incorrect_answers_count,
                max_length=incorrect_answers_count
            )

        class DynamicQuizSchema(BaseModel):
            title: str = Field(description="Quiz title based on subject")
            description: str = Field(description="Brief quiz description")
            questions: List[DynamicQuizQuestionSchema] = Field(
                description=f"List of {num_questions} quiz questions",
                min_length=num_questions,
                max_length=num_questions
            )

        return DynamicQuizSchema

    def get_random_subject(self) -> Subject:
        """Fetch a random subject from database"""
        subjects = list(Subject.objects.all())
        if not subjects:
            raise ValueError("No subjects found in database")
        return random.choice(subjects)

    def generate_quiz(self, subject: Subject = None) -> Dict[str, Any]:
        """
        Generate a complete quiz with specified number of questions using AI

        ⚠️ THIS METHOD ONLY GENERATES - IT DOES NOT SAVE TO DATABASE

        Args:
            subject: Subject object. If None, picks a random subject

        Returns:
            Dictionary containing:
            {
                "subject": Subject object,
                "quiz_data": {
                    "title": str,
                    "description": str,
                    "questions": [...]
                }
            }
        """
        if subject is None:
            subject = self.get_random_subject()

        logger.info(
            f"Generating quiz for subject: {subject.name} in {self.language} "
            f"with {self.options_per_question} options and {self.correct_answers_per_question} correct answer(s) per question"
        )

        # Build custom description context for the AI
        description_context = ""
        if self.custom_description:
            description_context = f"\nCustom Quiz Description/Focus: {self.custom_description}\nPlease generate questions that align with this description and focus area."

        # Calculate incorrect answers count
        incorrect_answers_count = self.options_per_question - self.correct_answers_per_question

        # Build question format description
        if self.correct_answers_per_question == 1:
            question_format = f"- Provide {self.correct_answers_per_question} correct answer\n- Provide {incorrect_answers_count} plausible incorrect answers (distractors)"
        else:
            question_format = f"- Provide {self.correct_answers_per_question} correct answers (multiple correct answers)\n- Provide {incorrect_answers_count} plausible incorrect answers (distractors)"

        prompt = PromptTemplate(
            template="""You are an expert quiz generator. Create a comprehensive quiz based on the following subject.

Subject: {subject_name}
Subject Description: {subject_description}
Language: {language}{description_context}

Generate a quiz with exactly {num_questions} questions in {language}. For each question:
- Create a clear, unambiguous question
{question_format}

The question should have exactly {options_per_question} total options ({correct_answers_per_question} correct + {incorrect_answers_count} incorrect).

Ensure the questions are:
- Varied in difficulty (mix easy, medium, hard)
- Clear and educational
- Focused on key concepts of the subject
- Written in {language}{description_alignment}

Return the response in the following JSON format:
{format_instructions}

Remember:
- Each question must have exactly {options_per_question} options ({correct_answers_per_question} correct + {incorrect_answers_count} incorrect)
- Make incorrect answers plausible but clearly wrong
- All text must be in {language}
- Return valid JSON only, no markdown or extra text
- The "correct_answers" field must contain exactly {correct_answers_per_question} answer(s)
- The "incorrect_answers" field must contain exactly {incorrect_answers_count} answer(s)""",
            input_variables=[
                "subject_name", "subject_description", "language", "num_questions",
                "description_context", "description_alignment", "question_format",
                "options_per_question", "correct_answers_per_question", "incorrect_answers_count"
            ],
            partial_variables={"format_instructions": self.parser.get_format_instructions()}
        )

        chain = prompt | self.llm | self.parser

        # Add alignment instruction if custom description exists
        description_alignment = "\n- Aligned with the custom description provided above" if self.custom_description else ""

        try:
            quiz_data = chain.invoke({
                "subject_name": subject.name,
                "subject_description": subject.description or "No description available",
                "language": self.language,
                "num_questions": self.num_questions,
                "description_context": description_context,
                "description_alignment": description_alignment,
                "question_format": question_format,
                "options_per_question": self.options_per_question,
                "correct_answers_per_question": self.correct_answers_per_question,
                "incorrect_answers_count": incorrect_answers_count
            })

            # If custom description provided, use it instead of AI-generated one
            if self.custom_description:
                quiz_data["description"] = self.custom_description

            logger.info(f"Successfully generated quiz data for {subject.name} in {self.language}")

            # Return the full data structure
            return {
                "subject": subject,
                "quiz_data": quiz_data,
                "metadata": {
                    "num_questions": self.num_questions,
                    "language": self.language,
                    "options_per_question": self.options_per_question,
                    "correct_answers_per_question": self.correct_answers_per_question
                }
            }

        except Exception as e:
            logger.error(f"Error generating quiz: {str(e)}")
            raise

    def save_quiz_to_database(
            self,
            subject: Subject,
            quiz_data: Dict,
            created_by: User,
            num_questions: int = None,
            language: str = None,
            options_per_question: int = None,
            correct_answers_per_question: int = None
    ) -> Quiz:
        """
        Save generated quiz data to database

        ⚠️ THIS METHOD ONLY SAVES - IT DOES NOT GENERATE

        Args:
            subject: Subject object
            quiz_data: Quiz data from AI generation (dict with title, description, questions)
            created_by: User who created the quiz
            num_questions: Number of questions (for logging)
            language: Language (for logging)
            options_per_question: Options per question (for logging)
            correct_answers_per_question: Correct answers per question (for logging)

        Returns:
            Created Quiz object with all questions and options
        """
        from django.db import transaction

        # Use instance values if not provided
        num_questions = num_questions or self.num_questions
        language = language or self.language
        options_per_question = options_per_question or self.options_per_question
        correct_answers_per_question = correct_answers_per_question or self.correct_answers_per_question

        try:
            with transaction.atomic():
                # Create Quiz with language
                quiz = Quiz.objects.create(
                    title=quiz_data.get("title", f"{subject.name} Quiz"),
                    description=quiz_data.get("description", ""),
                    subject=subject,
                    quiz_type="ai",
                    language=language,
                    created_by=created_by
                )

                # Create Questions and Answer Options
                for q_data in quiz_data.get("questions", []):
                    question = QuizQuestion.objects.create(
                        quiz=quiz,
                        question_text=q_data.get("question")
                    )

                    # Create correct answer option(s) - supports multiple
                    correct_answers = q_data.get("correct_answers", [])
                    if isinstance(correct_answers, str):  # Handle single string
                        correct_answers = [correct_answers]

                    for correct_answer in correct_answers:
                        QuizAnswerOption.objects.create(
                            question=question,
                            option_text=correct_answer,
                            is_correct=True
                        )

                    # Create incorrect answer options
                    for incorrect_answer in q_data.get("incorrect_answers", []):
                        QuizAnswerOption.objects.create(
                            question=question,
                            option_text=incorrect_answer,
                            is_correct=False
                        )

                logger.info(
                    f"Quiz saved to database with ID: {quiz.id} in {language} "
                    f"with {options_per_question} options and {correct_answers_per_question} correct answer(s) per question"
                )
                return quiz

        except Exception as e:
            logger.error(f"Error saving quiz to database: {str(e)}")
            raise

    def generate_and_save_quiz(self, subject: Subject = None, created_by: User = None) -> Quiz:
        """
        Complete workflow: Generate quiz with AI and save to database

        ⚠️ DEPRECATED: Use generate_quiz() then save_quiz_to_database() separately for better control

        Args:
            subject: Subject object. If None, picks a random subject
            created_by: User who created the quiz

        Returns:
            Created Quiz object
        """
        # Generate quiz (custom_description already stored in __init__)
        result = self.generate_quiz(subject)

        # Save to database
        quiz = self.save_quiz_to_database(
            result["subject"],
            result["quiz_data"],
            created_by=created_by
        )

        return quiz