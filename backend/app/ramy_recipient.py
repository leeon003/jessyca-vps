"""Datos de destinatario por borrador; documentos nunca se envían al modelo completos."""
import re

def valid_dni(value):return isinstance(value,str) and bool(re.fullmatch(r'[0-9]{8}',value))
def mask_dni(value):return '****'+value[-4:] if valid_dni(value) else 'Pendiente'
def redact(text):return re.sub(r'(?<![0-9])[0-9]{8}(?![0-9])',lambda m:mask_dni(m.group()),str(text))
def redact_messages(messages):return [{**m,'content':redact(m.get('content',''))} if isinstance(m.get('content'),str) else dict(m) for m in messages]
def prompt():return 'Gracias 😊. ¿Cuál es el DNI de 8 dígitos de la persona que recogerá el pedido? Lo usaremos para registrar el envío; no necesito una foto del documento.'
def handle(chat,text,s,save,valid_name,summary=None):
    if s.get('order'):return False,None
    stage=s.get('stage');answer=lambda text:(True,{'reply':text})
    if re.search(r'\b(precio|cuanto|cuánto|costo)\b',text.casefold()):return False,None
    if stage!='dni' and ('?' in text or re.search(r'\b(precio|cuanto|costo|garantia|caracteristicas|confianza|pago|comprobante|codigo)\b',text.casefold())):return False,None
    matches=re.findall(r'(?<![0-9])[0-9]{8}(?![0-9])',text)
    if stage=='name' and len(matches)==1:
        dni=matches[0]
        if text.strip()==dni:
            s['dni_destinatario']=dni;save(chat,s);return answer('Gracias. ¿Quién recogerá el pedido? Compárteme su nombre completo, por favor 😊.')
        name=re.sub(r'(?i)\b(?:mi\s+)?(?:nombre(?:\s+completo)?(?:\s+es)?|dni|documento|numero(?:\s+de\s+dni)?)\s*[:=-]?','',text.replace(dni,'')).strip(' ,;:-.\n')
        name=re.sub(r'\s*[,;]\s*',' ',name).strip()
        if valid_name(name):
            s['name']=name;s['dni_destinatario']=dni;s['stage']='city' if s.get('phone') else 'phone';save(chat,s)
            return answer('Gracias, registré los datos del destinatario para el borrador 😊. '+('¿A qué departamento enviamos tu pedido por Shalom?' if s.get('phone') else '¿Cuál es el WhatsApp de contacto?'))
    if stage=='dni':
        n=text.casefold()
        if len(matches)==1 and (re.fullmatch(r'\s*[0-9]{8}\s*',text) or re.fullmatch(r'(?i)\s*(?:mi\s+)?(?:dni|documento)(?:\s+es)?\s*[:=-]?\s*[0-9]{8}[ .]*',text)):
            s['dni_destinatario']=matches[0];s['stage']=s.pop('_after_dni_stage','city' if s.get('phone') else 'phone');save(chat,s)
            if s['stage']=='confirm' and summary:return answer(summary(s))
            return answer('Gracias 😊. '+('Revisemos la agencia de recojo. ¿A qué departamento enviamos tu pedido?' if s['stage']=='city' else 'Continuemos con la confirmación de la agencia y el pedido.' if s['stage']!='phone' else '¿Cuál es el WhatsApp de contacto?'))
        if any(x in n for x in ('no tengo dni','no quiero','no deseo','extranjero','carnet','pasaporte')):
            return answer('El equipo debe ayudarte a registrar el documento del destinatario. No envíes fotos ni datos de otro documento por ahora; todavía no registraré el pedido.')
        if '?' in text or 'por qué' in n or 'para que' in n:
            return answer('Lo usamos como dato del destinatario para registrar el envío. Solo necesito el número, sin foto. Si prefieres, el equipo puede ayudarte a completar ese paso.')
        return answer('Escribe únicamente los 8 dígitos del DNI del destinatario, por favor. Comprobar el formato no verifica su identidad.')
    if (stage in ('city','address','reference','agency_location','agency_choose','agency_confirm','agency_wait','confirm')
            and s.get('name') and not valid_dni(s.get('dni_destinatario'))):
        s['_after_dni_stage']=stage;s['stage']='dni';save(chat,s);return answer(prompt())
    return False,None
