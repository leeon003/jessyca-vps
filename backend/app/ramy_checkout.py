"""Flujo de venta controlado; la IA nunca elige IDs de pago ni ejecuta operaciones."""
import base64
import hashlib
import json
import logging
import re
import secrets
import unicodedata
from pathlib import Path
from threading import RLock
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError
from decimal import Decimal
from app.ramy_sales import catalog
from app.ramy_payments import payment_reply

ROOT = Path('/home/admin/jessyca-whatsapp/data/checkout')
TOKEN = Path('/home/admin/.config/jessyca-conversaciones.env')
BASE = 'http://127.0.0.1:8000/api/interno/ventas'
lock = RLock()

def norm(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.casefold()) if unicodedata.category(c) != 'Mn').strip(' ¡!¿?.,😊👋«»\"“”\'')

def path(chat_id): return ROOT/(hashlib.sha256(chat_id.encode()).hexdigest()+'.json')
def load(chat_id):
    p = path(chat_id)
    if not p.exists(): return {}
    return json.loads(p.read_text())
def save(chat_id, state):
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    p = path(chat_id); temp = p.with_suffix('.tmp')
    temp.write_text(json.dumps(state, ensure_ascii=False)); temp.chmod(0o600); temp.replace(p)

def token():
    for line in TOKEN.read_text().splitlines():
        if line.startswith('JESSYCA_CONVERSATIONS_TOKEN='):
            value = line.split('=',1)[1].strip()
            if len(value) >= 32: return value
    raise ValueError('Credencial interna no configurada')

def api(endpoint, body=None, content_type='application/json'):
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    req = Request(BASE+endpoint, data=data, headers={'X-Conversations-Token':token(), 'Content-Type':content_type}, method='POST' if body is not None else 'GET')
    with urlopen(req, timeout=15) as response: return json.load(response)

def phone(chat_id):
    m = re.fullmatch(r'whatsapp:(51\d{9})@s\.whatsapp\.net', chat_id)
    return m.group(1) if m else None

def prompt(s):
    stage = s['stage']
    if stage == 'confirm': return summary(s)
    return {'product':'¿Qué producto deseas comprar? Puedes escribir su nombre.',
        'quantity':'¿Cuántas unidades deseas?', 'name':'¿Cuál es tu nombre completo?',
        'phone':'¿Cuál es tu número de WhatsApp? Escríbelo con 9 dígitos o con 51 delante.',
        'city':'¿En qué ciudad y distrito recibirás tu pedido?',
        'address':'¿Cuál es tu dirección o agencia de destino para la entrega?',
        'reference':'¿Tienes alguna referencia para la entrega? Si no, escribe «sin referencia».'}[stage]

def summary(s):
    total = Decimal(s['product']['precio'])*s['quantity']
    return (f"Revisa tu pedido:\n• {s['quantity']} x {s['product']['nombre']} — S/ {s['product']['precio']} por unidad\n"
        f"Total de productos: S/ {total:.2f}\nNombre: {s['name']}\nWhatsApp: {s['phone']}\n"
        f"Destino: {s['city']}\nDirección/agencia: {s['address']}\nReferencia: {s['reference'] or 'Sin referencia'}\n"
        'El costo y las condiciones de envío los confirma el equipo. ¿Confirmas que registre este pedido? Escribe «confirmo» o «cancelar compra».')

def response(text, **extra): return {'reply':text, **extra}

def payment_message(order):
    if order['estado'] in ('CANCELADO','ENTREGADO'):
        return response(f"Pedido #{order['pedido_id']}: {order['estado']}. No solicito otro depósito para este pedido.")
    payment = order.get('pago_actual')
    if not payment:
        return response(f"Pedido #{order['pedido_id']}: estado {order['estado']}. El equipo continuará el seguimiento; no hay otro pago pendiente habilitado.")
    if payment.get('estado') == 'NO_VERIFICADO':
        return response(f"El pago del pedido #{order['pedido_id']} no fue verificado. Consulta al equipo antes de depositar nuevamente; puedes enviar un comprobante corregido para revisión.")
    official = payment_reply('medios de pago')['reply'].split('Antes de depositar,')[0].strip()
    return response(f"Tu pedido #{order['pedido_id']} quedó registrado.\nTotal de productos: S/ {order['total']}\n"
        f"Importe de {payment['tipo'].lower()} pendiente: S/ {payment['monto']}\n\n" + official +
        '\nEnvía el comprobante como foto JPG, PNG o WebP en este chat. Quedará pendiente de revisión manual; enviar una imagen no confirma el pago.', payment_qr=True)

