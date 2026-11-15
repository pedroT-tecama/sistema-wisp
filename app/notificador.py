"""Envío de correos de alerta: clase NotificadorCorreo.

Qué hace:
    Envía por SMTP el correo que arma MotorTelemetriaProactiva.disparar_alerta_critica()
    cuando un ruteador cae, cuando se restablece o cuando una cabecera no responde.
    Los datos del servidor y de la cuenta se leen del archivo .env; ninguno va en el código.
    Si ALERTA_CORREO no es 1 o falta algún dato, no envía nada.

Configuración (archivo .env):
    ALERTA_CORREO  : 1 activa el envío, 0 lo apaga (0 por defecto).
    SMTP_HOST      : servidor de correo, ej. smtp.gmail.com.
    SMTP_PORT      : 587 (STARTTLS) o 465 (SSL).
    SMTP_USER      : cuenta que envía.
    SMTP_PASS      : contraseña de aplicación de esa cuenta.
    ALERTA_DESTINO : una o varias direcciones, separadas por comas.

Con qué se relaciona:
    - Lo usa: app/monitoreo.py (MotorTelemetriaProactiva.disparar_alerta_critica).
    - Lo prueba: tests/test_monitoreo.py, con un correo simulado en su lugar.
"""
import os
import smtplib
from email.message import EmailMessage

from dotenv import load_dotenv

load_dotenv()


class NotificadorCorreo:
    """Envía un correo de texto a los destinatarios configurados en el .env."""

    def __init__(self):
        self.host = os.getenv("SMTP_HOST", "")
        self.puerto = int(os.getenv("SMTP_PORT", "587"))
        self.usuario = os.getenv("SMTP_USER", "")
        self._clave = os.getenv("SMTP_PASS", "")
        self.destinos = [d.strip() for d in os.getenv("ALERTA_DESTINO", "").split(",") if d.strip()]
        encendido = os.getenv("ALERTA_CORREO", "0") == "1"
        self.activo = encendido and bool(self.host and self.usuario and self._clave and self.destinos)

    def enviar(self, asunto: str, cuerpo: str) -> None:
        """Envía el correo; si el servidor no responde o rechaza la cuenta, lanza la excepción de smtplib.

        Es bloqueante: el monitoreo lo llama con asyncio.to_thread para no detener al sistema.
        """
        mensaje = EmailMessage()
        mensaje["Subject"] = asunto
        mensaje["From"] = self.usuario
        mensaje["To"] = ", ".join(self.destinos)
        mensaje.set_content(cuerpo)
        if self.puerto == 465:                                   # conexión cifrada desde el inicio
            with smtplib.SMTP_SSL(self.host, self.puerto, timeout=15) as servidor:
                servidor.login(self.usuario, self._clave)
                servidor.send_message(mensaje)
        else:                                                    # conexión que se cifra con STARTTLS
            with smtplib.SMTP(self.host, self.puerto, timeout=15) as servidor:
                servidor.starttls()
                servidor.login(self.usuario, self._clave)
                servidor.send_message(mensaje)
