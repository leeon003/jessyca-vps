"""Elegibilidad actual: catálogo/checkout/CRM; no envía ni verifica pagos."""
import json,secrets,time
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from hashlib import sha256
from fastapi import APIRouter,Header,HTTPException
from pydantic import BaseModel,Field
from app import ramy_checkout as checkout
from app.ramy_followup_policy import plan_followup
router=APIRouter(prefix='/ramy/seguimiento')
CONFIG=Path('/home/admin/.config/ramy-followups.json')
class Activity(BaseModel):
 chat_id:str=Field(pattern=r'^whatsapp:519\d{8}@s\.whatsapp\.net$')
 episode:str=Field(min_length=1,max_length=180)
 last_customer_at:float
 last_reply_at:float
 sent_phases:list[str]=Field(default_factory=list,max_length=5)

def evaluate_snapshot(activity,config,now):
 if not config.get('enabled') or activity.last_customer_at < config.get('activated_at',0):return None
 zone=ZoneInfo('America/Lima');hour=datetime.fromtimestamp(now,zone).hour
 with checkout.lock:s=checkout.load(activity.chat_id)
 if not s or s.get('chat_id')!=activity.chat_id:return None
 registered=bool(s.get('order'))
 order=checkout.status(s) if registered else None
 # Latest CRM result always required for a registered order.
 if registered and not order:return None
 lines=checkout.cart(s)
 product=', '.join(str(l['product']['nombre']) for l in lines) if lines else ''
 if not registered and not product:return None
 snapshot={'chat_id':activity.chat_id,'contact_allowed':True,'jessyca_active':True,'last_customer_at':activity.last_customer_at,'last_reply_at':activity.last_reply_at,'sent_phases':activity.sent_phases,'name':s.get('name'),'order_registered':registered,'product_name':product,'pending_question':bool(config.get('four_hours',False)) and s.get('stage') in ('quantity','name','phone','city','address','reference','confirm')}
 event=plan_followup(snapshot,order,now,hour,enabled=True,start=config['start_hour'],end=config['end_hour'])
 if event:
  closing=datetime.fromtimestamp(now,zone).replace(hour=config['end_hour'],minute=0,second=0,microsecond=0).timestamp() if config['end_hour']<24 else now+15
  event['valid_until']=min(now+15,closing)
 if event and not registered:event['id']=sha256((activity.chat_id+':'+activity.episode+':'+event['phase']).encode()).hexdigest()
 return event
@router.post('/evaluar')
def evaluate(activity:Activity,x_conversations_token:str=Header(default='')):
 if not x_conversations_token or not secrets.compare_digest(x_conversations_token,checkout.token()):raise HTTPException(401,'No autorizado')
 try:
  config=json.loads(CONFIG.read_text());now=time.time()
  if not 0<=config['start_hour']<config['end_hour']<=24:return {'event':None}
  return {'event':evaluate_snapshot(activity,config,now)}
 except Exception:return {'event':None} # Failure closed; normal sales continue.
