from crewai import Task
from agents import (
    email_search_agent,
    attachment_download_agent,
    data_extraction_agent,
    astra_db_agent,
    invoice_data_agent,
    monitoring_agent
)

# ----------------------------
# Task 1: Search emails and identify attachments
# ----------------------------
search_task = Task(
    description="""
    Search Outlook emails from the specified sender email address.
    Requirements:
    - Search emails from sender: {sender_email}
    - Optional filter: subject contains {subject_contains}
    - Look back {days_back} days (default: 1)
    - Only emails with attachments
    - Return messageId, attachmentId, attachmentName, and metadata
    """,
    agent=email_search_agent,
    expected_output="JSON with attachment metadata for all found attachments"
)

# ----------------------------
# Task 2: Download attachments (returns file_path)
# ----------------------------
download_task = Task(
    description="""
    Download attachments identified in search_task.
    Requirements:
    - Use messageId and attachmentId from search_task
    - Save each attachment locally and return file_path
    - Return metadata: filename, file_path, size, content_type, checksum
    - Handle download errors gracefully
    """,
    agent=attachment_download_agent,
    expected_output="JSON with filename, file_path, size, content_type, checksum",
    context=[search_task],
    input_transform=lambda result: result.get("attachments", [])
)

# ----------------------------
# Task 3: Extract data from downloaded attachments
# ----------------------------
data_extraction_task = Task(
    description="""
    Extract meaningful data from downloaded files using file_path from download_task.
    Requirements:
    - Handle PDFs, text files, CSVs, JSON
    - For PDFs: extract text and metadata
    - For text/CSV: extract lines
    - For JSON: parse directly
    - Return structured JSON ready for storage
    - Include filename and file_path in output
    """,
    agent=data_extraction_agent,
    expected_output="JSON containing extracted data for each file",
    context=[download_task],
    input_transform=lambda result: result  # result already contains file info
)

# ----------------------------
# Task 4: Store attachment metadata in Astra DB
# ----------------------------
storage_task = Task(
    description="""
    Store extracted attachment metadata into Astra DB (invoice_attachments table).
    Requirements:
    - Use extracted_data from data_extraction_task
    - Store all relevant fields: message_id, attachment_name, sender, subject, size, content_type
    - Use file_path only for reference; remove file after insert
    - Return record_id for audit trail
    """,
    agent=astra_db_agent,
    expected_output="JSON confirmation of successful metadata storage with record_id",
    context=[data_extraction_task, search_task],
    input_transform=lambda result: {
        "extracted_data": result.get("data", {})
    } if result.get("success") else {}
)

# ----------------------------
# Task 5: Store structured invoice data
# ----------------------------
invoice_storage_task = Task(
    description="""
    Store structured invoice data in Astra DB (invoice_data table) with audit trail.
    Requirements:
    - Use extracted invoice fields from data_extraction_task
    - Link invoices to attachment_record_id from storage_task
    - Store all relevant fields: message_id, attachment_name
    - Handle multiple invoices (up to 2 per attachment)
    - Include extraction timestamp, confidence scores
    - Return confirmation with all stored invoice record IDs
    """,
    agent=invoice_data_agent,
    expected_output="JSON confirmation of successful structured invoice storage",
    context=[storage_task, data_extraction_task, search_task],
    input_transform=lambda result: {
        "structured_invoice_data": result.get("data_extraction", {}),
        "attachment_record_id": result.get("storage", {}).get("record_id", ""),
        "file_path": result.get("file_path", ""),
        "message_id": result.get("search", {}).get("messageId", ""),
        "attachment_name": result.get("search", {}).get("attachmentName", ""),
    } if result.get("success") else {}
)


# ----------------------------
# Task 6: Monitor workflow
# ----------------------------
monitoring_task = Task(
    description="""
    Monitor the entire invoice processing workflow.
    Requirements:
    - Review results from all previous tasks
    - Verify data integrity in both invoice_attachments and invoice_data tables
    - Identify failures or incomplete processing
    - Provide summary metrics of processed invoices
    - Report any issues or recommendations for improvement
    """,
    agent=monitoring_agent,
    expected_output="Comprehensive workflow status report",
    context=[search_task, download_task, data_extraction_task, storage_task, invoice_storage_task]
)