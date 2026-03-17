#!/bin/bash
set -e

echo "miniMDM Docker Setup"
echo "===================="

# Check if Docker and Docker Compose are installed
if ! command -v docker &> /dev/null; then
    echo "Error: Docker is not installed. Please install Docker first."
    exit 1
fi

if ! command -v docker compose &> /dev/null; then
    echo "Error: Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

# Setup .env for Docker if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env file from .env.docker..."
    cp .env.docker .env
    echo "✓ .env created. Review and update security settings if needed."
fi

# Build and start services
echo ""
echo "Building Docker images..."
docker compose build

echo ""
echo "Starting services..."
docker compose up -d

echo ""
echo "Waiting for services to be ready..."
sleep 3

# Check if database is ready
echo "Checking PostgreSQL connection..."
docker compose exec -T postgres pg_isready -U minimdm

echo ""
echo "✓ Docker setup complete!"
echo ""
echo "Services are running:"
echo "  - PostgreSQL: localhost:5432"
echo "  - miniMDM App: http://localhost:8000"
echo ""
echo "To view logs:"
echo "  docker compose logs -f"
echo ""
echo "To stop services:"
echo "  docker compose down"
echo ""
echo "To stop and remove volumes:"
echo "  docker compose down -v"
