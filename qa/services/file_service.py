import os
import uuid
import logging
import tempfile

from PIL import Image
from datetime import datetime
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

# Configure logging
logger = logging.getLogger(__name__)


class FileAttachment:
    """File attachment with S3 temporary storage"""

    def __init__(self, file_data: bytes, filename: str, content_type: str):
        self.id = str(uuid.uuid4())
        self.filename = filename
        self.content_type = content_type
        self.size = len(file_data)

        # Generate S3 keys
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.temp_s3_key = f"temp_attachments/{timestamp}_{self.id}/{filename}"
        self.permanent_s3_key = None
        self.description = None

        # Upload to S3 immediately to free up memory
        self._upload_to_temp_s3(file_data)

        # Clear file data from memory after S3 upload
        self.file_data = None

    def _upload_to_temp_s3(self, file_data: bytes):
        """Upload file to temporary S3 location"""
        try:
            # Create ContentFile from bytes
            file_content = ContentFile(file_data, name=self.filename)

            # Upload to S3 temp location
            self.temp_s3_path = default_storage.save(self.temp_s3_key, file_content)

            logger.info(f"Uploaded temp file to S3: {self.temp_s3_key} ({self.size} bytes)")

        except Exception as e:
            logger.error(f"Failed to upload temp file to S3: {str(e)}")
            raise Exception(f"Failed to store file {self.filename}: {str(e)}")

    def get_file_data(self) -> bytes:
        """Retrieve file data from S3 when needed"""
        try:
            if default_storage.exists(self.temp_s3_key):
                with default_storage.open(self.temp_s3_key, 'rb') as f:
                    return f.read()
            else:
                raise FileNotFoundError(f"Temp file not found: {self.temp_s3_key}")
        except Exception as e:
            logger.error(f"Failed to retrieve temp file from S3: {str(e)}")
            return b""

    def save_temporarily(self) -> str:
        """Download from S3 to local temp file for processing"""
        try:
            file_data = self.get_file_data()
            if not file_data:
                return None

            suffix = os.path.splitext(self.filename)[1]
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                temp_file.write(file_data)
                return temp_file.name

        except Exception as e:
            logger.error(f"Failed to create local temp file: {str(e)}")
            return None

    def move_to_permanent(self, question_id: str) -> str:
        """Move from temp to permanent S3 location"""
        try:
            # Generate permanent S3 key
            self.permanent_s3_key = f"question_attachments/{question_id}/{self.id}_{self.filename}"

            # Copy file from temp to permanent location
            if default_storage.exists(self.temp_s3_key):
                # Read from temp location
                with default_storage.open(self.temp_s3_key, 'rb') as temp_file:
                    file_content = ContentFile(temp_file.read(), name=self.filename)

                # Save to permanent location
                permanent_path = default_storage.save(self.permanent_s3_key, file_content)

                # Get permanent URL
                permanent_url = default_storage.url(permanent_path)

                logger.info(f"Moved file to permanent S3: {self.permanent_s3_key}")
                return permanent_url
            else:
                raise FileNotFoundError(f"Temp file not found: {self.temp_s3_key}")

        except Exception as e:
            logger.error(f"Failed to move file to permanent storage: {str(e)}")
            return None

    def cleanup_temp(self):
        """Remove temporary file from S3"""
        try:
            if default_storage.exists(self.temp_s3_key):
                default_storage.delete(self.temp_s3_key)
                logger.info(f"Cleaned up temp file: {self.temp_s3_key}")
        except Exception as e:
            logger.error(f"Failed to cleanup temp file: {str(e)}")

    def cleanup_local_temp(self, temp_path: str):
        """Clean up local temporary file"""
        try:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
        except Exception as e:
            logger.error(f"Failed to cleanup local temp file: {str(e)}")

    def is_image(self) -> bool:
        return self.content_type.startswith('image/')

    def is_document(self) -> bool:
        """Check if file is a supported document type"""
        return self.content_type in [
            'application/pdf',
            'application/msword',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # DOCX
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',  # XLSX
            'application/vnd.ms-excel',  # XLS
            'text/plain',
            'text/csv'
        ]

    def is_pdf(self) -> bool:
        """Check if file is a PDF"""
        return self.content_type == 'application/pdf'

    def is_excel(self) -> bool:
        """Check if file is an Excel file"""
        return self.content_type in [
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',  # XLSX
            'application/vnd.ms-excel'  # XLS
        ]

    def is_word(self) -> bool:
        """Check if file is a Word document"""
        return self.content_type in [
            'application/msword',  # DOC
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document'  # DOCX
        ]

    def get_file_extension(self) -> str:
        """Get file extension from filename"""
        return os.path.splitext(self.filename)[1].lower()

    def get_display_type(self) -> str:
        """Get human-readable file type"""
        if self.is_image():
            return "Image"
        elif self.is_pdf():
            return "PDF Document"
        elif self.is_word():
            return "Word Document"
        elif self.is_excel():
            return "Excel Spreadsheet"
        elif self.content_type == 'text/csv':
            return "CSV File"
        elif self.content_type == 'text/plain':
            return "Text File"
        else:
            return "Document"

    def get_s3_url(self) -> str:
        """Generate S3 URL for file attachment"""
        s3_key = self.permanent_s3_key or self.temp_s3_key

        if s3_key:
            try:
                # Generate full S3 URL with region
                from django.conf import settings
                aws_region = getattr(settings, 'AWS_S3_REGION_NAME', 'ap-southeast-1')
                aws_bucket = getattr(settings, 'AWS_STORAGE_BUCKET_NAME', 'sln-mobile-app-project')

                return f"https://{aws_bucket}.s3.{aws_region}.amazonaws.com/{s3_key}"
            except Exception as e:
                logger.error(f"Error generating S3 URL: {str(e)}")

        return None

    def extract_document_content(self) -> str:
        """Extract text content from document files"""
        try:
            if self.content_type == 'text/plain':
                file_data = self.get_file_data()
                if file_data:
                    content = file_data.decode('utf-8', errors='ignore')
                    # Truncate if too long to avoid token limits
                    if len(content) > 5000:
                        content = content[:5000] + "... [content truncated due to length]"
                    return content

            elif self.content_type == 'text/csv':
                file_data = self.get_file_data()
                if file_data:
                    csv_content = file_data.decode('utf-8', errors='ignore')
                    lines = csv_content.splitlines()
                    # Show first 50 lines for CSV
                    if len(lines) > 50:
                        content = "\n".join(lines[:50]) + f"\n... [showing first 50 of {len(lines)} rows]"
                    else:
                        content = csv_content
                    return content

            elif self.content_type == 'application/pdf':
                return self._extract_pdf_content()

            elif self.content_type in ['application/vnd.openxmlformats-officedocument.wordprocessingml.document']:
                return self._extract_docx_content()

            elif self.content_type in [
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'application/vnd.ms-excel'
            ]:
                return self._extract_excel_content()

            else:
                return f"Document type {self.content_type} is not supported for content extraction."

        except Exception as e:
            logger.error(f"Error extracting document content: {str(e)}")
            return f"Error processing document: {str(e)}"

    def _extract_pdf_content(self) -> str:
        """Extract text content from PDF files"""
        try:
            import PyPDF2
            from io import BytesIO

            file_data = self.get_file_data()
            if not file_data:
                return "Could not retrieve PDF file data"

            pdf_reader = PyPDF2.PdfReader(BytesIO(file_data))
            text_content = []

            # Extract text from first 5 pages to avoid token limits
            max_pages = min(5, len(pdf_reader.pages))
            for page_num in range(max_pages):
                page = pdf_reader.pages[page_num]
                text_content.append(page.extract_text())

            content = "\n".join(text_content)
            if len(pdf_reader.pages) > max_pages:
                content += f"\n... [showing first {max_pages} of {len(pdf_reader.pages)} pages]"

            # Truncate if still too long
            if len(content) > 5000:
                content = content[:5000] + "... [content truncated due to length]"

            return content

        except ImportError:
            return "PDF processing requires PyPDF2. Please install it: pip install PyPDF2"
        except Exception as e:
            logger.error(f"Error extracting PDF content: {str(e)}")
            return f"Error processing PDF: {str(e)}"

    def _extract_docx_content(self) -> str:
        """Extract text content from DOCX files"""
        try:
            import docx
            from io import BytesIO

            file_data = self.get_file_data()
            if not file_data:
                return "Could not retrieve DOCX file data"

            doc = docx.Document(BytesIO(file_data))
            text_content = []

            for paragraph in doc.paragraphs:
                if paragraph.text.strip():
                    text_content.append(paragraph.text)

            content = "\n".join(text_content)

            # Truncate if too long
            if len(content) > 5000:
                content = content[:5000] + "... [content truncated due to length]"

            return content

        except ImportError:
            return "DOCX processing requires python-docx. Please install it: pip install python-docx"
        except Exception as e:
            logger.error(f"Error extracting DOCX content: {str(e)}")
            return f"Error processing DOCX: {str(e)}"

    def _extract_excel_content(self) -> str:
        """Extract content from Excel files"""
        try:
            import pandas as pd
            from io import BytesIO

            file_data = self.get_file_data()
            if not file_data:
                return "Could not retrieve Excel file data"

            # Read Excel file
            if self.content_type == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
                df = pd.read_excel(BytesIO(file_data), engine='openpyxl')
            else:
                df = pd.read_excel(BytesIO(file_data))

            # Convert to string representation, showing first 20 rows
            if len(df) > 20:
                content = df.head(20).to_string(index=False)
                content += f"\n... [showing first 20 of {len(df)} rows, {len(df.columns)} columns]"
            else:
                content = df.to_string(index=False)

            return content

        except ImportError:
            return "Excel processing requires pandas and openpyxl. Please install them: pip install pandas openpyxl"
        except Exception as e:
            logger.error(f"Error extracting Excel content: {str(e)}")
            return f"Error processing Excel file: {str(e)}"

    def to_dict(self):
        """Return a serializable representation for storing in ChatbotState"""
        return {
            "id": self.id,
            "filename": self.filename,
            "content_type": self.content_type,
            "size": self.size,
            "temp_s3_key": self.temp_s3_key,
            "permanent_s3_key": self.permanent_s3_key,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict):
        """Recreate FileAttachment from serialized dict (without file_data)"""
        obj = cls.__new__(cls)  # bypass __init__
        obj.id = data["id"]
        obj.filename = data["filename"]
        obj.content_type = data["content_type"]
        obj.size = data["size"]
        obj.temp_s3_key = data.get("temp_s3_key")
        obj.permanent_s3_key = data.get("permanent_s3_key")
        obj.description = data.get("description")
        obj.file_data = None
        return obj


