"""Fotos y fichas obtenidas solo del catálogo actual del CRM."""
import base64
import json
import re
import unicodedata
from decimal import Decimal
from urllib.request import urlopen
from urllib.parse import urlsplit
from app.ramy_checkout import load, lock, product_mentions

ORIGIN='http://127.0.0.1:8000'

def norm(t):
    return ''.join(c for c in unicodedata.normalize('NFD',t.casefold()) if unicodedata.category(c)!='Mn')

def handle_product_photo(chat_id,text,previous=None):
    n=norm(text)
    if not re.search(r'\b(fotos?|imagenes?|catalogo|catalago|catalogue)\b',n): return None
    try:
        with urlopen(ORIGIN+'/api/tienda/catalogo',timeout=5) as r: products=json.load(r)
        if not isinstance(products,list): raise ValueError()
        products=[p for p in products if p.get('stock')=='disponible' and not p.get('demo') and not str(p.get('sku','')).upper().startswith(('PRUEBA-','DEMO-'))]
        try:
            matches=product_mentions(n,products)
        except ValueError:
            return {'reply':'Hay varios productos que coinciden. ¿De cuál quieres la foto?\n'+'\n'.join('• '+p['nombre'] for p in products[:10])}
        if not matches:
            with lock: chosen=load(chat_id).get('product',{}).get('id')
            matches=[p for p in products if p['id']==chosen]
        if not matches and previous:
            for message in reversed(previous[-8:]):
                content=norm(message.get('content',''))
                # Priorizar el último producto mencionado explícitamente.
                matches=[p for p in products if norm(str(p['nombre'])) in content]
                if matches: break
        if not matches and len(products)==1: matches=products
        if len(matches)!=1:
            listing='\n'.join('• '+p['nombre'] for p in products[:10])
            return {'reply':('Tenemos estos productos:\n'+listing+'\n¿De cuál quieres ver la foto?') if products else 'Ahora no hay productos disponibles en el catálogo. El equipo puede ayudarte.'}
        p=matches[0]
        price=Decimal(str(p['precio']))
        if not price.is_finite() or price<0: raise ValueError()
        description=str(p.get('descripcionCorta','')).strip()[:600]
        reply=f"{p['nombre']} — S/ {price:.2f}\n"+description+'\n¿Cuántas unidades deseas?'
        image=p.get('imagen','');u=urlsplit(image)
        pid=re.fullmatch(r'crm-(\d+)',str(p.get('id','')))
        if not pid or u.scheme!='https' or u.netloc!='crm.ramy.info' or u.path!=f'/api/tienda/productos/{pid.group(1)}/imagen':
            return {'reply':reply+'\nNo tengo una foto verificada para adjuntar. Puedes consultar https://www.ramy.info/'}
        # Construir la ruta local con ID, sin seguir URL proporcionada por cliente/catálogo.
        with urlopen(ORIGIN+u.path,timeout=5) as r:
            data=r.read(5*1024*1024+1)
        if not data or len(data)>5*1024*1024 or not data.startswith(b'\xff\xd8\xff'): raise ValueError()
        return {'reply':reply,'product_image_base64':base64.b64encode(data).decode()}
    except (OSError,ValueError,KeyError,TypeError):
        return {'reply':'No pude cargar la foto del catálogo ahora. Puedes ver los productos en https://www.ramy.info/ o pedir ayuda al equipo.'}
