"""
Hotmart Marketplace Scraper con sesión autenticada.
Usa Playwright + anti-detección para scraping resiliente.

FLUJO:
1. Login en sso.hotmart.com → cookies de sesión
2. Si autenticado → usa app.hotmart.com/market (tiene comisión + temperatura)
3. Si no autenticado → usa hotmart.com/es/marketplace (solo nombre, precio, rating)

MARKETPLACES:
- Público:      hotmart.com/es/marketplace/CATEGORIA     → Cards: a.product-link
- Autenticado:  app.hotmart.com/market                   → Cards: hot-card / carousel items

SELECTORES AUTENTICADOS (verificados 2026-03-06):
- Temperatura: "25° 🔥" → span con °
- Comisión: "Comisión de hasta" + "35,64 US$"
- Precio máximo: "Precio máximo del producto: 50,00 US$"

NOTA DE LEGALIDAD: Respetar los Terms of Service de Hotmart.
"""

import asyncio
import re
import random
import json
from datetime import date
from pathlib import Path

from fake_useragent import UserAgent
from playwright.async_api import async_playwright, Page, Browser, BrowserContext
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.core.config import settings, ProductSnapshot
from src.core.logger import get_logger

logger = get_logger(__name__)
ua = UserAgent()

# Ruta para persistir cookies entre ejecuciones
COOKIES_PATH = Path(__file__).parent.parent.parent / ".hotmart_cookies.json"

# URLs
HOTMART_LOGIN_URL = "https://sso.hotmart.com/login"
HOTMART_APP_MARKET_URL = "https://app.hotmart.com/market"

# Categorías del marketplace público (fallback sin auth)
HOTMART_CATEGORIES = [
    "https://hotmart.com/es/marketplace/saude-e-esportes",
    "https://hotmart.com/es/marketplace/negocios-e-carreira",
    "https://hotmart.com/es/marketplace/educacao",
    "https://hotmart.com/es/marketplace/relacionamentos",
    "https://hotmart.com/es/marketplace/financas-e-investimentos",
    "https://hotmart.com/es/marketplace/tecnologia",
    "https://hotmart.com/es/marketplace/idiomas",
    "https://hotmart.com/es/marketplace/estilo-de-vida",
]

# Categorías para el marketplace autenticado (app.hotmart.com/market/search)
APP_CATEGORY_SLUGS = [
    "saude-e-esportes",
    "negocios-e-carreira",
    "educacao",
    "relacionamentos",
    "financas-e-investimentos",
    "tecnologia",
    "idiomas",
    "estilo-de-vida",
]


# ─────────────────────────────────────────────
# Browser / Page Setup
# ─────────────────────────────────────────────

async def _create_browser():
    """Crea browser con anti-detección y proxy opcional."""
    pw = await async_playwright().start()
    launch_options = {
        "headless": True,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ],
    }
    if settings.hotmart_scraper_proxy:
        launch_options["proxy"] = {"server": settings.hotmart_scraper_proxy}

    browser = await pw.chromium.launch(**launch_options)
    return pw, browser


async def _setup_context(browser: Browser) -> BrowserContext:
    """Context con stealth y cookies guardadas."""
    context = await browser.new_context(
        user_agent=ua.random,
        viewport={"width": 1920, "height": 1080},
        locale="es-ES",
    )
    if COOKIES_PATH.exists():
        try:
            cookies = json.loads(COOKIES_PATH.read_text(encoding="utf-8"))
            await context.add_cookies(cookies)
            logger.info("Cookies cargadas desde archivo")
        except Exception as e:
            logger.warning(f"Error cargando cookies: {e}")
    return context


