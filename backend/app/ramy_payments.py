"""Medios autorizados: respuesta determinista, sin cuentas inventadas por IA."""
import re
import unicodedata

def payment_reply(text):
    normalized = ''.join(c for c in unicodedata.normalize('NFD', text.casefold()) if unicodedata.category(c) != 'Mn')
    # Un comprobante enviado o «ya pagué» no es una solicitud de cuentas.
    if re.search(r'\b(ya pague|ya deposite|comprobante|constancia|voucher)\b', normalized):
        return None
    if not re.search(r'\b(yape|bcp|cci|qr|como pago|como pagar|donde pago|donde deposito|datos de pago|medios de pago|cuenta bancaria|cuentas bancarias)\b', normalized):
        return None
    return {
        'reply': (
            'Puedes usar estos medios oficiales de Tiendas RAMY 😊\n\n'
            'Yape: 923248212\n'
            'Titular: ALEXA ROJAS\n\n'
            'Cuenta BCP Soles: 19107507519051\n'
            'Cuenta interbancaria (CCI): 00219110750751905153\n'
            'Titular BCP: ALEXA ROJAS\n\n'
            'Antes de depositar, confirma con nosotros el pedido y el monto correspondiente. '
            'Luego envía tu comprobante en este chat para revisión del equipo. '
            'El pago queda pendiente de verificación; enviar el comprobante no lo aprueba automáticamente.'
        ),
        'payment_qr': True,
    }
