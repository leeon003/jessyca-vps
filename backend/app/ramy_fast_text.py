"""Vía rápida de texto: nunca invoca Ollama ni modifica verificación de pagos."""
import re,unicodedata
from decimal import Decimal

def norm(text):return ''.join(c for c in unicodedata.normalize('NFD',text.casefold()) if unicodedata.category(c)!='Mn')

def try_fast(message,api):
    text=message.text.strip();n=norm(text)
    if not text:return {'reply':'Escribe tu consulta para ayudarte.','needs_ai':False}
    if len(text)>2000:return {'reply':'¿Puedes enviarme tu consulta en mensajes más cortos?','needs_ai':False}
    with api.memory_lock:previous=list(api.histories.get(message.chat_id,[]))[-8:]
    result=api.handle_product_photo(message.chat_id,text,previous)
    if result is None and re.search(r'\b(caracteristicas?|descripcion|detalles|que incluye|para que sirve|como funciona|como se usa|garantia)\b',n):
        from app.ramy_checkout import product_mentions, load, prompt
        products=api.consultar_productos()
        if products is None:
            result={'reply':'No puedo comprobar la ficha del producto ahora. El equipo puede ayudarte antes de confirmar una compra.'}
        else:
            products=[p for p in products if p.get('disponible',0)>0]
            draft=load(message.chat_id)
            try:matches=product_mentions(n,products)
            except ValueError:
                matches=[]
                result={'reply':'Hay varios productos que coinciden. Dime el nombre completo para darte la información correcta.'}
            if result is None:
                if not matches and draft.get('product'):
                    matches=[p for p in products if p['id']==draft['product']['id']]
                if not matches and len(products)==1:matches=products
                if len(matches)!=1:
                    result={'reply':'¿De cuál producto quieres la información?\n'+'\n'.join('• '+p['nombre'] for p in products[:10])}
                else:
                    p=matches[0]
                    description=p.get('descripcion') or p.get('descripcionCorta') or ''
                    info=('La garantía no está especificada en esta ficha. El equipo debe confirmártela antes de comprar.' if 'garantia' in n and 'garant' not in norm(description) else 'Esto figura en la ficha del producto: '+description if description else 'La ficha no tiene una descripción adicional. El equipo puede confirmar ese detalle.')
                    next_step=prompt(draft) if draft.get('stage') and not draft.get('order') else '¿Qué otro dato del producto necesitas?'
                    result={'reply':f"{p['nombre']} — S/ {Decimal(str(p['precio'])):.2f}\n{info}\n{next_step}"}
    if result is None:result=api.handle_checkout(message.chat_id,text,previous)
    if result is None:result=api.payment_reply(text)
    if result is None and n.strip(' ¡!¿?.,:;😊👋✨\n\t') in ('hola','holi','holis','buenas','buenos dias','buenas tardes','buenas noches'):
        result={'reply':'Soy JESSYCA, asesora de ventas de Tiendas RAMY. ¡Hola! 😊\n¿En qué puedo ayudarte hoy con nuestros productos? 🛍️✨'}
    if result is None and re.search(r'\b(crm|vps|servidor|software)\b',n):
        result={'reply':'En Tiendas RAMY vendemos los productos de nuestro catálogo. Puedes verlos en https://www.ramy.info/. ¿Qué producto buscas?'}
    wants_catalog=any(p in n for p in ('que productos','que vendes','catalogo','catalago','productos disponibles','que tienes disponible'))
    wants_price=bool(re.search(r'\b(precios?|cuanto cuesta|cuanto vale|cuanto sale|costo)\b',n))
    if result is None and (wants_catalog or wants_price):
        products=api.consultar_productos()
        if products is None:result={'reply':'No puedo consultar el catálogo ahora. No avances con un depósito; el equipo puede ayudarte.'}
        else:
            products=[p for p in products if p.get('disponible',0)>0]
            if not products:result={'reply':'Ahora no hay productos disponibles en el catálogo. El equipo puede ayudarte.'}
            elif wants_catalog:
                result={'reply':'Estos son nuestros productos disponibles:\n'+'\n'.join('• '+p['nombre']+' — S/ '+str(p['precio']) for p in products[:10])+'\n¿Cuál te gustaría conocer mejor?'}
            else:
                from app.ramy_checkout import product_mentions
                try:matches=product_mentions(n,products)
                except ValueError:matches=[]
                if not matches:
                    for m in reversed(previous):
                        if m.get('role')!='assistant':continue
                        try:matches=product_mentions(norm(m.get('content','')),products)
                        except ValueError:matches=[]
                        if matches:break
                if len(matches)==1:
                    p=matches[0];result={'reply':f"El {p['nombre']} cuesta S/ {Decimal(str(p['precio'])):.2f} por unidad.\nEl envío se confirma por separado. ¿Cuántas unidades deseas?"}
                else:result={'reply':'¿De cuál producto quieres saber el precio?\n'+'\n'.join('• '+p['nombre'] for p in products[:10])}
    if result is None:return {'needs_ai':True}
    api.save_conversation(message.chat_id,previous,text,result['reply'])
    return {**result,'needs_ai':False}
