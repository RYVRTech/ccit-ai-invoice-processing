#!/usr/bin/env python3
"""
Daily automated invoice processing scheduler
Runs the CrewAI workflow on a schedule with configurable parameters
"""

import sys
import json
import logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Add the crewai_outlook directory to Python path
sys.path.append(str(Path(__file__).parent.parent / 'crewai_outlook'))

from crew import OutlookProcessingCrew

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('daily_processor.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

class DailyProcessor:
    """Automated daily invoice processing"""

    def __init__(self, config_file='scheduler_config.json'):
        """Initialize with configuration"""
        load_dotenv()
        self.config = self.load_config(config_file)
        self.crew = OutlookProcessingCrew()

    def load_config(self, config_file):
        """Load scheduler configuration"""
        config_path = Path(__file__).parent / config_file

        # Default configuration
        default_config = {
            "search_criteria": {
                "sender_email": "",
                "subject_contains": "invoice",
                "days_back": 1
            },
            "retry_attempts": 3,
            "retry_delay_minutes": 30,
            "notification_webhook": None,
            "max_runtime_minutes": 60
        }

        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    user_config = json.load(f)
                    default_config.update(user_config)
                    logger.info(f"Loaded configuration from {config_file}")
            except Exception as e:
                logger.warning(f"Failed to load config file: {e}. Using defaults.")
        else:
            # Create default config file
            with open(config_path, 'w') as f:
                json.dump(default_config, f, indent=2)
            logger.info(f"Created default configuration file: {config_file}")

        return default_config

    def run_daily_processing(self):
        """Execute the daily invoice processing workflow"""
        start_time = datetime.now()
        logger.info("=" * 60)
        logger.info("🚀 Starting daily invoice processing")
        logger.info(f"📅 Run date: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 60)

        try:
            # Prepare search criteria
            search_criteria = self.config["search_criteria"].copy()

            logger.info(f"📋 Search criteria:")
            logger.info(f"   • Sender: {search_criteria['sender_email'] or 'Any'}")
            logger.info(f"   • Subject contains: {search_criteria['subject_contains']}")
            logger.info(f"   • Days back: {search_criteria['days_back']}")

            # Run the CrewAI workflow
            logger.info("🤖 Initializing CrewAI workflow...")
            result = self.crew.run(
                sender_email=search_criteria['sender_email'],
                subject_contains=search_criteria['subject_contains'],
                days_back=search_criteria['days_back']
            )

            # Log results
            self.log_results(result, start_time)

            # Send notification if configured
            if self.config.get("notification_webhook"):
                self.send_notification(result, success=True)

            logger.info("✅ Daily processing completed successfully")
            return True

        except Exception as e:
            logger.error(f"❌ Daily processing failed: {str(e)}")

            # Send failure notification
            if self.config.get("notification_webhook"):
                self.send_notification(str(e), success=False)

            return False

    def log_results(self, result, start_time):
        """Log workflow results"""
        end_time = datetime.now()
        duration = end_time - start_time

        logger.info("📊 Workflow Results:")
        logger.info(f"   • Duration: {duration}")
        logger.info(f"   • Status: Completed")

        # Try to extract metrics from result
        result_str = str(result)
        if "attachments" in result_str.lower():
            logger.info("   • ✅ Email attachments processed")
        if "invoice" in result_str.lower():
            logger.info("   • ✅ Invoice data extracted")
        if "stored" in result_str.lower():
            logger.info("   • ✅ Data stored in database")

    def send_notification(self, result, success=True):
        """Send notification webhook (if configured)"""
        try:
            import requests

            webhook_url = self.config["notification_webhook"]
            if not webhook_url:
                return

            status = "✅ Success" if success else "❌ Failed"
            payload = {
                "text": f"CrewAI Invoice Processing - {status}",
                "timestamp": datetime.now().isoformat(),
                "result": str(result)[:500]  # Truncate long results
            }

            response = requests.post(webhook_url, json=payload, timeout=10)
            if response.status_code == 200:
                logger.info("📧 Notification sent successfully")
            else:
                logger.warning(f"⚠️ Notification failed: {response.status_code}")

        except Exception as e:
            logger.warning(f"⚠️ Failed to send notification: {e}")

def main():
    """Main entry point for scheduled execution"""
    processor = DailyProcessor()
    
    try:
        success = processor.run_daily_processing()
        exit_code = 0 if success else 1
        
    except KeyboardInterrupt:
        logger.info("🛑 Processing interrupted by user")
        exit_code = 130
        
    except Exception as e:
        logger.error(f"💥 Unexpected error: {e}")
        exit_code = 1
    
    logger.info("=" * 60)
    logger.info(f"🏁 Daily processing finished with exit code: {exit_code}")
    logger.info("=" * 60)
    
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
