import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import re
import time
import json
from datetime import datetime

# --- CONFIGURACIÓN GLOBAL ---
MODEL_NAME = "tucanasta.producto"
MONEDA = "CLP"
SUPERMERCADO_ID_JUMBO = 2


USER_AGENT_PERSONALIZADO = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# --- CONFIGURACIÓN JUMBO ---
URL_BASE_JUMBO = "https://www.jumbo.cl"
URL_OBJETIVO_JUMBO = "https://www.jumbo.cl/lacteos-huevos-y-congelados/huevos"
NOMBRE_SUPER_JUMBO = "Jumbo"


SELECTOR_PRODUCTO_CONTAINER = 'div[data-cnstrc-item-id]' 
SELECTOR_BOTON_VER_MAS = 'button.ne-load-more-button' # A veces usan botón "Ver más"
SELECTOR_LOADER = 'div.loading-spinner' # Para detectar cargas

# --- FUNCIÓN SCROLL INFINITO ---
def realizar_scroll_infinito(page):
    print(" -> Iniciando Scroll Infinito en Jumbo...")
    previous_height = page.evaluate("document.body.scrollHeight")
    no_change_count = 0
    
    while True:
        # Scroll al fondo
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(3) 
        
   
        try:
            boton = page.locator('button:has-text("Ver más productos"), button.search-results-button')
            if boton.is_visible():
                boton.click()
                print(" -> Botón 'Ver más' clickeado.")
                time.sleep(3)
        except:
            pass

        new_height = page.evaluate("document.body.scrollHeight")
        
        if new_height == previous_height:
            no_change_count += 1
            # Pequeño "meneito" para despertar el lazy load
            page.evaluate("window.scrollBy(0, -700)")
            time.sleep(1)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            
            if no_change_count >= 3:
                print(" -> Fin del scroll (Altura estable).")
                break
        else:
            no_change_count = 0
        
        previous_height = new_height

# --- 1. EXTRACCIÓN ---
def extraer_productos_jumbo(url):
    print(f"--- Iniciando extracción en {NOMBRE_SUPER_JUMBO} ---")
    productos_extraidos = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  
        context = browser.new_context(
            user_agent=USER_AGENT_PERSONALIZADO,
            viewport={'width': 1920, 'height': 1080}
        )
        page = context.new_page()
        
        try:
            page.goto(url, timeout=90000, wait_until="domcontentloaded")
            
           
            time.sleep(5) 

       
            try:
                page.wait_for_selector(SELECTOR_PRODUCTO_CONTAINER, timeout=30000)
                realizar_scroll_infinito(page)
            except Exception as e:
                print(f"⚠️ Alerta: No se cargaron productos o falló el scroll: {e}")
               

    
            contenedores = page.locator(SELECTOR_PRODUCTO_CONTAINER).all()
            print(f"✅ Productos encontrados en DOM: {len(contenedores)}")

            for contenedor in contenedores:
                try:
                    nombre = contenedor.get_attribute("data-cnstrc-item-name")
                    precio_str = contenedor.get_attribute("data-cnstrc-item-price")
                    item_id = contenedor.get_attribute("data-cnstrc-item-id")
                    
                    if not nombre or not precio_str:
                        continue

               
                    precio_entero = int(float(precio_str)) 

                    
                    marca = "Genérica"
                    try:
                        marca_elem = contenedor.locator("div.product-card-brand, .brand-name").first
                        if marca_elem.count() > 0:
                            marca = marca_elem.inner_text().strip()
                        else:
                            # Inferencia simple desde el nombre
                            marca = nombre.split(" ")[0] 
                    except:
                        pass

                    # 3. URL del producto
                    enlace_tag = contenedor.locator('a').first
                    href = enlace_tag.get_attribute('href')
                    url_producto = URL_BASE_JUMBO + href if href and not href.startswith('http') else (href or url)

                    # 4. Imagen
                    imagen_url = ""
                    img_tag = contenedor.locator('img').first
                    if img_tag.count() > 0:
                        imagen_url = img_tag.get_attribute('src')
                    
                    # Filtro de seguridad
                    if precio_entero <= 0:
                        continue

                    productos_extraidos.append({
                        'supermercado': NOMBRE_SUPER_JUMBO,
                        'nombre': nombre,
                        'marca': marca,
                        'nombre_corto': nombre, 
                        'precio_clp': precio_entero,
                        'url_origen': url_producto,
                        'imagen_url': imagen_url,
                        'disponible': True, # Si aparece en el listado suele estar disponible
                        'fecha_actualizacion': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')
                    })

                except Exception as e:
                    # print(f"Error en un producto: {e}")
                    continue

        except Exception as e:
            print(f"❌ ERROR CRÍTICO JUMBO: {e}")
        finally:
            browser.close()
            
    return productos_extraidos

# --- 2. FORMATO DJANGO ---
def formatear_a_django_serializado(datos, model_name, super_id):
    output = []
# Aqui cambian el pk de acuerdo a que numero van 
    pk = 1
    for p in datos:
        output.append({
            "model": model_name,
            "pk": pk,
            "fields": {
                "nombre": p['nombre'][:200],
                "marca": p['marca'][:100],
                "tipo": 'Despensa', 
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

# --EJECUCIÓN ---
if __name__ == "__main__":
    start_time = time.time()
    data = extraer_productos_jumbo(URL_OBJETIVO_JUMBO)
    
    if data:
        df = pd.DataFrame(data)
        df.drop_duplicates(subset=['url_origen'], keep='last', inplace=True)
        final_data = formatear_a_django_serializado(df.to_dict('records'), MODEL_NAME, SUPERMERCADO_ID_JUMBO)
        
        print(f"\n✅ Extracción JUMBO finalizada: {len(final_data)} productos.")
        print("Muestra:", json.dumps(final_data[:2], indent=2))

        #--aqui se cambia el nombre del archivo segun la categoria de productos.jason--
        with open('jumbo_.json', 'w', encoding='utf-8') as f:
            json.dump(final_data, f, indent=2, ensure_ascii=False)
            
        print("Archivo guardado: jumbo_huevos.json")
    else:
        print("⚠️ No se extrajeron datos.")
    
    print(f"Tiempo: {round(time.time() - start_time, 2)}s")