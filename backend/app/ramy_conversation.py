"""RAMY_CONVERSACION_V1: resolver dudas sin escribir pedidos, precios ni pagos."""
import re
import unicodedata
from decimal import Decimal
from app import memory_store

def norm(text):return ''.join(c for c in unicodedata.normalize('NFD',text.casefold()) if unicodedata.category(c)!='Mn')

def conversational(text):
    n=norm(text)
    if re.search(r'\b(cancelar|confirmo|comprobante|codigo|clave|ya pague|ya deposite|yape|cci|bcp)\b',n):return False
    return bool(re.search(r'\b(confianza|confiar|estafa|me preocupa|caro|pensarlo|pesima atencion|reclamo|garantia|caracteristicas|descripcion|detalles|marca)\b',n)) or ('?' in text and not re.search(r'\b(precio|cuanto|pago|saldo|pedido|envio|entrega|shalom|retiro)\b',n))

def answer(chat_id,text,previous,catalog,checkout):
    n=norm(text).strip()
    location=bool(re.search(r'\b(direccion|ubicacion|donde|tienen|hay|ir)\b.*\b(local|tienda|fisic[oa]|ramy)\b|\b(local|tienda)\b.*\b(fisic[oa]|queda|direccion|ubicacion)\b|\bdonde (estan|se encuentran)\b',n))
    if n.strip(' .!?¿¡') in ('☝','☝️','👆'):
        last=next((m.get('content','') for m in reversed(previous) if m.get('role')=='assistant'),'')
        location=bool(re.search(r'\b(local|tienda fisica|tienda online)\b',norm(last)))
    if location:return {'reply':'Somos una tienda online 😊 Vendemos únicamente por internet y no tenemos local físico.\nPuedes ver nuestros productos en https://www.ramy.info/.\n¿Qué producto te interesa?'}
    # Compra explícita y operaciones sensibles siguen el flujo controlado existente.
    if re.search(r'\b(quiero comprar|quiero pedir|deseo comprar|hacer un pedido|codigo|clave|comprobante|ya pague|saldo|yape|cci|bcp)\b',n):return None
    price=bool(re.search(r'\b(precios?|cuanto(?: esta| cuesta| vale| sale| seria| es| en total)?|costo|valor)\b',n))
    complaint=bool(re.search(r'\b(pesima atencion|mala atencion|no me atiendes|no respondes)\b',n))
    if not (price or complaint):return None
    products=catalog()
    if products is None:return {'reply':'Disculpa, ahora no puedo confirmar el precio. El equipo puede ayudarte antes de que realices cualquier pago.'}
    products=[p for p in products if p.get('disponible',0)>0]
    if not products:return {'reply':'Por el momento no puedo ofrecerte un producto disponible. Puedes consultar con el equipo en https://www.ramy.info/.'}
    try:matches=checkout.product_mentions(checkout.norm(text),products)
    except ValueError:return {'reply':'Hay más de un producto que coincide. ¿Cuál deseas cotizar?'}
    explicit=bool(matches)
    draft=checkout.load(chat_id)
    if price and draft.get('order') and (not matches or (len(matches)==1 and matches[0]['id']==(draft.get('product') or {}).get('id'))):
        try:
            order=checkout.status(draft)
            amount=Decimal(str(order['total']))
            if not amount.is_finite() or amount<0:raise ValueError()
            return {'reply':f"El total de productos de tu pedido #{order['pedido_id']} es *S/ {amount:.2f}*.\nLos pagos y el estado se confirman por separado; no he modificado tu pedido."}
        except Exception:
            return {'reply':'Ahora no puedo confirmar el importe de tu pedido en el CRM. El equipo debe revisarlo antes de que realices otro pago.'}
    if price and not matches and len(draft.get('items', [])) > 1:
        lookup={p['id']:p for p in products}
        lines=draft['items']
        if any(l['product']['id'] not in lookup for l in lines):
            return {'reply':'Uno de los productos requiere confirmar su disponibilidad con el equipo. No he cambiado tu pedido.'}
        if all(isinstance(l.get('quantity'),int) and 1<=l['quantity']<=100 for l in lines):
            rows=[];total=Decimal('0')
            for line in lines:
                p=lookup[line['product']['id']];subtotal=Decimal(str(p['precio']))*line['quantity'];total+=subtotal
                rows.append(str(line['quantity'])+' x '+p['nombre']+' — S/ '+format(subtotal,'.2f'))
            return {'reply':'\n'.join(rows)+'\nTotal de productos: *S/ '+format(total,'.2f')+'*. El envío se confirma por separado.'}
    if not matches:
        draft=checkout.load(chat_id);pid=(draft.get('product') or {}).get('id') or memory_store.facts(chat_id).get('interest_id')
        if pid:matches=[p for p in products if p['id']==pid]
    if not matches:
        # Solo mensajes del cliente, no listas de productos generadas por Jessyca.
        for m in reversed(previous):
            if m.get('role')!='user':continue
            try:found=checkout.product_mentions(checkout.norm(m.get('content','')),products)
            except ValueError:found=[]
            if found:matches=found;break
    if len(matches)==1:
        p=matches[0]
        if explicit:memory_store.remember_interest(chat_id,p['id'])
        line=f"{p['nombre']} está a *S/ {Decimal(str(p['precio'])):.2f} por unidad* 😊."
        draft=checkout.load(chat_id);qty=draft.get('quantity')
        if (draft.get('product') or {}).get('id')==p['id'] and isinstance(qty,int) and 1<=qty<=100:
            line+=f"\nPor {qty} unidades: *S/ {Decimal(str(p['precio']))*qty:.2f}*."
        if complaint:line='Disculpa por la confusión. '+line
        if draft.get('product') and draft['product']['id']!=p['id']:
            return {'reply':line+'\nTu pedido actual sigue con '+draft['product']['nombre']+'; no lo he cambiado.'}
        if draft.get('order'):return {'reply':line+'\nEl estado y los pagos de tu pedido se verifican por separado.'}
        return {'reply':line+('\n¿Te gustaría continuar con la compra?' if draft else '\n¿Te gustaría hacer el pedido?')}
    if len(matches)>1:
        return {'reply':'Estos son los precios por unidad 😊:\n'+'\n'.join(p['nombre']+' — *S/ '+format(Decimal(str(p['precio'])),'.2f')+'*' for p in matches[:10])+'\n¿Cuál te interesa?'}
    already=any('precios disponibles' in m.get('content','').casefold() for m in previous if m.get('role')=='assistant')
    if already:return {'reply':('Disculpa por la confusión. ' if complaint else '')+'¿Qué producto te interesa? Dime su nombre y te doy el precio exacto 😊.'}
    return {'reply':('Disculpa por la confusión. ' if complaint else '')+'Te comparto los precios disponibles 😊:\n'+'\n'.join(p['nombre']+' — *S/ '+format(Decimal(str(p['precio'])),'.2f')+'*' for p in products[:10])+'\n¿Cuál te interesa?'}
