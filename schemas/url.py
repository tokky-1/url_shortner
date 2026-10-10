
from typing import Annotated

from pydantic import BaseModel, HttpUrl, UrlConstraints
SubmittedUrl = Annotated[HttpUrl, UrlConstraints(max_length=2048)]


class ShortenRequest(BaseModel):
    url: SubmittedUrl


class ShortenResponse(BaseModel):
    code: str
    short_url: str


class HealthResponse(BaseModel):
    status: str


class ReadyResponse(BaseModel):
    status: str
    database: str
