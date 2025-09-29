# qa/tasks.py
from datetime import timedelta

import boto3
from celery import shared_task
import openai
import logging
from django.conf import settings
from .models import Question
from django.utils import timezone
from botocore.exceptions import ClientError
from django.apps import apps
from datetime import timezone as dt_timezone

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def generate_question_embedding(self, question_id):
    """
    Celery task to generate embedding for a question
    This runs asynchronously to avoid blocking the API response
    """
    try:
        question = Question.objects.get(id=question_id)

        # Skip if embedding already exists
        if question.embedding:
            logger.info(f"Question {question_id} already has embedding")
            return f"Question {question_id} already has embedding"

        # Create embedding text from title and body
        embedding_text = f"{question.title} {question.body}".strip()

        if not embedding_text:
            logger.error(f"No text to embed for question {question_id}")
            return f"No text to embed for question {question_id}"

        # Generate embedding using OpenAI
        client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
        embedding_model = getattr(settings, 'EMBEDDING_MODEL', 'text-embedding-ada-002')

        response = client.embeddings.create(
            input=embedding_text,
            model=embedding_model
        )

        embedding = response.data[0].embedding

        # Save embedding to database
        question.embedding = embedding
        question.save(update_fields=['embedding'])

        logger.info(f"Successfully generated embedding for question {question_id}")
        return f"Successfully generated embedding for question {question_id}"

    except Question.DoesNotExist:
        logger.error(f"Question {question_id} not found")
        raise Exception(f"Question {question_id} not found")

    except Exception as e:
        logger.error(f"Error generating embedding for question {question_id}: {e}")

        # Retry the task if we haven't exceeded max_retries
        try:
            raise self.retry(exc=e)
        except self.MaxRetriesExceededError:
            logger.error(f"Max retries exceeded for question {question_id}")
            raise Exception(f"Failed to generate embedding after {self.max_retries} retries: {str(e)}")


def get_s3_client():
    """Get configured S3 client"""
    try:
        return boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION_NAME
        )
    except Exception as e:
        logger.error(f"Failed to create S3 client: {str(e)}")
        return None


@shared_task
def cleanup_orphaned_temp_files():
    """
    Clean up temporary files in S3 that are older than 2 hours.
    These are files from conversations that were never saved or discarded properly.
    """
    try:
        s3_client = get_s3_client()
        if not s3_client:
            return {"status": "error", "message": "Failed to connect to S3"}

        bucket_name = settings.AWS_STORAGE_BUCKET_NAME
        temp_prefix = "temp_attachments/"
        cutoff_time = timezone.now() - timedelta(hours=2)

        cleaned_count = 0
        total_size = 0

        # List objects with temp prefix
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=bucket_name, Prefix=temp_prefix)

        for page in pages:
            if 'Contents' not in page:
                continue

            for obj in page['Contents']:
                # Check if file is older than cutoff
                if obj['LastModified'].astimezone(dt_timezone.utc) < cutoff_time:
                    try:
                        # Delete the object
                        s3_client.delete_object(Bucket=bucket_name, Key=obj['Key'])
                        cleaned_count += 1
                        total_size += obj['Size']

                        logger.info(f"Cleaned up temp file: {obj['Key']} ({obj['Size']} bytes)")

                    except ClientError as e:
                        logger.error(f"Failed to delete temp file {obj['Key']}: {str(e)}")

        logger.info(f"Cleanup completed: {cleaned_count} files, {total_size} bytes freed")

        return {
            "status": "success",
            "files_cleaned": cleaned_count,
            "bytes_freed": total_size,
            "message": f"Cleaned up {cleaned_count} orphaned temp files"
        }

    except Exception as e:
        logger.error(f"Error in cleanup_orphaned_temp_files: {str(e)}")
        return {"status": "error", "message": str(e)}


@shared_task
def cleanup_temp_files_by_age(hours_old: int = 2):
    """
    Clean up temp files older than specified hours.
    This is a more flexible version of cleanup_orphaned_temp_files.
    """
    try:
        s3_client = get_s3_client()
        if not s3_client:
            return {"status": "error", "message": "Failed to connect to S3"}

        bucket_name = settings.AWS_STORAGE_BUCKET_NAME
        temp_prefix = "temp_attachments/"
        cutoff_time = timezone.now() - timedelta(hours=hours_old)

        cleaned_count = 0
        total_size = 0

        # List and delete old temp files
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=bucket_name, Prefix=temp_prefix)

        # Collect keys to delete (S3 allows batch deletion)
        delete_keys = []

        for page in pages:
            if 'Contents' not in page:
                continue

            for obj in page['Contents']:
                if obj['LastModified'].replace(tzinfo=timezone.utc) < cutoff_time:
                    delete_keys.append({'Key': obj['Key']})
                    total_size += obj['Size']

                    # Batch delete when we have 1000 keys (S3 limit)
                    if len(delete_keys) >= 1000:
                        _batch_delete_s3_objects(s3_client, bucket_name, delete_keys)
                        cleaned_count += len(delete_keys)
                        delete_keys = []

        # Delete remaining keys
        if delete_keys:
            _batch_delete_s3_objects(s3_client, bucket_name, delete_keys)
            cleaned_count += len(delete_keys)

        logger.info(f"Batch cleanup completed: {cleaned_count} files, {total_size} bytes freed")

        return {
            "status": "success",
            "files_cleaned": cleaned_count,
            "bytes_freed": total_size,
            "hours_threshold": hours_old
        }

    except Exception as e:
        logger.error(f"Error in cleanup_temp_files_by_age: {str(e)}")
        return {"status": "error", "message": str(e)}


