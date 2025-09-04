import base64
import hashlib
import json, uuid, os, logging
from pathlib import Path
import httpx
from crewai_tools import BaseTool
import tempfile
import requests
from cassandra.cluster import Cluster
from cassandra.auth import PlainTextAuthProvider
from datetime import datetime
from decimal import Decimal

# ----------------------------
# Logging setup
# ----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger("InvoiceProcessor")


class AstraDBConnectionHelper:
    @staticmethod
    def get_config():
        database_id = os.getenv('ASTRA_DB_DATABASE_ID')
        token = os.getenv('ASTRA_DB_APPLICATION_TOKEN')
        keyspace = os.getenv('ASTRA_DB_KEYSPACE', 'invoices')
        if not database_id or not token:
            logger.error("Astra DB config missing.")
            raise ValueError("Astra DB config missing. Please set ASTRA_DB_DATABASE_ID and ASTRA_DB_APPLICATION_TOKEN")
        logger.info(f"Astra DB config loaded. Keyspace={keyspace}")
        return database_id, token, keyspace

    @staticmethod
    def connect(database_id: str, token: str, keyspace: str):
        logger.info("Requesting Astra DB secure bundle...")
        bundle_url = f"https://api.astra.datastax.com/v2/databases/{database_id}/secureBundleURL"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        resp = requests.post(bundle_url, headers=headers)
        resp.raise_for_status()
        bundle_download_url = resp.json().get("downloadURL")
        if not bundle_download_url:
            logger.error("Failed to retrieve secure bundle download URL")
            raise RuntimeError("Failed to retrieve secure bundle download URL")

        logger.info("Downloading secure bundle...")
        bundle_data = requests.get(bundle_download_url).content
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as f:
            f.write(bundle_data)
            bundle_path = f.name

        logger.info("Connecting to Astra DB cluster...")
        auth_provider = PlainTextAuthProvider(username="token", password=token)
        cluster = Cluster(cloud={"secure_connect_bundle": bundle_path}, auth_provider=auth_provider)
        session = cluster.connect(keyspace)
        logger.info("Astra DB connection established.")
        return session, cluster, bundle_path


# ----------------------------
# Outlook Download Tool
# ----------------------------
class OutlookDownloadTool(BaseTool):
    name: str = "outlook_download"
    description: str = "Download Outlook attachment using messageId and attachmentId"

    def _run(self, message_id: str, attachment_id: str, attachment_name: str) -> str:
        try:
            logger.info(f"Downloading attachment: message_id={message_id}, attachment_id={attachment_id}, name={attachment_name}")
            api_url = f"{os.getenv('OUTLOOK_API_BASE_URL')}/download"
            api_key = os.getenv('OUTLOOK_API_KEY')
            headers = {"Content-Type": "application/json", "X-api-key": api_key}
            payload = {"message_id": message_id, "attachment_id": attachment_id}

            response = httpx.post(api_url, json=payload, headers=headers, timeout=60)
            response.raise_for_status()

            data = response.json()
            content_base64 = data.get("content_base64", "")
            filename = data.get("filename", f"{uuid.uuid4()}.bin")

            project_root = Path(__file__).resolve().parent.parent
            downloads_dir = project_root / "downloads"
            downloads_dir.mkdir(parents=True, exist_ok=True)
            file_path = downloads_dir / filename

            file_bytes = base64.b64decode(content_base64) if content_base64 else b""
            with open(file_path, "wb") as f:
                f.write(file_bytes)

            checksum = hashlib.sha256(file_bytes).hexdigest() if file_bytes else None
            logger.info(f"Attachment saved: {file_path}, size={len(file_bytes)} bytes")

            return json.dumps({
                "success": True,
                "filename": filename,
                "file_path": str(file_path),
                "checksum": checksum,
                "content_type": data.get("content_type", "unknown"),
                "size": data.get("size", len(file_bytes)),
                "message_id": message_id,
                "attachment_id": attachment_id,
                "attachment_name": attachment_name
            }, indent=2)

        except Exception as e:
            logger.error(f"Download failed: {e}")
            return json.dumps({"success": False, "error": f"Download failed: {str(e)}"})


