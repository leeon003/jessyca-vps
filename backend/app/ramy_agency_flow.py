"""Selección persistente de agencias: IDs solo del CRM, ninguna aprobación por el LLM."""
import re,unicodedata
from urllib.parse import urlencode

def norm(s):
    return ' '.join(re.sub(r'[^a-z0-9 ]',' ',unicodedata.normalize('NFKD',str(s)).encode('ascii','ignore').decode().lower()).split())

def agency_prompt(s):
    stage=s.get('stage')
    if stage=='city':return '¿A qué departamento enviamos tu pedido? 📦'
    if stage in ('address','reference') and not s.get('order'):return 'Elegiremos una agencia Shalom para el recojo, sin domicilio. ¿A qué departamento enviamos tu pedido?'
    if stage=='agency_location':return '¿En qué departamento o provincia está ese lugar?'
    if stage=='agency_choose':return '¿Qué agencia prefieres? Responde con el número, nombre o dirección; también puedes pedir «más agencias».'
    if stage=='agency_confirm':
        a=s.get('_agency_pending') or {}
        return f"Elegiste Shalom {a.get('nombre','')}, en {a.get('direccion','')}, {a.get('provincia','')}. ¿Confirmas esa agencia para el recojo?"
    if stage=='agency_wait':return 'El destino sigue siendo '+str((s.get('_agency_filter') or {}).get('q','el que indicaste'))+'. Aún necesitamos confirmar las agencias disponibles allí. No hace falta cambiar de destino; el equipo de Tiendas RAMY debe completar esta revisión antes de registrar el pedido.'
    return None

