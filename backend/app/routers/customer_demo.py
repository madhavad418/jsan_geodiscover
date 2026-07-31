import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import Project, User

router = APIRouter(prefix="/customer-demo", tags=["Customer Demonstration"])
DATA_FILE = Path(__file__).parents[1] / "data" / "denpasar_customer_demo.json"


@router.get("/{project_id}")
def customer_demo_summary(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return {
        **payload["study"],
        "project_id": project.id,
        "project_name": project.name,
        "demo_only": True,
        "customer_safe_statement": (
            "JSAN compared authorised Grab and Google extracts, generated explainable overlap and incremental-candidate queues, "
            "and preserved evidence for controlled enrichment and QA. No candidate is released as a confirmed active Google gap in this demonstration."
        ),
    }