# ----------------------------
# Outlook Search Tool
# ----------------------------
class OutlookSearchTool(BaseTool):
    name: str = "outlook_search"
    description: str = "Search Outlook emails from a specific sender and extract attachments"

    def _run(self, sender_email: str, subject_contains: str = "", days_back: int = 1) -> str:
        try:
            logger.info(f"Searching Outlook emails: sender={sender_email}, subject_contains={subject_contains}, days_back={days_back}")
            api_url = f"{os.getenv('OUTLOOK_API_BASE_URL')}/search"
            api_key = os.getenv('OUTLOOK_API_KEY')
            headers = {"Content-Type": "application/json", "X-api-key": api_key}

            payload = {"days_back": days_back, "has_attachments": True, "top": 10}
            if sender_email.strip():
                payload["sender_email"] = sender_email.strip()
            if subject_contains.strip():
                payload["subject_contains"] = subject_contains.strip()

            response = httpx.post(api_url, json=payload, headers=headers, timeout=30)
            if response.status_code != 200:
                logger.error(f"Search API request failed: {response.status_code}")
                return json.dumps({"success": False, "error": f"API request failed: {response.status_code}"})

            data = response.json()
            results = []
            for message in data.get("items", []):
                if message.get("hasAttachments"):
                    for attachment in message.get("attachments", []):
                        results.append({
                            "messageId": message["messageId"],
                            "attachmentId": attachment["attachmentId"],
                            "attachmentName": attachment["name"],
                            "attachmentSize": attachment.get("size", 0),
                            "contentType": attachment.get("contentType", ""),
                            "subject": message.get("subject", ""),
                            "from": message.get("from_", message.get("from", "")),
                            "receivedAt": message.get("receivedAt", "")
                        })

            logger.info(f"Search complete. Found {len(results)} attachments.")
            return json.dumps({"success": True, "attachments_found": len(results), "attachments": results}, indent=2)

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return json.dumps({"success": False, "error": f"Search failed: {str(e)}"})


# ----------------------------
# Data Extraction Tool
# ----------------------------
class DataExtractionTool(BaseTool):
    name: str = "data_extraction"
    description: str = "Extract meaningful data from downloaded attachments using file_path and return structured invoices"

    def _run(self, file_path: str, content_type: str = "application/octet-stream", **kwargs) -> str:
        try:
            file_path = Path(file_path)
            logger.info(f"Extracting data from file: {file_path}")
            if not file_path.exists():
                logger.error(f"File not found: {file_path}")
                return json.dumps({
                    "success": False,
                    "error": f"File not found: {file_path}",
                    "data": {"filename": file_path.name, "file_path": str(file_path), "invoices": []}
                })

            results = {
                "filename": file_path.name,
                "file_path": str(file_path),
                "content_type": content_type,
                "extracted_text": "",
                "invoices": []
            }

            # Step 1: Extract text
            if content_type == "application/pdf" or file_path.suffix.lower() == ".pdf":
                from PyPDF2 import PdfReader
                reader = PdfReader(str(file_path))
                text_content = "\n".join([page.extract_text() or "" for page in reader.pages])
            elif content_type.startswith("text/") or file_path.suffix.lower() in [".txt", ".log"]:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    text_content = f.read()
            elif content_type == "application/json" or file_path.suffix.lower() == ".json":
                import json as pyjson
                with open(file_path, "r", encoding="utf-8") as f:
                    text_content = pyjson.dumps(pyjson.load(f))
            else:
                text_content = ""

            results["extracted_text"] = text_content
            logger.info(f"Extracted {len(text_content)} characters of text.")

            # Step 2: AI extraction
            if text_content.strip():
                invoices = self._extract_invoice_fields(text_content)
                results["invoices"] = invoices
                logger.info(f"Extracted {len(invoices)} invoices.")

            return json.dumps({"success": True, "data": results}, indent=2, default=str)

        except Exception as e:
            logger.error(f"Extraction failed: {e}")
            return json.dumps({
                "success": False,
                "error": f"Extraction failed: {str(e)}",
                "data": {"filename": str(file_path), "file_path": str(file_path), "invoices": []}
            })

    @staticmethod
    def _extract_invoice_fields(text_content: str) -> list:
        """Extract structured invoice fields from text using AI. Can handle multiple invoices (up to 2)."""
        try:
            from openai import OpenAI

            client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

            prompt = f"""
            Analyze the following text and extract structured invoice data. The text may contain 1 or 2 invoices maximum.

            Return a JSON array where each element represents one invoice with these fields:
            - invoice_number: string
            - vendor_name: string
            - vendor_address: string
            - invoice_date: string (YYYY-MM-DD format)
            - due_date: string (YYYY-MM-DD format)
            - total_amount: number
            - currency: string (e.g., USD, EUR)
            - tax_amount: number
            - subtotal_amount: number
            - line_items: array of objects with description, quantity, unit_price, total
            - payment_terms: string
            - purchase_order_number: string
            - bill_to_name: string
            - bill_to_address: string
            - ship_to_name: string
            - ship_to_address: string
            - notes: string
            - invoice_sequence: number (1 for first invoice, 2 for second if present)

            If a field is not found, use null. Be precise with numbers and dates.
            If only one invoice is found, return an array with one element.
            If no clear invoice structure is found, return an empty array.

            Invoice Text:
            {text_content}
            """

            response = client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1
            )

            extracted_invoices = json.loads(response.choices[0].message.content)

            # Ensure it's a list and add metadata
            if not isinstance(extracted_invoices, list):
                extracted_invoices = [extracted_invoices] if extracted_invoices else []

            # Limit to maximum 2 invoices and add metadata
            extracted_invoices = extracted_invoices[:2]
            for i, invoice in enumerate(extracted_invoices):
                invoice["confidence_score"] = 0.9  # High confidence for GPT-4
                invoice["extraction_method"] = "openai_gpt4"
                invoice["invoice_sequence"] = i + 1

            return extracted_invoices

        except Exception as e:
            # Fallback to single invoice structure
            return [{
                "invoice_number": None,
                "vendor_name": None,
                "vendor_address": None,
                "invoice_date": None,
                "due_date": None,
                "total_amount": None,
                "currency": None,
                "tax_amount": None,
                "subtotal_amount": None,
                "line_items": [],
                "payment_terms": None,
                "purchase_order_number": None,
                "bill_to_name": None,
                "bill_to_address": None,
                "ship_to_name": None,
                "ship_to_address": None,
                "notes": f"Extraction failed: {str(e)}",
                "confidence_score": 0.1,
                "extraction_method": "fallback",
                "invoice_sequence": 1
            }]