def handle_agency(chat,text,s,api,save,summary,is_question):
    n=norm(text);stage=s.get('stage');answer=lambda v:(True,{'reply':v})
    relevant=stage in ('name','dni','city','address','reference','agency_location','agency_choose','agency_confirm','agency_wait') or (stage=='confirm' and not s.get('_agency_confirmed'))
    changing=bool(re.search(r'\b(cambiar|cambia|modificar|otra agencia|otro destino)\b',n) and re.search(r'\b(agencia|destino|envio)\b',n))
    if s.get('order'):return False,None
    if not relevant and not changing:
        # Revalidar antes de registrar: agencia retirada o dirección cambiada obliga nueva confirmación.
        if stage=='confirm' and n in ('si','si confirmo','confirmo','confirmar','confirmo el pedido'):
            try:
                a=api('/agencias/'+str(s['agency']['ter_id']))
                if a.get('version')!=s['agency'].get('version'):raise ValueError('Cambio de agencia')
            except Exception:
                s['stage']='agency_wait';s.pop('_agency_confirmed',None);save(chat,s)
                return answer('Necesitamos revisar nuevamente la agencia antes de registrar el pedido. No deposites todavía; el equipo debe confirmarla.')
        return False,None
    if changing:
        for k in ('agency','_agency_pending','_agency_confirmed','_agency_choices','_agency_places','_agency_filter','_ramy_await_district'):
            s.pop(k,None)
        s['stage']='city';save(chat,s)
        return answer(agency_prompt(s))
    if re.search(r'\b(costo|cuanto|precio)\b.*\b(envio|flete|shalom)\b|\b(envio|flete)\b.*\b(costo|cuanto|precio)\b',n):
        return answer('El equipo confirma las condiciones del envío por Shalom; no te daré un costo sin verificar. '+agency_prompt(s))
    if re.search(r'\b(cuando|demora|llega|plazo)\b',n):
        return answer('El envío demora aproximadamente *3 días desde el despacho*; no es una fecha garantizada. El envío lo pagas aparte. '+agency_prompt(s))
    if re.search(r'\b(precio|precios|cuanto|costo|valor)\b',n):return False,None
    # Cantidades y consultas generales conservan el flujo comercial anterior.
    if re.search(r'\b(mejor|quiero|deseo|cambia)\s+(?:solo\s+)?(?:\d+|una?|uno|dos|tres)\b',n):return False,None
    if (is_question(text) and n not in ('si','si confirmo','confirmo','confirmar','confirmo el pedido')
            and not re.search(r'\b(agencias?|shalom|cerca|ubicacion)\b',n)):
        return True,None
    def fetch(filters):
        try:
            result=api('/agencias?'+urlencode(filters))
            if not isinstance(result,dict):raise ValueError('Respuesta inválida')
        except Exception:
            s['stage']='agency_wait';save(chat,s)
            return answer('Ahora no puedo consultar las agencias. El equipo debe confirmar el destino; no deposites todavía.')
        if result.get('estado')=='ACLARAR_UBICACION':
            s['_agency_places']=result.get('ubicaciones',[])[:4];s['_agency_filter']=filters;s['stage']='agency_location';save(chat,s)
            opts='\n'.join(str(i)+'. '+x['provincia']+' — '+x['departamento'] for i,x in enumerate(s['_agency_places'],1))
            return answer('Hay lugares con ese nombre:\n'+opts+'\n¿Cuál corresponde a tu destino?')
        choices=result.get('agencias') or []
        if result.get('estado') not in ('OK','ACOTAR_O_PAGINAR') or not choices:
            s['_agency_filter']=filters;s['stage']='agency_wait';save(chat,s)
            return answer(agency_prompt(s))
        required=('ter_id','nombre','direccion','departamento','provincia','distrito_reportado','version')
        if len(choices)>4 or any(not all(k in a for k in required) or type(a['ter_id'])!=int for a in choices):
            s['stage']='agency_wait';save(chat,s);return answer('La consulta de agencias necesita revisión del equipo. No deposites todavía.')
        s['_agency_choices']=choices;s['_agency_filter']=filters;s['_agency_more']=bool(result.get('hay_mas'));s['stage']='agency_choose';save(chat,s)
        lines=[]
        for i,a in enumerate(choices,1):
            address=re.split(r'REFERENCIA\s*:|REF\.',a['direccion'],maxsplit=1,flags=re.I)[0].strip()
            lines.append(f"{i}. Shalom {a['nombre']} — {address[:250]}, {a['distrito_reportado']}")
        return answer('Estas son las opciones revisadas para el recojo:\n'+'\n'.join(lines)+'\n¿Cuál te queda más cómoda para recoger? Responde con el número o nombre.'+(' Puedes pedir «más agencias» o indicar un distrito.' if s['_agency_more'] else ''))
    # Migrar borradores antiguos sin enviar sus direcciones ni registrar una agencia libre.
    if stage in ('address','reference','confirm') and not s.get('_agency_confirmed'):
        s.pop('_ramy_await_district',None);s['stage']='city';save(chat,s)
        if s.get('city'):return fetch({'q':s['city'],'pagina':1})
        return answer(agency_prompt(s))
    if stage=='agency_confirm':
        if n in ('si','si confirmo','confirmo','correcto','es correcto','si correcto','esa','confirmo esa agencia'):
            pending=s.get('_agency_pending') or {}
            try:
                fresh=api('/agencias/'+str(pending['ter_id']))
                if fresh.get('version')!=pending.get('version'):raise ValueError('Cambio de agencia')
            except Exception:
                s['stage']='agency_wait';save(chat,s);return answer('La agencia necesita confirmarse nuevamente con el equipo antes de continuar. No deposites todavía.')
            s['agency']=fresh;s['_agency_confirmed']=True;s['city']=fresh['provincia'][:120]
            s['address']=('Shalom '+fresh['nombre']+' — '+fresh['direccion'])[:1000];s['reference']='';s['stage']='confirm';save(chat,s)
            return answer(summary(s))
        if n in ('no','otra','otra agencia','cambiar'):s['stage']='agency_choose';save(chat,s);return fetch(s['_agency_filter'])
        if is_question(text):return True,None
        return answer(agency_prompt(s))
    if stage=='agency_location':
        opts=s.get('_agency_places',[])
        index=re.fullmatch(r'(?:(?:la|opcion) )?(\d+)',n)
        matches=[opts[int(index.group(1))-1]] if index and 1<=int(index.group(1))<=len(opts) else [p for p in opts if n in (norm(p['departamento']),norm(p['provincia']),norm(p['provincia']+' '+p['departamento']))]
        if len(matches)==1:
            f={**s['_agency_filter'],**matches[0],'pagina':1};s.pop('_agency_places',None);return fetch(f)
        if index:return answer('Ese número no corresponde a las opciones. '+agency_prompt(s))
        return fetch({'q':text.strip(),'pagina':1})
    if stage=='agency_choose':
        if n in ('mas','mas agencias','ver mas','otras','siguiente'):
            if not s.get('_agency_more'):return answer('No hay más opciones revisadas en esta búsqueda. Puedes indicar otro distrito o elegir una de las agencias mostradas.')
            return fetch({**s['_agency_filter'],'pagina':int(s['_agency_filter'].get('pagina',1))+1})
        opts=s.get('_agency_choices',[])
        m=re.fullmatch(r'(?:(?:la|opcion|agencia|numero) )?(\d+)',n)
        matches=[opts[int(m.group(1))-1]] if m and 1<=int(m.group(1))<=len(opts) else []
        if not m:
            exact=[a for a in opts if n in (norm(a['nombre']),norm(a['direccion']),norm('shalom '+a['nombre']))]
            matches=exact or [a for a in opts if len(n)>=4 and (n in norm(a['nombre']) or n in norm(a['direccion']))]
        if len(matches)==1:
            s['_agency_pending']=matches[0];s['stage']='agency_confirm';save(chat,s);return answer(agency_prompt(s))
        if m or len(matches)>1:
            if not s.get('_agency_list_repeated'):
                s['_agency_list_repeated']=True;return fetch(s['_agency_filter'])
            return answer('Necesito identificar una sola agencia. Escribe su nombre completo o un número de la lista anterior.')
        if n in ('no se','no conozco','ayuda','la mas cercana','cerca de mi','mi ubicacion'):
            return answer('¿En qué distrito te queda más cómodo recoger? No necesito tu domicilio ni tu ubicación en tiempo real.')
        if is_question(text):
            place=re.search(r'\b(?:en|para)\s+(.+)$',n)
            return fetch({'q':place.group(1),'pagina':1}) if place else fetch(s['_agency_filter'])
        return fetch({'q':text.strip(),'pagina':1})
    if stage=='agency_wait' and n in ('no se','no conozco','cual equipo','pero es para '+norm((s.get('_agency_filter') or {}).get('q',''))):return answer(agency_prompt(s))
    if stage in ('city','agency_wait'):
        if n in ('si','confirmo','ok','no se','no conozco'):return answer(agency_prompt(s))
        return fetch({'q':text.strip(),'pagina':1})
    return False,None


def priority_reply(chat,text):
    from app import ramy_checkout as checkout
    with checkout.lock:
        state=checkout.load(chat)
    if (not state.get('order') and state.get('product') and state.get('stage') in
        ('name','dni','city','address','reference','agency_location','agency_choose','agency_confirm','agency_wait')):
        return checkout.handle_checkout(chat,text)
    return None
