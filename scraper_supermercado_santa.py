import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import re
import time
import json
from datetime import datetime

# --- CONFIGURACIÓN DEL SITIO WEB  ---

URL_BASE = "https://www.santaisabel.cl"
# --- Aqui se coloca el URL despues del .cl/ --- 
URL_OBJETIVO = URL_BASE + "/carnes-y-pescados/vacuno" 
NOMBRE_SUPER = "Santa Isabel"


SELECTOR_PRODUCTO_CLAVE = 'a.product-card' 
SELECTOR_ACEPTAR_COOKIES = 'button:has-text("Aceptar todas las cookies")' 

# --- CONFIGURACIÓN DEL MODELO DJANGO  ---
MODEL_NAME = "tucanasta.producto"
SUPERMERCADO_ID = 4 
MONEDA = "CLP"

# --- FUNCIONES CENTRALES ---

def extraer_productos_santa_isabel(url):
    """
    Función de extracción que trunca el precio a los primeros 4 dígitos.
    """
    print(f"--- Iniciando extracción en {NOMBRE_SUPER} ({url}) ---")
    productos_extraidos = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) 
        page = browser.new_page()

        try:
            page.goto(url, timeout=90000) 

            # Manejo de Cookies
            try:
                page.click(SELECTOR_ACEPTAR_COOKIES, timeout=10000) 
                time.sleep(2) 
            except PlaywrightTimeoutError:
                pass
            
            # Esperar al selector clave
            page.wait_for_selector(SELECTOR_PRODUCTO_CLAVE, timeout=30000) 
            time.sleep(5) 
            
            contenedores = page.locator(SELECTOR_PRODUCTO_CLAVE).all()
            print(f"Se encontraron {len(contenedores)} productos listados.")

            # Iterar y extraer los datos
            for i, contenedor in enumerate(contenedores):
                try:
                    # Extracción de campos 
                    nombre_tag = contenedor.locator('p.product-card-name')
                    marca_tag = contenedor.locator('p.product-card-brand')
                    precio_texto = contenedor.locator('div.product-card-prices').inner_text()
                    imagen_url_tag = contenedor.locator('img').first
                    enlace_relativo = contenedor.get_attribute('href')
                    
                    # Procesamiento
                    nombre = nombre_tag.inner_text().strip()
                    marca = marca_tag.inner_text().strip()
                    precio_limpio = re.sub(r'[^\d]', '', precio_texto)
                    url_origen = URL_BASE + enlace_relativo
                    imagen_url = imagen_url_tag.get_attribute('src')

                    #  Redondeo/Truncamiento a 4 dígitos
                    if precio_limpio:
                        # 1. Tomar los primeros 4 dígitos de la cadena
                        precio_truncado_str = precio_limpio[:4]
                        # 2. Convertir a entero
                        precio_entero = int(precio_truncado_str)
                    else:
                        precio_entero = 0
                    
                    productos_extraidos.append({
                        'supermercado': NOMBRE_SUPER,
                        'nombre': f"{marca} - {nombre}",
                        'marca': marca,
                        'nombre_corto': nombre,
                        'precio_clp': precio_entero, 
                        'url_origen': url_origen,
                        'imagen_url': imagen_url if imagen_url and imagen_url.startswith('http') else None,
                        'fecha_actualizacion': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')
                    })
                    
                except Exception:
                    continue

        except Exception as e:
            print(f"❌ ERROR CRÍTICO DURANTE LA EXTRACCIÓN: {e}")

        finally:
            browser.close()
            
    return productos_extraidos


def formatear_a_django_serializado(datos_extraidos, model_name, supermercado_id):
    """
    Convierte la lista de diccionarios extraídos al formato serializado de Django.
    """
    productos_django = []
    pk_counter = 1
    
    for producto in datos_extraidos:
        
        fields = {
            "nombre": producto.get('nombre_corto'),
            "marca": producto.get('marca'),
            "tipo": 'Despensa',
            "descripcion": None,
            "supermercado": supermercado_id, 
            "precio": str(producto.get('precio_clp', 0)), 
            "moneda": MONEDA,
            "imagen_url": producto.get('imagen_url'),
            "producto_url": producto.get('url_origen'),
            "disponible": True,
            "fecha_actualizacion": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        }
        
        objeto_django = {
            "model": model_name,
            "pk": pk_counter,
            "fields": fields
        }
        
        productos_django.append(objeto_django)
        pk_counter += 1
        
    return productos_django

# --- EJECUCIÓN PRINCIPAL ---

if __name__ == "__main__":
    
    data_extraida = extraer_productos_santa_isabel(URL_OBJETIVO)
    
    if data_extraida:
        datos_serializados = formatear_a_django_serializado(
            data_extraida, 
            MODEL_NAME, 
            SUPERMERCADO_ID
        )
        
        print("\n==========================================================================")
        print(f"✅ EXTRACCIÓN FINALIZADA: {len(datos_serializados)} PRODUCTOS SERIALIZADOS")
        print("==========================================================================")
        
        print("Muestra de los primeros 5 ítems (PRECIO TRUNCADO A 4 DÍGITOS):")
        print(json.dumps(datos_serializados[:5], indent=2)) 

        #--aqui se cambia el nombre del archivo segun la categoria de productos.jason-- 
        file_name = 'santa_isabel_.json'
        with open(file_name, 'w', encoding='utf-8') as f:
            json.dump(datos_serializados, f, indent=2, ensure_ascii=False)
        
        print(f"\nTodos los datos guardados en el archivo '{file_name}'.")

    else:
        print("\n--- ⚠️ FALLO AL EXTRAER DATOS ---")

# -- para iniciarlo hay que colocar --python scraper_supermercado_santa.py--