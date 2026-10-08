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

    @property
    def DB_URL(self) -> str:
        # quote(safe="") percent-encodes everything outside the unreserved set,
        # which is what the userinfo part of a URL requires. quote_plus would
        # turn a space into "+", and "+" is not a space inside userinfo.
        user = urllib.parse.quote(self.DB_USER, safe="")
        password = urllib.parse.quote(self.DB_PASSWORD, safe="")
        return f"postgresql://{user}:{password}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
