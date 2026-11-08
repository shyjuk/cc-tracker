from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from database import User
from auth import get_db, hash_password, verify_password, create_access_token, get_current_user, is_request_secure

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

class AuthCredentials(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=4)

@router.get("/setup-status")
def check_setup_status(db: Session = Depends(get_db)):
    """Checks whether the first-time setup is required (no users exist)."""
    user_count = db.query(User).count()
    return {"setup_required": user_count == 0}

@router.post("/setup")
def setup_first_user(creds: AuthCredentials, request: Request, response: Response, db: Session = Depends(get_db)):
    """First-time setup: creates the initial admin user."""
    if db.query(User).count() > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Setup has already been completed. Please log in."
        )

    hashed = hash_password(creds.password)
    user = User(username=creds.username.strip(), hashed_password=hashed)
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": user.username})
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=30 * 24 * 3600,
        samesite="lax",
        secure=is_request_secure(request)
    )

    return {
        "success": True,
        "message": "Admin account created successfully",
        "username": user.username
    }

@router.post("/login")
def login(creds: AuthCredentials, request: Request, response: Response, db: Session = Depends(get_db)):
    """Authenticates user and returns session cookie and JWT token."""
    user = db.query(User).filter(User.username == creds.username.strip()).first()
    # Reject login if user doesn't exist, is an OAuth-only account (no password hash), or password is wrong
    if not user or user.hashed_password is None or not verify_password(creds.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )

    token = create_access_token({"sub": user.username})
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=30 * 24 * 3600,
        samesite="lax",
        secure=is_request_secure(request)
    )

    return {
        "success": True,
        "message": "Login successful",
        "username": user.username
    }

@router.post("/logout")
def logout(response: Response):
    """Logs out user by clearing the authentication cookie."""
    response.delete_cookie(key="access_token")
    return {"success": True, "message": "Logged out successfully"}

@router.get("/me")
def get_me(user: User = Depends(get_current_user)):
    """Returns the currently authenticated user."""
    return {
        "id": user.id,
        "username": user.username,
        "created_at": user.created_at.isoformat() if user.created_at else None
    }
