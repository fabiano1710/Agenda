import os, json, hashlib, hmac, secrets, logging
from pathlib import Path
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo
from contextlib import asynccontextmanager
import asyncio
from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import create_engine, Integer, String, Boolean, DateTime, ForeignKey, Text, select, or_, func, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, Session, sessionmaker
from sqlalchemy.exc import IntegrityError

logging.basicConfig(level=logging.INFO)
log=logging.getLogger('agenda')
ROOT=Path(__file__).parent
TZ=ZoneInfo(os.getenv('APP_TIMEZONE','America/Sao_Paulo'))
url=os.getenv('DATABASE_URL','sqlite:///./agenda_local.db')
if url.startswith('postgres://'): url='postgresql+psycopg2://'+url[11:]
elif url.startswith('postgresql://'): url='postgresql+psycopg2://'+url[13:]
engine=create_engine(url,pool_pre_ping=True,connect_args={'check_same_thread':False} if url.startswith('sqlite') else {})
SessionLocal=sessionmaker(engine,expire_on_commit=False)
class Base(DeclarativeBase): pass
class User(Base):
    __tablename__='users'
    id:Mapped[int]=mapped_column(primary_key=True)
    name:Mapped[str]=mapped_column(String(100))
    email:Mapped[str]=mapped_column(String(180),unique=True)
    password_hash:Mapped[str]=mapped_column(Text)
    theme:Mapped[str]=mapped_column(String(20),default='violet')
class Event(Base):
    __tablename__='events'
    id:Mapped[int]=mapped_column(primary_key=True)
    title:Mapped[str]=mapped_column(String(200))
    description:Mapped[str]=mapped_column(Text,default='')
    starts_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True)
    ends_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    owner_id:Mapped[int]=mapped_column(ForeignKey('users.id'))
    created_by_id:Mapped[int]=mapped_column(ForeignKey('users.id'))
    category:Mapped[str]=mapped_column(String(40),default='Pessoal')
    location:Mapped[str]=mapped_column(String(200),default='')
    remind_minutes:Mapped[int]=mapped_column(Integer,default=30)
    completed:Mapped[bool]=mapped_column(Boolean,default=False,index=True)
    completed_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    reminded_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
class Subscription(Base):
    __tablename__='subscriptions'
    id:Mapped[int]=mapped_column(primary_key=True)
    user_id:Mapped[int]=mapped_column(ForeignKey('users.id'))
    endpoint:Mapped[str]=mapped_column(Text,unique=True)
    payload:Mapped[str]=mapped_column(Text)

COLORS={'violet','blue','green','rose','orange','slate'}
CATEGORIES={'Pessoal','Trabalho','Saúde','Família','Financeiro','Outros'}
def password_hash(p):
    salt=secrets.token_bytes(16); key=hashlib.pbkdf2_hmac('sha256',p.encode(),salt,310000)
    return f'pbkdf2_sha256$310000${salt.hex()}${key.hex()}'
def verify_password(p,h):
    try:
        algo,cycles,salt,digest=h.split('$')
        if algo!='pbkdf2_sha256': return False
        result=hashlib.pbkdf2_hmac('sha256',p.encode(),bytes.fromhex(salt),int(cycles))
        return hmac.compare_digest(result,bytes.fromhex(digest))
    except Exception: return False

def db_session():
    with SessionLocal() as db: yield db

def local_dt(dt):
    if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ)
def get_user(request,db):
    uid=request.session.get('uid')
    return db.get(User,uid) if uid else None

def require_user(request,db):
    user=get_user(request,db)
    if not user: raise HTTPException(401,'Faça login para continuar.')
    return user

def csrf(request):
    token=request.session.get('csrf')
    if not token:
        token=secrets.token_urlsafe(32);request.session['csrf']=token
    return token

def check_csrf(request,token):
    if not token or not hmac.compare_digest(token,request.session.get('csrf','')):
        raise HTTPException(403,'Token de segurança inválido. Recarregue a página.')

def parse_start(raw):
    try: dt=datetime.fromisoformat(raw)
    except (TypeError,ValueError): raise HTTPException(422,'Informe data e hora válidas.')
    if dt.tzinfo is None: dt=dt.replace(tzinfo=TZ)
    return dt.astimezone(timezone.utc)

def seed(db):
    for prefix, defaultname in [('ADMIN','Eu'),('PARTNER','Minha esposa')]:
        email=os.getenv(prefix+'_EMAIL','').strip().lower()
        pw=os.getenv(prefix+'_PASSWORD','')
        if not email or not pw: continue
        if len(pw)<10: raise RuntimeError(prefix+'_PASSWORD deve ter no mínimo 10 caracteres')
        if not db.scalar(select(User).where(User.email==email)):
            db.add(User(email=email,name=os.getenv(prefix+'_NAME',defaultname),password_hash=password_hash(pw)))
    db.commit()

