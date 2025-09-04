import os
from crewai import Crew, Process
from crewai.tools.agent_tools import AgentTools
from dotenv import load_dotenv
from agents import (
    email_search_agent,
    attachment_download_agent,
    data_extraction_agent,
    astra_db_agent,
    invoice_data_agent,
    monitoring_agent
)
from tasks import (
    search_task,
    download_task,
    data_extraction_task,
    storage_task,
    invoice_storage_task,
    monitoring_task
)

# Load environment variables
load_dotenv()

class OutlookProcessingCrew:
    def __init__(self):
        self.crew = Crew(
            agents=[
                email_search_agent,
                attachment_download_agent,
                data_extraction_agent,
                astra_db_agent,
                invoice_data_agent,
                monitoring_agent
            ],
            tasks=[
                search_task,
                download_task,
                data_extraction_task,
                storage_task,
                invoice_storage_task,
                monitoring_task
            ],
            process=Process.sequential,
            verbose=2,
            memory=True,
            embedder={
                "provider": "openai",
                "config": {
                    "model": "text-embedding-3-small"
                }
            }
        )
    
    def run(self, sender_email: str, subject_contains: str = "", days_back: int = 1):
        """Execute the complete Outlook attachment processing workflow."""
        inputs={
            'sender_email': sender_email,
            'subject_contains': subject_contains,
            'days_back': days_back
        }
        
        print(f"🚀 Starting Outlook attachment processing workflow...")
        print(f"📧 Sender: {sender_email}")
        print(f"📋 Subject filter: {subject_contains or 'None'}")
        print(f"📅 Days back: {inputs['days_back']}")
        print("-" * 50)
        
        result = self.crew.kickoff(inputs=inputs)
        return result

def main():
    """Main function to run the CrewAI workflow."""
    # Example usage - you can modify these parameters
    sender_email = input("Enter sender email address: ").strip()
    subject_contains = input("Enter subject filter (optional): ").strip()
    days_back = input("Enter days back to search (default 1): ").strip()
    
    if not days_back:
        days_back = 1
    else:
        try:
            days_back = int(days_back)
        except ValueError:
            days_back = 1
    
    # Initialize and run the crew
    crew = OutlookProcessingCrew()
    result = crew.run(
        sender_email=sender_email,
        subject_contains=subject_contains,
        days_back=days_back
    )
    
    print("\n" + "="*50)
    print("🎉 WORKFLOW COMPLETED!")
    print("="*50)
    print(result)

if __name__ == "__main__":
    main()
