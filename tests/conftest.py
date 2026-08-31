import os


# The service has no environment default by design. Tests still configure one
# explicitly at process scope so isolated Settings(_env_file=None) calls boot.
os.environ.setdefault("PI_RAG_ENVIRONMENT", "development")
