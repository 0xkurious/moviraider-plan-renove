# Demo en directo: WhatsApp real con respond.io

Objetivo: que al confirmar un pedido con pack legal, **tu móvil reciba un WhatsApp** con el enlace para completar los datos de la matrícula, y otro al enviar el formulario.

```
Odoo (outbox) ──webhook──▶ bridge ──API v2──▶ respond.io ──▶ tu WhatsApp
```

Odoo no sabe nada de respond.io: solo emite eventos. El adaptador (`bridge/`) traduce cada evento a un mensaje y lo envía. Sin configuración, el adaptador **simula** y no envía nada.

## Qué necesitas (y no puedo hacer yo)

| Necesitas | Por qué |
|---|---|
| Cuenta de prueba de respond.io | La herramienta del proyecto. Hay prueba gratuita. |
| **Un número de empresa para WhatsApp** que no esté ya en uso en la app de WhatsApp (una SIM o línea aparte) | Es el remitente. Tu WhatsApp personal será el **destinatario**, no el remitente. |
| Tu móvil en la **misma red Wi-Fi** que este ordenador | El enlace del mensaje usa la IP local; `localhost` no se ve desde el móvil. |

## Pasos

1. **Crea la cuenta** de prueba en respond.io y **conecta el canal de WhatsApp** con tu número de empresa. Guía oficial de respond.io: <https://respond.io/help/whatsapp/whatsapp-business-platform-api-channel-configuration>
2. **Crea el token de la API**: *Settings → Integrations → Developer API → Add Access Token*. Cópialo.
3. **Abre la ventana de 24 h**: desde **tu** WhatsApp personal, escribe «hola» al número de empresa. Esto es obligatorio: WhatsApp solo permite a una empresa enviar texto libre en las 24 h siguientes a que el cliente escriba, y además crea tu contacto en respond.io.
4. **Configura el adaptador**: copia `.env.example` a `.env` y rellena:
   ```
   PROVIDER=respondio
   RESPONDIO_TOKEN=<tu token>
   LIVE_ALLOWED_PHONES=+34XXXXXXXXX      # tu móvil personal
   MESSAGE_MODE=text
   ```
   `.env` está en `.gitignore`: no se sube al repositorio. El adaptador **se niega a arrancar** sin `LIVE_ALLOWED_PHONES`.
5. **Arranca el adaptador y comprueba la configuración** (no muestra secretos):
   ```
   docker compose up -d bridge
   curl -s localhost:8001/health
   ```
6. **Haz que el enlace se abra desde el móvil**: `./scripts/lan_url.sh`. Después abre en el móvil la dirección que imprime (`http://<tu-ip>:8069/renove`). Si no abre, es el cortafuegos del ordenador: permite el puerto 8069 en la red local.
7. **Lanza la demo**:
   ```
   ./scripts/demo_order.sh +34XXXXXXXXX "Tu nombre"
   ```
   Crea un pedido con pack legal para ti y el WhatsApp sale en menos de un segundo. Abre el enlace, completa el formulario y recibirás el segundo mensaje.

## Si algo falla

Primero mira **Ventas → Pedidos → Cola de webhooks**: la columna *Último error* muestra el motivo exacto que devuelve respond.io. También `curl -s localhost:8001/messages` (teléfonos enmascarados) y `docker compose logs bridge`.

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `401` / token inválido | Token mal copiado o revocado | Genera otro y actualiza `.env`; `docker compose up -d bridge` |
| `404` / contacto no encontrado | No escribiste primero al número de empresa | Paso 3 |
| El error habla de la ventana de 24 h | Pasaron más de 24 h desde tu «hola» | Escribe «hola» otra vez, o usa `MESSAGE_MODE=template` |
| `bloqueado_lista` en `/messages` | El teléfono del cliente de la demo no coincide con `LIVE_ALLOWED_PHONES` | Usa el mismo número en `demo_order.sh` y en `.env` |
| El adaptador no arranca | Falta token o `LIVE_ALLOWED_PHONES` | Es intencionado: ver `docker compose logs bridge` |
| El mensaje llega pero el enlace no abre | Móvil en otra red, o cortafuegos | Paso 6 |

## Modo plantilla (opcional)

Con `MESSAGE_MODE=template` la empresa puede escribir primero, sin que tú escribas antes. Hay que crear y **aprobar** en respond.io estas tres plantillas con el cuerpo **exacto** (las variables `{{n}}` y su orden importan) y poner `RESPONDIO_CHANNEL_ID` en `.env`. La aprobación de Meta puede tardar de minutos a horas.

| Nombre | Evento | Categoría | Idioma | Cuerpo |
|---|---|---|---|---|
| `matricula_datos` | `case.created` | Utilidad | Español (`es`) | `Hola {{1}}, tu pedido {{2}} incluye el pack legal. Para matricular tu {{3}} necesitamos 3 datos. Complétalos aquí (2 minutos): {{4}}` |
| `matricula_recibida` | `case.data_received` | Utilidad | Español (`es`) | `Gracias {{1}}, hemos recibido los datos de tu {{2}}. Nos ocupamos del resto del trámite.` |
| `matricula_enviada` | `case.sent_to_gestoria` | Utilidad | Español (`es`) | `Hola {{1}}, tu expediente {{2}} ya está en manos de la gestoría. Te escribimos con novedades.` |

## Seguridad y buenas prácticas

- **Solo escribe a números de la lista permitida.** La base de demo contiene teléfonos inventados que podrían ser de personas reales.
- El token vive solo en `.env`. Revócalo cuando termines la demo.
- WhatsApp exige consentimiento (*opt-in*) del destinatario. Aquí el destinatario eres tú.
- Odoo no expone nada a internet: solo es accesible desde tu red local.

## Lo que está verificado y lo que no

- **Verificado:** la regla de la ventana de 24 h y de las plantillas (documentación de Meta y de respond.io); el endpoint `POST /contact/{identifier}/message` en `https://api.respond.io/v2`, el identificador `phone:+…`, la autenticación con *Bearer token* y el formato de mensaje de texto y de plantilla (SDK y servidor MCP oficiales de respond.io); el comportamiento del adaptador frente a un servidor que imita esa API (28 tests).
- **No verificado contra la API real** (no hay credenciales en este entorno): los límites de peticiones, el comportamiento exacto al escribir a un contacto que no existe, y el formato de la plantilla, que se ha deducido del ejemplo del SDK oficial. La primera llamada real puede requerir un ajuste; el motivo aparecerá en la cola de webhooks.