def push_enabled():return bool(os.getenv('VAPID_PUBLIC_KEY') and os.getenv('VAPID_PRIVATE_KEY') and os.getenv('VAPID_SUBJECT'))

def deliver_reminders():
    if not push_enabled():return
    from pywebpush import webpush, WebPushException
    now=datetime.now(timezone.utc)
    with SessionLocal() as db:
        # claim before sending prevents repeated alerts in a single worker; schedule a single Railway replica
        events=db.scalars(select(Event).where(Event.completed==False,Event.reminded_at.is_(None),Event.starts_at>=now-timedelta(hours=1),Event.starts_at<=now+timedelta(days=1))).all()
        for event in events:
            if event.starts_at-timedelta(minutes=event.remind_minutes)>now: continue
            event.reminded_at=now
            db.commit()
            subs=db.scalars(select(Subscription).where(Subscription.user_id==event.owner_id)).all()
            for sub in subs:
                try:
                    webpush(subscription_info=json.loads(sub.payload),data=json.dumps({'title':'Lembrete: '+event.title,'body':'Compromisso em '+local_dt(event.starts_at).strftime('%d/%m às %H:%M'),'url':'/'}),vapid_private_key=os.getenv('VAPID_PRIVATE_KEY'),vapid_claims={'sub':os.getenv('VAPID_SUBJECT')},ttl=3600)
                except WebPushException as exc:
                    log.warning('Erro push: %s',exc)
                    if getattr(getattr(exc,'response',None),'status_code',None) in (404,410):
                        db.delete(sub);db.commit()
                except Exception as exc:log.warning('Falha push: %s',exc)

async def reminder_loop():
    while True:
        try: await asyncio.to_thread(deliver_reminders)
        except Exception:log.exception('Worker de lembretes')
        await asyncio.sleep(60)

@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    with SessionLocal() as db: seed(db)
    task=asyncio.create_task(reminder_loop())
    yield
    task.cancel()
    try: await task
    except asyncio.CancelledError:pass

app=FastAPI(title='Agenda Família',lifespan=lifespan)
key=os.getenv('SECRET_KEY','')
if not key and os.getenv('RAILWAY_ENVIRONMENT'):raise RuntimeError('Defina SECRET_KEY em produção')
app.add_middleware(SessionMiddleware,secret_key=key or 'somente-para-desenvolvimento-local',https_only=os.getenv('COOKIE_SECURE','0')=='1',same_site='lax',max_age=60*60*24*30)
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
templates=Jinja2Templates(directory=str(ROOT/'templates'))

@app.get('/health')
def health():return {'status':'ok'}

@app.get('/login',response_class=HTMLResponse)
def login_page(request:Request,db:Session=Depends(db_session)):
    if get_user(request,db):return RedirectResponse('/',303)
    return templates.TemplateResponse('login.html',{'request':request,'csrf':csrf(request),'error':''})

@app.post('/login')
def login(request:Request,email:str=Form(...),password:str=Form(...),token:str=Form(...),db:Session=Depends(db_session)):
    check_csrf(request,token)
    user=db.scalar(select(User).where(User.email==email.strip().lower()))
    if not user or not verify_password(password,user.password_hash):
        return templates.TemplateResponse('login.html',{'request':request,'csrf':csrf(request),'error':'E-mail ou senha inválidos.'},status_code=401)
    request.session.clear();request.session['uid']=user.id;csrf(request)
    return RedirectResponse('/',303)

@app.post('/logout')
def logout(request:Request,token:str=Form(...)):
    check_csrf(request,token);request.session.clear();return RedirectResponse('/login',303)

@app.get('/',response_class=HTMLResponse)
def index(request:Request,db:Session=Depends(db_session)):
    user=get_user(request,db)
    if not user:return RedirectResponse('/login',303)
    people=db.scalars(select(User).order_by(User.id)).all()
    events=db.scalars(select(Event).order_by(Event.starts_at.asc(),Event.id.asc())).all()
    items=[{'id':e.id,'title':e.title,'description':e.description,'start':local_dt(e.starts_at).strftime('%Y-%m-%dT%H:%M'),'end':local_dt(e.ends_at).strftime('%Y-%m-%dT%H:%M') if e.ends_at else '', 'date':local_dt(e.starts_at).strftime('%d/%m/%Y'),'time':local_dt(e.starts_at).strftime('%H:%M'),'owner':e.owner_id,'category':e.category,'location':e.location,'remind':e.remind_minutes,'completed':e.completed} for e in events]
    return templates.TemplateResponse('dashboard.html',{'request':request,'user':user,'people':people,'events':items,'csrf':csrf(request),'push_enabled':push_enabled(),'vapid_public':os.getenv('VAPID_PUBLIC_KEY','')})

