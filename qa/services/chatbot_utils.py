"""
Utility functions for chatbot operations, primarily used by views.
These functions handle database operations, file management, and conversation persistence.
"""

import json
import logging
from typing import Dict, Any, List, Optional
from django.apps import apps
from langchain_core.messages import HumanMessage, RemoveMessage, AIMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from .token_management import TOKEN_LIMITS
from .file_service import FileAttachment

logger = logging.getLogger(__name__)


def chat(chatbot_instance, message: str, user_id: str = None, thread_id: str = "default",
         file_attachments: List[FileAttachment] = None) -> Dict[str, Any]:
    """
    Main chat interface with token tracking.
    This function is called by the view to process user messages.
    """
    try:
        # Check message length before processing
        message_tokens = chatbot_instance.token_counter.count_tokens(message)
        if message_tokens > TOKEN_LIMITS['MAX_SINGLE_MESSAGE_TOKENS']:
            return {
                "response": f"Your message is too long!. Please rewrite it for better response",
                "status": "error",
                "thread_id": thread_id,
                "token_info": {
                    "message_tokens": message_tokens,
                    "max_message_tokens": TOKEN_LIMITS['MAX_SINGLE_MESSAGE_TOKENS'],
                    "conversation_tokens": 0,
                    "token_status": chatbot_instance._get_token_status(0)
                }
            }

        # Conversation config
        config = {"configurable": {"thread_id": thread_id}}

        # Load current state
        try:
            current_state = chatbot_instance.graph.get_state(config)
            current_conversation_tokens = current_state.values.get("conversation_tokens", 0)
            existing_attachments = current_state.values.get("file_attachments", [])
            temp_attachment_ids = current_state.values.get("temp_attachment_ids", [])
            current_subject = current_state.values.get("current_subject")
            all_conversation_files = current_state.values.get("all_conversation_files", [])
            # NEW: Track full conversation history
            full_history = current_state.values.get("full_conversation_history", [])
        except:
            current_conversation_tokens = 0
            existing_attachments = []
            temp_attachment_ids = []
            current_subject = None
            all_conversation_files = []
            full_history = []

        # Too long conversation check
        if current_conversation_tokens > TOKEN_LIMITS['CRITICAL_TOKENS']:
            if file_attachments:
                cleanup_temp_attachments(file_attachments)

            return {
                "response": "This conversation has reached the maximum length. Please start a new chat to continue.",
                "status": "conversation_too_long",
                "thread_id": thread_id,
                "token_info": {
                    "message_tokens": message_tokens,
                    "conversation_tokens": current_conversation_tokens,
                    "token_status": chatbot_instance._get_token_status(current_conversation_tokens)
                }
            }

        # Only pass NEW attachments to the graph (not accumulated ones)
        new_attachments_for_graph = []
        new_attachment_ids = []
        if file_attachments:
            new_attachments_for_graph = [att.to_dict() for att in file_attachments]
            new_attachment_ids = [att.id for att in file_attachments]

        # Build structured HumanMessage with ONLY new attachments
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

        # Call graph with ONLY new attachments
        result = chatbot_instance.graph.invoke({
            "messages": [input_message],
            "user_id": user_id,
            "thread_id": thread_id,
            "conversation_tokens": current_conversation_tokens,
            "current_subject": current_subject,
            "file_attachments": new_attachments_for_graph,
            "all_conversation_files": all_conversation_files,
            "temp_attachment_ids": temp_attachment_ids + new_attachment_ids,
            "full_conversation_history": full_history  # Pass existing history
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
                "token_status": chatbot_instance._get_token_status(final_conversation_tokens)
            },
            "current_subject": result.get("current_subject"),
            "subject_change_detected": result.get("subject_change_detected", False),
            "suggested_new_subject": result.get("suggested_new_subject"),
            "attachments": attachment_info,
            "all_conversation_files": result.get("all_conversation_files", all_conversation_files)
        }

    except Exception as e:
        logger.error(f"Error in chat: {str(e)}")

        if file_attachments:
            cleanup_temp_attachments(file_attachments)

        return {
            "response": "I apologize, but I encountered an error. Please try again.",
            "status": "error",
            "error": str(e),
            "thread_id": thread_id,
            "token_info": {
                "message_tokens": chatbot_instance.token_counter.count_tokens(message) if message else 0,
                "conversation_tokens": 0,
                "token_status": chatbot_instance._get_token_status(0)
            }
        }


