from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import MessagesState, StateGraph, START, END
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import SystemMessage, HumanMessage, RemoveMessage
from typing_extensions import Literal
from typing import Dict, Any, List, Optional
import json
import logging
from django.apps import apps
from ..tasks import generate_question_embedding

from .token_management import TOKEN_LIMITS, TokenCounter
from .file_service import FileAttachment, FileProcessor

# Configure logging
logger = logging.getLogger(__name__)


class ChatbotState(MessagesState):
    """Extended state for the chatbot with conversation summary and token tracking"""
    summary: str
    user_id: str
    thread_id: str
    total_tokens: int
    conversation_tokens: int
    current_subject: str  # Track current conversation subject
    subject_change_detected: bool  # Flag for subject change
    suggested_new_subject: str  # New subject suggestion
    file_attachments: List[Dict[str, Any]]  # File attachments for this conversation
    temp_attachment_ids: List[str]  # Temporary attachment IDs for cleanup


class SmartLearningChatbot:
    """Smart Learning System Chatbot with memory management, token tracking, and database integration"""

    def __init__(self):
        # Get model configuration from Django settings
        model_config = self._get_model_config()
        self.model = ChatOpenAI(**model_config)
        self.memory = MemorySaver()
        self.token_counter = TokenCounter(model_config.get('model', 'gpt-4o'))
        self.file_processor = FileProcessor()
        self.graph = None
        self._build_graph()

    def _get_model_config(self):
        """Get model configuration from Django settings"""
        default_config = {
            'model': 'gpt-4o',
            'temperature': 0,
            'max_tokens': 1000
        }

        try:
            from django.conf import settings
            if hasattr(settings, 'CHATBOT_CONFIG') and 'MODEL_CONFIG' in settings.CHATBOT_CONFIG:
                return {**default_config, **settings.CHATBOT_CONFIG['MODEL_CONFIG']}
        except:
            pass

        return default_config

    def _build_graph(self):
        """Build the LangGraph workflow"""
        workflow = StateGraph(ChatbotState)

        # Add nodes
        workflow.add_node("conversation", self._call_model)
        workflow.add_node("detect_subject", self._detect_subject_node)
        workflow.add_node("summarize_conversation", self._summarize_conversation)

        # Set entry point
        workflow.add_edge(START, "conversation")

        # Add conditional edges
        workflow.add_conditional_edges("conversation", self._should_continue_after_conversation)
        workflow.add_edge("detect_subject", "summarize_conversation")
        workflow.add_edge("summarize_conversation", END)

        # Compile the graph
        self.graph = workflow.compile(checkpointer=self.memory)

    def _get_system_message(self) -> str:
        """Get the system message for the Smart Learning System"""
        return """You are an AI assistant for a Smart Learning System designed to help students with educational questions and learning.

Your role is to:
- Provide clear, accurate, and helpful answers to educational questions across various subjects
- Explain complex concepts in an understandable way
- Encourage learning and critical thinking
- Adapt your explanations to the student's level of understanding
- Ask clarifying questions when needed to provide better assistance
- Be patient, supportive, and encouraging
- Help students learn rather than just giving direct answers when appropriate

When files are attached to messages:
- Analyze images to understand visual content and provide relevant educational insights
- Review documents to understand context and provide comprehensive assistance
- Reference file content in your responses when relevant

Always maintain a helpful, educational tone and focus on facilitating learning and understanding."""

    def _process_attachments(self, attachments: List[dict]) -> str:
        """Process file attachments and return context for the AI model"""
        if not attachments:
            return ""

        context_parts = ["\n\nAttached files analysis:"]

        for att_data in attachments:
            try:
                attachment = FileAttachment.from_dict(att_data)

                if attachment.is_image():
                    description = self.file_processor.process_image(attachment)
                elif attachment.is_document() or attachment.is_pdf():
                    description = self.file_processor.process_document(attachment)
                else:
                    description = (
                        f"File '{attachment.filename}' "
                        f"({attachment.content_type}, {attachment.size} bytes) - type not fully supported"
                    )

                att_data["description"] = description
                context_parts.append(f"- {description}")

            except Exception as e:
                logger.error(f"Error processing attachment {att_data.get('filename')}: {str(e)}")
                context_parts.append(
                    f"- File '{att_data.get('filename')}' (processing error: {str(e)})"
                )

        return "\n".join(context_parts)

    def _call_model(self, state: ChatbotState) -> Dict[str, Any]:
        """Call the model with conversation context and token tracking, including file analysis"""
        try:
            # Check last user message
            current_message = state["messages"][-1] if state["messages"] else None
            if current_message and hasattr(current_message, 'content'):
                message_tokens = self.token_counter.count_tokens(str(current_message.content))
                if message_tokens > TOKEN_LIMITS['MAX_SINGLE_MESSAGE_TOKENS']:
                    error_response = HumanMessage(
                        content=f"I apologize, but your message is too long ({message_tokens} tokens). "
                                f"Please keep messages under {TOKEN_LIMITS['MAX_SINGLE_MESSAGE_TOKENS']} tokens for better processing."
                    )
                    return {
                        "messages": [error_response],
                        "total_tokens": state.get("total_tokens", 0) + message_tokens,
                        "conversation_tokens": state.get("conversation_tokens", 0) + message_tokens,
                        "file_attachments": state.get("file_attachments", []),
                        "temp_attachment_ids": state.get("temp_attachment_ids", [])
                    }

            # Get summary if exists
            summary = state.get("summary", "")

            # File attachments (dicts from state)
            attachments = state.get("file_attachments", [])

            # Prepare system message
            system_message_content = self._get_system_message()
            if summary:
                system_message_content += f"\n\nConversation summary so far: {summary}"
            system_message = SystemMessage(content=system_message_content)

            # Prepare user message with proper OpenAI format
            if current_message:
                # Extract text content from the current message
                if isinstance(current_message.content, list):
                    # If content is already structured (list format)
                    text_content = ""
                    for item in current_message.content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text_content += item.get("text", "")
                else:
                    # If content is a simple string
                    text_content = str(current_message.content)

                # Build the user message content
                user_message_content = [{"type": "text", "text": text_content}]

                # Process attachments and add to message
                processed_attachments = []
                for att in attachments:
                    attachment_obj = FileAttachment.from_dict(att)

                    if attachment_obj.is_image():
                        # Handle images with URL
                        image_url = attachment_obj.get_s3_url()
                        if image_url:
                            user_message_content.append({
                                "type": "image_url",
                                "image_url": {
                                    "url": image_url,
                                    "detail": "high"  # Use high detail for better analysis
                                }
                            })
                            logger.info(f"Added image to message: {att.get('filename')}")

                    elif attachment_obj.is_document():
                        # Handle documents by extracting text content
                        try:
                            document_content = attachment_obj.extract_document_content()
                            if document_content:
                                user_message_content.append({
                                    "type": "text",
                                    "text": f"\n\n--- Content from {att.get('filename')} ---\n{document_content}\n--- End of {att.get('filename')} ---\n"
                                })
                                logger.info(f"Added document content to message: {att.get('filename')}")
                        except Exception as e:
                            logger.error(f"Error processing document {att.get('filename')}: {str(e)}")
                            user_message_content.append({
                                "type": "text",
                                "text": f"\n\n--- {att.get('filename')} (processing error: {str(e)}) ---\n"
                            })

                    # Mark as processed
                    att["processed"] = True
                    processed_attachments.append(att)

                user_message = HumanMessage(content=user_message_content)
            else:
                user_message = HumanMessage(content="Hello")
                processed_attachments = attachments

            # Final messages list - use previous messages + new user message
            messages = [system_message] + state["messages"][:-1] + [user_message]

            logger.info(f"Sending messages to model: {len(messages)} messages")

            # Log the structure of the last message for debugging
            if messages:
                last_msg = messages[-1]
                if hasattr(last_msg, 'content') and isinstance(last_msg.content, list):
                    content_types = [item.get('type') for item in last_msg.content]
                    logger.info(f"User message structure: {content_types}")

            # Count tokens before sending
            input_tokens = self.token_counter.count_message_tokens(messages)

            # Call model
            response = self.model.invoke(messages)

            # Count response tokens
            response_tokens = self.token_counter.count_tokens(str(response.content))
            total_tokens = input_tokens + response_tokens

            # Update conversation tokens
            current_conversation_tokens = state.get("conversation_tokens", 0)
            new_conversation_tokens = current_conversation_tokens + self.token_counter.count_tokens(
                text_content if current_message else "") + response_tokens

            return {
                "messages": [response],
                "total_tokens": total_tokens,
                "conversation_tokens": new_conversation_tokens,
                "current_subject": state.get("current_subject"),  # Keep existing subject (initially null)
                "subject_change_detected": False,  # Will be set in detect_subject node
                "suggested_new_subject": None,  # Will be set in detect_subject node
                "file_attachments": processed_attachments,
                "temp_attachment_ids": state.get("temp_attachment_ids", [])
            }

        except Exception as e:
            logger.error(f"Error in _call_model: {str(e)}")
            return {
                "messages": [HumanMessage(content="Sorry, I had trouble processing your request.")],
                "file_attachments": state.get("file_attachments", []),
                "temp_attachment_ids": state.get("temp_attachment_ids", [])
            }

    def _detect_subject_node(self, state: ChatbotState) -> Dict[str, Any]:
        """Dedicated node for subject detection in the graph workflow"""
        try:
            # Get the last user message for subject detection
            current_message = None
            message_text = ""

            # Find the most recent user message
            for msg in reversed(state["messages"]):
                if isinstance(msg, HumanMessage):
                    current_message = msg
                    break

            if current_message:
                # Extract text content from the message
                if isinstance(current_message.content, list):
                    for item in current_message.content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            message_text += item.get("text", "")
                else:
                    message_text = str(current_message.content)

            if not message_text.strip():
                # If no text found, keep current subject
                return {
                    "current_subject": state.get("current_subject"),
                    "subject_change_detected": False,
                    "suggested_new_subject": None
                }

            # Detect subject using the existing method
            new_subject = self._detect_subject(message_text, state)
            previous_subject = state.get("current_subject")

            subject_change = False
            suggested_subject = None

            # Check for subject change (only if previous_subject is not null)
            if previous_subject and previous_subject.lower() != new_subject.lower():
                subject_change = True
                suggested_subject = new_subject
                logger.info(f"Subject change detected: {previous_subject} -> {new_subject}")
            elif not previous_subject:
                # First time setting subject (was null)
                logger.info(f"Setting initial subject: {new_subject}")

            return {
                "current_subject": new_subject,
                "subject_change_detected": subject_change,
                "suggested_new_subject": suggested_subject
            }

        except Exception as e:
            logger.error(f"Error in _detect_subject_node: {str(e)}")
            return {
                "current_subject": state.get("current_subject"),
                "subject_change_detected": False,
                "suggested_new_subject": None
            }

    def _detect_subject(self, message: str, state: ChatbotState = None) -> str:
        """Detect subject with conversation context for better continuity"""

        # Build context for subject detection
        context_parts = []

        # Add conversation summary if available
        if state and hasattr(state, 'summary') and state.summary:
            context_parts.append(f"Previous conversation: {state.summary}")
        elif state and state.get("summary"):
            context_parts.append(f"Previous conversation: {state['summary']}")

        # Add current subject if available
        current_subject = None
        if state:
            if hasattr(state, 'current_subject'):
                current_subject = state.current_subject
            else:
                current_subject = state.get("current_subject")

        if current_subject and current_subject != "General":
            context_parts.append(f"Current subject: {current_subject}")

        # Add recent messages for context (last 2-3 messages)
        messages = None
        if state:
            if hasattr(state, 'messages'):
                messages = state.messages
            else:
                messages = state.get("messages")

        if messages:
            recent_messages = messages[-4:]  # Last 4 messages for context
            for msg in recent_messages:
                if hasattr(msg, 'content'):
                    role = "User" if isinstance(msg, HumanMessage) else "Assistant"
                    content = str(msg.content)[:200]  # Limit content length
                    context_parts.append(f"{role}: {content}")

        # Build context string
        context_text = "\n".join(context_parts) if context_parts else "No previous context"

        # Quick check for obvious continuation phrases
        continuation_phrases = [
            "continue", "tiếp tục", "tiếp đi", "keep going", "go on",
            "what about", "also", "and", "more", "next", "then",
            "explain more", "tell me more", "can you", "please"
        ]

        message_lower = message.lower().strip()
        is_likely_continuation = any(phrase in message_lower for phrase in continuation_phrases)

        # If it's likely a continuation and we have a current subject, return current subject
        if is_likely_continuation and current_subject and current_subject != "General":
            logger.info(f"Detected continuation phrase '{message}' - maintaining subject: {current_subject}")
            return current_subject

        subject_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a subject classifier for educational conversations. 

    Analyze the current question along with the conversation context to determine the main subject area.

    Rules:
    1. If the current question is a follow-up or continuation of a previous topic, maintain subject continuity
    2. Only change subject if the user clearly asks about a completely different topic  
    3. Consider phrases like "continue", "tiếp tục", "tiếp đi", "also", "what about", "can you explain more" as continuation signals
    4. Reply ONLY with the single main subject (e.g., Mathematics, Physics, Chemistry, Biology, History, Geography, Literature, Computer Science, etc.)
    5. If unsure between continuing current subject vs new subject, prefer continuity
    6. Vietnamese phrases: "tiếp đi" = "continue", "tiếp tục" = "continue", "làm tiếp" = "continue"

    Context:
    {context}

    Current question: {question}"""),
            ("human", "What is the main subject of this question considering the conversation context?")
        ])

        try:
            chain = subject_prompt | self.model
            resp = chain.invoke({
                "context": context_text,
                "question": message
            })
            detected_subject = resp.content.strip()

            # Log for debugging
            logger.info(
                f"Subject detection - Current: {current_subject}, Detected: {detected_subject}, Message: {message[:100]}")

            return detected_subject
        except Exception as e:
            logger.error(f"Error in subject detection: {str(e)}")
            # Fallback: return current subject if available, otherwise General
            return current_subject if current_subject else "General"

    def _summarize_conversation(self, state: ChatbotState) -> Dict[str, Any]:
        """Summarize the conversation to manage memory"""
        try:
            summary = state.get("summary", "")

            # Create summarization prompt
            if summary:
                summary_message = (
                    f"Current summary of the conversation: {summary}\n\n"
                    "Please update this summary by incorporating the new messages above. "
                    "Keep the summary concise but comprehensive, focusing on key topics discussed "
                    "and important educational content."
                )
            else:
                summary_message = (
                    "Please create a concise summary of this educational conversation. "
                    "Focus on the main topics discussed, key questions asked, and important "
                    "learning points covered."
                )

            # Add attachment info to summary if present
            attachments = state.get("file_attachments", [])
            if attachments:
                attachment_info = f"\n\nFiles discussed: {', '.join([att.get('filename') for att in attachments])}"
                summary_message += attachment_info

            # Add prompt to messages
            messages = state["messages"] + [HumanMessage(content=summary_message)]
            response = self.model.invoke(messages)

            # Keep only the 2 most recent messages
            delete_messages = [RemoveMessage(id=m.id) for m in state["messages"][:-2]]

            return {
                "summary": response.content,
                "messages": delete_messages,
                "current_subject": state.get("current_subject"),
                "subject_change_detected": state.get("subject_change_detected", False),
                "suggested_new_subject": state.get("suggested_new_subject"),
                "file_attachments": attachments,
                "temp_attachment_ids": state.get("temp_attachment_ids", [])
            }

        except Exception as e:
            logger.error(f"Error in _summarize_conversation: {str(e)}")
            return {
                "summary": summary,
                "messages": [],
                "file_attachments": state.get("file_attachments", []),
                "temp_attachment_ids": state.get("temp_attachment_ids", [])
            }

    def _save_attachments_to_s3(self, attachments: List[dict], question_id: str) -> List[str]:
        """Move attachments from temp to permanent S3 storage"""
        saved_urls = []
        QuestionFileAttachment = apps.get_model('qa', 'QuestionFileAttachment')
        Question = apps.get_model('qa', 'Question')

        try:
            question = Question.objects.get(id=question_id)

            for att_data in attachments:
                try:
                    # Reconstruct FileAttachment from dict
                    attachment = FileAttachment.from_dict(att_data)

                    # Move file to permanent S3 location
                    permanent_url = attachment.move_to_permanent(question_id)

                    if permanent_url:
                        # Create database record with S3 key as the file field
                        QuestionFileAttachment.objects.create(
                            question=question,
                            file=attachment.permanent_s3_key
                        )

                        saved_urls.append(permanent_url)
                        logger.info(f"Saved attachment {attachment.filename} to permanent S3")

                        # Clean up temp file after successful move
                        attachment.cleanup_temp()

                except Exception as e:
                    logger.error(f"Error saving attachment {att_data.get('filename')}: {str(e)}")

        except Exception as e:
            logger.error(f"Error in _save_attachments_to_s3: {str(e)}")

        return saved_urls

    def _cleanup_temp_attachments(self, attachments: List[dict]):
        """Clean up temporary files from S3"""
        for att_data in attachments:
            try:
                # Reconstruct FileAttachment from dict
                attachment = FileAttachment.from_dict(att_data)
                attachment.cleanup_temp()
            except Exception as e:
                logger.error(
                    f"Error cleaning up temp file {att_data.get('filename')}: {str(e)}"
                )

    def _save_conversation_summary(self, state: ChatbotState, summary_content: str) -> Optional[str]:
        """Save the conversation summary to database and return question ID"""
        try:
            logger.info(f"Raw summary content from model:\n{summary_content}")

            # Clean up summary_content in case model returns ```json ... ```
            cleaned_content = summary_content.strip()
            if cleaned_content.startswith("```"):
                # Remove the opening ```json or ```
                lines = cleaned_content.split('\n')
                if lines[0].strip() in ['```json', '```']:
                    lines = lines[1:]
                # Remove the closing ```
                if lines and lines[-1].strip() == '```':
                    lines = lines[:-1]
                cleaned_content = '\n'.join(lines).strip()

            # Replace LaTeX notation that causes JSON parsing issues
            # Convert \( and \) to regular parentheses for JSON compatibility
            cleaned_content = cleaned_content.replace('\\(', '(')
            cleaned_content = cleaned_content.replace('\\)', ')')
            # Handle other common LaTeX escapes
            cleaned_content = cleaned_content.replace('\\vec{', 'vec(')
            cleaned_content = cleaned_content.replace('\\overline{', 'overline(')
            cleaned_content = cleaned_content.replace('\\', '')  # Remove any remaining backslashes

            logger.info(f"Cleaned content for JSON parsing:\n{cleaned_content}")

            # Try to parse JSON
            try:
                summary_data = json.loads(cleaned_content)
            except json.JSONDecodeError as first_error:
                # If JSON parsing still fails, try to extract data manually
                logger.warning(f"JSON parsing failed: {first_error}. Attempting manual extraction.")

                # Manual extraction as fallback
                import re

                subject_match = re.search(r'"subject":\s*"([^"]+)"', cleaned_content)
                title_match = re.search(r'"title":\s*"([^"]+)"', cleaned_content)
                question_body_match = re.search(r'"question_body":\s*"([^"]+)"', cleaned_content, re.DOTALL)
                answer_summary_match = re.search(r'"answer_summary":\s*"([^"]+)"', cleaned_content, re.DOTALL)

                summary_data = {
                    'subject': subject_match.group(1) if subject_match else 'General',
                    'title': title_match.group(1) if title_match else 'Chatbot Conversation',
                    'question_body': question_body_match.group(
                        1) if question_body_match else 'User questions unavailable',
                    'answer_summary': answer_summary_match.group(
                        1) if answer_summary_match else 'AI responses unavailable'
                }

                logger.info(f"Manually extracted summary data: {summary_data}")

            logger.info(f"Final parsed summary result: {json.dumps(summary_data, indent=2)}")

            # Django models
            Subject = apps.get_model('qa', 'Subject')
            Question = apps.get_model('qa', 'Question')
            Answer = apps.get_model('qa', 'Answer')

            # Subject
            subject_name = summary_data.get('subject', 'General')
            subject, created = Subject.objects.get_or_create(
                name=subject_name,
                defaults={'description': f'Questions and discussions about {subject_name}'}
            )

            # User
            from django.contrib.auth import get_user_model
            User = get_user_model()
            user = None
            if state.get('user_id'):
                try:
                    user = User.objects.get(id=state['user_id'])
                except User.DoesNotExist:
                    pass

            if user:
                # Create Question - use question_body instead of summary
                question = Question.objects.create(
                    user=user,
                    subject=subject,
                    title=summary_data.get('title', 'Chatbot Conversation')[:255],
                    body=summary_data.get('question_body', '')[:5000],  # Changed from 'summary' to 'question_body'
                    is_public=False
                )
                logger.info(f"Question saved: {question}")

                # Create Answer - use answer_summary instead of summary
                Answer.objects.create(
                    question=question,
                    content=summary_data.get('answer_summary', ''),  # Changed from 'summary' to 'answer_summary'
                    is_ai_generated=True
                )
                logger.info(f"Answer saved for user {user.id} under subject {subject.name}")

                # Generate embedding asynchronously using Celery
                try:
                    generate_question_embedding.delay(str(question.id))
                    logger.info(f"Queued embedding generation for question {question.id}")
                except Exception as e:
                    logger.error(f"Failed to queue embedding generation for question {question.id}: {str(e)}")
                    # Continue without failing the save operation

                return str(question.id)

        except Exception as e:
            logger.error(f"Error saving conversation summary: {str(e)}")

        return None

    def _should_continue_after_conversation(self, state: ChatbotState) -> Literal["detect_subject", END]:
        """Determine the next action after conversation node"""
        messages = state["messages"]

        # If there are more than 6 messages, go to subject detection then summarization
        if len(messages) > 6:
            return "detect_subject"

        # Otherwise end the conversation
        return END

    def _get_token_status(self, conversation_tokens: int) -> Dict[str, Any]:
        """Get token status information for frontend"""
        return {
            "current_tokens": conversation_tokens,
            "max_tokens": TOKEN_LIMITS['MAX_CONVERSATION_TOKENS'],
            "warning_threshold": TOKEN_LIMITS['WARNING_TOKENS'],
            "critical_threshold": TOKEN_LIMITS['CRITICAL_TOKENS'],
            "usage_percentage": round((conversation_tokens / TOKEN_LIMITS['MAX_CONVERSATION_TOKENS']) * 100, 1),
            "status": self._get_token_status_level(conversation_tokens),
            "should_start_new_chat": conversation_tokens > TOKEN_LIMITS['CRITICAL_TOKENS'],
            "warning_message": self._get_token_warning_message(conversation_tokens)
        }

    def _get_token_status_level(self, tokens: int) -> str:
        """Get token status level"""
        if tokens > TOKEN_LIMITS['CRITICAL_TOKENS']:
            return "critical"
        elif tokens > TOKEN_LIMITS['WARNING_TOKENS']:
            return "warning"
        else:
            return "normal"

    def _get_token_warning_message(self, tokens: int) -> str:
        """Get appropriate warning message based on token count"""
        if tokens > TOKEN_LIMITS['CRITICAL_TOKENS']:
            return "This conversation is getting very long. Please start a new chat for better performance."
        elif tokens > TOKEN_LIMITS['WARNING_TOKENS']:
            return "This conversation is getting long. Consider starting a new chat soon."
        else:
            return None

    def create_file_attachment(self, file_data: bytes, filename: str, content_type: str) -> FileAttachment:
        """Create a new file attachment with immediate S3 temp upload"""
        return FileAttachment(file_data, filename, content_type)

    def chat(self, message: str, user_id: str = None, thread_id: str = "default",
             file_attachments: List[FileAttachment] = None) -> Dict[str, Any]:
        """Main chat interface with token tracking"""
        try:
            # Check message length before processing
            message_tokens = self.token_counter.count_tokens(message)
            if message_tokens > TOKEN_LIMITS['MAX_SINGLE_MESSAGE_TOKENS']:
                return {
                    "response": f"Your message is too long ({message_tokens} tokens). Please keep messages under {TOKEN_LIMITS['MAX_SINGLE_MESSAGE_TOKENS']} tokens.",
                    "status": "error",
                    "thread_id": thread_id,
                    "token_info": {
                        "message_tokens": message_tokens,
                        "max_message_tokens": TOKEN_LIMITS['MAX_SINGLE_MESSAGE_TOKENS'],
                        "conversation_tokens": 0,
                        "token_status": self._get_token_status(0)
                    }
                }

            # Conversation config
            config = {"configurable": {"thread_id": thread_id}}

            # Load current state
            try:
                current_state = self.graph.get_state(config)
                current_conversation_tokens = current_state.values.get("conversation_tokens", 0)
                existing_attachments = current_state.values.get("file_attachments", [])
                temp_attachment_ids = current_state.values.get("temp_attachment_ids", [])
                current_subject = current_state.values.get("current_subject")  # Could be None initially
            except:
                current_conversation_tokens = 0
                existing_attachments = []
                temp_attachment_ids = []
                current_subject = None  # Start with null subject

            # Too long conversation check
            if current_conversation_tokens > TOKEN_LIMITS['CRITICAL_TOKENS']:
                if file_attachments:
                    self._cleanup_temp_attachments(file_attachments)

                return {
                    "response": "This conversation has reached the maximum length. Please start a new chat to continue.",
                    "status": "conversation_too_long",
                    "thread_id": thread_id,
                    "token_info": {
                        "message_tokens": message_tokens,
                        "conversation_tokens": current_conversation_tokens,
                        "token_status": self._get_token_status(current_conversation_tokens)
                    }
                }

            # Merge attachments
            all_attachments = existing_attachments.copy()
            new_attachment_ids = []
            if file_attachments:
                all_attachments.extend([att.to_dict() for att in file_attachments])
                new_attachment_ids = [att.id for att in file_attachments]

            # Build structured HumanMessage
            user_message_content = [{"type": "text", "text": message}]

            if file_attachments:
                for att in file_attachments:
                    att_dict = att.to_dict()
                    file_url = att_dict.get("s3_url") or att_dict.get("temp_url")
                    if not file_url:
                        continue

                    if att.is_image():
                        user_message_content.append({
                            "type": "image_url",
                            "image_url": {"url": file_url}
                        })
                    else:
                        user_message_content.append({
                            "type": "file",
                            "file_url": file_url
                        })

            input_message = HumanMessage(content=user_message_content)

            # Call graph with initial null subject
            result = self.graph.invoke({
                "messages": [input_message],
                "user_id": user_id,
                "thread_id": thread_id,
                "conversation_tokens": current_conversation_tokens,
                "current_subject": current_subject,  # Initially None/null
                "file_attachments": all_attachments,
                "temp_attachment_ids": temp_attachment_ids + new_attachment_ids
            }, config)

            # Extract response
            if result.get("messages"):
                last_message = result["messages"][-1]
                response_content = getattr(last_message, 'content', str(last_message))
            else:
                response_content = "I'm here to help with your learning questions!"

            # Tokens
            final_conversation_tokens = result.get("conversation_tokens", current_conversation_tokens)
            total_tokens = result.get("total_tokens", 0)

            # Attachments in response
            final_attachments = result.get("file_attachments", [])
            attachment_info = []
            if final_attachments:
                attachment_info = [
                    {
                        "filename": att.get("filename"),
                        "content_type": att.get("content_type"),
                        "size": att.get("size"),
                        "processed": bool(att.get("description"))
                    }
                    for att in final_attachments
                ]

            return {
                "message": message,
                "response": response_content,
                "status": "success",
                "thread_id": thread_id,
                "token_info": {
                    "message_tokens": message_tokens,
                    "conversation_tokens": final_conversation_tokens,
                    "total_tokens": total_tokens,
                    "token_status": self._get_token_status(final_conversation_tokens)
                },
                "current_subject": result.get("current_subject"),
                "subject_change_detected": result.get("subject_change_detected", False),
                "suggested_new_subject": result.get("suggested_new_subject"),
                "attachments": attachment_info
            }

        except Exception as e:
            logger.error(f"Error in chat: {str(e)}")

            if file_attachments:
                self._cleanup_temp_attachments(file_attachments)

            return {
                "response": "I apologize, but I encountered an error. Please try again.",
                "status": "error",
                "error": str(e),
                "thread_id": thread_id,
                "token_info": {
                    "message_tokens": self.token_counter.count_tokens(message) if message else 0,
                    "conversation_tokens": 0,
                    "token_status": self._get_token_status(0)
                }
            }

    def get_conversation_state(self, thread_id: str = "default") -> Dict[str, Any]:
        """Get the current state of a conversation thread with token information"""
        try:
            config = {"configurable": {"thread_id": thread_id}}
            state = self.graph.get_state(config)

            conversation_tokens = state.values.get("conversation_tokens", 0)
            attachments = state.values.get("file_attachments", [])

            attachment_info = []
            if attachments:
                attachment_info = [
                    {
                        "filename": att.get("filename"),
                        "content_type": att.get("content_type"),
                        "size": att.get("size")
                    }
                    for att in attachments
                ]

            return {
                "summary": state.values.get("summary", ""),
                "message_count": len(state.values.get("messages", [])),
                "conversation_tokens": conversation_tokens,
                "token_status": self._get_token_status(conversation_tokens),
                "attachments": attachment_info,
                "status": "success"
            }
        except Exception as e:
            logger.error(f"Error getting conversation state: {str(e)}")
            return {"status": "error", "error": str(e)}

    def save_conversation(self, thread_id: str, user_id: str = None) -> Dict[str, Any]:
        """
        Manually save a conversation with all attachments to the database.
        This preserves attachments by uploading them to S3.
        """
        try:
            # Load conversation state
            config = {"configurable": {"thread_id": thread_id}}
            state = self.graph.get_state(config)

            if not state or not state.values.get("messages"):
                return {"status": "error", "message": "No conversation found for this thread."}

            # Separate user questions and AI answers
            user_messages = []
            ai_messages = []

            # Process existing summary
            if state.values.get("summary"):
                user_messages.append(f"Previous conversation context: {state.values['summary']}")

            # Separate messages by type
            for msg in state.values.get("messages", []):
                if hasattr(msg, 'content'):
                    if isinstance(msg, HumanMessage):
                        user_messages.append(str(msg.content))
                    else:  # AI message
                        ai_messages.append(str(msg.content))

            # Add attachment information
            attachments = state.values.get("file_attachments", [])
            if attachments:
                attachment_filenames = [att.get('filename') for att in attachments]
                user_messages.append(f"Files attached: {', '.join(attachment_filenames)}")

            # Combine user questions into question body
            question_body = "\n\n".join(user_messages)

            # Combine AI responses for answer summarization
            ai_responses_text = "\n\n".join(ai_messages)

            # Updated prompt for proper Q&A extraction
            analysis_prompt = f"""Please analyze this educational conversation and extract the following information:

    User Questions/Content:
    {question_body}

    AI Responses:
    {ai_responses_text}

    Please format your response as JSON with the following structure:
    {{
        "subject": "Main subject area (e.g., Mathematics, Physics, Chemistry, Biology, History, etc.)",
        "title": "Brief title summarizing the main question/topic",
        "question_body": "All user questions and requests combined into a coherent question body",
        "answer_summary": "Give the detail answer of all question even it different aspect, not summary",
        "key_topics": ["topic1", "topic2", "topic3"]
    }}

    Guidelines:
    - question_body should contain what the user asked about, their questions, and context
    - answer_summary should be a detail of the AI's educational responses and explanations for each question in the conversation
    - Keep both sections informative but concise"""

            analysis_response = self.model.invoke([HumanMessage(content=analysis_prompt)])

            # Attach user_id into state for saving
            state.values["user_id"] = user_id
            state.values["thread_id"] = thread_id

            # Save to DB and get question ID
            question_id = self._save_conversation_summary(state.values, analysis_response.content)

            # Save attachments to S3 if question was created
            saved_attachments = []
            if question_id and attachments:
                saved_urls = self._save_attachments_to_s3(attachments, question_id)
                saved_attachments = [
                    {"filename": att.get("filename"), "url": url}
                    for att, url in zip(attachments, saved_urls) if url
                ]
            else:
                # Clean up temp files if save failed
                self._cleanup_temp_attachments(attachments)

            # Clear conversation after successful save
            self.graph.update_state(config, {
                "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES)],
                "file_attachments": [],
                "temp_attachment_ids": []
            })

            return {
                "status": "success",
                "message": "Conversation saved successfully.",
                "question_id": question_id,
                "saved_attachments": saved_attachments
            }

        except Exception as e:
            logger.error(f"Error saving conversation: {str(e)}")
            return {"status": "error", "message": str(e)}

    def create_conversation_summary(self, thread_id: str, user_id: str = None) -> Dict[str, Any]:
        """
        Create a full summary of a conversation thread and save it to the database.
        This method is kept for backward compatibility but now calls save_conversation.
        """
        return self.save_conversation(thread_id, user_id)

    def cleanup_conversation(self, thread_id: str) -> Dict[str, Any]:
        """Delete full conversation: attachments + messages."""
        try:
            config = {"configurable": {"thread_id": thread_id}}
            state = self.graph.get_state(config)

            # 1. Cleanup attachments if any
            if state:
                attachments = state.values.get("file_attachments", [])
                self._cleanup_temp_attachments(attachments)

            # 2. Remove all messages + reset attachments
            self.graph.update_state(config, {
                "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES)],
                "file_attachments": [],
                "temp_attachment_ids": []
            })

            return {"status": "success", "message": "Conversation fully cleared"}

        except Exception as e:
            logger.error(f"Error cleaning up conversation: {str(e)}")
            return {"status": "error", "error": str(e)}


# Global chatbot instance
_chatbot_instance = None


def get_chatbot():
    """Get or create the global chatbot instance"""
    global _chatbot_instance
    if _chatbot_instance is None:
        _chatbot_instance = SmartLearningChatbot()
    return _chatbot_instance


def initialize_chatbot():
    """Initialize the chatbot on startup"""
    try:
        get_chatbot()
        logger.info("Smart Learning Chatbot initialized successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize chatbot: {str(e)}")
        return False