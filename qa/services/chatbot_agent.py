import os
from django.conf import settings
from langchain_openai import ChatOpenAI
from langgraph.graph import MessagesState, StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import SystemMessage, HumanMessage, RemoveMessage
from typing_extensions import Literal
from typing import Dict, Any, List
import json
import logging
import tiktoken
from django.apps import apps

# Configure logging
logger = logging.getLogger(__name__)

# Token limits configuration - can be overridden by Django settings
DEFAULT_TOKEN_LIMITS = {
    'MAX_CONVERSATION_TOKENS': 12000,  # Maximum tokens in a conversation
    'WARNING_TOKENS': 10000,  # Warning threshold
    'CRITICAL_TOKENS': 11500,  # Critical threshold - force new chat
    'MAX_SINGLE_MESSAGE_TOKENS': 2000,  # Maximum tokens in a single message
}


# Get token limits from Django settings if available
def get_token_limits():
    try:
        from django.conf import settings
        if hasattr(settings, 'CHATBOT_CONFIG') and 'TOKEN_LIMITS' in settings.CHATBOT_CONFIG:
            return settings.CHATBOT_CONFIG['TOKEN_LIMITS']
    except:
        pass
    return DEFAULT_TOKEN_LIMITS


TOKEN_LIMITS = get_token_limits()


class ChatbotState(MessagesState):
    """Extended state for the chatbot with conversation summary and token tracking"""
    summary: str
    user_id: str
    thread_id: str
    total_tokens: int
    conversation_tokens: int


class TokenCounter:
    """Helper class to count tokens using tiktoken"""

    def __init__(self, model_name: str = "gpt-4o"):
        try:
            # Get the encoding for the specific model
            self.encoding = tiktoken.encoding_for_model(model_name)
        except KeyError:
            # Fallback to cl100k_base encoding (used by GPT-4)
            self.encoding = tiktoken.get_encoding("cl100k_base")

    def count_tokens(self, text: str) -> int:
        """Count tokens in a text string"""
        if not text:
            return 0
        return len(self.encoding.encode(text))

    def count_message_tokens(self, messages: List) -> int:
        """Count tokens in a list of messages"""
        total = 0
        for message in messages:
            if hasattr(message, 'content'):
                total += self.count_tokens(str(message.content))
                # Add tokens for message formatting (role, etc.)
                total += 4  # Approximate overhead per message
        return total

    def truncate_text_to_tokens(self, text: str, max_tokens: int) -> str:
        """Truncate text to fit within token limit"""
        if not text:
            return text

        tokens = self.encoding.encode(text)
        if len(tokens) <= max_tokens:
            return text

        # Truncate tokens and decode back to text
        truncated_tokens = tokens[:max_tokens]
        return self.encoding.decode(truncated_tokens)


class SmartLearningChatbot:
    """Smart Learning System Chatbot with memory management, token tracking, and database integration"""

    def __init__(self):
        # Get model configuration from Django settings
        model_config = self._get_model_config()
        self.model = ChatOpenAI(**model_config)
        self.memory = MemorySaver()
        self.token_counter = TokenCounter(model_config.get('model', 'gpt-4o'))
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
        workflow.add_node("summarize_conversation", self._summarize_conversation)
        workflow.add_node("total_summarize", self._total_summarize_and_save)

        # Set entry point
        workflow.add_edge(START, "conversation")

        # Add conditional edges
        workflow.add_conditional_edges("conversation", self._should_continue)
        workflow.add_edge("summarize_conversation", END)
        workflow.add_edge("total_summarize", END)

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

