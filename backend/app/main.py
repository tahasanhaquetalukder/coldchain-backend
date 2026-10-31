from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from app.database import engine, Base, get_db
from app.models import User, Fridge, VaccineBatch
from app.audit import verify_audit_chain
from passlib.context import CryptContext

# ডাটাবেস টেবিলগুলো অটো জেনারেট করার জন্য
Base.metadata.create_all(bind=engine)

app = FastAPI(title="ColdChain Vaccine Monitoring API", version="1.0.0")

# CORS কনফিগারেশন (ফ্রন্টএন্ড কানেক্ট করার জন্য)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Welcome to ColdChain Vaccine Monitoring & Management API"}

@app.get("/api/audit-logs/verify-integrity")
def verify_integrity_route(db: Session = Depends(get_db)):
    result = verify_audit_chain(db)
    return result