import logging
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
import yaml
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response

from claims_signer import sign_claims
from config import settings
from schemas import Claims, MockUser

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

_users: dict[str, MockUser] = {}


def _load_users():
    try:
        with open(settings.mock_users_file) as f:
            data = yaml.safe_load(f)
        for entry in data.get("users", []):
            user = MockUser(token=entry["token"], claims=Claims(**entry["claims"]))
            _users[user.token] = user
        logger.info("Loaded %d mock users", len(_users))
    except Exception as exc:
        logger.warning("Could not load mock users from %s: %s", settings.mock_users_file, exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_users()
    app.state.http = httpx.AsyncClient(timeout=30.0)
    logger.info("gateway-stub startup complete")
    yield
    await app.state.http.aclose()


app = FastAPI(title="gateway-stub", version="1.0.0", lifespan=lifespan)


def _get_user(authorization: str) -> MockUser:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    user = _users.get(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user


@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy(
    path: str,
    request: Request,
    authorization: Annotated[str, Header(alias="Authorization")] = "",
):
    user = _get_user(authorization)
    claims_b64, sig = sign_claims(user.claims, settings.claims_signing_key)

    headers = dict(request.headers)
    # Strip any client-injected claims headers (header injection prevention)
    headers.pop("x-trusted-claims", None)
    headers.pop("x-claims-sig", None)
    headers.pop("authorization", None)
    headers["x-trusted-claims"] = claims_b64
    headers["x-claims-sig"] = sig

    body = await request.body()
    url = f"{settings.query_service_url}/v1/{path}"

    resp = await request.app.state.http.request(
        method=request.method,
        url=url,
        headers=headers,
        content=body,
    )
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=dict(resp.headers),
    )


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    return {"status": "ok", "users_loaded": len(_users)}