def status(s):
    return api('/pedidos/'+str(s['order']['pedido_id'])+'?'+urlencode({'whatsapp':s['phone']}))

# RAMY_CHECKOUT_CONVERSACIONAL_V2
# RAMY_COMPRA_NATURAL_V3
PRICE = re.compile(r'\b(precios?|cuanto(?:s)?(?: cuesta| vale| sale| es| seria| por| en total)?|costo|valor)\b')
QUESTION = re.compile(r'\b(precio|cuanto|cual|como|cuando|donde|garantia|disponible|disponibilidad|envio|pagar|pago|yape|bcp|confirmo|cancelar|gracias|hola|ayuda|comprar)\b')

def is_question(text):
    return '?' in text or '¿' in text or bool(QUESTION.search(norm(text)))

def valid_name(text):
    parts = text.strip().split()
    return (3 <= len(text.strip()) <= 180 and len(parts) >= 2 and not is_question(text)
        and all(c.isalpha() or c in " -'’" for c in text.strip()))

def valid_field(field, value):
    if field == 'name': return valid_name(value or '')
    if field == 'phone': return bool(re.fullmatch(r'519\d{8}', value or ''))
    limits = {'city': (2,120), 'address': (3,1000), 'reference': (0,500)}
    lo, hi = limits[field]
    return isinstance(value,str) and lo <= len(value.strip()) <= hi and not is_question(value)

def repair_draft(s):
    if s.get('order') or not s.get('product') or not s.get('quantity'): return False
    fields = ['name','phone','city','address','reference']
    stages = ['name','phone','city','address','reference','confirm']
    if s.get('stage') not in stages: return False
    reached = stages.index(s['stage'])
    for i, field in enumerate(fields):
        if i >= reached: break
        if not valid_field(field, s.get(field)):
            for later in fields[i:]:
                if later != 'phone': s.pop(later,None)
            s['stage'] = field
            return True
    return False

def price_reply(s):
    product = s.get('product')
    if not product: return None
    products = catalog()
    if products is None: return response('No puedo verificar el precio ahora. No avances con un depósito; consultaré el catálogo cuando esté disponible.')
    current = next((p for p in products if p['id'] == product['id']), None)
    if not current: return response('El producto ya no aparece en el catálogo disponible. El equipo debe confirmar su disponibilidad antes de continuar.')
    s['product'] = current
    value = Decimal(str(current['precio']))
    reply = f"El {current['nombre']} cuesta S/ {value:.2f} por unidad."
    if s.get('quantity'): reply += f"\nPor {s['quantity']} unidades: S/ {value*s['quantity']:.2f}."
    return response(reply + '\nEl envío se confirma por separado.\n' + prompt(s))

