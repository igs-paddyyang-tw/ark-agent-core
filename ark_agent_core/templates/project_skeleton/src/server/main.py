"""專案入口 — 使用 ark-agent-core 建立 FastAPI app。"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ark_agent_core.skills.registry import SkillRegistry

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """啟動時初始化 Skill Registry。"""
    registry = SkillRegistry()
    # 掃描內建 Skills
    registry.auto_discover("ark_agent_core.skills.builtin")
    registry.auto_discover("ark_agent_core.skills.builtin.wiki")
    registry.auto_discover("ark_agent_core.skills.builtin.llm")
    # 掃描業務 Skills
    registry.auto_discover("src.skills.internal")

    app.state.skill_registry = registry
    yield


app = FastAPI(title="My Agent", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"])


@app.get("/")
async def root():
    return {"name": "My Agent", "framework": "ark-agent-core"}


@app.get("/api/v1/health")
async def health():
    return {"status": "ok"}


@app.get("/api/v1/skills")
async def list_skills(request):
    return request.app.state.skill_registry.list_skills()
