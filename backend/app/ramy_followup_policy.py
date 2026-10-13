"""Política pura y fail-closed: no consulta red, no agenda y no envía mensajes."""
from hashlib import sha256
from math import isfinite
from app.ramy_advance_reminder import advance_reminder

def plan_followup(s, order, now, hour, enabled=False, start=9, end=20):
    if not enabled or not start <= hour < end:return None
    if s.get('contact_allowed') is not True or s.get('jessyca_active') is not True:return None
    if any(s.get(k) for k in ('human','paused','no_contact','cancelled','deferred')):return None
    try:
        customer=float(s['last_customer_at']);reply=float(s['last_reply_at']);clock=float(now)
        if not all(isfinite(v) for v in (customer,reply,clock)):return None
    except (KeyError,ValueError,TypeError):return None
    if not 0 < customer <= reply <= clock:return None
    chat=s.get('chat_id')
    if not isinstance(chat,str) or not chat:return None
    elapsed=(clock-reply)/3600
    sent=set(s.get('sent_phases') or [])
    if s.get('order_registered'):
        if order is None or elapsed < 24 or 'advance24' in sent:return None
        text=advance_reminder(order,s.get('name'))
        if text is None:return None
        phase='advance24'
        # Reminder tied to one payment, even if client activity timestamps change.
        identity=f"{chat}:advance24:{order.get('pedido_id')}:{order['pago_actual'].get('id')}"
        if order.get('pedido_id') is None or order['pago_actual'].get('id') is None:return None
    else:
        if order is not None:return None
        product=s.get('product_name')
        if not isinstance(product,str) or not product.strip():return None
        if elapsed >= 72:phase='lead72';text='Gracias por tu interés 😊. Cuando quieras retomar la compra, aquí estaremos para ayudarte. ¡Que tengas un buen día!'
        elif elapsed >= 24:phase='lead24';text=f'Hola 😊. Si te quedó alguna duda sobre {product}, con gusto te ayudo. ¿Hay algún detalle que quieras confirmar?'
        elif elapsed >= 4 and s.get('pending_question') is True:phase='lead4';text=f'Hola 😊. Si necesitas ayuda con {product}, estoy aquí para ayudarte. ¿Qué detalle te gustaría confirmar?'
        else:return None
        if phase in sent or 'lead72' in sent:return None
        identity=f'{chat}:{reply}:{phase}'
    return {'id':sha256(identity.encode()).hexdigest(),'phase':phase,'text':text}
