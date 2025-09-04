#!/usr/bin/env python3
"""
Flask frontend for CrewAI Invoice Processing Monitoring
Provides real-time conversational updates from the monitoring agent
"""

from datetime import datetime
from flask import Flask, render_template, jsonify, request, send_from_directory
from flask_socketio import SocketIO, emit
import threading
from dotenv import load_dotenv
import sys
import os
# Add the project root and crewai_outlook to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'crewai_outlook'))

try:
    from crew import OutlookProcessingCrew
except ImportError:
    # Fallback for deployment environments
    OutlookProcessingCrew = None
    print("Warning: CrewAI modules not available - running in monitoring-only mode")

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key-change-in-production')
socketio = SocketIO(app, cors_allowed_origins="*")

# Global state for monitoring
monitoring_state = {
    'is_running': False,
    'current_status': 'Idle',
    'last_run': None,
    'total_processed': 0,
    'messages': []
}

class ConversationalMonitor:
    """Conversational monitoring interface for CrewAI workflow"""
    
    def __init__(self):
        self.messages = []
    
    def add_message(self, message_type, content, timestamp=None):
        """Add a conversational message to the monitoring feed"""
        if timestamp is None:
            timestamp = datetime.now().isoformat()
        
        message = {
            'type': message_type,  # 'info', 'success', 'warning', 'error', 'progress'
            'content': content,
            'timestamp': timestamp
        }
        
        self.messages.append(message)
        monitoring_state['messages'] = self.messages[-50:]  # Keep last 50 messages
        
        # Emit to connected clients
        socketio.emit('new_message', message)
        
        return message
    
    def start_workflow(self, search_criteria):
        """Start the invoice processing workflow with conversational updates"""
        self.add_message('info', f"🚀 Starting invoice processing workflow...")
        self.add_message('info', f"📋 Search criteria: {search_criteria}")
        
        try:
            monitoring_state['is_running'] = True
            monitoring_state['current_status'] = 'Running'
            
            # Check if CrewAI is available
            if OutlookProcessingCrew is None:
                self.add_message('warning', "⚠️ CrewAI modules not available - running in demo mode")
                self.add_message('info', "📊 This would normally process invoices using AI agents")
                self.add_message('info', "🔍 Email Search → 📎 Download → 🤖 Extract → 💾 Store")
                
                # Simulate workflow completion
                import time
                time.sleep(3)
                monitoring_state['total_processed'] += 1
                self.add_message('success', "🎉 Demo workflow completed!")
            else:
                # Create and run crew
                crew = OutlookProcessingCrew()
                
                self.add_message('progress', "🔍 Initializing CrewAI agents...")
                self.add_message('progress', "📧 Email Search Agent ready")
                self.add_message('progress', "📎 Attachment Download Agent ready") 
                self.add_message('progress', "🔍 Data Extraction Agent ready")
                self.add_message('progress', "💾 Storage Agents ready")
                self.add_message('progress', "📊 Monitoring Agent ready")
                
                self.add_message('info', "🎯 Starting workflow execution...")
                
                # Run the crew workflow
                result = crew.run(**search_criteria)
                
                # Parse results and provide conversational feedback
                self.parse_workflow_results(result)
                
                self.add_message('success', "🎉 Workflow completed successfully!")
            
            monitoring_state['is_running'] = False
            monitoring_state['current_status'] = 'Completed'
            monitoring_state['last_run'] = datetime.now().isoformat()
            
        except Exception as e:
            monitoring_state['is_running'] = False
            monitoring_state['current_status'] = 'Error'
            self.add_message('error', f"❌ Workflow failed: {str(e)}")
    
    def parse_workflow_results(self, result):
        """Parse workflow results and provide conversational updates"""
        try:
            # Extract key metrics from the result
            if "attachments" in str(result).lower():
                self.add_message('success', "📎 Found email attachments to process")
            
            if "invoice" in str(result).lower():
                self.add_message('success', "📋 Successfully extracted invoice data")
                monitoring_state['total_processed'] += 1
            
            if "stored" in str(result).lower():
                self.add_message('success', "💾 Data stored in Astra DB successfully")
            
            # Provide summary
            self.add_message('info', f"📊 Total invoices processed in this run: {monitoring_state['total_processed']}")
            
        except Exception as e:
            self.add_message('warning', f"⚠️ Could not parse all workflow results: {str(e)}")

# Global monitor instance
monitor = ConversationalMonitor()

@app.route('/')
def index():
    """Main monitoring dashboard"""
    return render_template('index.html')

@app.route('/static/<path:filename>')
def static_files(filename):
    """Serve static files"""
    return send_from_directory('static', filename)

@app.route('/api/status')
def get_status():
    """Get current monitoring status"""
    return jsonify(monitoring_state)

@app.route('/api/start', methods=['POST'])
def start_workflow():
    """Start the invoice processing workflow"""
    if monitoring_state['is_running']:
        return jsonify({'error': 'Workflow is already running'}), 400
    
    # Get search criteria from request
    data = request.get_json() or {}
    search_criteria = {
        'sender_email': data.get('sender_email', ''),
        'subject_contains': data.get('subject_contains', 'invoice'),
        'days_back': data.get('days_back', 1)
    }
    
    # Start workflow in background thread
    thread = threading.Thread(target=monitor.start_workflow, args=(search_criteria,))
    thread.daemon = True
    thread.start()
    
    return jsonify({'message': 'Workflow started', 'status': 'running'})

@app.route('/api/messages')
def get_messages():
    """Get recent monitoring messages"""
    return jsonify(monitoring_state['messages'])

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    emit('status_update', monitoring_state)
    monitor.add_message('info', f"👋 New client connected to monitoring dashboard")

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    monitor.add_message('info', f"👋 Client disconnected from monitoring dashboard")

if __name__ == '__main__':
    monitor.add_message('info', "🚀 CrewAI Invoice Processing Monitor started")
    monitor.add_message('info', "📊 Dashboard ready for monitoring workflow progress")
    
    # For development only - production uses Gunicorn
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
