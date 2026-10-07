import csv
import io
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, asc

from deps import get_db, get_current_user, require_approver
from schemas import (
    ExpenseCreate, ExpenseUpdate, ExpenseOut, DecisionRequest,
    BulkDecisionRequest, StatsOut,
)
import models
from timeutil import utcnow, to_ist

router = APIRouter()

TWO_STAGE_TYPES = {"Regional Trip"}


def _push_history(expense: models.Expense, by: str, action: str, note: str = ""):
    expense.history.append(models.ExpenseHistory(by=by, action=action, note=note, at=utcnow()))


def _visible_query(db: Session, user: models.User):
    """Employees only ever see their own requests; head/hr see everything."""
    q = db.query(models.Expense).options(joinedload(models.Expense.history))
    if user.role not in ("head", "hr"):
        q = q.filter(models.Expense.employee_id == user.username)
    return q


def _attach_pending_files(db: Session, expense: models.Expense, data: dict):
    """Link file ids (uploaded earlier via /api/files/upload) to this expense."""
    ids = []
    for v in (data or {}).values():
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict) and item.get("id"):
                    ids.append(item["id"])
    if not ids:
        return
    db.query(models.FileAsset).filter(models.FileAsset.id.in_(ids)).update(
        {models.FileAsset.expense_id: expense.id}, synchronize_session=False
    )
    db.commit()