def safe_event(db,event_id):
    event=db.get(Event,event_id)
    if not event:raise HTTPException(404,'Compromisso não encontrado.')
    return event

def validate_owner(db,owner_id):
    if not db.get(User,owner_id):raise HTTPException(422,'Membro inválido.')

def event_form_data(title,description,start,end,owner_id,category,location,remind_minutes):
    if not title.strip():raise HTTPException(422,'Título obrigatório.')
    if len(title)>200:raise HTTPException(422,'Título muito longo.')
    start_dt=parse_start(start)
    end_dt=parse_start(end) if end else None
    if end_dt and end_dt<start_dt:raise HTTPException(422,'O término deve ser após o início.')
    if category not in CATEGORIES: category='Outros'
    if remind_minutes not in (0,5,15,30,60,1440):raise HTTPException(422,'Lembrete inválido.')
    return dict(title=title.strip(),description=description.strip()[:4000],starts_at=start_dt,ends_at=end_dt,owner_id=owner_id,category=category,location=location.strip()[:200],remind_minutes=remind_minutes)

@app.post('/events')
def create_event(request:Request,title:str=Form(...),description:str=Form(''),start:str=Form(...),end:str=Form(''),owner_id:int=Form(...),category:str=Form('Pessoal'),location:str=Form(''),remind_minutes:int=Form(30),token:str=Form(...),db:Session=Depends(db_session)):
    user=require_user(request,db);check_csrf(request,token);validate_owner(db,owner_id)
    data=event_form_data(title,description,start,end,owner_id,category,location,remind_minutes)
    db.add(Event(**data,created_by_id=user.id));db.commit()
    return RedirectResponse('/?saved=1',303)

@app.post('/events/{event_id}/edit')
def edit_event(event_id:int,request:Request,title:str=Form(...),description:str=Form(''),start:str=Form(...),end:str=Form(''),owner_id:int=Form(...),category:str=Form('Pessoal'),location:str=Form(''),remind_minutes:int=Form(30),token:str=Form(...),db:Session=Depends(db_session)):
    require_user(request,db);check_csrf(request,token);validate_owner(db,owner_id);event=safe_event(db,event_id)
    data=event_form_data(title,description,start,end,owner_id,category,location,remind_minutes)
    changed=any(getattr(event,k)!=v for k,v in data.items())
    for k,v in data.items():setattr(event,k,v)
    if changed:event.reminded_at=None
    db.commit();return RedirectResponse('/?saved=1',303)

@app.post('/events/{event_id}/toggle')
def toggle_event(event_id:int,request:Request,token:str=Form(...),db:Session=Depends(db_session)):
    require_user(request,db);check_csrf(request,token);event=safe_event(db,event_id)
    event.completed=not event.completed;event.completed_at=datetime.now(timezone.utc) if event.completed else None
    db.commit();return RedirectResponse('/',303)

@app.post('/events/{event_id}/delete')
def delete_event(event_id:int,request:Request,token:str=Form(...),db:Session=Depends(db_session)):
    require_user(request,db);check_csrf(request,token);db.delete(safe_event(db,event_id));db.commit();return RedirectResponse('/',303)

@app.post('/theme')
def theme(request:Request,color:str=Form(...),token:str=Form(...),db:Session=Depends(db_session)):
    user=require_user(request,db);check_csrf(request,token)
    if color not in COLORS:raise HTTPException(422,'Cor inválida.')
    user.theme=color;db.commit();return RedirectResponse('/',303)

@app.get('/push/public-key')
def public_key(request:Request,db:Session=Depends(db_session)):
    require_user(request,db);return {'key':os.getenv('VAPID_PUBLIC_KEY','')}

@app.post('/push/subscribe')
async def subscribe(request:Request,db:Session=Depends(db_session)):
    user=require_user(request,db)
    if not push_enabled():raise HTTPException(503,'Notificações não configuradas.')
    token=request.headers.get('X-CSRF-Token','');check_csrf(request,token)
    data=await request.json()
    endpoint=data.get('endpoint','')
    if not endpoint.startswith('https://') or not isinstance(data.get('keys'),dict):raise HTTPException(422,'Assinatura inválida.')
    sub=db.scalar(select(Subscription).where(Subscription.endpoint==endpoint))
    if not sub:sub=Subscription(endpoint=endpoint,user_id=user.id,payload=json.dumps(data));db.add(sub)
    else:sub.user_id=user.id;sub.payload=json.dumps(data)
    db.commit();return {'ok':True}

@app.get('/manifest.webmanifest')
def manifest():return FileResponse(ROOT/'static'/'manifest.webmanifest',media_type='application/manifest+json')
@app.get('/service-worker.js')
def service_worker():return FileResponse(ROOT/'static'/'service-worker.js',media_type='application/javascript',headers={'Service-Worker-Allowed':'/'})
