"""Avisos locales: leer el CRM, no verificar pagos ni liberar códigos."""
import hashlib,json,re,secrets
from pathlib import Path
from threading import RLock
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode
from fastapi import APIRouter,Header,HTTPException
from pydantic import BaseModel,Field
from app import ramy_checkout as checkout
router=APIRouter(prefix='/ramy/notificaciones')
LEDGER=Path('/home/admin/jessyca-whatsapp/data/avisos-pedidos.json')
mutex=RLock();cursor=0;offered={}

def auth(value):
    if not value or not secrets.compare_digest(value,checkout.token()):raise HTTPException(401,'No autorizado')
def ledger():
    if not LEDGER.exists():return {}
    return json.loads(LEDGER.read_text())
def acknowledge(event_id):
    with mutex:
        data=ledger();data[event_id]=True
        LEDGER.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        tmp=LEDGER.with_suffix('.tmp');tmp.write_text(json.dumps(data));tmp.chmod(0o600);tmp.replace(LEDGER)
def sessions():
    result=[]
    for p in sorted(checkout.ROOT.glob('*.json')):
        try:
            s=json.loads(p.read_text())
            if not s.get('order') or not re.fullmatch(r'519\d{8}',s.get('phone','')):continue
            chat_id=s.get('chat_id') or 'whatsapp:'+s['phone']+'@s.whatsapp.net'
            if checkout.path(chat_id).name!=p.name:continue
            jid=chat_id.removeprefix('whatsapp:')
            if not re.fullmatch(r'\d+@(?:s\.whatsapp\.net|lid)',jid):continue
            result.append((s,jid))
        except (OSError,ValueError,TypeError):continue
    return result

def event(s,jid):
    try:
        order=checkout.status(s)
        payment=order.get('pago_actual')
        if (order['estado'] in ('EN_TRANSITO','ESPERANDO_SALDO','SALDO_EN_REVISION') and payment
            and payment['tipo']=='SALDO' and payment['estado']=='EN_REVISION' and not payment.get('comprobante_recibido')):
            key=f"{order['pedido_id']}:saldo:{payment['id']}"
            reply=checkout.payment_message(order)
        elif order['estado'] in ('CODIGO_LIBERADO','ENTREGADO') and re.fullmatch(r'\d{4}',str(order.get('codigo_retiro',''))):
            key=f"{order['pedido_id']}:codigo:{order['codigo_retiro']}"
            reply={'reply':f"El equipo autorizó el código de retiro de tu pedido #{order['pedido_id']}: {order['codigo_retiro']}.\nGuárdalo y compártelo únicamente al retirar tu pedido."}
        else:return None
        eid=hashlib.sha256(key.encode()).hexdigest()
        with mutex:
            if ledger().get(eid):return None
        return {'id':eid,'jid':jid,'text':reply['reply'],'payment_qr':bool(reply.get('payment_qr'))}
    except Exception:return None

@router.get('')
def pending(x_conversations_token:str=Header(default='')):
    global cursor
    auth(x_conversations_token)
    rows=sessions()
    if not rows:return {'events':[]}
    with mutex:
        batch=[rows[(cursor+i)%len(rows)] for i in range(min(3,len(rows)))];cursor=(cursor+len(batch))%len(rows)
    # Consultas de red aisladas: no tomar el bloqueo del checkout ni llamar a Ollama.
    with ThreadPoolExecutor(max_workers=3) as pool:events=list(pool.map(lambda row:event(*row),batch))
    with mutex:
        for row,e in zip(batch,events):
            if e:offered[e['id']]=row
        if len(offered)>1000:
            for key in list(offered)[:-1000]:offered.pop(key,None)
    return {'events':[e for e in events if e]}

class EventId(BaseModel):id:str=Field(pattern=r'^[a-f0-9]{64}$')
@router.post('/validar')
def validate(v:EventId,x_conversations_token:str=Header(default='')):
    auth(x_conversations_token)
    with mutex:row=offered.get(v.id)
    if row:
        s,jid=row
        chat_id=s.get('chat_id') or 'whatsapp:'+s['phone']+'@s.whatsapp.net'
        current=checkout.load(chat_id)
        if current.get('order',{}).get('pedido_id')==s['order']['pedido_id']:
            e=event(current,jid)
            if e and e['id']==v.id:return {'event':e}
    return {'event':None}
@router.post('/confirmar-envio')
def delivered(v:EventId,x_conversations_token:str=Header(default='')):
    auth(x_conversations_token);acknowledge(v.id);return {'ok':True}
