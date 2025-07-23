#!/bin/bash

echo "Starting AIDRIN with Celery and Redis..."

# Build and start the services
docker-compose up --build -d

echo "Services started!"
echo "Flask app: http://localhost:5000"
echo "Flower (Celery monitoring): http://localhost:5555"
echo "Redis: localhost:6379"

echo ""
echo "To view logs:"
echo "  docker-compose logs -f"
echo ""
echo "To stop services:"
echo "  docker-compose down" 