Always maintain a helpful, educational tone and focus on facilitating learning and understanding."""

    def _call_model(self, state: ChatbotState) -> Dict[str, Any]:
        """Call the model with conversation context and token tracking"""
        try:
            # Check if single message exceeds limit
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
                        "conversation_tokens": state.get("conversation_tokens", 0) + message_tokens
                    }

            # Get summary if it exists
            summary = state.get("summary", "")

            # Prepare messages with system context
            system_message = SystemMessage(content=self._get_system_message())

            if summary:
                # Add summary to system context
                summary_context = f"\nConversation summary so far: {summary}"
                enhanced_system = SystemMessage(content=self._get_system_message() + summary_context)
                messages = [enhanced_system] + state["messages"]
            else:
                messages = [system_message] + state["messages"]

            # Count tokens before sending
            input_tokens = self.token_counter.count_message_tokens(messages)

            response = self.model.invoke(messages)

            # Count response tokens
            response_tokens = self.token_counter.count_tokens(str(response.content))
            total_tokens = input_tokens + response_tokens

            # Update conversation tokens
            current_conversation_tokens = state.get("conversation_tokens", 0)
            new_conversation_tokens = current_conversation_tokens + self.token_counter.count_tokens(
                str(current_message.content)) + response_tokens

            return {
                "messages": [response],
                "total_tokens": total_tokens,
                "conversation_tokens": new_conversation_tokens
            }

        except Exception as e:
            logger.error(f"Error in _call_model: {str(e)}")
            error_response = HumanMessage(content="I apologize, but I encountered an error. Please try again.")
            return {
                "messages": [error_response],
                "total_tokens": state.get("total_tokens", 0),
                "conversation_tokens": state.get("conversation_tokens", 0)
            }

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

            # Add prompt to messages
            messages = state["messages"] + [HumanMessage(content=summary_message)]
            response = self.model.invoke(messages)

            # Keep only the 2 most recent messages
            delete_messages = [RemoveMessage(id=m.id) for m in state["messages"][:-2]]

            return {
                "summary": response.content,
                "messages": delete_messages
            }

        except Exception as e:
            logger.error(f"Error in _summarize_conversation: {str(e)}")
            return {"summary": summary, "messages": []}

    def _total_summarize_and_save(self, state: ChatbotState) -> Dict[str, Any]:
        """Create a comprehensive summary and save to database"""
        try:
            # Get all messages and summary
            all_content = []
            if state.get("summary"):
                all_content.append(f"Previous summary: {state['summary']}")

            # Add recent messages
            for msg in state["messages"]:
                if hasattr(msg, 'content'):
                    role = "User" if isinstance(msg, HumanMessage) else "Assistant"
                    all_content.append(f"{role}: {msg.content}")

            conversation_text = "\n".join(all_content)

            # Create comprehensive summary prompt
            summary_prompt = f"""Please analyze this educational conversation and provide:

1. A comprehensive summary of the entire conversation
2. The main subject/topic area discussed (e.g., Mathematics, Physics, Chemistry, Biology, History, etc.)
3. Key learning points and concepts covered
4. Questions asked and answers provided

Conversation:
{conversation_text}