def _batch_delete_s3_objects(s3_client, bucket_name: str, delete_keys: list):
    """Helper function to batch delete S3 objects"""
    try:
        if not delete_keys:
            return

        response = s3_client.delete_objects(
            Bucket=bucket_name,
            Delete={'Objects': delete_keys}
        )

        # Log any errors from the batch delete
        if 'Errors' in response:
            for error in response['Errors']:
                logger.error(f"Failed to delete {error['Key']}: {error['Message']}")

        # Log successful deletions
        if 'Deleted' in response:
            for deleted in response['Deleted']:
                logger.debug(f"Successfully deleted: {deleted['Key']}")

    except ClientError as e:
        logger.error(f"Batch delete failed: {str(e)}")


@shared_task
def cleanup_temp_files_by_thread_ids(thread_ids: list):
    """
    Clean up temp files for specific thread IDs.
    Useful when you know which conversations to clean up.
    """
    try:
        s3_client = get_s3_client()
        if not s3_client:
            return {"status": "error", "message": "Failed to connect to S3"}

        bucket_name = settings.AWS_STORAGE_BUCKET_NAME
        cleaned_count = 0
        total_size = 0

        for thread_id in thread_ids:
            # List objects for this thread (temp files contain timestamps, so we need to search)
            paginator = s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=bucket_name, Prefix="temp_attachments/")

            for page in pages:
                if 'Contents' not in page:
                    continue

                for obj in page['Contents']:
                    # Check if this temp file belongs to one of our thread IDs
                    # This is a simple contains check - you might want more sophisticated matching
                    if any(tid in obj['Key'] for tid in thread_ids):
                        try:
                            s3_client.delete_object(Bucket=bucket_name, Key=obj['Key'])
                            cleaned_count += 1
                            total_size += obj['Size']
                            logger.info(f"Cleaned up thread temp file: {obj['Key']}")
                        except ClientError as e:
                            logger.error(f"Failed to delete thread temp file {obj['Key']}: {str(e)}")

        return {
            "status": "success",
            "files_cleaned": cleaned_count,
            "bytes_freed": total_size,
            "thread_ids_processed": len(thread_ids)
        }

    except Exception as e:
        logger.error(f"Error in cleanup_temp_files_by_thread_ids: {str(e)}")
        return {"status": "error", "message": str(e)}


@shared_task
def monitor_s3_storage_usage():
    """
    Monitor S3 storage usage and send alerts if needed.
    This helps track costs and storage growth.
    """
    try:
        s3_client = get_s3_client()
        if not s3_client:
            return {"status": "error", "message": "Failed to connect to S3"}

        bucket_name = settings.AWS_STORAGE_BUCKET_NAME

        # Count objects and sizes by prefix
        storage_stats = {
            "temp_attachments": {"count": 0, "size": 0},
            "question_attachments": {"count": 0, "size": 0},
            "total": {"count": 0, "size": 0}
        }

        # Get all objects in bucket
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=bucket_name)

        for page in pages:
            if 'Contents' not in page:
                continue

            for obj in page['Contents']:
                size = obj['Size']
                storage_stats["total"]["count"] += 1
                storage_stats["total"]["size"] += size

                if obj['Key'].startswith('temp_attachments/'):
                    storage_stats["temp_attachments"]["count"] += 1
                    storage_stats["temp_attachments"]["size"] += size
                elif obj['Key'].startswith('question_attachments/'):
                    storage_stats["question_attachments"]["count"] += 1
                    storage_stats["question_attachments"]["size"] += size

        # Convert bytes to MB for readability
        for category in storage_stats:
            storage_stats[category]["size_mb"] = round(storage_stats[category]["size"] / 1024 / 1024, 2)

        # Check for concerning patterns
        alerts = []

        # Alert if temp files are taking too much space
        temp_size_mb = storage_stats["temp_attachments"]["size_mb"]
        if temp_size_mb > 1000:  # More than 1GB of temp files
            alerts.append(f"High temp storage usage: {temp_size_mb}MB")

        # Alert if temp file count is high
        temp_count = storage_stats["temp_attachments"]["count"]
        if temp_count > 10000:  # More than 10k temp files
            alerts.append(f"High temp file count: {temp_count} files")

        logger.info(f"S3 Storage Stats: {storage_stats}")
        if alerts:
            logger.warning(f"S3 Storage Alerts: {'; '.join(alerts)}")

        return {
            "status": "success",
            "storage_stats": storage_stats,
            "alerts": alerts
        }

    except Exception as e:
        logger.error(f"Error in monitor_s3_storage_usage: {str(e)}")
        return {"status": "error", "message": str(e)}


