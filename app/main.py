from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import Base, engine, SessionLocal
from routers import auth, users, expenses, files
from config import settings
# import seed

app = FastAPI(title="Expense Tracker API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# @app.on_event("startup")
# def on_startup():
#     # Creates tables if they don't exist yet, then seeds the 5 demo accounts
#     # (head / hr / emp1 / emp2 / emp3) so login works the first time you run this.
#     Base.metadata.create_all(bind=engine)
#     db = SessionLocal()
#     try:
#         seed.seed_users(db)
#     finally:
#         db.close()


app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(expenses.router, prefix="/api/expenses", tags=["expenses"])
app.include_router(files.router, prefix="/api/files", tags=["files"])


@app.get("/api/health")
def health():
    return {"status": "ok"}
