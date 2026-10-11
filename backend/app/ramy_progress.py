"""Extrae el estado del flujo controlado sin consultar al modelo ni al CRM."""
from functools import wraps
import inspect
from app.ramy_checkout import load, lock
STAGES={'product':('ELEGIR_PRODUCTO','Producto'),'quantity':('PRODUCTO_INTERES','Cantidad'),'name':('ESPERANDO_DATOS','Nombre completo'),'phone':('ESPERANDO_DATOS','Celular'),'city':('ESPERANDO_DATOS','Ciudad'),'address':('ESPERANDO_DATOS','Dirección o agencia'),'reference':('ESPERANDO_DATOS','Referencia de entrega'),'confirm':('ESPERANDO_CONFIRMACION','Confirmar resumen'),'receipt':('ESPERANDO_COMPROBANTE','Comprobante para revisión')}
def snapshot(chat_id):
    with lock:s=load(chat_id)
    etapa,pendiente=STAGES.get(s.get('stage'),('CONSULTA_INICIAL','Consulta del cliente'))
    p=s.get('product') or {};order=s.get('order') or {}
    return {'etapa':etapa,'pendiente':pendiente,'producto':str(p.get('nombre',''))[:180],'pedido_id':order.get('pedido_id'),'nombre':str(s.get('name',''))[:180],'ciudad':str(s.get('city',''))[:120]}
def track_progress(fn):
    @wraps(fn)
    def tracked(message):
        result=fn(message)
        if isinstance(result,dict) and isinstance(result.get('reply'),str):
            try:
                progress=snapshot(message.chat_id)
                if result['reply'].startswith('Detuve esta solicitud de compra.'):
                    progress.update(etapa='CANCELADO',pendiente='Solicitud cancelada por el cliente')
                result={**result,'sales_progress':progress}
            except Exception:pass  # El seguimiento nunca impide responder ni crear el pedido.
        return result
    tracked.__signature__=inspect.signature(fn,eval_str=True)
    return tracked