async def _setup_page(context: BrowserContext) -> Page:
    """Página con stealth anti-detección."""
    page = await context.new_page()
    await page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        window.chrome = {runtime: {}};
    """)
    return page


async def _save_cookies(context: BrowserContext):
    """Persiste cookies para reutilizar entre ejecuciones."""
    try:
        cookies = await context.cookies()
        COOKIES_PATH.write_text(json.dumps(cookies, indent=2), encoding="utf-8")
        logger.info(f"Cookies guardadas: {len(cookies)} cookies")
    except Exception as e:
        logger.warning(f"Error guardando cookies: {e}")


async def _random_delay():
    """Delay aleatorio anti rate-limiting."""
    delay = random.uniform(settings.scraper_delay_min, settings.scraper_delay_max)
    await asyncio.sleep(delay)


# ─────────────────────────────────────────────
# Login Flow
# ─────────────────────────────────────────────

async def _login_hotmart(page: Page) -> bool:
    """
    Login en Hotmart SSO.
    Selectores: input#username, input#password, button#submit-button
    """
    if not settings.hotmart_email or not settings.hotmart_password:
        logger.warning("HOTMART_EMAIL/PASSWORD no configurados → scraping sin auth")
        return False

    try:
        logger.info("Iniciando login en Hotmart SSO...")
        await page.goto(HOTMART_LOGIN_URL, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)

        await (await page.wait_for_selector("input#username", timeout=10000)).fill(
            settings.hotmart_email
        )
        await asyncio.sleep(0.5)

        await (await page.wait_for_selector("input#password", timeout=5000)).fill(
            settings.hotmart_password
        )
        await asyncio.sleep(0.5)

        try:
            # First try the default id, then fallback to any submit button
            submit_btn = await page.wait_for_selector("button#submit-button, button[type='submit']", timeout=5000)
            if submit_btn:
                await submit_btn.click()
        except Exception:
            # Fallback for headless environments if button is obscured
            logger.warning("Botón de submit no encontrado, intentando enviar con Enter...")
            await page.keyboard.press("Enter")

        # Esperar redirección post-login
        try:
            await page.wait_for_url(
                re.compile(r"app\.hotmart\.com"),
                timeout=15000,
            )
            logger.info("✅ Login exitoso en Hotmart")
            return True
        except Exception:
            error_el = await page.query_selector('[class*="error"], [class*="alert"]')
            if error_el:
                logger.error(f"Error login: {await error_el.inner_text()}")
            else:
                logger.error("Login falló: timeout en redirección")
            return False

    except Exception as e:
        logger.error(f"Error durante login: {e}")
        return False


async def _check_session(page: Page) -> bool:
    """Verifica si la sesión está autenticada accediendo al market de afiliados."""
    try:
        await page.goto(HOTMART_APP_MARKET_URL, wait_until="networkidle", timeout=20000)
        await asyncio.sleep(2)
        # Si redirige al login, no hay sesión
        current_url = page.url
        if "sso.hotmart.com" in current_url or "login" in current_url:
            return False
        # Verificar que el market cargó
        title = await page.title()
        return "hotmart" in title.lower() or "mercado" in title.lower() or "market" in current_url
    except Exception:
        return False


# ─────────────────────────────────────────────
# Number Parsing
# ─────────────────────────────────────────────

def _parse_number(text: str) -> float:
    """Extrae número de texto, formatos BR/ES."""
    if not text:
        return 0.0
    cleaned = "".join(c for c in text if c.isdigit() or c in ".,")
    if not cleaned:
        return 0.0
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _detect_currency(text: str) -> str:
    """Detecta moneda del texto de precio."""
    if not text:
        return "USD"
    if "R$" in text or "BRL" in text:
        return "BRL"
    if "US$" in text or "USD" in text:
        return "USD"
    if "MX$" in text or "MXN" in text:
        return "MXN"
    if "€" in text or "EUR" in text:
        return "EUR"
    return "USD"


def _extract_category_from_url(url: str) -> str:
    """Extrae categoría de la URL."""
    parts = url.rstrip("/").split("/")
    return parts[-1] if parts else "unknown"


# ─────────────────────────────────────────────
# AUTHENTICATED Marketplace (app.hotmart.com/market)
# Cards muestran: título, rating, temperatura°, comisión, precio máximo
# ─────────────────────────────────────────────

async def _scrape_app_market(
    context: BrowserContext, max_products: int = 50
) -> list[ProductSnapshot]:
    """
    Scraping del marketplace autenticado (app.hotmart.com/market).
    Este marketplace tiene un layout diferente con carruseles por sección.
    """
    page = await _setup_page(context)
    all_products: list[ProductSnapshot] = []

    try:
        logger.info(f"Scraping marketplace autenticado: {HOTMART_APP_MARKET_URL}")
        await page.goto(HOTMART_APP_MARKET_URL, wait_until="networkidle", timeout=30000)
        await _random_delay()

        # Scroll para cargar más contenido
        for _ in range(8):
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await asyncio.sleep(1.5)

        # Los product cards en el market autenticado están en divs con estructura:
        # - Imagen
        # - Rating ★ (N) + Temperatura° 🔥
        # - Título
        # - "Comisión de hasta" + valor
        # - "Precio máximo del producto:" + valor

        # Buscar todos los cards que contengan "Comisión de hasta"
        # Estrategia: buscar los containers que tienen la estructura completa
        all_text_content = await page.inner_text("body")

        # Buscar links a productos individuales
        product_links = await page.query_selector_all(
            'a[href*="/market/product/"], a[href*="/marketplace/productos/"]'
        )

        if not product_links:
            # Fallback: buscar cualquier card-like element
            product_links = await page.query_selector_all(
                '[class*="card"], [class*="Card"]'
            )

        logger.info(f"Encontrados {len(product_links)} elementos de producto en market autenticado")

        seen_names = set()
        for link in product_links[:max_products]:
            try:
                product = await _extract_from_auth_card(link, page)
                if product and product.nombre not in seen_names:
                    seen_names.add(product.nombre)
                    all_products.append(product)
            except Exception as e:
                logger.warning(f"Error extrayendo producto autenticado: {e}")
                continue
            await _random_delay()

        logger.info(f"Extraídos {len(all_products)} productos del market autenticado")

    except Exception as e:
        logger.error(f"Error en marketplace autenticado: {e}")
    finally:
        await page.close()

    return all_products


async def _extract_from_auth_card(card, page: Page) -> ProductSnapshot | None:
    """
    Extrae datos de un card del marketplace autenticado.

    Estructura verificada 2026-03-06:
    - Rating: "5.0 ★ (1) 25° 🔥"
    - Título: "Elimina los Síntomas Físicos de la Ansiedad"
    - Comisión: "Comisión de hasta\n35,64 US$"
    - Precio: "Precio máximo del producto: 50,00 US$"
    """
    try:
        full_text = await card.inner_text()
        if not full_text or len(full_text.strip()) < 5:
            return None

        # ─── URL ───
        url_venta = ""
        href = await card.get_attribute("href")
        if href:
            url_venta = href
        else:
            link_el = await card.query_selector("a[href]")
            if link_el:
                url_venta = await link_el.get_attribute("href") or ""

        # ─── DOM Selectors for Authenticated Market ───
        
        # ─── Temperatura: buscar textContent "XX°" ───
        temperatura = 0.0
        temp_el = await card.query_selector("span:has-text('°')")
        if temp_el:
            temp_text = await temp_el.inner_text()
            temp_match = re.search(r"(\d+)\s*°", temp_text)
            if temp_match:
                temperatura = float(temp_match.group(1))

        if not temperatura:
            # Fallback
            temp_match = re.search(r"(\d+)\s*°", full_text)
            if temp_match:
                temperatura = float(temp_match.group(1))

        # ─── Rating: "X.X ★" o "X.X" antes de "(N)" ───
        rating = 0.0
        rating_match = re.search(r"(\d+[.,]\d+)\s*[★⭐]", full_text)
        if not rating_match:
            rating_match = re.search(r"^(\d+[.,]\d+)\s", full_text)
        if rating_match:
            rating = _parse_number(rating_match.group(1))

        # ─── Num ratings: "(N)" ───
        num_ratings = 0
        reviews_match = re.search(r"\((\d+)\)", full_text)
        if reviews_match:
            num_ratings = int(reviews_match.group(1))

        # ─── Nombre: línea más larga que no es comisión/precio/rating ───
        nombre = ""
        lines = [l.strip() for l in full_text.split("\n") if l.strip()]
        for line in lines:
            # Saltar líneas que son datos numéricos o labels
            if re.match(r"^[\d.,]+\s*(US\$|R\$|€|BRL|USD|MXN)", line):
                continue
            if "comisión" in line.lower() or "comissão" in line.lower():
                continue
            if "precio máximo" in line.lower() or "preço máximo" in line.lower():
                continue
            if re.match(r"^[\d.,°★⭐()\s🔥]+$", line):
                continue
            if len(line) > 3 and not nombre:
                nombre = line
                break

        if not nombre:
            return None

        # ─── Comisión: "Comisión de hasta\nXX,XX US$" ───
        comision_pct = 0.0
        comision_el = await card.query_selector("text=/Comisi[oó]n de hasta/i, text=/Comiss[aã]o de at[eé]/i")
        if comision_el:
            parent = await comision_el.evaluate_handle("el => el.parentElement")
            if parent:
                parent_text = await parent.inner_text()
                comision_match = re.search(r"([\d.,]+)\s*(US\$|R\$|€|BRL|USD|MXN)?", parent_text.replace(await comision_el.inner_text(), ""))
                if comision_match:
                    comision_pct = _parse_number(comision_match.group(1))
        
        if not comision_pct:
            # Fallback
            comision_match = re.search(
                r"[Cc]omisi[oó]n\s+de\s+hasta\s*\n?\s*([\d.,]+)\s*(US\$|R\$|€|BRL|USD|MXN)?",
                full_text,
            )
            if not comision_match:
                comision_match = re.search(
                    r"[Cc]omiss[aã]o\s+de\s+at[eé]\s*\n?\s*([\d.,]+)",
                    full_text,
                )
            if comision_match:
                comision_pct = _parse_number(comision_match.group(1))

        # ─── Precio máximo del producto ───
        precio = 0.0
        moneda = "USD"
        precio_el = await card.query_selector("text=/Precio máximo del producto:/i, text=/Preço máximo do produto:/i")
        if precio_el:
            parent = await precio_el.evaluate_handle("el => el.parentElement")
            if parent:
                parent_text = await parent.inner_text()
                precio_match = re.search(r"([\d.,]+)\s*(US\$|R\$|€|BRL|USD|MXN)?", parent_text.replace(await precio_el.inner_text(), ""))
                if precio_match:
                    precio = _parse_number(precio_match.group(1))
                    if len(precio_match.groups()) > 1 and precio_match.group(2):
                        moneda = _detect_currency(precio_match.group(2))
        
        if not precio:
            precio_match = re.search(
                r"[Pp]recio\s+m[aá]ximo\s+del\s+producto:\s*([\d.,]+)\s*(US\$|R\$|€)?",
                full_text,
            )
            if not precio_match:
                precio_match = re.search(
                    r"[Pp]re[cç]o\s+m[aá]ximo\s+do\s+produto:\s*([\d.,]+)",
                    full_text,
                )
            if precio_match:
                precio = _parse_number(precio_match.group(1))
                if len(precio_match.groups()) > 1 and precio_match.group(2):
                    moneda = _detect_currency(precio_match.group(2))

        # Calcular comisión como porcentaje si tenemos precio
        if comision_pct > 0 and precio > 0:
            comision_pct = round((comision_pct / precio) * 100, 1)
        elif comision_pct > 0:
            # Si no hay precio, asumir que el valor ya es útil
            pass

        # ─── Hotmart ID ───
        hotmart_id = ""
        if url_venta:
            parts = url_venta.rstrip("/").split("/")
            if parts:
                hotmart_id = parts[-1].split("?")[0]
        if not hotmart_id:
            hotmart_id = f"ht_{hash(nombre) % 10**8}"

        # ─── Categoría ───
        categoria = "market"  # Marketplace general

        return ProductSnapshot(
            hotmart_id=hotmart_id,
            nombre=nombre.strip(),
            categoria=categoria,
            precio=precio,
            moneda=moneda,
            comision_pct=comision_pct,
            temperatura=temperatura,
            rating=rating,
            num_ratings=num_ratings,
            url_venta=url_venta,
            fecha=date.today(),
        )

    except Exception as e:
        logger.warning(f"Error parsing auth card: {e}")
        return None


# ─────────────────────────────────────────────
# PUBLIC Marketplace (hotmart.com/es/marketplace)
# Fallback cuando no hay auth
# ─────────────────────────────────────────────

async def _scrape_public_category(
    context: BrowserContext,
    category_url: str,
    max_products: int = 50,
) -> list[ProductSnapshot] | None:
    """Scraping de una categoría del marketplace público."""
    page = None
    try:
        page = await _setup_page(context)
        logger.info(f"Scraping público: {category_url}")
        await page.goto(category_url, wait_until="networkidle", timeout=30000)
        await _random_delay()

        for _ in range(5):
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await asyncio.sleep(1.5)

        categoria = _extract_category_from_url(category_url)
        products = []

        product_cards = await page.query_selector_all("a.product-link")
        if not product_cards:
            product_cards = await page.query_selector_all('a[href*="/marketplace/productos/"]')

        if not product_cards:
            logger.error(f"No se encontraron cards en {categoria}")
            return []

        logger.info(f"Encontrados {len(product_cards)} cards en {categoria}")

        for card in product_cards[:max_products]:
            try:
                product = await _extract_from_public_card(card, page, categoria)
                if product:
                    products.append(product)
            except Exception as e:
                logger.warning(f"Error extrayendo producto público: {e}")
            await _random_delay()

        logger.info(f"Extraídos {len(products)} productos de {categoria}")
        return products

    except Exception as e:
        logger.error(f"Error scraping {category_url}: {e}")
        return None
    finally:
        if page:
            await page.close()


async def _extract_from_public_card(card, page: Page, categoria: str) -> ProductSnapshot | None:
    """Extrae datos de un card del marketplace público (sin auth)."""
    try:
        url_venta = await card.get_attribute("href") or ""
        aria_label = await card.get_attribute("aria-label") or ""

        # Nombre
        nombre = ""
        content_divs = await card.query_selector_all(":scope > div")
        if len(content_divs) >= 2:
            inner_divs = await content_divs[1].query_selector_all("div")
            if inner_divs:
                nombre = (await inner_divs[0].inner_text() or "").strip()
                if nombre:
                    nombre = nombre.split("\n")[0].strip()
        if not nombre and aria_label:
            match = re.match(r"^(.+?)\s*[-–]\s*", aria_label)
            if match:
                nombre = match.group(1).strip()
        if not nombre:
            return None

        # Precio
        precio = 0.0
        moneda = "USD"
        precio_el = await card.query_selector("h3")
        if precio_el:
            precio_text = await precio_el.inner_text()
            match = re.search(r"([\d.,]+)", precio_text)
            if match:
                precio = _parse_number(match.group(1))
            moneda = _detect_currency(precio_text)

        # Rating y Reviews
        rating = 0.0
        num_ratings = 0
        spans = await card.query_selector_all("span")
        for span in spans:
            text = (await span.inner_text() or "").strip()
            if not text:
                continue
            if re.match(r"^\d+[.,]\d+$", text) and rating == 0.0:
                rating = _parse_number(text)
            elif re.match(r"^\(\d+\)$", text) and num_ratings == 0:
                num_ratings = int(text.strip("()"))

        # Hotmart ID
        hotmart_id = ""
        if url_venta:
            parts = url_venta.rstrip("/").split("/")
            if parts:
                hotmart_id = parts[-1].split("?")[0]
        if not hotmart_id:
            hotmart_id = f"ht_{hash(nombre) % 10**8}"

        return ProductSnapshot(
            hotmart_id=hotmart_id,
            nombre=nombre.strip(),
            categoria=categoria,
            precio=precio,
            moneda=moneda,
            comision_pct=0.0,
            temperatura=0.0,
            rating=rating,
            num_ratings=num_ratings,
            url_venta=url_venta,
            fecha=date.today(),
        )
    except Exception as e:
        logger.warning(f"Error parsing public card: {e}")
        return None


# ─────────────────────────────────────────────
# Notificación de fallos
# ─────────────────────────────────────────────

async def _notify_scraper_failure(url: str, error: str):
    logger.error(f"SCRAPER FAILURE: {url} — {error}")


# ─────────────────────────────────────────────
# API Pública — compatibilidad con imports existentes
# ─────────────────────────────────────────────

async def scrape_category(
    category_url: str, max_products: int = 50
) -> list[ProductSnapshot] | None:
    """Scraping de una sola categoría (público, sin auth)."""
    pw, browser = None, None
    try:
        pw, browser = await _create_browser()
        context = await _setup_context(browser)
        result = await _scrape_public_category(context, category_url, max_products)
        return result
    except Exception as e:
        logger.error(f"Error: {e}")
        return None
    finally:
        if browser:
            await browser.close()
        if pw:
            await pw.stop()


async def scrape_all_categories(
    categories: list[str] | None = None,
) -> list[ProductSnapshot]:
    """
    CONTRACT:
      Input:  categories: list[str] (URLs de categorías Hotmart)
      Output: list[ProductSnapshot] (lista plana, todas las categorías)
      - Si hay credenciales → login + marketplace autenticado (con comisión/temperatura)
      - Si no hay credenciales → marketplace público (sin comisión/temperatura)
      - Login UNA sola vez, reutiliza context
    """
    if categories is None:
        categories = HOTMART_CATEGORIES

    pw, browser = None, None
    all_products: list[ProductSnapshot] = []
    failed_categories = 0

    try:
        pw, browser = await _create_browser()
        context = await _setup_context(browser)
        page = await _setup_page(context)

        # ── Intentar autenticación ──
        is_authenticated = False
        if settings.hotmart_email and settings.hotmart_password:
            is_authenticated = await _check_session(page)
            if not is_authenticated:
                is_authenticated = await _login_hotmart(page)
                if is_authenticated:
                    await _save_cookies(context)
        await page.close()

        auth_label = "AUTENTICADO ✅" if is_authenticated else "SIN AUTH ⚠️"
        logger.info(f"Modo: [{auth_label}] — {len(categories)} categorías")

        if is_authenticated:
            # ── SCRAPING AUTENTICADO: app.hotmart.com/market ──
            logger.info("Usando marketplace de afiliados (app.hotmart.com/market)")
            auth_products = await _scrape_app_market(context, max_products=200)
            all_products.extend(auth_products)
        else:
            # ── SCRAPING PÚBLICO: hotmart.com/es/marketplace ──
            logger.info("Usando marketplace público (sin comisión/temperatura)")
            for cat_url in categories:
                try:
                    result = await _scrape_public_category(context, cat_url)
                    if result is None:
                        failed_categories += 1
                    else:
                        all_products.extend(result)
                except Exception as e:
                    failed_categories += 1
                    logger.error(f"Error en {cat_url}: {e}")
                await _random_delay()

    except Exception as e:
        logger.error(f"Error fatal: {e}")
    finally:
        if browser:
            await browser.close()
        if pw:
            await pw.stop()

    logger.info(
        f"Scraping completo: {len(all_products)} productos "
        f"({failed_categories} categorías fallidas)"
    )
    return all_products
