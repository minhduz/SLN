import numpy as np
from typing import List, Dict, Any, Optional
from django.db.models import Q
from django.conf import settings
import openai
import logging

from ..models import Question

logger = logging.getLogger(__name__)


class VectorSearchService:
    """
    Service for handling vector similarity search for questions
    Implements Phase 1: Steps 0.1-0.3 from the flow diagram
    """

    def __init__(self):
        self.client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
        self.embedding_model = getattr(settings, 'EMBEDDING_MODEL', 'text-embedding-ada-002')

    def generate_query_embedding(self, query_text: str) -> List[float]:
        """
        Generate embedding vector for the user's query
        Step 0.1: Process user question for vector search
        """
        if not query_text or not query_text.strip():
            raise ValueError("Query text cannot be empty")

        try:
            response = self.client.embeddings.create(
                input=query_text.strip(),
                model=self.embedding_model
            )

            embedding = response.data[0].embedding
            logger.info(f"Generated embedding for query: '{query_text[:50]}...'")
            return embedding

        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            raise Exception(f"Failed to generate embedding: {str(e)}")

    def calculate_cosine_similarity(self, vector1: List[float], vector2: List[float]) -> float:
        """Calculate cosine similarity between two vectors"""
        if not vector1 or not vector2:
            return 0.0

        try:
            vec1 = np.array(vector1, dtype=np.float32)
            vec2 = np.array(vector2, dtype=np.float32)

            dot_product = np.dot(vec1, vec2)
            norm1 = np.linalg.norm(vec1)
            norm2 = np.linalg.norm(vec2)

            if norm1 == 0 or norm2 == 0:
                return 0.0

            similarity = dot_product / (norm1 * norm2)
            return float(similarity)

        except Exception as e:
            logger.error(f"Error calculating similarity: {e}")
            return 0.0

    def search_similar_questions(
            self,
            query_text: str,
            limit: int = 10,
            min_similarity: float = 0.7,
            include_private: bool = False,
            user_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Main method for searching similar questions (basic cosine similarity only).
        Step 0.2 + 0.3: Return list of most relevant questions
        """
        if not query_text or not query_text.strip():
            return {
                'success': False,
                'error': 'Query text is required',
                'results': [],
                'count': 0,
                'query': '',
                'search_params': {}
            }

        # Validate and sanitize parameters
        limit = max(1, min(limit, 50))  # Between 1 and 50
        min_similarity = max(0.0, min(min_similarity, 1.0))  # Between 0 and 1

        search_params = {
            'limit': limit,
            'min_similarity': min_similarity,
            'include_private': include_private,
            'user_id': user_id,
        }

        try:
            # Generate query embedding
            query_embedding = self.generate_query_embedding(query_text)

            # Build base queryset
            queryset = Question.objects.filter(
                embedding__isnull=False
            ).select_related('subject', 'user').prefetch_related('answers')

            # Apply privacy filters
            if not include_private:
                if user_id:
                    queryset = queryset.filter(
                        Q(is_public=True) | Q(user_id=user_id)
                    )
                else:
                    queryset = queryset.filter(is_public=True)

            # Process questions and calculate similarity
            similar_questions = []
            for question in queryset.iterator(chunk_size=100):
                if not question.embedding:
                    continue

                similarity = self.calculate_cosine_similarity(
                    query_embedding,
                    question.embedding
                )

                if similarity >= min_similarity:
                    similar_questions.append({
                        'question': question,
                        'similarity': similarity,
                        'question_data': {
                            'id': str(question.id),
                            'title': question.title,
                            'body': question.body,
                            'subject_name': question.subject.name if question.subject else None,
                            'subject_id': str(question.subject.id) if question.subject else None,
                            'user_name': question.user.username if question.user else 'Anonymous',
                            'created_at': question.created_at,
                            'answer_count': question.answers.count(),
                            'is_public': question.is_public
                        }
                    })

            # Sort by similarity score (descending) and limit results
            similar_questions.sort(key=lambda x: x['similarity'], reverse=True)
            results = similar_questions[:limit]

            logger.info(f"Search completed: {len(results)} results for query: '{query_text[:50]}...'")

            return {
                'success': True,
                'results': results,
                'count': len(results),
                'query': query_text,
                'search_params': search_params
            }

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'results': [],
                'count': 0,
                'query': query_text,
                'search_params': search_params
            }