class FileProcessor:
    """Handles file processing for different types with S3 storage"""

    @staticmethod
    def process_image(attachment: FileAttachment) -> str:
        """Process image stored in S3"""
        temp_path = None
        try:
            temp_path = attachment.save_temporarily()
            if not temp_path:
                return f"Image file '{attachment.filename}' (failed to download for processing)"

            with Image.open(temp_path) as img:
                width, height = img.size
                format_name = img.format
                mode = img.mode

                description = (
                    f"Image file '{attachment.filename}' "
                    f"({format_name}, {width}x{height}, {mode} mode, {attachment.size} bytes)"
                )
                attachment.description = description
                return description

        except Exception as e:
            logger.error(f"Error processing image {attachment.filename}: {str(e)}")
            return f"Image file '{attachment.filename}' (unable to process: {str(e)})"
        finally:
            if temp_path:
                attachment.cleanup_local_temp(temp_path)

    @staticmethod
    def process_document(attachment: FileAttachment) -> str:
        """Process documents and extract content"""
        try:
            # Use the new extract_document_content method
            content = attachment.extract_document_content()

            # Create a description that includes the content
            if content and not content.startswith("Error") and not content.startswith("Could not"):
                description = f"{attachment.get_display_type()} '{attachment.filename}' ({attachment.size} bytes):\n{content}"
            else:
                description = f"{attachment.get_display_type()} '{attachment.filename}' ({attachment.size} bytes) - {content}"

            attachment.description = description
            return description

        except Exception as e:
            logger.error(f"Error processing document {attachment.filename}: {str(e)}")
            return f"Document file '{attachment.filename}' (unable to process: {str(e)})"