@shared_task
def validate_permanent_attachments():
    """
    Validate that all permanent attachments in database still exist in S3.
    This helps catch issues with file deletions or corruption.
    """
    try:
        s3_client = get_s3_client()
        if not s3_client:
            return {"status": "error", "message": "Failed to connect to S3"}

        QuestionFileAttachment = apps.get_model('qa', 'QuestionFileAttachment')
        bucket_name = settings.AWS_STORAGE_BUCKET_NAME

        # Get all permanent attachments from database
        attachments = QuestionFileAttachment.objects.all()

        missing_files = []
        valid_files = 0

        for attachment in attachments:
            s3_key = str(attachment.file)  # This should be the S3 key

            try:
                # Check if file exists in S3
                s3_client.head_object(Bucket=bucket_name, Key=s3_key)
                valid_files += 1
            except ClientError as e:
                if e.response['Error']['Code'] == '404':
                    missing_files.append({
                        'attachment_id': str(attachment.id),
                        'question_id': str(attachment.question.id),
                        's3_key': s3_key,
                        'created_at': attachment.created_at.isoformat()
                    })
                else:
                    logger.error(f"Error checking file {s3_key}: {str(e)}")

        if missing_files:
            logger.warning(f"Found {len(missing_files)} missing permanent files")

            # Optionally clean up database records for missing files
            # Be careful with this in production
            # for missing in missing_files:
            #     QuestionFileAttachment.objects.filter(id=missing['attachment_id']).delete()

        return {
            "status": "success",
            "total_attachments": len(attachments),
            "valid_files": valid_files,
            "missing_files": len(missing_files),
            "missing_file_details": missing_files
        }

    except Exception as e:
        logger.error(f"Error in validate_permanent_attachments: {str(e)}")
        return {"status": "error", "message": str(e)}


@shared_task
def emergency_cleanup_all_temp_files():
    """
    Emergency cleanup of ALL temp files regardless of age.
    Use this carefully in case of storage emergencies.
    """
    try:
        s3_client = get_s3_client()
        if not s3_client:
            return {"status": "error", "message": "Failed to connect to S3"}

        bucket_name = settings.AWS_STORAGE_BUCKET_NAME
        temp_prefix = "temp_attachments/"

        cleaned_count = 0
        total_size = 0

        logger.warning("EMERGENCY CLEANUP: Deleting ALL temp files")

        # List all temp objects
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=bucket_name, Prefix=temp_prefix)

        delete_keys = []

        for page in pages:
            if 'Contents' not in page:
                continue

            for obj in page['Contents']:
                delete_keys.append({'Key': obj['Key']})
                total_size += obj['Size']

                # Batch delete when we have 1000 keys
                if len(delete_keys) >= 1000:
                    _batch_delete_s3_objects(s3_client, bucket_name, delete_keys)
                    cleaned_count += len(delete_keys)
                    delete_keys = []

        # Delete remaining keys
        if delete_keys:
            _batch_delete_s3_objects(s3_client, bucket_name, delete_keys)
            cleaned_count += len(delete_keys)

        logger.warning(f"EMERGENCY CLEANUP completed: {cleaned_count} files, {total_size} bytes freed")

        return {
            "status": "success",
            "files_cleaned": cleaned_count,
            "bytes_freed": total_size,
            "message": "Emergency cleanup completed - ALL temp files deleted"
        }

    except Exception as e:
        logger.error(f"Error in emergency_cleanup_all_temp_files: {str(e)}")
        return {"status": "error", "message": str(e)}


# Celery beat schedule - add this to your Django settings.py
"""
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    # Clean up temp files older than 2 hours, every hour
    'cleanup-orphaned-temp-files': {
        'task': 'your_app.tasks.cleanup_orphaned_temp_files',
        'schedule': crontab(minute=0),  # Every hour at minute 0
    },

    # Monitor storage usage daily at 2 AM
    'monitor-s3-storage': {
        'task': 'your_app.tasks.monitor_s3_storage_usage',
        'schedule': crontab(hour=2, minute=0),  # Daily at 2 AM
    },

    # Validate permanent attachments weekly
    'validate-permanent-attachments': {
        'task': 'your_app.tasks.validate_permanent_attachments',
        'schedule': crontab(hour=3, minute=0, day_of_week=0),  # Weekly on Sunday at 3 AM
    },

    # More aggressive cleanup during peak hours (optional)
    'aggressive-temp-cleanup': {
        'task': 'your_app.tasks.cleanup_temp_files_by_age',
        'schedule': crontab(minute='*/30', hour='9-17'),  # Every 30 min during business hours
        'kwargs': {'hours_old': 1}  # Clean files older than 1 hour during peak
    },
}

CELERY_TIMEZONE = 'UTC'
"""