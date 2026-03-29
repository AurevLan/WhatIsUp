"""Probe test configuration — ensure consistent env for all tests."""

import os

# Force localhost URL for tests (Docker image sets CENTRAL_API_URL=http://server:8000)
os.environ["CENTRAL_API_URL"] = "http://localhost:8000"
