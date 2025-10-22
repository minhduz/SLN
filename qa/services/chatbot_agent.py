from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import MessagesState, StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import SystemMessage, HumanMessage, RemoveMessage
from typing_extensions import Literal
from typing import Dict, Any, List
import logging
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
    current_subject: str
    subject_change_detected: bool
    suggested_new_subject: str
    file_attachments: List[Dict[str, Any]]
    all_conversation_files: List[Dict[str, Any]]  # ALL files (new!)
    temp_attachment_ids: List[str]
    full_conversation_history: List[Dict[str, str]]  # Lightweight Q&A storage (not sent to model)


class SmartLearningChatbot:
    """Smart Learning System Chatbot with memory management, token tracking, and database integration"""

    def __init__(self):
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

        workflow.add_node("conversation", self._call_model)
        workflow.add_node("detect_subject", self._detect_subject_node)
        workflow.add_node("summarize_conversation", self._summarize_conversation)

        workflow.add_edge(START, "conversation")

        # After conversation → either detect subject or end
        workflow.add_conditional_edges("conversation", self._should_continue_after_conversation)

        # After subject detection → either summarize (every 6) or end
        workflow.add_conditional_edges("detect_subject", self._should_summarize_after_subject_detection)

        workflow.add_edge("summarize_conversation", END)
        self.graph = workflow.compile(checkpointer=self.memory)

    def _get_system_message(self) -> str:
        """Get the system message for the Smart Learning System"""
        return """You are an AI assistant for a Smart Learning System designed to help students with educational questions and learning. Your role is to:
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

    def _call_model(self, state: ChatbotState) -> Dict[str, Any]:
        """Call the model with conversation context and token tracking, including file analysis"""
        try:
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
                        "temp_attachment_ids": state.get("temp_attachment_ids", []),
                        "full_conversation_history": state.get("full_conversation_history", [])
                    }

            summary = state.get("summary", "")
            attachments = state.get("file_attachments", [])

            system_message_content = self._get_system_message()
            if summary:
                system_message_content += f"\n\nConversation summary so far: {summary}"
            system_message = SystemMessage(content=system_message_content)

            # Extract user message text for history tracking
            user_message_text = ""
            if current_message:
                if isinstance(current_message.content, list):
                    text_content = ""
                    for item in current_message.content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text_content += item.get("text", "")
                    user_message_text = text_content
                else:
                    user_message_text = str(current_message.content)

                user_message_content = [{"type": "text", "text": user_message_text}]

                processed_attachments = []
                for att in attachments:
                    attachment_obj = FileAttachment.from_dict(att)
                    if attachment_obj.is_image():
                        image_url = attachment_obj.get_s3_url()
                        if image_url:
                            user_message_content.append({
                                "type": "image_url",
                                "image_url": {
                                    "url": image_url,
                                    "detail": "high"
                                }
                            })
                            logger.info(f"Added image to message: {att.get('filename')}")
                    elif attachment_obj.is_document():
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

                    att["processed"] = True
                    processed_attachments.append(att)

                user_message = HumanMessage(content=user_message_content)
            else:
                user_message = HumanMessage(content="Hello")
                processed_attachments = attachments

            messages = [system_message] + state["messages"][:-1] + [user_message]
            logger.info(f"Sending messages to model: {len(messages)} messages")

            input_tokens = self.token_counter.count_message_tokens(messages)
            response = self.model.invoke(messages)
            response_tokens = self.token_counter.count_tokens(str(response.content))
            total_tokens = input_tokens + response_tokens

            current_conversation_tokens = state.get("conversation_tokens", 0)
            new_conversation_tokens = current_conversation_tokens + self.token_counter.count_tokens(
                user_message_text if current_message else "") + response_tokens

            # 🆕 TRACK FULL HISTORY - Add this Q&A pair to history
            # This is stored separately and NOT included in the messages sent to the model
            # So it doesn't increase token usage!
            full_history = state.get("full_conversation_history", [])
            full_history.append({
                "user_message": user_message_text,
                "ai_response": str(response.content),
                "timestamp": None  # Could add timestamp if needed
            })

            logger.info(f"Added to history - Total entries: {len(full_history)}")

            return {
                "messages": [response],
                "total_tokens": total_tokens,
                "conversation_tokens": new_conversation_tokens,
                "current_subject": state.get("current_subject"),
                "subject_change_detected": False,
                "suggested_new_subject": None,
                "file_attachments": processed_attachments,
                "all_conversation_files": state.get("all_conversation_files", []) + processed_attachments,
                "temp_attachment_ids": state.get("temp_attachment_ids", []),
                "full_conversation_history": full_history  # 🆕 Return updated history
            }

        except Exception as e:
            logger.error(f"Error in _call_model: {str(e)}")
            return {
                "messages": [HumanMessage(content="Sorry, I had trouble processing your request.")],
                "file_attachments": state.get("file_attachments", []),
                "temp_attachment_ids": state.get("temp_attachment_ids", []),
                "full_conversation_history": state.get("full_conversation_history", [])
            }

    def _detect_subject_node(self, state: ChatbotState) -> Dict[str, Any]:
        """Dedicated node for subject detection in the graph workflow"""
        try:
            user_message = None
            ai_response = None
            user_message_text = ""
            ai_response_text = ""

            # ✅ FIX: Get BOTH the last user message AND the AI response
            messages = state["messages"]
            for i in range(len(messages) - 1, -1, -1):
                msg = messages[i]
                # Get the most recent AI message (the response)
                if ai_response is None and not isinstance(msg, HumanMessage):
                    ai_response = msg
                    if hasattr(msg, 'content'):
                        ai_response_text = str(msg.content)
                # Get the most recent user message
                elif user_message is None and isinstance(msg, HumanMessage):
                    user_message = msg
                    if isinstance(msg.content, list):
                        for item in msg.content:
                            if isinstance(item, dict) and item.get("type") == "text":
                                user_message_text += item.get("text", "")
                    else:
                        user_message_text = str(msg.content)

                # Stop once we have both
                if user_message and ai_response:
                    break

            if not user_message_text.strip() and not ai_response_text.strip():
                return {
                    "current_subject": state.get("current_subject"),
                    "subject_change_detected": False,
                    "suggested_new_subject": None
                }

            # ✅ FIX: Pass BOTH user message and AI response to subject detection
            new_subject = self._detect_subject(
                user_message=user_message_text,
                ai_response=ai_response_text,
                state=state
            )
            previous_subject = state.get("current_subject")
            subject_change = False
            suggested_subject = None

            if previous_subject and previous_subject.lower() != new_subject.lower():
                subject_change = True
                suggested_subject = new_subject
                logger.info(f"Subject change detected: {previous_subject} -> {new_subject}")

                return {
                    "current_subject": previous_subject,  # Keep the OLD subject
                    "subject_change_detected": subject_change,
                    "suggested_new_subject": suggested_subject  # Suggest the NEW subject
                }
            elif not previous_subject:
                logger.info(f"Setting initial subject: {new_subject}")
                return {
                    "current_subject": new_subject,
                    "subject_change_detected": False,
                    "suggested_new_subject": None
                }
            else:
                return {
                    "current_subject": new_subject,
                    "subject_change_detected": False,
                    "suggested_new_subject": None
                }

        except Exception as e:
            logger.error(f"Error in _detect_subject_node: {str(e)}")
            return {
                "current_subject": state.get("current_subject"),
                "subject_change_detected": False,
                "suggested_new_subject": None
            }

    def _detect_subject(self, user_message: str, ai_response: str = "", state: ChatbotState = None) -> str:
        """Detect subject with both user question AND AI response for better accuracy"""
        context_parts = []

        if state and state.get("summary"):
            context_parts.append(f"Previous conversation: {state['summary']}")

        current_subject = state.get("current_subject") if state else None
        if current_subject and current_subject != "General":
            context_parts.append(f"Current subject: {current_subject}")

        messages = state.get("messages") if state else None
        if messages:
            recent_messages = messages[-4:-2]  # Get previous messages (not the current Q&A pair)
            for msg in recent_messages:
                if hasattr(msg, 'content'):
                    role = "User" if isinstance(msg, HumanMessage) else "Assistant"
                    content = str(msg.content)[:200]
                    context_parts.append(f"{role}: {content}")

        context_text = "\n".join(context_parts) if context_parts else "No previous context"

        # Check for continuation phrases
        continuation_phrases = [
            "continue", "tiếp tục", "tiếp đi", "keep going", "go on", "what about",
            "also", "and", "more", "next", "then", "explain more", "tell me more",
            "can you", "please"
        ]
        message_lower = user_message.lower().strip()
        is_likely_continuation = any(phrase in message_lower for phrase in continuation_phrases)

        if is_likely_continuation and current_subject and current_subject != "General":
            logger.info(f"Detected continuation phrase '{user_message}' - maintaining subject: {current_subject}")
            return current_subject

        # ✅ FIX: Updated prompt to analyze BOTH user message and AI response
        subject_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a subject classifier for educational conversations. Analyze the current question-answer pair along with the conversation context to determine the main subject area.

    **IMPORTANT**: Pay special attention to the AI's RESPONSE, as it contains the actual subject content - especially when the user's message is brief or just says "help me" or "solve this".

    Rules:
    1. Analyze BOTH the user's question AND the AI's response to understand the true subject
    2. The AI's response often contains more subject-specific content (formulas, terminology, concepts)
    3. If the current question is a follow-up or continuation of a previous topic, maintain subject continuity
    4. Only change subject if the user clearly asks about a completely different topic
    5. Consider phrases like "continue", "tiếp tục", "giải hộ tôi", "help me", "also", "what about" as potential continuation signals
    6. Reply ONLY with the single main subject (e.g., Mathematics, Physics, Chemistry, Biology, History, Geography, Literature, Computer Science, etc.)
    7. If unsure between continuing current subject vs new subject, prefer continuity
    8. Vietnamese phrases: "giải hộ tôi" = "help me solve", "tiếp đi" = "continue", "tiếp tục" = "continue"

    Context: {context}
    User's question: {user_question}
    AI's response: {ai_response}"""),
            ("human", "What is the main subject of this question-answer pair considering the conversation context?")
        ])

        try:
            chain = subject_prompt | self.model
            resp = chain.invoke({
                "context": context_text,
                "user_question": user_message,
                "ai_response": ai_response[:1000]  # Limit AI response length to avoid token overflow
            })
            detected_subject = resp.content.strip()
            logger.info(
                f"Subject detection - Current: {current_subject}, Detected: {detected_subject}, "
                f"User: {user_message[:100]}, AI: {ai_response[:100]}"
            )
            return detected_subject
        except Exception as e:
            logger.error(f"Error in subject detection: {str(e)}")
            return current_subject if current_subject else "General"

    def _summarize_conversation(self, state: ChatbotState) -> Dict[str, Any]:
        """Summarize the conversation to manage memory"""
        try:
            summary = state.get("summary", "")

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

            attachments = state.get("file_attachments", [])
            if attachments:
                attachment_info = f"\n\nFiles discussed: {', '.join([att.get('filename') for att in attachments])}"
                summary_message += attachment_info

            messages = state["messages"] + [HumanMessage(content=summary_message)]
            response = self.model.invoke(messages)

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

    def _should_summarize_after_subject_detection(self, state: ChatbotState) -> Literal["summarize_conversation", END]:
        """
        Determine whether to summarize after subject detection
        - Summarize every 6 messages
        - Otherwise just end
        """
        messages = state["messages"]
        message_count = len(messages)

        # Check if we should summarize (every 6 messages)
        if message_count >= 6 and message_count % 6 == 0:
            logger.info(f"Triggering summarization at {message_count} messages")
            return "summarize_conversation"

        logger.info(f"Skipping summarization at {message_count} messages (waiting for next 6-message interval)")
        return END

    def _should_continue_after_conversation(self, state: ChatbotState) -> Literal["detect_subject", END]:
        """
        Determine the next action after conversation node
        - Detect subject every 2 messages
        - Summarize every 6 messages (after subject detection)
        """
        messages = state["messages"]
        message_count = len(messages)

        # Check if we should detect subject (every 2 messages)
        # We use modulo to check: 2, 4, 6, 8, 10...
        if message_count >= 2 and message_count % 2 == 0:
            logger.info(f"Triggering subject detection at {message_count} messages")
            return "detect_subject"

        return END

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