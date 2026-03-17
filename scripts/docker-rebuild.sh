#!/bin/bash

LOG_FILE="docker-build.log"

echo "miniMDM Docker Rebuild"
echo "====================="
echo "Build log: $LOG_FILE"
echo ""

{
  echo "Stopping and removing containers..."
  docker compose down -v || true

  echo ""
  echo "Building Docker images..."
  docker compose build --no-cache

  echo ""
  echo "Starting services..."
  docker compose up -d

  echo ""
  echo "Waiting for services to be ready..."
  sleep 3

  echo "Checking PostgreSQL connection..."
  docker compose exec -T postgres pg_isready -U minimdm

  echo ""
  echo "✓ Rebuild complete!"
  echo ""
  echo "Services are running:"
  echo "  - PostgreSQL: localhost:5432"
  echo "  - miniMDM App: http://localhost:8000"
  echo ""
  echo "To view logs:"
  echo "  docker compose logs -f"
} 2>&1 | tee "$LOG_FILE"

if [ ${PIPESTATUS[0]} -ne 0 ]; then
  echo ""
  echo "❌ Build failed. Check $LOG_FILE for details."
  exit 1
fi
