"""Cierre comercial determinista; el registro y pago continúan en el backend existente."""
import re
from decimal import Decimal
from threading import local
_guard=local()
TERMS=('Separas tu pedido con *S/10*, que se descuentan del total. '
       '*El saldo lo completas al recoger en Shalom, antes de retirar el producto*. '
       '*El envío lo pagas aparte*. Los pagos los revisa una persona del equipo.')
DELIVERY='El envío por Shalom demora aproximadamente *3 días desde el despacho*. Es un plazo estimado, no una fecha garantizada. El envío lo pagas aparte.'

def run_original(c,chat,text,previous):
    before=getattr(_guard,'active',False);_guard.active=True
    try:return c.handle_checkout(chat,text,previous)
    finally:_guard.active=before

def query(text,c):
    n=c.norm(text)
    n=re.sub(r'\b(?:provincia|departamento|distrito|agencias?|shalom|envio|para|en|la|el|de|del|es|a|por|recoger|recojo)\b',' ',n)
    return ' '.join(n.split())[:200]

NOTICE=('Para preparar tu pedido, te pediré el nombre y DNI de quien recogerá y elegiremos la agencia Shalom 😊. '
        '*Al confirmar la agencia con tus datos completos, registraremos tu pedido*. '
        'Después te compartiré el detalle y los medios para realizar el adelanto de *S/10*.')

def notice_question(c,chat,s,question):
    if not s.get('_registration_notice_sent'):
        s['_registration_notice_sent']=True;c.save(chat,s)
        return c.response(NOTICE+'\n'+question)
    return c.response(question)

def finish(c,chat,s,previous):
    # Nunca ejecutar el registro por una mera pregunta ni antes de completar el borrador.
    if not s.get('_sales_intent'):return None
    if s.get('order'):return None
    if not s.get('product'):return None
    if not all(type(x.get('quantity')) is int and 1<=x['quantity']<=100 for x in c.cart(s)):return c.response(c.quantity_prompt(s))
    if not s.get('name'):s['stage']='name';c.save(chat,s);return notice_question(c,chat,s,'¿Quién recogerá el pedido? Compárteme su nombre completo y DNI de 8 dígitos, por favor 😊.')
    from app.ramy_recipient import valid_dni
    if not valid_dni(s.get('dni_destinatario')):s['stage']='dni';c.save(chat,s);return notice_question(c,chat,s,'Gracias 😊. ¿Cuál es el DNI de 8 dígitos de quien recogerá el pedido?')
    if not s.get('phone'):s['stage']='phone';c.save(chat,s);return notice_question(c,chat,s,'¿Cuál es el WhatsApp de contacto?')
    if not s.get('_agency_confirmed'):
        if s.get('stage') in ('agency_choose','agency_confirm','agency_location','agency_wait'):return None
        s['stage']='city';c.save(chat,s)
        dest=s.pop('_destination_query',None)
        if dest:
            c.save(chat,s)
            from app.ramy_agency_flow import handle_agency
            handled,r=handle_agency(chat,dest,s,c.api,c.save,c.summary,c.is_question)
            # Una agencia nombrada expresamente y única puede pasar a confirmación final.
            choices=s.get('_agency_choices',[])
            if handled and len(choices)==1 and s.pop('_agency_explicit',False):
                a=choices[0];n=c.norm(dest)
                meaningful=[t for t in c.norm(a['nombre']).split() if t not in ('av','calle','jr','shalom','agencia')]
                if meaningful and all(t in n.split() for t in meaningful):
                    s['_agency_pending']=a;s['stage']='agency_confirm';c.save(chat,s)
                    handle_agency(chat,'si',s,c.api,c.save,c.summary,c.is_question)
                    return finish(c,chat,c.load(chat),previous)
            return r
        return notice_question(c,chat,s,'¿A qué departamento enviamos tu pedido? Si ya sabes la agencia Shalom, puedes indicármela directamente 😊.')
    s['stage']='confirm';c.save(chat,s)
    details=c.summary(s).split('Enviamos por Shalom')[0].rstrip()
    result=run_original(c,chat,'confirmo',previous)
    current=c.load(chat)
    if current.get('order') and result and result.get('payment_qr'):
        return {**result,'reply':details+'\n'+TERMS+'\n\n'+result['reply']}
    return result

