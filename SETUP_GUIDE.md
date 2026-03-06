# 🚀 Guía de Configuración — Hotmart Tracker

> **Tiempo estimado total:** 30-45 minutos
> **Costo total:** $0

---

## Antes de empezar

Copia el archivo de ejemplo de variables:

```powershell
cd d:\WorkSpace\TRABAJO\hotmart-tracker
copy .env.example .env
```

Ahora ve llenando cada token siguiendo los pasos de abajo. Abre `.env` en tu editor y ve pegando cada valor.

---

## PASO 1: Supabase (Base de datos) — ~5 min

### 1.1 Crear cuenta
1. Ir a **[supabase.com](https://supabase.com)**
2. Click en **"Start your project"**
3. Iniciar sesión con **GitHub** (la forma más rápida)

### 1.2 Crear proyecto
1. Click en **"New Project"**
2. Llenar:
   - **Name:** `hotmart-tracker`
   - **Database Password:** genera una contraseña segura (guárdala por si acaso)
   - **Region:** selecciona la más cercana a ti (ej: `South America (São Paulo)`)
3. Click en **"Create new project"**
4. Esperar ~2 minutos a que se cree

### 1.3 Obtener las keys
1. Una vez creado, ir a **Settings** (engranaje en la barra lateral izquierda)
2. Click en **"API"** en el menú lateral
3. Copiar estos dos valores a tu `.env`:

```env
SUPABASE_URL=https://xxxxxxxxxx.supabase.co     ← "Project URL"
SUPABASE_SERVICE_KEY=eyJhbGciOi...               ← "service_role" key (la de ABAJO, NO la "anon")
```

> ⚠️ **IMPORTANTE:** usa la key `service_role` (dice "secret"), NO la `anon` key. La `service_role` tiene permisos completos para crear tablas y escribir datos.

✅ **Verificación:** ya puedes ver el **Table Editor** vacío en Supabase. Las tablas se crearán cuando ejecutemos el código.

---

## PASO 2: Telegram Bot — ~3 min

### 2.1 Crear el bot
1. Abrir **Telegram** (app o web)
2. Buscar **@BotFather** y abrir el chat
3. Enviar: `/newbot`
4. Te pedirá un **nombre** para el bot → escribe: `Hotmart Tracker`
5. Te pedirá un **username** → escribe algo único como: `hotmart_tracker_tuNombre_bot` (debe terminar en `_bot`)
6. BotFather te dará un token así: `7123456789:AAH...`

```env
TELEGRAM_BOT_TOKEN=7123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 2.2 Obtener tu Chat ID
1. Envía **cualquier mensaje** a tu bot nuevo (búscalo por el username que creaste)
2. Abre esta URL en tu navegador (reemplazando el TOKEN):

```
https://api.telegram.org/bot<TU_TOKEN>/getUpdates
```

3. En el JSON que aparece, busca `"chat":{"id":123456789}` — ese número es tu Chat ID

```env
TELEGRAM_CHAT_ID=123456789
```

### 2.3 Probar que funciona
Abre esta URL en el navegador (reemplazando TOKEN y CHAT_ID):

```
https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<CHAT_ID>&text=Hotmart%20Tracker%20conectado!
```

✅ **Verificación:** deberías recibir el mensaje "Hotmart Tracker conectado!" en Telegram.

---

## PASO 3: YouTube Data API v3 — ~5 min

### 3.1 Crear proyecto en Google Cloud
1. Ir a **[console.cloud.google.com](https://console.cloud.google.com)**
2. Si es tu primera vez, aceptar los términos de servicio
3. Click en el selector de proyectos (arriba a la izquierda) → **"New Project"**
4. **Name:** `hotmart-tracker` → click **"Create"**
5. Esperar a que se cree y asegurarte de que está seleccionado

### 3.2 Habilitar la API
1. Ir al menú ☰ → **"APIs & Services"** → **"Library"**
2. Buscar **"YouTube Data API v3"**
3. Click en el resultado → click **"Enable"**

### 3.3 Crear API Key
1. Ir al menú ☰ → **"APIs & Services"** → **"Credentials"**
2. Click **"+ Create Credentials"** → **"API Key"**
3. Se genera una key al instante → copiarla

```env
YT_API_KEY=AIzaSy...
```

> 💡 **Opcional pero recomendado:** click en "Edit API Key" → en "API restrictions" seleccionar "Restrict key" → elegir solo "YouTube Data API v3". Esto protege tu key.

✅ **Verificación:** abre esta URL en el navegador (reemplazando la KEY):
```
https://www.googleapis.com/youtube/v3/search?part=snippet&q=test&key=<TU_API_KEY>
```
Deberías ver resultados JSON de YouTube.

---

## PASO 4: Facebook Ad Library API — ~15 min

> Este es el más complejo, pero sigue siendo gratis. Si quieres empezar sin Facebook, puedes dejarlo para después — el pipeline funciona con valores por defecto cuando la señal de FB no está disponible.

### 4.1 Crear cuenta de desarrollador
1. Ir a **[developers.facebook.com](https://developers.facebook.com)**
2. Click en **"Get Started"** o **"My Apps"**
3. Si te pide verificar tu cuenta de Facebook, completar la verificación

### 4.2 Crear App
1. Click en **"Create App"**
2. Seleccionar tipo: **"Business"** (o "Other" si no ves "Business")
3. **App name:** `Hotmart Tracker`
4. **Contact email:** tu email
5. Click **"Create App"**

### 4.3 Agregar Marketing API
1. En el dashboard de tu app, buscar **"Add Products"**
2. Buscar **"Marketing API"** → click **"Set Up"**

### 4.4 Generar Token
1. Ir a **"Tools"** → **"Graph API Explorer"** (o ir directamente a [developers.facebook.com/tools/explorer](https://developers.facebook.com/tools/explorer/))
2. En el selector de arriba, elegir tu app **"Hotmart Tracker"**
3. Click en **"Generate Access Token"**
4. En los permisos, buscar y activar: **`ads_read`**
5. Click **"Generate Access Token"** → aceptar permisos → copiar el token

### 4.5 Convertir a Long-Lived Token (dura 60 días)
El token del paso anterior expira en 1 hora. Para extenderlo:

1. Ir a tu app en [developers.facebook.com](https://developers.facebook.com) → **Settings** → **Basic**
2. Copiar tu **App ID** y **App Secret**
3. Abrir esta URL en el navegador (reemplazando los 3 valores):

```
https://graph.facebook.com/v19.0/oauth/access_token?grant_type=fb_exchange_token&client_id=<APP_ID>&client_secret=<APP_SECRET>&fb_exchange_token=<TOKEN_CORTO>
```

4. El JSON te dará un `access_token` nuevo que dura 60 días

```env
FB_ACCESS_TOKEN=EAAI...
```

> ⚠️ **Cada 60 días** deberás repetir el paso 4.5 para renovar el token. Pon un recordatorio.

✅ **Verificación:** abre esta URL (reemplazando TOKEN):
```
https://graph.facebook.com/v19.0/ads_archive?access_token=<TOKEN>&search_terms=test&ad_reached_countries=BR&limit=1
```
Deberías ver datos de anuncios en JSON.

---

## PASO 5: Subir todo a GitHub — ~3 min

Una vez que tengas tus tokens en `.env`, sube el proyecto:

```powershell
cd d:\WorkSpace\TRABAJO\hotmart-tracker
git add .
git status
```

> ⚠️ **VERIFICAR:** en `git status` NO debería aparecer `.env` (solo `.env.example`). Si aparece `.env`, algo salió mal con el `.gitignore`.

```powershell
git commit -m "Add project structure, .gitignore, and env template"
git push origin main
```

---

## PASO 6: Configurar GitHub Secrets — ~3 min

1. Ir a tu repositorio en **GitHub.com**
2. Click en **"Settings"** (pestaña arriba del repo)
3. En el menú izquierdo: **"Secrets and variables"** → **"Actions"**
4. Click **"New repository secret"** y agregar uno por uno:

| Nombre del Secret | Valor |
|---|---|
| `SUPABASE_URL` | `https://xxx.supabase.co` |
| `SUPABASE_SERVICE_KEY` | `eyJhbGciOi...` |
| `TELEGRAM_BOT_TOKEN` | `7123456789:AAH...` |
| `TELEGRAM_CHAT_ID` | `123456789` |
| `YT_API_KEY` | `AIzaSy...` |
| `FB_ACCESS_TOKEN` | `EAAI...` (si lo tienes, sino dejarlo para después) |

5. Luego ir a la pestaña **"Variables"** (al lado de Secrets) y agregar:

| Nombre de Variable | Valor |
|---|---|
| `TARGET_MARKET` | `BR` |
| `SCORE_ALERT_THRESHOLD` | `65` |

---

## ✅ Checklist Final

- [ ] Supabase: URL y service_role key en `.env`
- [ ] Telegram: bot creado, token y chat ID en `.env`, mensaje de prueba recibido
- [ ] YouTube: API habilitada, key en `.env`, búsqueda de prueba funciona
- [ ] Facebook: token en `.env` (o dejado para después)
- [ ] `.env` NO aparece en `git status`
- [ ] Código subido a GitHub con `git push`
- [ ] Secrets configurados en GitHub → Settings → Secrets

---

> **¿Siguiente paso?** Una vez completado esto, podemos empezar con la **Sesión 1** del plan: crear la configuración en Python, el schema de base de datos, y el cliente DB.