# ----------------------------
# Invoice Data Storage Tool
# ----------------------------
class InvoiceDataStorageTool(BaseTool):
    name: str = "invoice_data_storage"
    description: str = "Store structured invoice data in Astra DB invoice_data table with audit trail"

    def _run(self, structured_invoice_data: str, attachment_record_id: str) -> str:
        try:
            logger.info("Storing invoice data into Astra DB...")
            database_id, token, keyspace = AstraDBConnectionHelper.get_config()
            session, cluster, bundle_path = AstraDBConnectionHelper.connect(database_id, token, keyspace)
            table_name = "invoice_data"

            # Parse structured invoice data
            if isinstance(structured_invoice_data, str):
                try:
                    invoice_data = json.loads(structured_invoice_data)
                except json.JSONDecodeError:
                    return json.dumps({"success": False, "error": "Invalid JSON in structured_invoice_data"})
            else:
                invoice_data = structured_invoice_data

            if "structured_invoice_data" in invoice_data:
                invoice_data = invoice_data["structured_invoice_data"]

            if isinstance(invoice_data, str):
                invoice_data = json.loads(invoice_data)

            invoices_to_store = [invoice_data]
            message_id = invoice_data.get("message_id", "")

            if isinstance(invoices_to_store, dict):
                invoices_to_store = [invoices_to_store]
            invoices_to_store = invoices_to_store[:2]

            extraction_timestamp = datetime.utcnow()
            created_timestamp = datetime.utcnow()

            insert_query = f"""
            INSERT INTO {table_name} (
                id, attachment_record_id, message_id, attachment_name, invoice_number,
                vendor_name, vendor_address, invoice_date, due_date, total_amount,
                currency, tax_amount, subtotal_amount, line_items, payment_terms,
                purchase_order_number, bill_to_name, bill_to_address, ship_to_name,
                ship_to_address, notes, confidence_score, extraction_method,
                extraction_timestamp, created_at, updated_at, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            prepared = session.prepare(insert_query)

            def safe_decimal(value):
                if value is None: return None
                try:
                    return Decimal(str(value).replace(",", ""))  # Remove commas
                except:
                    return None

            def safe_date(date_str):
                if not date_str: return None
                for fmt in ("%d %b %Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
                    try:
                        return datetime.strptime(date_str, fmt).date()
                    except:
                        continue
                return None

            stored_invoices = []
            for invoice in invoices_to_store:
                individual_record_id = uuid.uuid4()
                session.execute(prepared, [
                    individual_record_id,
                    uuid.UUID(attachment_record_id),
                    message_id,
                    invoice.get("attachment_name", ""),
                    invoice.get("invoice_number"),
                    invoice.get("vendor_name"),
                    invoice.get("vendor_address"),
                    safe_date(invoice.get("invoice_date")),
                    safe_date(invoice.get("due_date")),
                    safe_decimal(invoice.get("total_amount")),
                    invoice.get("currency"),
                    safe_decimal(invoice.get("tax_amount")),
                    safe_decimal(invoice.get("subtotal_amount")),
                    json.dumps(invoice.get("line_items", [])),
                    invoice.get("payment_terms"),
                    invoice.get("purchase_order_number"),
                    invoice.get("bill_to_name", invoice.get("customer_name")),
                    invoice.get("bill_to_address", invoice.get("customer_address")),
                    invoice.get("ship_to_name"),
                    invoice.get("ship_to_address"),
                    invoice.get("notes"),
                    invoice.get("confidence_score", 0.0),
                    invoice.get("extraction_method", "unknown"),
                    extraction_timestamp,
                    created_timestamp,
                    created_timestamp,
                    "crewai_outlook_processor"
                ])
                stored_invoices.append({
                    "record_id": str(individual_record_id),
                    "invoice_number": invoice.get("invoice_number"),
                    "vendor_name": invoice.get("vendor_name"),
                    "total_amount": invoice.get("total_amount"),
                    "invoice_sequence": invoice.get("invoice_sequence", 1)
                })
                logger.info(f"Stored invoice {invoice.get('invoice_number')} with record_id={individual_record_id}")

            cluster.shutdown()
            os.unlink(bundle_path)
            file_path = invoice_data.get("file_path")
            if file_path and os.path.exists(file_path):
                os.remove(file_path)

            return json.dumps({
                "success": True,
                "invoices_stored": len(stored_invoices),
                "attachment_record_id": attachment_record_id,
                "table": table_name,
                "keyspace": keyspace,
                "extraction_timestamp": extraction_timestamp.isoformat(),
                "stored_invoices": stored_invoices
            }, indent=2, default=str)

        except Exception as e:
            logger.error(f"Invoice data storage failed: {e}")
            return json.dumps({"success": False, "error": f"Invoice data storage failed: {str(e)}"})



# ----------------------------
# AstraDB Tool
# ----------------------------
class AstraDBTool(BaseTool):
    name: str = "astra_db_storage"
    description: str = "Store extracted attachment metadata in Astra DB invoice_attachments table"

    def _run(self, extracted_data: dict) -> str:
        try:
            logger.info("Storing attachment metadata into Astra DB...")
            database_id, token, keyspace = AstraDBConnectionHelper.get_config()
            session, cluster, bundle_path = AstraDBConnectionHelper.connect(database_id, token, keyspace)
            table_name = os.getenv("ASTRA_DB_TABLE", "invoice_attachments")

            # Ensure we have a dict
            if isinstance(extracted_data, str):
                extracted_data = json.loads(extracted_data)

            if "extracted_data" in extracted_data:
                data_payload = extracted_data["extracted_data"]
            else:
                data_payload = extracted_data

            # data_payload must be a dict
            if isinstance(data_payload, str):
                data_payload = json.loads(data_payload)

            filename = data_payload.get("attachment_name", "unknown")
            file_path_to_remove = data_payload.get("file_path")
            record_id = uuid.uuid4()
            timestamp = datetime.utcnow()

            insert_query = f"""
            INSERT INTO {table_name} (
                id, message_id, attachment_name, sender_email, subject, 
                received_at, extracted_data, content_type, file_size, 
                processing_status, created_at, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            prepared = session.prepare(insert_query)

            session.execute(prepared, [
                record_id,
                data_payload.get("message_id", ""),
                filename,
                data_payload.get("sender", ""),
                data_payload.get("subject", ""),
                timestamp,
                json.dumps(data_payload),
                data_payload.get("content_type", ""),
                data_payload.get("size", 0),
                "completed",
                timestamp,
                "crewai_outlook_processor"
            ])
            logger.info(f"Stored attachment metadata id={record_id}, name={filename}")

            cluster.shutdown()
            os.unlink(bundle_path)

            # Remove file safely
            if file_path_to_remove and os.path.exists(file_path_to_remove):
                os.remove(file_path_to_remove)

            return json.dumps({
                "success": True,
                "record_id": str(record_id),
                "table": table_name,
                "keyspace": keyspace,
                "timestamp": timestamp.isoformat(),
                "message": "Data successfully inserted into Astra DB"
            }, indent=2, default=str)

        except Exception as e:
            logger.error(f"Astra DB storage failed: {e}")
            return json.dumps({"success": False, "error": f"Astra DB storage failed: {str(e)}"})