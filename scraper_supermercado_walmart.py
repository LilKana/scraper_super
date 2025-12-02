import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import re
import time
import json
from datetime import datetime

# --- CONFIGURACIÓN GLOBAL ---
MODEL_NAME = "tucanasta.producto"
MONEDA = "CLP"

#  CONFIGURACIÓN ANTI-BLOQUEO
USER_AGENT_PERSONALIZADO = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


URL_BASE_LIDER = "https://super.lider.cl"
URL_OBJETIVO_LIDER = URL_BASE_LIDER + "/browse/despensa/conservas/46589040_33283038"
NOMBRE_SUPER_LIDER = "Lider Supermercado"
SUPERMERCADO_ID_LIDER = 1

# Selectores
SELECTOR_PRODUCTO_CONTAINER = 'li[data-item-id], div[data-item-id]'
SELECTOR_MARCA_LIDER = 'div.mb1.mt2.b.f6.black'
SELECTOR_NOMBRE_LIDER = 'span.w_q67L, span[role="heading"]'
SELECTOR_PRECIO_LIDER = 'span[data-automation-id="product-price"], div[data-automation-id="product-price"]'
SELECTOR_IMAGEN_LIDER = 'img'

# Selectores Ubicación
SELECTOR_MODAL_OPENER = 'div[data-testid="location-banner"]'
SELECTOR_INPUT_UBICACION = 'input[placeholder="Buscar Comuna"]'
SELECTOR_RESULTADO_UBICACION = 'div[data-testid="location-list"] > button'
SELECTOR_BOTON_CERRAR_COOKIES = 'button:has-text("Aceptar todas las cookies")'

# --- FUNCIÓN SCROLL ---
def realizar_scroll_infinito(page):
    print(" -> Iniciando Scroll Infinito...")
    previous_height = page.evaluate("document.body.scrollHeight")
    while True:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(2)
        new_height = page.evaluate("document.body.scrollHeight")
        if new_height == previous_height:
            page.evaluate("window.scrollBy(0, -500)")
            time.sleep(1)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)
            final_height = page.evaluate("document.body.scrollHeight")
            if final_height == new_height:
                break
        previous_height = new_height

# --- 1. EXTRACCIÓN ---
def extraer_productos_lider(url):
    print(f"--- Iniciando extracción en {NOMBRE_SUPER_LIDER} ---")
    productos_extraidos = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=100)
        context = browser.new_context(user_agent=USER_AGENT_PERSONALIZADO, viewport={'width': 1366, 'height': 768})
        page = context.new_page()
        
        try:
            page.goto(url, timeout=90000, wait_until="domcontentloaded")
            
            # Cookies
            try:
                page.click(SELECTOR_BOTON_CERRAR_COOKIES, timeout=4000)
            except: pass

            # Ubicación
            try:
                page.wait_for_selector(SELECTOR_PRECIO_LIDER, timeout=5000)
            except:
                try:
                    page.wait_for_selector(SELECTOR_MODAL_OPENER, timeout=10000)
                    page.click(SELECTOR_MODAL_OPENER)
                    time.sleep(2)
                    page.fill(SELECTOR_INPUT_UBICACION, "Independencia")
                    time.sleep(2)
                    page.locator(SELECTOR_RESULTADO_UBICACION).first.click()
                    page.wait_for_load_state("networkidle", timeout=15000)
                    time.sleep(3)
                except Exception: pass

            # Carga
            try:
                page.wait_for_selector(SELECTOR_PRODUCTO_CONTAINER, timeout=20000)
                realizar_scroll_infinito(page)
            except:
                return []

            # Procesamiento
            contenedores = page.locator(SELECTOR_PRODUCTO_CONTAINER).all()
            print(f"✅ Productos encontrados: {len(contenedores)}")

            for contenedor in contenedores:
                try:
                    texto = contenedor.inner_text()
                    disponible = False if "Agotado" in texto else True

                    marca_loc = contenedor.locator(SELECTOR_MARCA_LIDER).first
                    nombre_loc = contenedor.locator(SELECTOR_NOMBRE_LIDER).first
                    precio_loc = contenedor.locator(SELECTOR_PRECIO_LIDER).first
                    
                    marca = marca_loc.inner_text().strip() if marca_loc.count() else "Genérico"
                    nombre = nombre_loc.inner_text().strip() if nombre_loc.count() else "Sin nombre"
                    precio_texto = precio_loc.inner_text() if precio_loc.count() else "0"
                    
                
                    precio_limpio = re.sub(r'[^\d]', '', precio_texto)
                    if precio_limpio:
                        # Tomamos solo los primeros 4 caracteres
                        precio_4_digitos = precio_limpio[:4]
                        precio_entero = int(precio_4_digitos)
                    else:
                        precio_entero = 0

                    # Links e Imágenes
                    enlace_tag = contenedor.locator('a').first
                    url_origen = URL_BASE_LIDER + enlace_tag.get_attribute('href') if enlace_tag.count() else url
                    
                    img_tag = contenedor.locator(SELECTOR_IMAGEN_LIDER).first
                    imagen_url = None
                    if img_tag.count():
                        imagen_url = img_tag.get_attribute('src')
                        if not imagen_url or "data:image" in imagen_url:
                            imagen_url = img_tag.get_attribute('data-src')

                    if precio_entero == 0 and nombre == "Sin nombre": continue

                    productos_extraidos.append({
                        'supermercado': NOMBRE_SUPER_LIDER,
                        'nombre': f"{marca} - {nombre}",
                        'marca': marca,
                        'nombre_corto': nombre,
                        'precio_clp': precio_entero, # Entero truncado
                        'url_origen': url_origen,
                        'imagen_url': imagen_url,
                        'disponible': disponible,
                        'fecha_actualizacion': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')
                    })
                except: continue

        except Exception as e:
            print(f"Error: {e}")
        finally:
            browser.close()
            
    return productos_extraidos

# --- 2. FORMATO ---
def formatear_a_django_serializado(datos, model_name, super_id):
    output = []
    pk = 1
    for p in datos:
        output.append({
            "model": model_name,
            "pk": pk,
            "fields": {
                "nombre": p['nombre_corto'][:200],
                "marca": p['marca'][:100],
                "tipo": "Despensa",
                "descripcion": p['nombre'],
                "supermercado": super_id,
                "precio": p['precio_clp'], 
                "moneda": MONEDA,
                "imagen_url": p['imagen_url'] or "",
                "producto_url": p['url_origen'],
                "disponible": p['disponible'],
                "fecha_actualizacion": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
            }
        })
        pk += 1
    return output

# --- 3. EJECUCIÓN ---
if __name__ == "__main__":
    data = extraer_productos_lider(URL_OBJETIVO_LIDER)
    if data:
        df = pd.DataFrame(data)
        df.drop_duplicates(subset=['url_origen'], keep='last', inplace=True)
        final_data = formatear_a_django_serializado(df.to_dict('records'), MODEL_NAME, SUPERMERCADO_ID_LIDER)
        
        print(f"✅ Extracción finalizada: {len(final_data)} productos.")
        # Verificación visual del truncado
        print("Muestra (Precio truncado a 4 dígitos):", json.dumps(final_data[:1], indent=2))

        #--aqui se cambia el nombre del archivo segun la categoria de productos .json-- 
        with open('lider_.json', 'w', encoding='utf-8') as f:
            json.dump(final_data, f, indent=2, ensure_ascii=False)