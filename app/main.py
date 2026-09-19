import os
import re
import uuid
import secrets
from datetime import datetime, timezone
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Literal
from fastapi import FastAPI, UploadFile, File, HTTPException, Header, Depends, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, ForeignKey, String, DateTime, Integer, Text, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session, sessionmaker
from apscheduler.schedulers.background import BackgroundScheduler

DB_URL = os.getenv('DATABASE_URL', 'sqlite:///./data/hl.db')
if DB_URL.startswith('postgres://'):
    DB_URL = 'postgresql+psycopg://' + DB_URL[len('postgres://'):]
elif DB_URL.startswith('postgresql://'):
    DB_URL = 'postgresql+psycopg://' + DB_URL[len('postgresql://'):]
TOKEN = os.getenv('APP_ADMIN_TOKEN', '')
UPLOAD_DIR = Path(os.getenv('UPLOAD_DIR', './uploads'))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
if os.getenv('RENDER') and (DB_URL.startswith('sqlite') or not UPLOAD_DIR.is_absolute()):
    raise RuntimeError('Render requires a persistent PostgreSQL DATABASE_URL and absolute UPLOAD_DIR')
if os.getenv('RENDER') and len(TOKEN) < 32:
    raise RuntimeError('Set APP_ADMIN_TOKEN to a random secret of at least 32 characters')
engine = create_engine(DB_URL, connect_args={'check_same_thread': False} if DB_URL.startswith('sqlite') else {}, pool_pre_ping=True)
SessionLocal = sessionmaker(engine)
PLATFORMS = ('tiktok', 'youtube', 'instagram', 'facebook', 'linkedin')
MAX_BYTES = 250 * 1024 * 1024

class Base(DeclarativeBase): pass
class Media(Base):
    __tablename__ = 'media_assets'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    filename: Mapped[str] = mapped_column(String(80))
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
class SocialAccount(Base):
    __tablename__ = 'social_accounts'
    platform: Mapped[str] = mapped_column(String(30), primary_key=True)
    status: Mapped[str] = mapped_column(String(30), default='disconnected')
class Job(Base):
    __tablename__ = 'publish_jobs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    media_id: Mapped[str] = mapped_column(ForeignKey('media_assets.id'))
    title: Mapped[str] = mapped_column(String(200))
    caption: Mapped[str] = mapped_column(Text, default='')
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default='scheduled')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
class Target(Base):
    __tablename__ = 'publish_targets'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey('publish_jobs.id'))
    platform: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default='blocked_unconnected')
    error: Mapped[str] = mapped_column(Text, default='Official OAuth/API integration is not configured')

class JobInput(BaseModel):
    media_id: str
    title: str = Field(min_length=1, max_length=200)
    caption: str = Field(default='', max_length=5000)
    platforms: list[Literal['tiktok','youtube','instagram','facebook','linkedin']] = Field(min_length=1)
    scheduled_at: datetime | None = None


def auth(x_admin_token: str | None = Header(default=None)):
    if not TOKEN or not x_admin_token or not secrets.compare_digest(x_admin_token, TOKEN):
        raise HTTPException(401, 'Invalid admin token')

def serialize_job(db: Session, j: Job):
    targets = db.scalars(select(Target).where(Target.job_id == j.id)).all()
    return {'id':j.id,'media_id':j.media_id,'title':j.title,'caption':j.caption,'scheduled_at':j.scheduled_at.isoformat(), 'status':j.status,'targets':[{'platform':t.platform,'status':t.status,'error':t.error} for t in targets]}

def tick():
    # Fail closed: never claim a real publish without an approved provider adapter.
    with SessionLocal() as db:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        jobs = db.scalars(select(Job).where(Job.status == 'scheduled', Job.scheduled_at <= now)).all()
        for job in jobs:
            job.status = 'blocked_unconnected'
        db.commit()

scheduler = BackgroundScheduler(timezone='UTC')
@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        for platform in PLATFORMS:
            if not db.get(SocialAccount, platform): db.add(SocialAccount(platform=platform))
        db.commit()
    scheduler.add_job(tick, 'interval', seconds=10, id='due_jobs', replace_existing=True, max_instances=1)
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)

