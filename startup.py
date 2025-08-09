
#!/usr/bin/env python3
"""
Startup script for the Temporal Monitoring System
Initializes database, checks dependencies, and starts the application
"""

import os
import sys
import subprocess
import logging
from datetime import datetime

def check_dependencies():
    """Check if all required dependencies are installed"""
    required_packages = [
        'flask', 'flask_sqlalchemy', 'numpy', 'scipy', 'scikit-learn',
        'matplotlib', 'requests', 'beautifulsoup4', 'dateutil', 'gunicorn'
    ]
    
    missing = []
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing.append(package)
    
    if missing:
        print(f"Missing dependencies: {', '.join(missing)}")
        print("Run: poetry add " + " ".join(missing))
        return False
    
    print("✅ All dependencies are installed")
    return True

def setup_environment():
    """Set up environment variables and directories"""
    
    # Create necessary directories
    directories = [
        'data/_meta',
        'logs',
        'static/css',
        'static/js',
        'templates',
        'instance'
    ]
    
    for dir_path in directories:
        os.makedirs(dir_path, exist_ok=True)
        print(f"✅ Directory created/verified: {dir_path}")
    
    # Set default environment variables
    env_vars = {
        'FLASK_ENV': 'development',
        'SESSION_SECRET': 'dev-secret-key-change-in-production',
        'DATABASE_URL': 'sqlite:///instance/temporal_monitoring.db'
    }
    
    for key, value in env_vars.items():
        if key not in os.environ:
            os.environ[key] = value
            print(f"✅ Environment variable set: {key}")

def initialize_database():
    """Initialize the database schema"""
    try:
        from app import app, db
        with app.app_context():
            db.create_all()
            print("✅ Database initialized")
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        return False
    return True

def generate_initial_data():
    """Generate initial synthetic data if none exists"""
    try:
        from generate_synthetic import generate_all_data
        generate_all_data()
        print("✅ Initial synthetic data generated")
    except Exception as e:
        print(f"⚠️  Synthetic data generation skipped: {e}")

def check_system_status():
    """Perform basic system health checks"""
    print("\n🔍 System Status Check:")
    
    # Check Python version
    python_version = sys.version_info
    print(f"Python version: {python_version.major}.{python_version.minor}.{python_version.micro}")
    
    # Check if port 5000 is available
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('0.0.0.0', 5000))
        sock.close()
        if result == 0:
            print("⚠️  Port 5000 is already in use")
        else:
            print("✅ Port 5000 is available")
    except Exception as e:
        print(f"Port check failed: {e}")

def main():
    """Main startup routine"""
    print("🚀 Starting Temporal Monitoring System Setup")
    print("=" * 50)
    
    # Step 1: Check dependencies
    if not check_dependencies():
        sys.exit(1)
    
    # Step 2: Setup environment
    setup_environment()
    
    # Step 3: Initialize database
    if not initialize_database():
        sys.exit(1)
    
    # Step 4: Generate initial data
    generate_initial_data()
    
    # Step 5: System status check
    check_system_status()
    
    print("\n✅ Startup complete! Ready to run the application.")
    print("To start the server, run:")
    print("  gunicorn --bind 0.0.0.0:5000 --reuse-port --reload main:app")
    print("\nOr use the Run button in Replit")

if __name__ == "__main__":
    main()