Please format your response as JSON with the following structure:
{{
    "subject": "Main subject area",
    "title": "Brief title summarizing the main question/topic",
    "summary": "Comprehensive summary of the conversation",
    "key_topics": ["topic1", "topic2", "topic3"]
}}"""

            # Get comprehensive summary
            summary_response = self.model.invoke([HumanMessage(content=summary_prompt)])

            # Parse the response and save to database
            self._save_conversation_summary(state, summary_response.content)

            return {"messages": []}

        except Exception as e:
            logger.error(f"Error in _total_summarize_and_save: {str(e)}")
            return {"messages": []}

    def _save_conversation_summary(self, state: ChatbotState, summary_content: str):
        """Save the conversation summary to database"""
        try:
            # Parse the JSON response
            import json
            summary_data = json.loads(summary_content)

            # Get Django models
            Subject = apps.get_model('qa', 'Subject')
            Question = apps.get_model('qa', 'Question')
            Answer = apps.get_model('qa', 'Answer')

            # Get or create subject
            subject_name = summary_data.get('subject', 'General')
            subject, created = Subject.objects.get_or_create(
                name=subject_name,
                defaults={'description': f'Questions and discussions about {subject_name}'}
            )

            # Get user
            from django.contrib.auth import get_user_model
            User = get_user_model()
            user = None
            if state.get('user_id'):
                try:
                    user = User.objects.get(id=state['user_id'])
                except User.DoesNotExist:
                    pass

            if user:
                # Create question record
                question = Question.objects.create(
                    user=user,
                    subject=subject,
                    title=summary_data.get('title', 'Chatbot Conversation')[:255],
                    body=summary_data.get('summary', '')[:5000],  # Limit body length
                    is_public=False  # Keep private by default
                )

                # Create AI-generated answer
                Answer.objects.create(
                    question=question,
                    content=summary_data.get('summary', ''),
                    is_ai_generated=True
                )

                logger.info(f"Saved conversation summary for user {user.id} in subject {subject.name}")

        except Exception as e:
            logger.error(f"Error saving conversation summary: {str(e)}")

    def _should_continue(self, state: ChatbotState) -> Literal["summarize_conversation", "total_summarize", END]:
        """Determine the next action based on conversation state and token limits"""
        messages = state["messages"]
        conversation_tokens = state.get("conversation_tokens", 0)

        # If conversation exceeds critical token limit, force total summary
        if conversation_tokens > TOKEN_LIMITS['CRITICAL_TOKENS']:
            return "total_summarize"

        # If there are more than 10 messages or warning token limit reached, do a total summary
        elif len(messages) > 10 or conversation_tokens > TOKEN_LIMITS['WARNING_TOKENS']:
            return "total_summarize"

        # If there are more than 6 messages, summarize
        elif len(messages) > 6:
            return "summarize_conversation"

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

    def chat(self, message: str, user_id: str = None, thread_id: str = "default") -> Dict[str, Any]:
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

            # Create config for this conversation thread
            config = {"configurable": {"thread_id": thread_id}}

            # Get current conversation state to check token count
            try:
                current_state = self.graph.get_state(config)
                current_conversation_tokens = current_state.values.get("conversation_tokens", 0)

                # Check if conversation is already too long
                if current_conversation_tokens > TOKEN_LIMITS['CRITICAL_TOKENS']:
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
            except:
                current_conversation_tokens = 0

            # Create input message
            input_message = HumanMessage(content=message)

            # Invoke the graph
            result = self.graph.invoke({
                "messages": [input_message],
                "user_id": user_id,
                "thread_id": thread_id,
                "conversation_tokens": current_conversation_tokens
            }, config)

            # Extract the response and token information
            if result.get("messages"):
                last_message = result["messages"][-1]
                response_content = getattr(last_message, 'content', str(last_message))
            else:
                response_content = "I'm here to help with your learning questions!"

            # Get final token counts
            final_conversation_tokens = result.get("conversation_tokens", current_conversation_tokens)
            total_tokens = result.get("total_tokens", 0)

            return {
                "response": response_content,
                "status": "success",
                "thread_id": thread_id,
                "token_info": {
                    "message_tokens": message_tokens,
                    "conversation_tokens": final_conversation_tokens,
                    "total_tokens": total_tokens,
                    "token_status": self._get_token_status(final_conversation_tokens)
                }
            }

        except Exception as e:
            logger.error(f"Error in chat: {str(e)}")
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

            return {
                "summary": state.values.get("summary", ""),
                "message_count": len(state.values.get("messages", [])),
                "conversation_tokens": conversation_tokens,
                "token_status": self._get_token_status(conversation_tokens),
                "status": "success"
            }
        except Exception as e:
            logger.error(f"Error getting conversation state: {str(e)}")
            return {"status": "error", "error": str(e)}

    def clear_conversation(self, thread_id: str = "default") -> Dict[str, Any]:
        """Clear a conversation thread"""
        try:
            # Note: MemorySaver doesn't have a direct clear method
            # This would need to be implemented based on your persistence needs
            return {"status": "success", "message": "Conversation cleared"}
        except Exception as e:
            logger.error(f"Error clearing conversation: {str(e)}")
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