def dispatch(c,chat,text,previous=None):
    if getattr(_guard,'active',False):return False,None
    previous=previous or [];n=c.norm(text)
    with c.lock:
        s=c.load(chat)
        if re.search(r'\b(cancelar|cancela|no deseo|ya no quiero|yo te aviso|nueva compra)\b',n):return False,None
        sensitive=bool(re.search(r'\b(ya pague|ya deposite|comprobante|codigo|clave|yape|bcp|cci)\b',n))
        payment_question=(not sensitive and bool(re.search(r'\b(pago|pagar|adelanto|anticipo|contra entrega|contraentrega|al recoger|envio(?: es)? gratis|envio(?: es)? gratuito|flete)\b',n)))
        if payment_question:return True,c.response(TERMS+('' if s.get('order') else '\n'+next_question(c,s)))
        if c._ramy_delivery_question(n):return True,c.response(DELIVERY+('' if s.get('order') else '\n'+next_question(c,s)))
        if s.get('order'):return False,None
        if sensitive:return False,None
        price=bool(re.search(r'\b(precios?|cuanto|cuánto|cuesta|valor)\b',n))
        if price and not re.search(r'\b(foto|imagen)\b',n):
            products=c.catalog()
            if not products:return True,c.response('Ahora no puedo verificar el precio. No realices un depósito hasta confirmarlo.')
            try:matches=c.product_mentions(n,products)
            except ValueError:matches=[]
            if len(matches)==1:
                p=matches[0]
                if not s:
                    run_original(c,chat,'quiero comprar '+p['nombre'],previous);s=c.load(chat)
                    if s.get('product'):s['_sales_intent']=False;c.save(chat,s)
                return True,c.response(f"{p['nombre']} está a *S/ {Decimal(str(p['precio'])):.2f} por unidad* 😊.\n"+next_question(c,s))
            return False,None
        yes=n in ('si','si quiero','si por favor','claro','dale')
        # Retomar el producto conocido de memoria, sin inferirlo desde una lista de la asesora.
        if not s and yes:
            try:
                from app.memory_store import facts
                pid=facts(chat).get('interest_id');products=c.catalog() or [];known=[p for p in products if p['id']==pid]
            except Exception:known=[]
            if len(known)==1:run_original(c,chat,'quiero comprar '+known[0]['nombre'],previous);s=c.load(chat)
        if not s.get('product'):return False,None
        if not c.is_question(text) and re.fullmatch(c.product_pattern(s['product']),n):return True,c.response(next_question(c,s))
        if yes and s.get('stage')=='quantity':s['_sales_intent']=True;c.save(chat,s);return True,c.response('Claro 😊. ¿Cuántas unidades deseas?')
        if re.search(r'\b(quiero|deseo|mejor|cambia|solo)\b',n):return False,None
        if s.get('stage') in ('name','dni','city','agency_choose','agency_wait') and not c.is_question(text):
            packet=re.search(r'(?<!\d)([0-9]{8})(?!\d)',text)
            if packet and ('dni' in n or s.get('stage') in ('name','dni')):
                s['dni_destinatario']=packet.group(1)
                prefix=text[:packet.start()];prefix=re.sub(r'(?i)\b(?:mi nombre es|nombre completo|nombre|dni|documento)\s*[:=-]?','',prefix).strip(' ,;:.\n')
                if c.valid_name(prefix):s['name']=prefix
                tail=text[packet.end():]
                if re.search(r'(?i)\b(agencia|shalom|para)\b',tail):
                    s['_destination_query']=query(tail,c);s['_agency_explicit']=True
                    s['stage']='city'
                s['_sales_intent']=True;c.save(chat,s)
                return True,finish(c,chat,s,previous) or c.response(next_question(c,s))
        location=(bool(re.search(r'\b(para|departamento|provincia|distrito|agencias?|shalom)\b',n)) and not c.is_question(text))
        if location and s.get('stage') not in ('agency_choose','agency_confirm','agency_location','agency_wait'):
            destination=query(text,c)
            if destination:
                s['_destination_query']=destination;s['_agency_explicit']=bool(re.search(r'\b(agencia|shalom)\b',n));s['_sales_intent']=True;c.save(chat,s)
                result=finish(c,chat,s,previous)
                return True,result or c.response(next_question(c,s))
        if s.get('stage')=='quantity':
            # Aceptar «1 una unidad» y «una unidad», sin tomar DNI/teléfono como cantidad.
            q=re.fullmatch(r'(\d{1,3})(?:\s+(?:una?|uno))?(?:\s+(?:unidad(?:es)?|par(?:es)?))?',n)
            words={'un':1,'una':1,'uno':1,'dos':2,'tres':3,'cuatro':4,'cinco':5,'seis':6,'siete':7,'ocho':8,'nueve':9,'diez':10}
            w=re.fullmatch(r'(un|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)(?:\s+(?:unidad(?:es)?|par(?:es)?))?',n)
            qty=int(q.group(1)) if q else words[w.group(1)] if w else None
            if qty is None and not c.is_question(text):
                try:mentioned=c.product_mentions(n,c.catalog() or [])
                except ValueError:mentioned=[]
                unit=re.search(r'(?<![0-9])([0-9]{1,3})\s+(?:(?:una?|uno)\s+)?unidad(?:es)?\b',n)
                if unit and len(mentioned)==1 and mentioned[0]['id']==s['product']['id']:qty=int(unit.group(1))
            if qty is not None:
                if not 1<=qty<=100:return True,c.response('Indícame una cantidad de 1 a 100 unidades, por favor.')
                s['_sales_intent']=True;c.save(chat,s);result=run_original(c,chat,str(qty),previous);s=c.load(chat)
                reply=finish(c,chat,s,previous) or result
                if not s.get('_sales_terms_sent'):
                    current=c.load(chat);current['_sales_terms_sent']=True;c.save(chat,current);reply={**reply,'reply':TERMS+'\n'+reply['reply']}
                return True,reply
        if s.get('stage') in ('name','dni') and not c.is_question(text):
            # DNI acompañado de nombre, o cada dato por separado.
            docs=re.findall(r'(?<!\d)[0-9]{8}(?!\d)',text)
            if len(docs)==1:
                s['dni_destinatario']=docs[0]
                name=re.sub(r'(?i)\b(?:mi nombre es|nombre completo|nombre|dni|documento|mi dni es)\s*[:=-]?','',text.replace(docs[0],'' )).strip(' ,;:.\n')
                if c.valid_name(name):s['name']=name
                s['_sales_intent']=True;c.save(chat,s);return True,finish(c,chat,s,previous) or c.response(next_question(c,s))
            if s['stage']=='name' and c.valid_name(text):
                s['name']=text.strip();s['_sales_intent']=True;c.save(chat,s);return True,finish(c,chat,s,previous) or c.response(next_question(c,s))
        if s.get('stage') in ('agency_choose','agency_confirm','agency_location','agency_wait','city'):
            if c.is_question(text) and not re.search(r'\b(agencia|shalom|cerca)\b',n):return False,None
            if s.get('stage')=='city':s['_sales_intent']=True
            from app.ramy_agency_flow import handle_agency
            handled,result=handle_agency(chat,text,s,c.api,c.save,c.summary,c.is_question)
            if handled and result:
                s=c.load(chat)
                if s.get('_agency_confirmed') and s.get('_sales_intent'):return True,finish(c,chat,s,previous) or result
                return True,result
        return False,None

def next_question(c,s):
    if not s.get('product'):return '¿Qué producto te interesa?'
    if not s.get('quantity'):return '¿Cuántas unidades deseas?'
    if not s.get('name'):return '¿Quién recogerá el pedido? Compárteme su nombre completo y DNI, por favor.'
    if not s.get('dni_destinatario'):return '¿Cuál es el DNI del destinatario?'
    if s.get('agency'):return 'Podemos continuar con los datos que faltan del pedido.'
    if s.get('_destination_query'):return 'Conservo el destino que indicaste; continuemos con los datos del destinatario.'
    return '¿A qué departamento enviamos tu pedido?'
