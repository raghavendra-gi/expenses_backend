import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL", "mysql+pymysql://root:Raghavan%4010@localhost:3306/expense_tracker"
    )
    secret_key: str = os.getenv("SECRET_KEY", "dev-secret-change-me")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))
    storage_dir: str = os.getenv("STORAGE_DIR", "./storage")
    cors_origins: list = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")]


settings = Settings()

os.makedirs(settings.storage_dir, exist_ok=True)
