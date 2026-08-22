#!/bin/bash
set -e

# This script is run automatically by PostgreSQL's docker-entrypoint-initdb.d
# The database and user are already created by docker-compose variables
# This script just ensures the database is properly initialized

echo "Database initialization script running..."
echo "Database 'minimdm' has been created with user 'minimdm'"
echo "The application will handle schema and table creation on startup."
