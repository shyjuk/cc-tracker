import os
from datetime import datetime, timedelta
from typing import Optional
import bcrypt
import jwt
from fastapi import Request, HTTPException, status, Depends
from sqlalchemy.orm import Session
from database import SessionLocal, User

_SECRET_KEY_RAW = os.getenv("SECRET_KEY", "")
if not _SECRET_KEY_RAW or len(_SECRET_KEY_RAW) < 32:
    raise RuntimeError(
        "SECRET_KEY environment variable is required and must be at least 32 characters. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    )
SECRET_KEY = _SECRET_KEY_RAW
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30

def is_request_secure(request: Request) -> bool:
    """Detects whether request is over HTTPS (directly or through a cloud reverse proxy)."""
    if request.url.scheme == "https":
        return True
    if request.headers.get("x-forwarded-proto", "").lower() == "https":
        return True
    return os.getenv("SECURE_COOKIES", "false").lower() in ("true", "1")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def hash_password(password: str) -> str:
    """Hashes a password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain password against a bcrypt hash."""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Encodes a JWT access token."""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """
    Dependency that extracts and verifies the user from
    either an HttpOnly cookie 'access_token' or an Authorization header.
    """
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
        elif request.query_params.get("token"):
            token = request.query_params.get("token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload"
            )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token"
        )

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        from database import get_setting
        owner_email = get_setting("owner_email")
        if owner_email and (username.strip().lower() == owner_email.strip().lower()):
            user = User(username=username, hashed_password=None)
            db.add(user)
            db.commit()
            db.refresh(user)
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )

    return user

def get_optional_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    """Helper that returns the user if logged in, or None if not."""
    try:
        return get_current_user(request, db)
    except HTTPException:
        return None
