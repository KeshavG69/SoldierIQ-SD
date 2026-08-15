"""
Configuration constants for the authentication module
"""

import os
from dotenv import load_dotenv

load_dotenv()

# Secret key for JWT - in production, use a secure random key
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this-in-production-please-use-strong-key")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))  # 24 hours
