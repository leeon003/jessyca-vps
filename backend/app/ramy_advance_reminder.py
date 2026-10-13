"""Plantilla de adelanto: sin programación ni envío automático."""
from decimal import Decimal, InvalidOperation

def advance_reminder(order, name=None):
    payment=order.get('pago_actual') or {}
    if order.get('estado') not in ('NUEVO','ADELANTO_EN_REVISION'):return None
    if payment.get('tipo')!='ADELANTO' or payment.get('estado')!='EN_REVISION' or payment.get('comprobante_recibido'):return None
    try:
        if Decimal(str(payment.get('monto'))) != Decimal('10'):return None
    except (InvalidOperation, TypeError):return None
    # Avoid sending user-entered formatting or template placeholders as a name.
    first=str(name or '').split()[0] if str(name or '').split() else ''
    if not first.isalpha() or len(first)>40:first=''
    greeting=('Hola, '+first) if first else 'Hola'
    return greeting+' 😊. El adelanto de *S/10* de tu pedido sigue pendiente. Si tuviste algún inconveniente o necesitas ayuda para completarlo, estoy aquí para ayudarte.'
