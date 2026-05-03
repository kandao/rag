from functools import lru_cache
from typing import AsyncGenerator

import httpx
import redis.asyncio as aioredis
from elasticsearch import AsyncElasticsearch
from fastapi import Request

from config import settings


def get_redis(request: Request) -> aioredis.Redis:
    return request.app.state.redis


def get_es_client(request: Request) -> AsyncElasticsearch:
    return request.app.state.es


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http
