#!/usr/bin/env python3
"""
WSGI entry point for production deployment
"""
import os
import sys

# Add the project directory to Python path
sys.path.insert(0, os.path.dirname(__file__))

from app import app

# Set production environment
os.environ.setdefault('FLASK_ENV', 'production')

if __name__ == "__main__":
    app.run()
