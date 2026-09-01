import os

# Set minimal required env vars before any app module is imported, so tests
# can run without a hand-written .env file (CI convenience). These are NOT
# used for anything security-sensitive in the test run itself.
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-characters-long")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/pulsepin")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
