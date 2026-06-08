#!/bin/bash
# Setup script for the MCP tool environment

set -e

echo "Setting up my_tool environment..."

# Create virtual environment
python -m venv .venv

# Activate it
source .venv/bin/activate

# Install dependencies
pip install -e .

echo "Setup complete!"
echo "To test: .venv/bin/python server.py"
