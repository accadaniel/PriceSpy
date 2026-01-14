from pydantic_settings import BaseSettings
from functools import lru_cache
import os


class Settings(BaseSettings):
    serpapi_key: str = ""
    resend_api_key: str = ""
    from_email: str = "onboarding@resend.dev"
    database_path: str = "./data/pricespy.db"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