app = FastAPI(title='(HL) Global Publisher API', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
@app.middleware('http')
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    return response
app.mount('/static', StaticFiles(directory='app/static'), name='static')
@app.get('/')
def home(): return FileResponse('app/static/index.html')
@app.get('/api/health')
def health(): return {'ok':True, 'name':'(HL)全球发布'}
@app.get('/api/accounts', dependencies=[Depends(auth)])
def accounts():
    with SessionLocal() as db:
        return [{'platform':a.platform,'status':a.status} for a in db.scalars(select(SocialAccount)).all()]
@app.post('/api/media', dependencies=[Depends(auth)], status_code=201)
async def upload(file: UploadFile = File(...)):
    name = (file.filename or 'video').replace('\\','/').split('/')[-1][:255]
    ext = Path(name).suffix.lower()
    if ext not in ('.mp4','.mov','.webm'):
        raise HTTPException(415, 'Only MP4, MOV and WEBM are supported')
    if file.content_type not in ('video/mp4','video/quicktime','video/webm','application/octet-stream'):
        raise HTTPException(415, 'Unsupported media type')
    media_id = str(uuid.uuid4())
    filename = media_id + ext
    dest = UPLOAD_DIR / filename
    size = 0
    try:
        with dest.open('wb') as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES: raise HTTPException(413, 'Maximum file size is 250 MiB')
                out.write(chunk)
        if size == 0: raise HTTPException(400, 'Empty file')
        # Basic signature check; production requires ffprobe and malware scanning.
        with dest.open('rb') as f: head = f.read(32)
        valid = (ext in ('.mp4','.mov') and b'ftyp' in head[:16]) or (ext == '.webm' and head.startswith(b'\x1a\x45\xdf\xa3'))
        if not valid: raise HTTPException(415, 'Invalid video file signature')
        with SessionLocal() as db:
            db.add(Media(id=media_id,name=name,filename=filename,size=size)); db.commit()
        return {'id':media_id,'name':name,'size':size}
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
@app.get('/api/media', dependencies=[Depends(auth)])
def media_list():
    with SessionLocal() as db:
        return [{'id':m.id,'name':m.name,'size':m.size} for m in db.scalars(select(Media).order_by(Media.created_at.desc())).all()]
@app.get('/api/media/{media_id}/download', dependencies=[Depends(auth)])
def media_download(media_id: str):
    with SessionLocal() as db:
        m = db.get(Media, media_id)
        if not m: raise HTTPException(404, 'Media not found')
        path = UPLOAD_DIR / m.filename
        if not path.is_file(): raise HTTPException(404, 'Media file unavailable')
        return FileResponse(path, filename=m.name)
@app.post('/api/jobs', dependencies=[Depends(auth)], status_code=201)
def create_job(payload: JobInput):
    with SessionLocal() as db:
        if not db.get(Media, payload.media_id): raise HTTPException(404, 'Media not found')
        when = payload.scheduled_at or datetime.now(timezone.utc)
        if when.tzinfo is None: raise HTTPException(422, 'scheduled_at must include timezone')
        when = when.astimezone(timezone.utc).replace(tzinfo=None)
        job = Job(id=str(uuid.uuid4()),media_id=payload.media_id,title=payload.title,caption=payload.caption,scheduled_at=when,status='scheduled')
        db.add(job)
        for p in dict.fromkeys(payload.platforms):
            db.add(Target(id=str(uuid.uuid4()),job_id=job.id,platform=p))
        db.commit(); db.refresh(job)
        return serialize_job(db,job)
@app.get('/api/jobs', dependencies=[Depends(auth)])
def list_jobs():
    with SessionLocal() as db:
        return [serialize_job(db,j) for j in db.scalars(select(Job).order_by(Job.created_at.desc())).all()]
@app.post('/api/jobs/{job_id}/cancel', dependencies=[Depends(auth)])
def cancel_job(job_id: str):
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if not job: raise HTTPException(404, 'Job not found')
        if job.status != 'scheduled': raise HTTPException(409, 'Only scheduled jobs can be cancelled')
        job.status = 'cancelled'; db.commit()
        return {'id':job.id,'status':job.status}
