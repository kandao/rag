from pydantic import BaseModel


class Claims(BaseModel):
    user_id: str
    groups: list[str]
    role: str | None
    clearance_level: int
    iss: str = "gateway-stub"
    iat: int = 0


class MockUser(BaseModel):
    token: str
    claims: Claims
