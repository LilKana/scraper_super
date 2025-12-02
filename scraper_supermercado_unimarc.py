import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import re
import time
import json
from datetime import datetime

# --- CONFIGURACIÓN GLOBAL ---
MODEL_NAME = "tucanasta.producto"
MONEDA = "CLP"
SUPERMERCADO_ID_UNIMARC = 2

# 🛑 USER AGENT (Vital para evitar bloqueos)
USER_AGENT_PERSONALIZADO = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# URL OBJETIVO (Arroz y Legumbres)
URL_OBJETIVO_UNIMARC = "https://www.unimarc.cl/category/despensa/arroz-y-legumbres"
NOMBRE_SUPER_UNIMARC = "Unimarc"

# --- SELECTORES ---
# Buscamos enlaces que lleven a productos, ignorando banners u otros links
SELECTOR_CARD_LINK = 'a[href^="/product/"]' 
# Selector genérico por si encontramos el ID del precio
SELECTOR_PRECIO_ID = '[id^="ListPrice"]' 

# --- FUNCIÓN SCROLL ---
def realizar_scroll_infinito(page):
    """Baja por la página para activar la carga de productos (Lazy Load)"""
    print(" -> Iniciando Scroll Infinito...")
    previous_height = page.evaluate("document.body.scrollHeight")
    no_change_count = 0
    
    while True:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1.5) # Espera breve para renderizado
        
        new_height = page.evaluate("document.body.scrollHeight")
        if new_height == previous_height:
            no_change_count += 1
            # Pequeño rebote hacia arriba para desbloquear cargas trabadas
            page.evaluate("window.scrollBy(0, -400)")
            time.sleep(0.5)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            
            if no_change_count >= 5: # Si tras 5 intentos no crece, terminamos
                print(" -> Fin del scroll.")
                break
        else:
            no_change_count = 0
        previous_height = new_height

# --- EXTRACCIÓN PRINCIPAL ---
def extraer_productos_unimarc(url):
    print(f"--- Iniciando extracción en {NOMBRE_SUPER_UNIMARC} ---")
    productos_extraidos = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=USER_AGENT_PERSONALIZADO,
            viewport={'width': 1366, 'height': 800}
        )
        page = context.new_page()
        
        try:
            page.goto(url, timeout=90000, wait_until="domcontentloaded")
            
            # 1. ESPERA INTELIGENTE
            # No esperamos precios inmediatamente, esperamos los links de productos
            try:
                page.wait_for_selector(SELECTOR_CARD_LINK, timeout=20000)
                print(" -> Catálogo cargado inicialmente.")
            except:
                print("⚠️ Alerta: No se detectaron enlaces iniciales, intentando scroll igual.")

            # 2. SCROLL PARA CARGAR TODO
            realizar_scroll_infinito(page)
            
            # 3. PROCESAMIENTO
            links_productos = page.locator(SELECTOR_CARD_LINK).all()
            print(f"✅ Enlaces detectados tras scroll: {len(links_productos)}")
            
            urls_procesadas = set()

            for link in links_productos:
                try:
                    href = link.get_attribute('href')
                    # Filtros de seguridad para evitar duplicados o links rotos
                    if not href or href in urls_procesadas or "/product/" not in href:
                        continue

                    urls_procesadas.add(href)
                    full_url = "https://www.unimarc.cl" + href

                    # --- BÚSQUEDA DEL CONTENEDOR ---
                    # El link es hijo del contenedor. Subimos 4 niveles para encontrar
                    # el bloque que contiene tanto el nombre como el precio.
                    contenedor_padre = link.locator('xpath=./ancestor::div[4]').first

                    # A. Nombre
                    nombre = link.get_attribute('title')
                    if not nombre:
                        img = link.locator('img').first
                        if img.count() > 0:
                            nombre = img.get_attribute('alt')
                    
                    if not nombre: continue 

                    # B. Precio (Lógica Robusta)
                    precio_entero = 0
                    
                    # Intento 1: Buscar por ID (ListPrice...)
                    precio_elem = contenedor_padre.locator(SELECTOR_PRECIO_ID).first
                    
                    # Intento 2: Buscar visualmente cualquier texto con formato "$..."
                    # 🛑 CORRECCIÓN APLICADA AQUÍ:
                    # Usamos r"" y la sintaxis text=/regex/ de Playwright
                    if precio_elem.count() == 0:
                        precio_elem = contenedor_padre.locator(r"text=/\$\s?[\d\.]+/").first

                    if precio_elem.count() > 0:
                        precio_texto = precio_elem.inner_text()
                        # Limpiamos todo lo que no sea número
                        precio_limpio = re.sub(r'[^\d]', '', precio_texto)
                        if precio_limpio:
                            precio_entero = int(precio_limpio)

                    # C. Otros Datos
                    marca = nombre.split(" ")[0] if nombre else "Genérica"
                    
                    imagen_url = ""
                    img_tag = link.locator('img').first
                    if img_tag.count() > 0:
                        imagen_url = img_tag.get_attribute('src')

                    # Guardar solo si encontramos precio válido
                    if precio_entero > 0:
                        productos_extraidos.append({
                            'supermercado': NOMBRE_SUPER_UNIMARC,
                            'nombre': nombre,
                            'marca': marca,
                            'nombre_corto': nombre,
                            'precio_clp': precio_entero,
                            'url_origen': full_url,
                            'imagen_url': imagen_url,
                            'disponible': True,
                            'fecha_actualizacion': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')
                        })

                except Exception as e:
                    continue

        except Exception as e:
            print(f"❌ ERROR GENERAL: {e}")
        finally:
            browser.close()
            
    return productos_extraidos

# --- FORMATO ---
def formatear_a_django_serializado(datos, model_name, super_id):
    output = []
    pk = 1
    for p in datos:
        output.append({
            "model": model_name,
            "pk": pk,
            "fields": {
                "nombre": p['nombre'][:200],
                "marca": p['marca'][:100],
                "tipo": "Despensa",
                "descripcion": p['nombre'],
                "supermercado": super_id,
                "precio": p['precio_clp'],
                "moneda": MONEDA,
                "imagen_url": p['imagen_url'] or "",
                "producto_url": p['url_origen'],
                "disponible": True,
                "fecha_actualizacion": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
            }
        })
        pk += 1
    return output

# --- EJECUCIÓN ---
if __name__ == "__main__":
    start_time = time.time()
    data = extraer_productos_unimarc(URL_OBJETIVO_UNIMARC)
    
    if data:
        df = pd.DataFrame(data)
        # Eliminamos duplicados
        df.drop_duplicates(subset=['nombre_corto', 'precio_clp'], keep='last', inplace=True)
        final_data = formatear_a_django_serializado(df.to_dict('records'), MODEL_NAME, SUPERMERCADO_ID_UNIMARC)
        
        print(f"\n✅ Extracción UNIMARC finalizada: {len(final_data)} productos.")
        if len(final_data) > 0:
            print("Muestra:", json.dumps(final_data[:1], indent=2))
        
        with open('unimarc_arroz_final.json', 'w', encoding='utf-8') as f:
            json.dump(final_data, f, indent=2, ensure_ascii=False)
            print(f"Archivo guardado: unimarc_arroz_final.json")
    else:
        print("⚠️ No se extrajeron datos.")
    
    print(f"Tiempo: {round(time.time() - start_time, 2)}s")