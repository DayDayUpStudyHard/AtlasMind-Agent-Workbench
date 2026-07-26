"""FastAPI 应用工厂 + CORS 中间件。"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import internal_router, kb_router, router

app = FastAPI(title="AtlasMind AI Service API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/chat")
app.include_router(kb_router, prefix="/api/kb")
app.include_router(internal_router, prefix="/internal")