def handle_checkout(chat_id, text, previous=None):
    with lock:
        s = load(chat_id); n = norm(text)
        if re.search(r'\b(cancelar compra|cancela(?:r)? (?:el )?pedido|ya no deseo|no deseo|ya no quiero|no quiero comprar|dejalo|yo te aviso|te aviso luego|mas adelante|por ahora no)\b', n):
            if s.get('order'): return response('El pedido ya está registrado. Una persona del equipo debe gestionar su cancelación; no lo he cancelado.')
            save(chat_id, {}); return response('Detuve esta solicitud de compra. Gracias por avisarme; cuando quieras retomarla, aquí estaré. 😊')
        start = bool(re.search(r'\b(quiero comprar|quiero pedir|hacer (?:un |el )?pedido|lo quiero|comprar ahora|quiero el|quiero un|quiero una)\b', n))
        previous = previous or []
        last_assistant = next((m.get('content','') for m in reversed(previous) if m.get('role')=='assistant'), '')
        accepted_offer = n in ('si','si quiero','si por favor') and bool(re.search(r'\b(comprar|pedido)\b', norm(last_assistant)))
        if not s and not start and re.search(r'\b(deseo|quiero|comprar|pedir|llevo)\b', n):
            candidates = catalog()
            start = bool(candidates and any(norm(p['nombre']) in n for p in candidates))
        start = start or accepted_offer
        if not s and not start: return None
        if not s:
            s = {'stage':'product','request':secrets.token_hex(24)}
            if phone(chat_id): s['phone'] = phone(chat_id)
        if s.get('order'):
            if start: return response('Ya tienes un pedido registrado en este chat. Para otro pedido, escribe «nueva compra».')
            if n == 'nueva compra':
                save(chat_id, {}); return handle_checkout(chat_id, 'quiero comprar')
            # RAMY_CODIGO_LIBERADO_V1: datos de retiro solo desde respuesta autorizada del CRM.
            wants_status = bool(re.search(r'\b(codigo|clave|retiro|retirar|shalom|estado|pago|pagar|pague|transferi|yape|bcp|cci|qr|comprobante|deposite)\b', n)) or n in ('ok','okay','listo','gracias','muchas gracias','ya envie','si','confirmo')
            if wants_status:
                try:
                    order = status(s); s['order'] = order; save(chat_id,s)
                    code = order.get('codigo_retiro')
                    if code and re.fullmatch(r'\d{4}',str(code)) and order['estado'] in ('CODIGO_LIBERADO','ENTREGADO'):
                        return response(f"El equipo autorizó el código de retiro de tu pedido #{order['pedido_id']}: {code}.\nGuárdalo y compártelo únicamente al retirar tu pedido.")
                    if re.search(r'\b(codigo|clave|retiro|retirar|shalom)\b',n):
                        return response(f"El código de retiro del pedido #{order['pedido_id']} todavía no está habilitado para compartir. El equipo debe liberarlo manualmente en el CRM.")
                    payment = order.get('pago_actual')
                    if n in ('ok','okay','listo','gracias','muchas gracias','si','confirmo') or (payment and payment.get('comprobante_recibido')):
                        if payment and payment.get('comprobante_recibido') and payment.get('estado') == 'EN_REVISION':
                            return response(f"El comprobante de tu pedido #{order['pedido_id']} sigue pendiente de revisión del equipo. No necesitas repetir el depósito. 😊")
                        return response(f"Tu pedido #{order['pedido_id']} está registrado, con estado {order['estado']}. El equipo continuará con el siguiente paso. 😊")
                except Exception:
                    return response('No pude comprobar el estado del pedido en el CRM. El equipo debe revisarlo; no comparto ningún código ni solicito otro depósito.')
            if any(w in n for w in ['pago','pagar','pague','transferi','yape','bcp','cci','qr','estado','comprobante','deposite','ya envie']):
                try:
                    order = status(s); s['order'] = order; save(chat_id,s)
                    if any(w in n for w in ('pague','deposite','transferi','comprobante','ya envie')) and order.get('pago_actual'):
                        if order['pago_actual'].get('estado') == 'NO_VERIFICADO': return payment_message(order)
                        if order['pago_actual'].get('comprobante_recibido'):
                            return response(f"El comprobante del pedido #{order['pedido_id']} está registrado y pendiente de revisión. El equipo debe verificar el pago; no necesitas repetir el depósito.")
                        return response(f"Envía el comprobante del pedido #{order['pedido_id']} como una foto JPG, PNG o WebP de hasta 8 MB en este chat. Lo registraré para revisión, sin aprobar automáticamente el pago.")
                    return payment_message(order)
                except Exception: return response('No pude consultar el estado del pedido. No deposites otro importe hasta que el equipo lo confirme.')
            return None
        correction = re.search(r'\b(?:quiero|deseo|cambia(?:r)?(?: a)?|mejor)\s+(\d{1,3})(?:\s*(?:unidades?|nomas|no mas))?\b', n)
        if correction and s.get('product') and s.get('quantity'):
            quantity = int(correction.group(1))
            if not 1 <= quantity <= 100: return response('La cantidad debe estar entre 1 y 100 unidades.')
            s['quantity'] = quantity
            if s.get('stage') == 'name':
                name = re.split(r'\b(?:me equivoqu[eé]|quiero|deseo|mejor|cambia)\b', text, maxsplit=1, flags=re.I)[0].strip(' ,.;')
                if valid_name(name):
                    s['name'] = name; s['stage'] = 'city' if s.get('phone') else 'phone'
            repair_draft(s)
            reply = price_reply(s); save(chat_id,s); return reply
        repaired = repair_draft(s)
        if repaired: save(chat_id,s)
        if PRICE.search(n) and s.get('product'):
            reply = price_reply(s); save(chat_id,s); return reply
        if repaired:
            return response('Necesito corregir los datos anteriores antes de registrar el pedido. No he registrado un nuevo pedido.\n'+prompt(s))
        # Consultas durante la recopilación pasan a la IA sin convertirlas en datos.
        if n in ('hola','holi','buenas'): return None
        if is_question(text) and s['stage'] not in ('product','confirm'): return None
        stage = s['stage']
        if stage == 'product':
            products = catalog()
            if products is None: return response('No puedo verificar el catálogo ahora. Inténtalo de nuevo antes de confirmar la compra.')
            selection = norm(last_assistant) if accepted_offer else n
            matches = [p for p in products if norm(p['nombre']) in selection]
            if len(matches) != 1:
                save(chat_id,s)
                available = '\n'.join('• '+p['nombre']+' — S/ '+p['precio'] for p in products[:10])
                return response('Elige un producto disponible:\n'+available+'\n'+prompt(s))
            s['product'] = matches[0]; s['stage'] = 'quantity'
            initial = re.search(r'\b(?:quiero|deseo|llevo|pedir|comprar)\s+(\d{1,3})\b', n)
            if not initial:
                initial = re.search(r'\b(\d{1,3})\s+unidades?\b', n)
            if initial and 1 <= int(initial.group(1)) <= 100:
                s['quantity'] = int(initial.group(1)); s['stage'] = 'name'
                save(chat_id,s); return price_reply(s)
            save(chat_id,s)
            return response(f"El {s['product']['nombre']} cuesta S/ {Decimal(str(s['product']['precio'])):.2f} por unidad.\n"+prompt(s))
        elif stage == 'quantity':
            m = re.fullmatch(r'(\d{1,3})(?:\s*(?:unidades?|por favor))?', n)
            if not m or not 1 <= int(m.group(1)) <= 100: return response('Indica una cantidad entre 1 y 100 unidades. El CRM comprobará el stock antes de registrar.')
            s['quantity'] = int(m.group(1)); s['stage'] = 'name'
        elif stage == 'name':
            if not valid_name(text): return response('Escribe tu nombre completo para el pedido.')
            s['name'] = text.strip(); s['stage'] = 'city' if s.get('phone') else 'phone'
        elif stage == 'phone':
            value = re.sub(r'[\s+()-]', '', text)
            if re.fullmatch(r'9\d{8}', value): value = '51'+value
            if not re.fullmatch(r'519\d{8}', value): return response('Escribe un celular peruano de 9 dígitos, empezando con 9.')
            s['phone'] = value; s['stage'] = 'city'
        elif stage in ('city','address','reference'):
            limit = {'city':120,'address':1000,'reference':500}[stage]
            if not valid_field(stage, '' if stage == 'reference' and n in ('sin referencia','ninguna','no') else text.strip()): return response(prompt(s))
            s[stage] = '' if stage == 'reference' and n in ('sin referencia','ninguna','no') else text.strip()
            s['stage'] = {'city':'address','address':'reference','reference':'confirm'}[stage]
        elif stage == 'confirm':
            if n not in ('si','si confirmo','confirmo','confirmar','confirmo el pedido'): return response(summary(s))
            p = s['product']
            match = re.fullmatch(r'crm-(\d+)', p['id'])
            if not match: return response('No pude identificar este producto en el CRM. El equipo debe revisarlo.')
            payload = {'solicitud_id':s['request'],'nombre_completo':s['name'],'whatsapp':s['phone'],
                'provincia':s['city'],'direccion':s['address'],'referencia':s['reference'],
                'producto_id':int(match.group(1)),'cantidad':s['quantity'], 'precio_esperado':p['precio'],'confirmado':True}
            save(chat_id,s)  # ID estable antes de llamar: reintentar no duplica pedidos.
            try:
                s['order'] = api('/pedidos', payload); s['stage'] = 'receipt'; save(chat_id,s)
                return payment_message(s['order'])
            except HTTPError as e:
                logging.getLogger(__name__).error('RAMY_PEDIDO_REGISTRO HTTP=%s', e.code)
                if e.code == 409:
                    products = catalog() or []
                    updated = next((x for x in products if x['id'] == p['id']), None)
                    if updated: s['product'] = updated
                    else: s.pop('product',None); s['stage']='product'
                    save(chat_id,s)
                    return response('El precio o la disponibilidad cambió, o la cantidad supera el stock. No se confirmó un nuevo pedido. Reduce la cantidad escribiendo «cancelar compra» y comienza nuevamente, o revisa el resumen actualizado:\n'+prompt(s))
                return response('No se confirmó el registro del pedido. Intenta escribir «confirmo» otra vez o solicita ayuda del equipo; no deposites todavía.')
            except Exception as e:
                logging.getLogger(__name__).error('RAMY_PEDIDO_REGISTRO error=%s', type(e).__name__)
                return response('No pude confirmar el registro del pedido. El equipo debe revisar la conexión al CRM; no deposites todavía. Puedes reintentar con «confirmo» o dejar la compra para después.')
        save(chat_id,s)
        return response(prompt(s))

