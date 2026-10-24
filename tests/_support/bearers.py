import jwt

_SIGNING_KEY = "a-test-signing-key-that-is-long-enough-for-hs256"


def jwt_shaped(subject: str) -> str:
    return jwt.encode({"sub": subject}, _SIGNING_KEY, algorithm="HS256")