def save_conversation(chatbot_instance, thread_id: str, user_id: str = None) -> Dict[str, Any]:
    """
    Manually save a conversation with all attachments to the database.

    This function retrieves:
    1. full_conversation_history - Lightweight Q&A pairs stored separately (NEVER passed to AI)
    2. Current messages - Recent unsummarized messages still in state
    3. Summary - Condensed version of older messages (for context only)

    The full_conversation_history does NOT increase token usage during conversation
    because it's stored as simple strings and only used when saving to database.

    This preserves attachments by uploading them to S3.
    Called by views when user wants to save a conversation.
    """
    try:
        # Load conversation state
        config = {"configurable": {"thread_id": thread_id}}
        state = chatbot_instance.graph.get_state(config)

        if not state:
            return {"status": "error", "message": "No conversation found for this thread."}

        # Get full conversation history (includes all Q&A pairs)
        full_history = state.values.get("full_conversation_history", [])

        logger.info("=" * 80)
        logger.info(f"SAVE CONVERSATION - Thread ID: {thread_id}")
        logger.info("=" * 80)

        # Log current state messages
        current_messages = state.values.get("messages", [])
        logger.info(f"\n📨 Current State Messages (after summarization): {len(current_messages)}")
        for i, msg in enumerate(current_messages):
            msg_type = "USER" if isinstance(msg, HumanMessage) else "AI"
            content_preview = str(msg.content)[:200] if hasattr(msg, 'content') else str(msg)[:200]
            logger.info(f"  [{i}] {msg_type}: {content_preview}...")

        # Log full history
        logger.info(f"\n📚 Full Conversation History: {len(full_history)} entries")
        for i, entry in enumerate(full_history):
            logger.info(f"  [{i}] USER: {entry.get('user_message', '')[:100]}...")
            logger.info(f"       AI: {entry.get('ai_response', '')[:100]}...")

        # Log summary
        summary = state.values.get("summary", "")
        logger.info(f"\n📋 Summary exists: {bool(summary)}")
        if summary:
            logger.info(f"   Summary preview: {summary[:200]}...")

        # Check if we have any conversation data
        if not full_history and not current_messages:
            return {"status": "error", "message": "No conversation found for this thread."}

        # Collect all user questions and AI responses
        user_messages = []
        ai_messages = []

        # Add summary context if exists
        if summary:
            user_messages.append(f"Previous conversation context: {summary}")

        # Add from full history (most important - these are NEVER lost)
        for entry in full_history:
            user_msg = entry.get("user_message", "")
            ai_msg = entry.get("ai_response", "")
            if user_msg:
                user_messages.append(user_msg)
            if ai_msg:
                ai_messages.append(ai_msg)

        # Add any remaining messages from current state (recent unsummarized messages)
        for msg in current_messages:
            if hasattr(msg, 'content'):
                content = str(msg.content)
                if isinstance(msg, HumanMessage):
                    user_messages.append(content)
                else:  # AI message
                    ai_messages.append(content)

        logger.info(f"\n📊 Collection Summary:")
        logger.info(f"   Total user messages: {len(user_messages)}")
        logger.info(f"   Total AI responses: {len(ai_messages)}")

        # Add attachment information
        attachments = state.values.get("all_conversation_files", [])
        if attachments:
            attachment_filenames = [att.get('filename') for att in attachments]
            user_messages.append(f"Files attached: {', '.join(attachment_filenames)}")
            logger.info(f"   Attachments: {len(attachments)} files")

        # Combine user questions into question body
        question_body = "\n\n".join(user_messages)

        # Combine AI responses for answer summarization
        ai_responses_text = "\n\n".join(ai_messages)

        logger.info(f"\n📝 Final Content Length:")
        logger.info(f"   Question body: {len(question_body)} chars")
        logger.info(f"   AI responses: {len(ai_responses_text)} chars")

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
- Keep both sections informative but concise
- If the user using any language, then generate the same it (eg: user use Vietnamese then using it to generate using Vietnamese as well)
"""

        logger.info(f"\n🤖 Sending to model for analysis...")
        analysis_response = chatbot_instance.model.invoke([HumanMessage(content=analysis_prompt)])
        logger.info(f"   Model response received: {len(analysis_response.content)} chars")

        # Attach user_id into state for saving
        state.values["user_id"] = user_id
        state.values["thread_id"] = thread_id

        # Save to DB and get question ID
        question_id = save_conversation_summary(chatbot_instance, state.values, analysis_response.content)
        logger.info(f"\n💾 Saved to database - Question ID: {question_id}")

        # Save attachments to S3 if question was created
        saved_attachments = []
        if question_id and attachments:
            saved_urls = save_attachments_to_s3(attachments, question_id)
            saved_attachments = [
                {"filename": att.get("filename"), "url": url}
                for att, url in zip(attachments, saved_urls) if url
            ]
            logger.info(f"   Saved {len(saved_attachments)} attachments to S3")
        else:
            # Clean up temp files if save failed
            cleanup_temp_attachments(attachments)
            logger.info(f"   Cleaned up {len(attachments)} temp attachments")

        # Clear conversation after successful save
        chatbot_instance.graph.update_state(config, {
            "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES)],
            "file_attachments": [],
            "temp_attachment_ids": [],
            "full_conversation_history": [],
            # ✅ FIX: Reset token counters after save
            "conversation_tokens": 0,
            "total_tokens": 0,
            # ✅ FIX: Reset other state
            "summary": "",
            "current_subject": None,
            "subject_change_detected": False,
            "suggested_new_subject": None
        })

        logger.info("=" * 80)
        logger.info("SAVE CONVERSATION COMPLETED")
        logger.info("=" * 80)

        return {
            "status": "success",
            "message": "Conversation saved successfully.",
            "question_id": question_id,
            "saved_attachments": saved_attachments
        }

    except Exception as e:
        logger.error(f"❌ Error saving conversation: {str(e)}", exc_info=True)
        return {"status": "error", "message": str(e)}


def cleanup_conversation(chatbot_instance, thread_id: str) -> Dict[str, Any]:
    """
    Delete full conversation: attachments + messages.
    Called by views when user wants to clear a conversation.
    """
    try:
        config = {"configurable": {"thread_id": thread_id}}
        state = chatbot_instance.graph.get_state(config)

        # Cleanup attachments if any
        if state:
            all_files = state.values.get("all_conversation_files", [])
            cleanup_temp_attachments(all_files)

        # Remove all messages + reset ALL state fields
        chatbot_instance.graph.update_state(config, {
            "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES)],
            "file_attachments": [],
            "temp_attachment_ids": [],
            "all_conversation_files": [],
            "full_conversation_history": [],
            # ✅ FIX: Reset token counters
            "conversation_tokens": 0,
            "total_tokens": 0,
            # ✅ FIX: Reset other conversation state
            "summary": "",
            "current_subject": None,
            "subject_change_detected": False,
            "suggested_new_subject": None
        })

        return {"status": "success", "message": "Conversation fully cleared"}

    except Exception as e:
        logger.error(f"Error cleaning up conversation: {str(e)}")
        return {"status": "error", "error": str(e)}


def create_file_attachment(file_data: bytes, filename: str, content_type: str) -> FileAttachment:
    """
    Create a new file attachment with immediate S3 temp upload.
    Called by views when processing file uploads.
    """
    return FileAttachment(file_data, filename, content_type)


def save_attachments_to_s3(attachments: List[dict], question_id: str) -> List[str]:
    """
    Move attachments from temp to permanent S3 storage.
    Internal utility function called during conversation save.
    """
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
        logger.error(f"Error in save_attachments_to_s3: {str(e)}")

    return saved_urls


def cleanup_temp_attachments(attachments: List[dict]):
    """
    Clean up temporary files from S3.
    Called when conversation is cleared or when error occurs.
    """
    for att_data in attachments:
        try:
            # Reconstruct FileAttachment from dict
            attachment = FileAttachment.from_dict(att_data)
            attachment.cleanup_temp()
        except Exception as e:
            logger.error(f"Error cleaning up temp file {att_data.get('filename')}: {str(e)}")


def save_conversation_summary(chatbot_instance, state: Dict[str, Any], summary_content: str) -> Optional[str]:
    """
    Save the conversation summary to database and return question ID.
    Internal utility function called during conversation save.
    """
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
        cleaned_content = cleaned_content.replace('\\(', '(')
        cleaned_content = cleaned_content.replace('\\)', ')')
        cleaned_content = cleaned_content.replace('\\vec{', 'vec(')
        cleaned_content = cleaned_content.replace('\\overline{', 'overline(')
        cleaned_content = cleaned_content.replace('\\', '')

        logger.info(f"Cleaned content for JSON parsing:\n{cleaned_content}")

        # Try to parse JSON
        try:
            summary_data = json.loads(cleaned_content)
        except json.JSONDecodeError as first_error:
            # If JSON parsing still fails, try to extract data manually
            logger.warning(f"JSON parsing failed: {first_error}. Attempting manual extraction.")

            import re
            subject_match = re.search(r'"subject":\s*"([^"]+)"', cleaned_content)
            title_match = re.search(r'"title":\s*"([^"]+)"', cleaned_content)
            question_body_match = re.search(r'"question_body":\s*"([^"]+)"', cleaned_content, re.DOTALL)
            answer_summary_match = re.search(r'"answer_summary":\s*"([^"]+)"', cleaned_content, re.DOTALL)

            summary_data = {
                'subject': subject_match.group(1) if subject_match else 'General',
                'title': title_match.group(1) if title_match else 'Chatbot Conversation',
                'question_body': question_body_match.group(1) if question_body_match else 'User questions unavailable',
                'answer_summary': answer_summary_match.group(1) if answer_summary_match else 'AI responses unavailable'
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
            # Create Question
            question = Question.objects.create(
                user=user,
                subject=subject,
                title=summary_data.get('title', 'Chatbot Conversation')[:255],
                body=summary_data.get('question_body', '')[:5000],
                is_public=False
            )
            logger.info(f"Question saved: {question}")

            # Create Answer
            Answer.objects.create(
                question=question,
                content=summary_data.get('answer_summary', ''),
                is_ai_generated=True
            )
            logger.info(f"Answer saved for user {user.id} under subject {subject.name}")

            # Generate embedding asynchronously using Celery
            try:
                from ..tasks import generate_question_embedding
                generate_question_embedding.delay(str(question.id))
                logger.info(f"Queued embedding generation for question {question.id}")
            except Exception as e:
                logger.error(f"Failed to queue embedding generation for question {question.id}: {str(e)}")

            return str(question.id)

    except Exception as e:
        logger.error(f"Error saving conversation summary: {str(e)}")

    return None