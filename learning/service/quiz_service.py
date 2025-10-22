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
    correct_answer: str = Field(description="The correct answer text")
    incorrect_answers: List[str] = Field(
        description="List of 3 incorrect answer options",
        min_length=3,
        max_length=3
    )


class QuizSchema(BaseModel):
    """Schema for complete quiz"""
    title: str = Field(description="Quiz title based on subject")
    description: str = Field(description="Brief quiz description")
    questions: List[QuizQuestionSchema] = Field(
        description="List of 10 quiz questions",
        min_length=10,
        max_length=10
    )


class AIQuizGenerator:
    """Service to generate quizzes using OpenAI and LangChain"""

    def __init__(self, num_questions: int = 10, language: str = 'English',):
        """
        Initialize the quiz generator

        Args:
            num_questions: Number of questions to generate (default: 10, max: 20)
            language: Language for the quiz (default: 'English')
        """
        if num_questions < 1 or num_questions > 20:
            raise ValueError("Number of questions must be between 1 and 20")
        self.num_questions = num_questions
        self.language = language
        self.llm = ChatOpenAI(
            model=settings.OPENAI_MODEL,
            temperature=0.7,
            max_tokens=4000,
            api_key=settings.OPENAI_API_KEY
        )
        # Create dynamic schema based on number of questions
        self.QuizSchema = self._create_quiz_schema(num_questions)
        self.parser = JsonOutputParser(pydantic_object=self.QuizSchema)

    def _create_quiz_schema(self, num_questions: int):
        """Dynamically create quiz schema based on number of questions"""

        class DynamicQuizSchema(BaseModel):
            title: str = Field(description="Quiz title based on subject")
            description: str = Field(description="Brief quiz description")
            questions: List[QuizQuestionSchema] = Field(
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

        Args:
            subject: Subject object. If None, picks a random subject

        Returns:
            Dictionary containing quiz data ready to be saved
        """
        if subject is None:
            subject = self.get_random_subject()

        logger.info(f"Generating quiz for subject: {subject.name} in {self.language}")

        prompt = PromptTemplate(
            template="""You are an expert quiz generator. Create a comprehensive quiz based on the following subject.

Subject: {subject_name}
Subject Description: {subject_description}
Language: {language}

Generate a quiz with exactly {num_questions} questions in {language}. For each question:
- Create a clear, unambiguous question
- Provide 1 correct answer
- Provide 3 plausible incorrect answers (distractors)

Ensure the questions are:
- Varied in difficulty (mix easy, medium, hard)
- Clear and educational
- Focused on key concepts of the subject
- Written in {language}

Return the response in the following JSON format:
{format_instructions}

Remember:
- Each question must have exactly 4 options (1 correct + 3 incorrect)
- Make incorrect answers plausible but clearly wrong
- All text must be in {language}
- Return valid JSON only, no markdown or extra text""",
            input_variables=["subject_name", "subject_description", "language", "num_questions"],
            partial_variables={"format_instructions": self.parser.get_format_instructions()}
        )

        chain = prompt | self.llm | self.parser

        try:
            quiz_data = chain.invoke({
                "subject_name": subject.name,
                "subject_description": subject.description or "No description available",
                "language": self.language,
                "num_questions": self.num_questions
            })

            logger.info(f"Successfully generated quiz data for {subject.name} in {self.language}")
            return {
                "subject": subject,
                "quiz_data": quiz_data
            }

        except Exception as e:
            logger.error(f"Error generating quiz: {str(e)}")
            raise

    def save_quiz_to_database(self, subject: Subject, quiz_data: Dict, created_by:User) -> Quiz:
        """
        Save generated quiz data to database

        Args:
            subject: Subject object
            quiz_data: Quiz data from AI generation

        Returns:
            Created Quiz object with all questions and options
        """
        from django.db import transaction

        try:
            with transaction.atomic():
                # Create Quiz with language
                quiz = Quiz.objects.create(
                    title=quiz_data.get("title", f"{subject.name} Quiz"),
                    description=quiz_data.get("description", ""),
                    subject=subject,
                    quiz_type="ai",
                    language=self.language,
                    created_by=created_by  # ✅ Set the creator
                )

                # Create Questions and Answer Options
                for q_data in quiz_data.get("questions", []):
                    question = QuizQuestion.objects.create(
                        quiz=quiz,
                        question_text=q_data.get("question")
                    )

                    # Create correct answer option
                    QuizAnswerOption.objects.create(
                        question=question,
                        option_text=q_data.get("correct_answer"),
                        is_correct=True
                    )

                    # Create incorrect answer options
                    for incorrect_answer in q_data.get("incorrect_answers", []):
                        QuizAnswerOption.objects.create(
                            question=question,
                            option_text=incorrect_answer,
                            is_correct=False
                        )

                logger.info(f"Quiz saved to database with ID: {quiz.id} in {self.language}")
                return quiz

        except Exception as e:
            logger.error(f"Error saving quiz to database: {str(e)}")
            raise

    def generate_and_save_quiz(self, subject: Subject = None, created_by: User = None) -> Quiz:
        """
        Complete workflow: Generate quiz with AI and save to database

        Args:
            subject: Subject object. If None, picks a random subject

        Returns:
            Created Quiz object
        """
        # Generate quiz
        result = self.generate_quiz(subject)

        # Save to database
        quiz = self.save_quiz_to_database(
            result["subject"],
            result["quiz_data"],
            created_by=created_by
        )

        return quiz