#!/bin/bash

echo "Starting AIDRIN with Celery and Redis"

docker-compose up --build -d 

echo "Services started!"
echo "Flask app (Docker): http://localhost:5000"
echo "Flower (Celery monitoring): http://localhost:5555"
echo "Redis: localhost:6379"

echo ""
echo "Setting up Python environment variables for Flask"
export FLASK_ENV=development
export FLASK_APP=aidrin/main.py

echo "Starting Flask app"
nohup flask run > flask_app.log 2>&1 &
echo "Flask app (local): http://localhost:5000 (see flask_app.log for output)"

echo "To view logs:"
echo "  docker-compose logs -f"
echo "  tail -f flask_app.log"
echo ""
echo "To stop services:"
echo "  docker-compose down"
echo "  pkill -f 'flask run'" 