@router.get("", response_model=list[ExpenseOut])
def list_expenses(
    status_filter: Optional[str] = Query(None, alias="status"),
    type_filter: Optional[str] = Query(None, alias="type"),
    employee: Optional[str] = None,
    sort_by: str = "created_date",
    sort_dir: str = "desc",
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    q = _visible_query(db, current_user)
    if status_filter:
        q = q.filter(models.Expense.status == status_filter)
    if type_filter:
        q = q.filter(models.Expense.type == type_filter)
    if employee and current_user.role in ("head", "hr"):
        q = q.filter(models.Expense.employee_id == employee)

    sort_col = getattr(models.Expense, sort_by, models.Expense.created_date)
    q = q.order_by(desc(sort_col) if sort_dir == "desc" else asc(sort_col))
    return q.all()


@router.get("/stats", response_model=StatsOut)
def stats(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    items = _visible_query(db, current_user).all()

    def bucket(status_name):
        b = [e for e in items if e.status == status_name]
        return len(b), sum(float((e.data or {}).get("amount") or 0) for e in b)

    total = len(items)
    total_amount = sum(float((e.data or {}).get("amount") or 0) for e in items)
    a_n, a_amt = bucket("Approved")
    p_n, p_amt = bucket("Pending")
    r_n, r_amt = bucket("Rejected")
    i_n, i_amt = bucket("In Progress")

    return StatsOut(
        total=total, total_amount=total_amount,
        approved=a_n, approved_amount=a_amt,
        pending=p_n, pending_amount=p_amt,
        rejected=r_n, rejected_amount=r_amt,
        in_progress=i_n, in_progress_amount=i_amt,
    )


@router.get("/export/csv")
def export_csv(
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    q = _visible_query(db, current_user)
    if status_filter:
        q = q.filter(models.Expense.status == status_filter)
    items = q.order_by(desc(models.Expense.created_date)).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Name", "Type", "Amount (INR)", "Date", "Time"])
    total = 0.0
    for e in items:
        amount = float((e.data or {}).get("amount") or 0)
        total += amount
        submitted = e.submitted_date or e.created_date
        if submitted:
            submitted = to_ist(submitted)   # stored in UTC, exported in IST
        writer.writerow([
            e.employee_name, e.type, amount,
            submitted.strftime("%d-%b-%Y") if submitted else "",
            submitted.strftime("%H:%M") if submitted else "",
        ])
    writer.writerow(["TOTAL", "", total, "", ""])
    buf.seek(0)

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=expenses.csv"},
    )


@router.get("/{expense_id}", response_model=ExpenseOut)
def get_expense(expense_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    e = _visible_query(db, current_user).filter(models.Expense.id == expense_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Expense not found")
    return e


@router.post("", response_model=ExpenseOut)
def create_expense(
    payload: ExpenseCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role != "employee":
        raise HTTPException(status_code=403, detail="Only employees submit expenses")

    is_start = payload.type in TWO_STAGE_TYPES and payload.stage == "start"
    expense = models.Expense(
        employee_id=current_user.username,
        employee_name=current_user.display_name,
        type=payload.type,
        data=payload.data,
        status="In Progress" if is_start else "Pending",
        created_date=utcnow(),
        submitted_date=utcnow(),
    )
    _push_history(expense, current_user.display_name, "Trip started" if is_start else "Submitted for approval")

    db.add(expense)
    db.commit()
    db.refresh(expense)
    _attach_pending_files(db, expense, payload.data)
    return expense


@router.put("/{expense_id}", response_model=ExpenseOut)
def update_expense(
    expense_id: int,
    payload: ExpenseUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Handles three of the frontend's flows with one endpoint, based on current status:
      - In Progress -> closing leg of a two-stage trip (Regional Trip "end trip")
      - Pending      -> plain edit
      - Rejected     -> fix & resubmit
    """
    e = (
        db.query(models.Expense)
        .options(joinedload(models.Expense.history))
        .filter(models.Expense.id == expense_id)
        .first()
    )
    if not e:
        raise HTTPException(status_code=404, detail="Expense not found")
    if e.employee_id != current_user.username:
        raise HTTPException(status_code=403, detail="You can only edit your own expenses")

    if e.status == "In Progress":
        e.data = {**(e.data or {}), **payload.data}
        e.status = "Pending"
        e.submitted_date = utcnow()
        _push_history(e, current_user.display_name, "Trip ended and submitted for approval")
    elif e.status == "Pending":
        e.data = payload.data
        e.submitted_date = utcnow()
        _push_history(e, current_user.display_name, "Edited by employee")
    elif e.status == "Rejected":
        e.data = payload.data
        e.status = "Pending"
        e.submitted_date = utcnow()
        e.decided_by = None
        e.decided_date = None
        e.rejection_reason = None
        _push_history(e, current_user.display_name, "Resubmitted for approval")
    else:
        raise HTTPException(status_code=400, detail="Approved expenses cannot be edited")

    db.commit()
    db.refresh(e)
    _attach_pending_files(db, e, payload.data)
    return e


@router.post("/{expense_id}/decide", response_model=ExpenseOut)
def decide_expense(
    expense_id: int,
    payload: DecisionRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_approver),
):
    if payload.status not in ("Approved", "Rejected"):
        raise HTTPException(status_code=400, detail="status must be Approved or Rejected")

    e = (
        db.query(models.Expense)
        .options(joinedload(models.Expense.history))
        .filter(models.Expense.id == expense_id)
        .first()
    )
    if not e:
        raise HTTPException(status_code=404, detail="Expense not found")
    if e.status == "In Progress":
        raise HTTPException(status_code=400, detail="That trip has not been submitted yet")

    comment = (payload.reason or "").strip()

    e.status = payload.status
    e.decided_by = current_user.display_name
    e.decided_by_role = current_user.role
    e.decided_date = utcnow()
    # rejection_reason only holds a REJECTION reason. Approving clears any old one.
    e.rejection_reason = comment if (payload.status == "Rejected" and comment) else None
    # the comment for either outcome is kept in the activity history
    _push_history(e, current_user.display_name, f"{payload.status} by {current_user.role}", comment)

    db.commit()
    db.refresh(e)
    return e


@router.post("/bulk-decide")
def bulk_decide(
    payload: BulkDecisionRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_approver),
):
    if payload.status not in ("Approved", "Rejected"):
        raise HTTPException(status_code=400, detail="status must be Approved or Rejected")

    items = (
        db.query(models.Expense)
        .options(joinedload(models.Expense.history))
        .filter(models.Expense.id.in_(payload.ids), models.Expense.status != "In Progress")
        .all()
    )

    comment = (payload.reason or "").strip()

    for e in items:
        e.status = payload.status
        e.decided_by = current_user.display_name
        e.decided_by_role = current_user.role
        e.decided_date = utcnow()
        e.rejection_reason = comment if (payload.status == "Rejected" and comment) else None
        _push_history(e, current_user.display_name, f"{payload.status} in bulk by {current_user.role}", comment)

    db.commit()
    return {"updated": len(items)}


@router.delete("/{expense_id}")
def delete_expense(expense_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    e = db.query(models.Expense).filter(models.Expense.id == expense_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Expense not found")
    if e.employee_id != current_user.username:
        raise HTTPException(status_code=403, detail="You can only delete your own expenses")
    if e.status == "Approved":
        raise HTTPException(status_code=400, detail="Approved expenses cannot be deleted")

    db.delete(e)
    db.commit()
    return {"deleted": True}