def expects_receipt(chat_id):
    with lock: return bool(load(chat_id).get('order'))

def checkout_context(chat_id):
    with lock:
        s = load(chat_id)
        if not s.get('product'): return ''
        if s.get('order'):
            return ('\nProducto seleccionado: '+s['product']['nombre']+'. El pedido ya está registrado. '
                'Resuelve la duda sin volver a pedir datos o confirmar otro pedido. Para estados de pago o envío se consulta el CRM, nunca se infieren.')
        # Datos de la venta, sin dirección, nombre, cuentas ni IDs internos para la IA.
        return ('\nProducto seleccionado por el cliente: '+s['product']['nombre']+
            '. Está en una compra en curso. Resuelve la duda y luego retoma la pregunta pendiente: '+
            (prompt(s) if s.get('stage') in ('quantity','name','phone','city','address','reference') else 'confirmar el resumen del pedido.'))

def receive_receipt(chat_id, image):
    with lock:
        s = load(chat_id)
        if not s.get('order'): return None
        try:
            order = status(s); s['order']=order; save(chat_id,s)
            payment = order.get('pago_actual')
            if not payment: return response('Este pedido no tiene un pago pendiente habilitado. El equipo revisará tu consulta; no he registrado otro comprobante.')
            raw = base64.b64decode(image.split(',',1)[-1] if image.startswith('data:') else image, validate=True)
            if not raw or len(raw)>8*1024*1024: return response('Envía una imagen JPG, PNG o WebP de hasta 8 MB.')
            kind = 'image/jpeg' if raw.startswith(b'\xff\xd8\xff') else 'image/png' if raw.startswith(b'\x89PNG\r\n\x1a\n') else 'image/webp' if raw[:4]==b'RIFF' and raw[8:12]==b'WEBP' else None
            if not kind: return response('El comprobante debe ser una foto JPG, PNG o WebP.')
            boundary = 'ramy-'+secrets.token_hex(16)
            data = (f'--{boundary}\r\nContent-Disposition: form-data; name="whatsapp"\r\n\r\n{s["phone"]}\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="comprobante"; filename="comprobante"\r\nContent-Type: {kind}\r\n\r\n').encode()+raw+f'\r\n--{boundary}--\r\n'.encode()
            result = api('/pagos/'+str(payment['id'])+'/comprobante', data, 'multipart/form-data; boundary='+boundary)
            if result.get('estado') != 'EN_REVISION': raise ValueError('Respuesta inesperada')
            return response(f"Tu comprobante quedó registrado en el pedido #{order['pedido_id']} y está pendiente de revisión. El equipo comprobará el pago y te indicará el siguiente paso. 😊")
        except Exception:
            return response('No pude confirmar que el comprobante quedara registrado. Reenvíalo como una foto nueva o solicita ayuda del equipo. No hemos confirmado el pago.')
