import urllib.parse
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DB_HOST: str
    DB_PORT: int
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str

    BASE_URL: str

    @property
    def DB_URL(self) -> str:
        user = urllib.parse.quote(self.DB_USER, safe="")
        password = urllib.parse.quote(self.DB_PASSWORD, safe="")
        return f"postgresql://{user}:{password}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    def short_url(self, code: str) -> str:
        """Absolute URL for a short code, tolerating a trailing slash."""
        return f"{self.BASE_URL.rstrip('/')}/{code}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
