from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from database import CardRule, User
from auth import get_db, get_current_user
from parsers import PARSER_REGISTRY, get_parser
from email_fetcher import EmailFetcher
from pdf_decryptor import decrypt_pdf_bytes

router = APIRouter(prefix="/api/rules", tags=["Statement Mapping Rules"])

class RuleCreateSchema(BaseModel):
    card_code: str = Field(..., min_length=2, max_length=50)
    sheet_col: str = Field(..., min_length=2, max_length=100)
    subject_query: str = Field(..., min_length=2, max_length=255)
    password: Optional[str] = ""
    parser: str = Field(..., min_length=2, max_length=50)
    is_active: bool = True

class RuleUpdateSchema(BaseModel):
    card_code: Optional[str] = None
    sheet_col: Optional[str] = None
    subject_query: Optional[str] = None
    password: Optional[str] = None
    parser: Optional[str] = None
    is_active: Optional[bool] = None

class TestRuleQuerySchema(BaseModel):
    query: str
    password: Optional[str] = ""
    parser: Optional[str] = ""

@router.get("")
def list_rules(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Lists all configured card statement mapping rules."""
    rules = db.query(CardRule).order_by(CardRule.id.asc()).all()
    return [
        {
            "id": r.id,
            "card_code": r.card_code,
            "sheet_col": r.sheet_col,
            "subject_query": r.subject_query,
            "password": r.password,
            "has_password": bool(r.password),
            "parser": r.parser,
            "is_active": r.is_active,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None
        }
        for r in rules
    ]

@router.get("/parsers")
def get_available_parsers(current_user: User = Depends(get_current_user)):
    """Returns the list of registered parser names."""
    return list(PARSER_REGISTRY.keys())

@router.post("")
def create_rule(
    rule_data: RuleCreateSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Creates a new card statement mapping rule."""
    card_code = rule_data.card_code.strip().upper()
    existing = db.query(CardRule).filter(CardRule.card_code == card_code).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Card rule with code '{card_code}' already exists."
        )

    if rule_data.parser not in PARSER_REGISTRY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid parser '{rule_data.parser}'. Available: {list(PARSER_REGISTRY.keys())}"
        )

    new_rule = CardRule(
        card_code=card_code,
        sheet_col=rule_data.sheet_col.strip(),
        subject_query=rule_data.subject_query.strip(),
        password=rule_data.password.strip() if rule_data.password else "",
        parser=rule_data.parser.strip(),
        is_active=rule_data.is_active
    )
    db.add(new_rule)
    db.commit()
    db.refresh(new_rule)

    return {"success": True, "message": f"Rule for '{card_code}' created successfully.", "id": new_rule.id}

@router.put("/{rule_id}")
def update_rule(
    rule_id: int,
    update_data: RuleUpdateSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Updates an existing card statement mapping rule."""
    rule = db.query(CardRule).filter(CardRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found.")

    if update_data.card_code is not None:
        new_code = update_data.card_code.strip().upper()
        # Ensure unique if changed
        if new_code != rule.card_code:
            dup = db.query(CardRule).filter(CardRule.card_code == new_code).first()
            if dup:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Card code '{new_code}' already in use.")
            rule.card_code = new_code

    if update_data.sheet_col is not None:
        rule.sheet_col = update_data.sheet_col.strip()
    if update_data.subject_query is not None:
        rule.subject_query = update_data.subject_query.strip()
    if update_data.password is not None:
        rule.password = update_data.password.strip()
    if update_data.parser is not None:
        if update_data.parser not in PARSER_REGISTRY:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid parser '{update_data.parser}'.")
        rule.parser = update_data.parser
    if update_data.is_active is not None:
        rule.is_active = update_data.is_active

    db.commit()
    return {"success": True, "message": f"Rule '{rule.card_code}' updated successfully."}

@router.delete("/{rule_id}")
def delete_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Deletes a card statement mapping rule."""
    rule = db.query(CardRule).filter(CardRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found.")

    card_code = rule.card_code
    db.delete(rule)
    db.commit()
    return {"success": True, "message": f"Rule '{card_code}' deleted successfully."}

@router.post("/test")
def test_rule_in_gmail(
    test_data: TestRuleQuerySchema,
    current_user: User = Depends(get_current_user)
):
    """
    Tests an IMAP search query against Gmail in real-time.
    Optionally decrypts and parses the PDF if password and parser are provided.
    """
    query = test_data.query.strip()
    if not query:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Search query is required.")

    try:
        with EmailFetcher() as fetcher:
            msg_id, raw_pdf = fetcher.fetch_latest_pdf(query)
            if not raw_pdf:
                return {
                    "found": False,
                    "message": f"No email or PDF attachment found matching query: {query}"
                }

            result = {
                "found": True,
                "message": f"Successfully found email and PDF attachment ({len(raw_pdf):,} bytes).",
                "msg_id": msg_id,
                "pdf_size": len(raw_pdf)
            }

            # Optional: test decrypt & parse if password provided
            if test_data.password and test_data.parser:
                try:
                    stream = decrypt_pdf_bytes(raw_pdf, test_data.password)
                    result["decrypted"] = True
                    parser = get_parser(test_data.parser, stream)
                    parsed_res = parser.parse()
                    result["parsed"] = {
                        "month": parsed_res.get("month"),
                        "year": parsed_res.get("year"),
                        "total_due": parsed_res.get("total_due"),
                        "transactions_count": len(parsed_res.get("transactions", []))
                    }
                except Exception as parse_err:
                    result["decrypted"] = False
                    result["parse_error"] = str(parse_err)

            return result

    except Exception as e:
        return {
            "found": False,
            "error": f"IMAP connection or search error: {str(e)}"
        }
