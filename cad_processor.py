import os
import sys
import tempfile
import subprocess
import math
import ezdxf
from ezdxf import bbox, recover
from ezdxf.addons.drawing import Frontend, RenderContext, layout
from ezdxf.addons.drawing.pymupdf import PyMuPdfBackend
from ezdxf.addons.drawing.config import Configuration, ColorPolicy, BackgroundPolicy
from ezdxf.math import BoundingBox2d
import pymupdf

def safe_read_dxf(dxf_path):
    """
    Intenta leer el archivo DXF de forma súper rápida usando ezdxf.readfile estándar.
    Si falla (por ejemplo, debido a corrupción de cabecera), recurre a recover.readfile
    para reparar estructuras de coordenadas dañadas de forma automática.
    """
    try:
        # ezdxf.readfile estándar es entre 3 y 5 veces más rápido porque no realiza
        # la auditoría completa ni reparación de entidades excepto si es estrictamente necesario.
        return ezdxf.readfile(dxf_path)
    except Exception as e:
        print(f"Lectura estándar falló: {e}. Intentando recuperación automática con auditoría...")
        try:
            doc, auditor = recover.readfile(dxf_path)
            return doc
        except Exception:
            raise e

def is_valid_bbox(box):
    """
    Verifica de forma estricta que una caja de límites (BoundingBox2d) sea válida,
    tenga datos válidos y no contenga coordenadas NaN o Inf.
    """
    if box is None or not box.has_data:
        return False
    try:
        # Verificar NaN e Infinitos
        for val in (box.extmin.x, box.extmin.y, box.extmax.x, box.extmax.y):
            if val is None or math.isnan(val) or math.isinf(val):
                return False
        # El área debe ser positiva y razonable
        w = box.extmax.x - box.extmin.x
        h = box.extmax.y - box.extmin.y
        if w <= 1e-3 or h <= 1e-3:
            return False
        return True
    except Exception:
        return False

def get_resource_path(relative_path):
    """
    Obtiene la ruta absoluta de un recurso, compatible con desarrollo local
    y ejecutable empaquetado con PyInstaller.
    """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def get_short_path_name(long_name):
    """
    Obtiene la versión corta (8.3 format) de una ruta en Windows.
    Esto es crucial para evitar errores con caracteres no-ASCII (tildes, eñes, etc.)
    en herramientas de consola compiladas bajo entornos POSIX como LibreDWG.
    """
    if not long_name or sys.platform != "win32":
        return long_name
    try:
        import ctypes
        from ctypes import wintypes
        
        # Cargar kernel32
        _GetShortPathNameW = ctypes.windll.kernel32.GetShortPathNameW
        _GetShortPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        _GetShortPathNameW.restype = wintypes.DWORD
        
        # Primero calcular el tamaño necesario del búfer
        buf_size = _GetShortPathNameW(long_name, None, 0)
        if buf_size == 0:
            # Si el archivo o directorio no existe aún, intentamos resolver
            # su directorio padre y concatenar el nombre del archivo
            parent, child = os.path.split(long_name)
            if parent:
                parent_short = get_short_path_name(parent)
                return os.path.join(parent_short, child)
            return long_name
            
        buf = ctypes.create_unicode_buffer(buf_size)
        _GetShortPathNameW(long_name, buf, buf_size)
        return buf.value
    except Exception as e:
        print(f"Error al obtener short path name para {long_name}: {e}")
        return long_name

def convert_dwg_to_dxf(dwg_path, dxf_path):
    """
    Convierte un archivo DWG a DXF usando el ejecutable dwg2dxf de LibreDWG.
    """
    dwg2dxf_exe = get_resource_path(os.path.join("libredwg_bin", "dwg2dxf.exe"))
    if not os.path.exists(dwg2dxf_exe):
        # Intentar en la carpeta local de desarrollo si no se encuentra en el ejecutable
        dwg2dxf_exe = os.path.join(os.path.dirname(__file__), "libredwg_bin", "dwg2dxf.exe")
        if not os.path.exists(dwg2dxf_exe):
            raise FileNotFoundError(f"No se encontró el convertidor LibreDWG en {dwg2dxf_exe}")
            
    # Convertir rutas a formato corto (8.3) para evitar problemas con espacios y caracteres especiales/no-ASCII
    dwg2dxf_exe_short = get_short_path_name(dwg2dxf_exe)
    dxf_path_short = get_short_path_name(dxf_path)
    dwg_path_short = get_short_path_name(dwg_path)
    
    cmd = [dwg2dxf_exe_short, "-y", "-o", dxf_path_short, dwg_path_short]
    print(f"Ejecutando: {' '.join(cmd)}")
    
    # Ocultar ventana de consola en Windows al ejecutar el proceso
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        
    # Configurar variables de entorno agregando la carpeta de LibreDWG al PATH para la resolución de sus DLLs
    env = os.environ.copy()
    exe_dir = os.path.dirname(dwg2dxf_exe)
    if exe_dir:
        env["PATH"] = os.path.abspath(exe_dir) + os.pathsep + env.get("PATH", "")
        
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        startupinfo=startupinfo,
        env=env,
        check=False
    )
    
    if result.returncode != 0:
        raise RuntimeError(f"Error al convertir DWG a DXF (código {result.returncode}):\n{result.stderr}")
        
    if not os.path.exists(dxf_path):
        raise FileNotFoundError(f"La conversión finalizó, pero no se generó el archivo de salida en {dxf_path}")
        
    return dxf_path

def pre_analyze_dxf(dxf_path):
    """
    Analiza de forma rápida el archivo DXF para extraer:
    1. Lista de presentaciones (Layouts/Paper Space).
    2. Lista de nombres de bloques (INSERT) y su frecuencia en el espacio modelo.
    3. Capas (Layers) disponibles en el espacio modelo.
    """
    doc = safe_read_dxf(dxf_path)
    msp = doc.modelspace()
    
    # 1. Pestañas de presentación (Layouts)
    # Excluimos "Model" porque es el espacio modelo
    layouts = [lay.name for lay in doc.layouts if lay.name != "Model"]
    
    # 2. Bloques en espacio modelo
    block_counts = {}
    for entity in msp.query('INSERT'):
        name = entity.dxf.name
        block_counts[name] = block_counts.get(name, 0) + 1
        
    blocks = sorted(list(block_counts.items()), key=lambda x: -x[1])
    
    # 3. Capas de polilíneas cerradas (candidatas a rótulos)
    layers = set()
    for entity in msp.query('LWPOLYLINE POLYLINE'):
        if entity.is_closed:
            layers.add(entity.dxf.layer)
            
    return {
        "layouts": layouts,
        "blocks": blocks,
        "layers": sorted(list(layers))
    }

def sort_boxes(boxes):
    """
    Ordena una lista de BoundingBox2d simulando orden de lectura (de arriba a abajo, de izquierda a derecha).
    Usa una tolerancia vertical basada en la altura promedio de las cajas.
    """
    if not boxes:
        return []
        
    # Calcular altura promedio para la tolerancia de alineación vertical
    avg_height = sum((b.extmax.y - b.extmin.y) for b in boxes) / len(boxes)
    tolerance = avg_height * 0.5  # 50% de la altura promedio como tolerancia
    
    # Ordenar por Y descendente primero (arriba a abajo)
    sorted_boxes = sorted(boxes, key=lambda b: -b.extmax.y)
    
    grouped_boxes = []
    current_group = []
    
    for box in sorted_boxes:
        if not current_group:
            current_group.append(box)
        else:
            # Si el borde superior está dentro de la tolerancia, pertenecen a la misma "fila"
            ref_box = current_group[0]
            if abs(ref_box.extmax.y - box.extmax.y) < tolerance:
                current_group.append(box)
            else:
                # Ordenar la fila actual de izquierda a derecha (X ascendente)
                grouped_boxes.extend(sorted(current_group, key=lambda b: b.extmin.x))
                current_group = [box]
                
    if current_group:
        grouped_boxes.extend(sorted(current_group, key=lambda b: b.extmin.x))
        
    return grouped_boxes

def get_polyline_points(entity):
    """Obtiene los puntos 2D de una polilínea (LWPOLYLINE o POLYLINE)."""
    if entity.dxftype() == 'LWPOLYLINE':
        return [p[:2] for p in entity.get_points()]
    elif entity.dxftype() == 'POLYLINE':
        return [p.dxf.location[:2] for p in entity.vertices]
    return []

def is_geometrically_closed(entity):
    """
    Verifica si una polilínea es cerrada geométricamente,
    incluso si su bandera is_closed es False en AutoCAD.
    """
    if entity.is_closed:
        return True
    if entity.dxftype() in ('LWPOLYLINE', 'POLYLINE'):
        points = get_polyline_points(entity)
        if len(points) >= 3:
            p1 = points[0]
            p2 = points[-1]
            # Tolerancia de distancia para cerrar el contorno
            return math.hypot(p1[0] - p2[0], p1[1] - p2[1]) < 2.0
    return False

def filter_nested_boxes(boxes):
    """
    Filtra rectángulos concéntricos o anidados (ej. borde exterior del papel y margen interno).
    Conserva únicamente el rectángulo exterior (más grande), el cual representa el formato del plano.
    """
    if not boxes:
        return []
    # Ordenar por área descendente para procesar los más grandes primero
    sorted_boxes = sorted(
        boxes, 
        key=lambda b: (b.extmax.x - b.extmin.x) * (b.extmax.y - b.extmin.y), 
        reverse=True
    )
    unique_boxes = []
    
    for box in sorted_boxes:
        is_nested = False
        for kept in unique_boxes:
            w_kept = kept.extmax.x - kept.extmin.x
            h_kept = kept.extmax.y - kept.extmin.y
            # Tolerancia del 8% del tamaño del plano exterior
            tol_x = w_kept * 0.08
            tol_y = h_kept * 0.08
            
            # Verificar si box está contenido dentro de kept
            if (kept.extmin.x - tol_x <= box.extmin.x <= kept.extmax.x + tol_x) and \
               (kept.extmin.y - tol_y <= box.extmin.y <= kept.extmax.y + tol_y) and \
               (kept.extmin.x - tol_x <= box.extmax.x <= kept.extmax.x + tol_x) and \
               (kept.extmin.y - tol_y <= box.extmax.y <= kept.extmax.y + tol_y):
                is_nested = True
                break
        if not is_nested:
            unique_boxes.append(box)
            
    return unique_boxes

def find_rectangles_from_lines(msp, min_size=(0.05, 0.05), cache=None):
    """
    Intenta reconstruir rectángulos cerrados y alineados a los ejes a partir
    de entidades LINE individuales de manera ultra rápida (O(H^2 log V)).
    Usa una longitud de línea mínima calculada dinámicamente según la escala del espacio modelo.
    """
    from ezdxf.math import BoundingBox2d, Vec2
    import math
    import bisect
    
    lines = list(msp.query('LINE'))
    if len(lines) < 4:
        return []
        
    # Calcular extensión general del Espacio Modelo para definir un umbral de longitud dinámico
    try:
        msp_box = bbox.extents(msp, cache=cache)
        if msp_box.has_data:
            w_msp = msp_box.extmax.x - msp_box.extmin.x
            h_msp = msp_box.extmax.y - msp_box.extmin.y
            max_dim = max(w_msp, h_msp)
            # El borde de una hoja debe medir al menos el 1.5% del tamaño total del dibujo,
            # con un tope máximo conservador de 10.0 unidades (para planos en mm/cm).
            min_line_length = max(0.05, min(10.0, max_dim * 0.015))
        else:
            min_line_length = 10.0
    except Exception:
        min_line_length = 10.0
        
    v_lines = []
    h_lines = []
    tol = 0.5  # Tolerancia angular para líneas verticales/horizontales
    
    for line in lines:
        p1 = line.dxf.start
        p2 = line.dxf.end
        
        dx = abs(p1.x - p2.x)
        dy = abs(p1.y - p2.y)
        length = math.hypot(p1.x - p2.x, p1.y - p2.y)
        
        # Omitir segmentos que son más cortos que el límite dinámico
        if length < min_line_length:
            continue
            
        if dx < tol:  # Vertical
            y_min = min(p1.y, p2.y)
            y_max = max(p1.y, p2.y)
            v_lines.append({
                "x": (p1.x + p2.x) / 2.0,
                "y_min": y_min,
                "y_max": y_max,
                "length": y_max - y_min,
                "layer": line.dxf.layer
            })
        elif dy < tol:  # Horizontal
            x_min = min(p1.x, p2.x)
            x_max = max(p1.x, p2.x)
            h_lines.append({
                "y": (p1.y + p2.y) / 2.0,
                "x_min": x_min,
                "x_max": x_max,
                "length": x_max - x_min,
                "layer": line.dxf.layer
            })
            
    # Indexar líneas verticales por X para búsquedas binarias ultrarrápidas
    v_sorted = sorted(v_lines, key=lambda l: l["x"])
    v_xs = [v["x"] for v in v_sorted]
    
    def has_vertical_connection(x_target, y_min_target, y_max_target, length_target, align_tol, length_tol):
        # Búsqueda binaria del rango de coordenadas X candidatas
        idx = bisect.bisect_left(v_xs, x_target - align_tol)
        while idx < len(v_sorted) and v_sorted[idx]["x"] <= x_target + align_tol:
            v = v_sorted[idx]
            if abs(v["y_min"] - y_min_target) < align_tol and \
               abs(v["y_max"] - y_max_target) < align_tol and \
               abs(v["length"] - length_target) < length_tol:
                return True
            idx += 1
        return False

    rect_candidates = []
    
    # Emparejar líneas horizontales (tienen que compartir X similar y estar en Y distintos)
    h_count = len(h_lines)
    for i in range(h_count):
        h1 = h_lines[i]
        for j in range(i + 1, h_count):
            h2 = h_lines[j]
            
            # Asegurar que h1 sea la de abajo y h2 la de arriba
            if h1["y"] > h2["y"]:
                h_bottom, h_top = h2, h1
            else:
                h_bottom, h_top = h1, h2
                
            height = h_top["y"] - h_bottom["y"]
            if height < min_size[1]:
                continue
                
            # Deben tener anchos similares y coincidir en X
            width_avg = (h_bottom["length"] + h_top["length"]) / 2.0
            if width_avg < min_size[0]:
                continue
                
            length_tol = max(5.0, width_avg * 0.015)
            align_tol = max(5.0, width_avg * 0.015)
            
            if abs(h_bottom["length"] - h_top["length"]) > length_tol:
                continue
            if abs(h_bottom["x_min"] - h_top["x_min"]) > align_tol or \
               abs(h_bottom["x_max"] - h_top["x_max"]) > align_tol:
                continue
                
            x_min = (h_bottom["x_min"] + h_top["x_min"]) / 2.0
            x_max = (h_bottom["x_max"] + h_top["x_max"]) / 2.0
            y_min = h_bottom["y"]
            y_max = h_top["y"]
            
            # Buscar si existen las dos líneas verticales que cierran el rectángulo
            h_len_tol = max(5.0, height * 0.015)
            h_align_tol = max(5.0, height * 0.015)
            
            if has_vertical_connection(x_min, y_min, y_max, height, h_align_tol, h_len_tol) and \
               has_vertical_connection(x_max, y_min, y_max, height, h_align_tol, h_len_tol):
                box = BoundingBox2d([Vec2(x_min, y_min), Vec2(x_max, y_max)])
                rect_candidates.append(box)
                
    return rect_candidates

def detect_sheets_in_modelspace(dxf_path, method="auto", block_name=None, layer_name=None, min_size=(0.05, 0.05), sort_sheets=True):
    """
    Detecta áreas de planos en el Espacio Modelo del DXF.
    Retorna una lista de objetos BoundingBox2d ordenados y filtrados.
    """
    doc = safe_read_dxf(dxf_path)
    msp = doc.modelspace()
    cache = bbox.Cache()
    
    candidates = []
    
    if method == "block" and block_name:
        # Buscar por inserciones de un bloque específico
        for entity in msp.query(f'INSERT[name=="{block_name}"]'):
            try:
                entity_box = bbox.extents([entity], cache=cache)
                if not is_valid_bbox(entity_box):
                    continue
                # Validar que tenga dimensiones mínimas válidas
                w = entity_box.extmax.x - entity_box.extmin.x
                h = entity_box.extmax.y - entity_box.extmin.y
                if w >= min_size[0] and h >= min_size[1]:
                    candidates.append(entity_box)
            except Exception as e:
                print(f"Error calculando bounding box para el bloque {block_name}: {e}")
                
    elif method == "polyline":
        # Buscar polilíneas cerradas (LWPOLYLINE y POLYLINE)
        if layer_name:
            entities = list(msp.query(f'LWPOLYLINE[layer=="{layer_name}"]')) + list(msp.query(f'POLYLINE[layer=="{layer_name}"]'))
        else:
            entities = list(msp.query('LWPOLYLINE')) + list(msp.query('POLYLINE'))
            
        for entity in entities:
            if is_geometrically_closed(entity):
                try:
                    entity_box = bbox.extents([entity], cache=cache)
                    if not is_valid_bbox(entity_box):
                        continue
                    w = entity_box.extmax.x - entity_box.extmin.x
                    h = entity_box.extmax.y - entity_box.extmin.y
                    if w >= min_size[0] and h >= min_size[1]:
                        candidates.append(entity_box)
                except Exception as e:
                    print(f"Error calculando bounding box para polilínea: {e}")
                    
    else:  # method == "auto" (Detección automática de rectángulos estándar A0-A4 y personalizados)
        # 1. Buscar polilíneas cerradas
        entities = list(msp.query('LWPOLYLINE')) + list(msp.query('POLYLINE'))
        for entity in entities:
            if is_geometrically_closed(entity):
                try:
                    entity_box = bbox.extents([entity], cache=cache)
                    if not is_valid_bbox(entity_box):
                        continue
                    w = entity_box.extmax.x - entity_box.extmin.x
                    h = entity_box.extmax.y - entity_box.extmin.y
                    
                    if w >= min_size[0] and h >= min_size[1]:
                        # Aceptar un rango de aspecto amplio para formatos apaisados, verticales y alargados (1.0 a 3.0)
                        ratio = max(w, h) / min(w, h)
                        if 1.0 <= ratio <= 3.0:
                            candidates.append(entity_box)
                except Exception as e:
                    pass
                    
        # 2. Buscar rectángulos compuestos por líneas sueltas
        try:
            line_rects = find_rectangles_from_lines(msp, min_size=min_size, cache=cache)
            candidates.extend(line_rects)
        except Exception as e:
            print(f"Error al reconstruir rectángulos desde líneas sueltas: {e}")
                    
    # Filtrar rectángulos anidados (ej. conservar solo el marco exterior)
    if candidates:
        candidates = filter_nested_boxes(candidates)
        
    if sort_sheets:
        candidates = sort_boxes(candidates)
        
    return candidates

def process_file_to_pdf(dwg_path, output_pdf_path, config, progress_callback=None):
    """
    Función principal que orquesta la conversión de DWG a PDF.
    
    config es un diccionario con las siguientes claves:
    - mode: "layouts" o "modelspace"
    - ms_method: "auto", "block" o "polyline"
    - block_name: (str) nombre del bloque si se selecciona ese método
    - layer_name: (str) nombre de la capa si se selecciona ese método
    - combine_pdf: (bool) si se combinan en un solo PDF o se guardan por separado
    - orientation: "auto", "landscape" o "portrait"
    """
    # Crear un archivo temporal con nombre seguro en formato ASCII
    temp_dir = tempfile.gettempdir()
    dxf_name = f"temp_blueprint_process_{os.getpid()}_{int(time.time())}.dxf"
    temp_dxf_path = os.path.join(temp_dir, dxf_name)
    
    try:
        if progress_callback:
            progress_callback("Convirtiendo DWG a DXF...", 0.1)
            
        convert_dwg_to_dxf(dwg_path, temp_dxf_path)
        
        doc = safe_read_dxf(temp_dxf_path)
        ctx = RenderContext(doc)
        
        pdf_pages_bytes = []
        
        if config.get("mode") == "layouts":
            # Obtener layouts activos (Paper Space)
            layout_names = config.get("selected_layouts")
            if not layout_names:
                layout_names = [lay.name for lay in doc.layouts if lay.name != "Model"]
            
            if not layout_names:
                raise ValueError("El archivo no contiene pestañas de presentación (Layouts/Paper Space).")
                
            total_layouts = len(layout_names)
            valid_layouts_processed = 0
            
            for idx, lay_name in enumerate(layout_names):
                lay_obj = doc.layout(lay_name)
                
                # Verificar si el layout contiene elementos con límites válidos (evita layouts vacíos por defecto)
                lay_box = bbox.extents(lay_obj)
                if not is_valid_bbox(lay_box):
                    print(f"Layout '{lay_name}' está vacío o no contiene elementos válidos. Omitiendo.")
                    continue
                
                if progress_callback:
                    progress_callback(f"Renderizando Layout '{lay_name}' ({idx+1}/{total_layouts})...", 0.2 + (idx/total_layouts)*0.6)
                
                backend = PyMuPdfBackend()
                color_mode = config.get("color_mode", "color")
                draw_config = Configuration(
                    background_policy=BackgroundPolicy.WHITE,
                    color_policy=ColorPolicy.BLACK if color_mode == "monochrome" else ColorPolicy.COLOR
                )
                Frontend(ctx, backend, config=draw_config).draw_layout(lay_obj)
                
                # Configurar página. Si se puede, leer dimensiones del layout
                try:
                    page = layout.Page.from_dxf_layout(lay_obj)
                    # Forzar dimensiones válidas si se leen como 0 o NaN
                    if page.width <= 1e-2 or page.height <= 1e-2 or math.isnan(page.width) or math.isnan(page.height):
                        page = layout.Page(297, 210, layout.Units.mm)
                except Exception:
                    # Alternativa por defecto A4 horizontal
                    page = layout.Page(297, 210, layout.Units.mm)
                    
                try:
                    pdf_bytes = backend.get_pdf_bytes(page)
                    pdf_pages_bytes.append((f"Layout_{lay_name}", pdf_bytes))
                    valid_layouts_processed += 1
                except ValueError as ve:
                    if "empty" in str(ve).lower() or "bounding box" in str(ve).lower():
                        print(f"Layout '{lay_name}' no contiene elementos graficables. Omitiendo.")
                        continue
                    else:
                        raise ve
                
            if valid_layouts_processed == 0:
                raise ValueError("Todas las pestañas de presentación (Layouts) en el archivo están vacías o no contienen geometrías válidas.")
                
        else:
            # Procesar espacio modelo usando encuadres seleccionados
            sheets = config.get("selected_sheets")
            if sheets is None:
                if progress_callback:
                    progress_callback("Analizando espacio modelo y detectando hojas/rótulos...", 0.3)
                    
                sheets = detect_sheets_in_modelspace(
                    temp_dxf_path,
                    method=config.get("ms_method", "auto"),
                    block_name=config.get("block_name"),
                    layer_name=config.get("layer_name")
                )
            
            if not sheets:
                raise ValueError("No se detectó ninguna hoja/rótulo en el espacio modelo con los criterios seleccionados.")
                
            total_sheets = len(sheets)
            msp = doc.modelspace()
            
            for idx, sheet_box in enumerate(sheets):
                if progress_callback:
                    progress_callback(f"Renderizando plano {idx+1}/{total_sheets}...", 0.4 + (idx/total_sheets)*0.5)
                
                w = sheet_box.extmax.x - sheet_box.extmin.x
                h = sheet_box.extmax.y - sheet_box.extmin.y
                
                # Determinar dimensiones de página basadas en el aspecto real en mm
                is_landscape = w > h
                
                # Ajustar orientación según configuración
                config_orient = config.get("orientation", "auto")
                if config_orient == "landscape":
                    page_w, page_h = 297, 210
                elif config_orient == "portrait":
                    page_w, page_h = 210, 297
                else:  # auto
                    page_w, page_h = (297, 210) if is_landscape else (210, 297)
                    
                page = layout.Page(page_w, page_h, layout.Units.mm, margins=layout.Margins.all(5))
                
                backend = PyMuPdfBackend()
                color_mode = config.get("color_mode", "color")
                draw_config = Configuration(
                    background_policy=BackgroundPolicy.WHITE,
                    color_policy=ColorPolicy.BLACK if color_mode == "monochrome" else ColorPolicy.COLOR
                )
                Frontend(ctx, backend, config=draw_config).draw_layout(msp)
                
                try:
                    pdf_bytes = backend.get_pdf_bytes(page, render_box=sheet_box)
                    pdf_pages_bytes.append((f"Plano_{idx+1}", pdf_bytes))
                except ValueError as ve:
                    if "empty" in str(ve).lower() or "bounding box" in str(ve).lower():
                        print(f"Plano {idx+1} en el Espacio Modelo está vacío. Omitiendo.")
                        continue
                    else:
                        raise ve
                
        # Guardado de resultados
        if progress_callback:
            progress_callback("Guardando archivos PDF...", 0.9)
            
        combine_pdf = config.get("combine_pdf", True)
        
        output_files = []
        if combine_pdf:
            # Crear un único PDF combinado
            merged_pdf = pymupdf.open()
            for name, pdf_bytes in pdf_pages_bytes:
                page_doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
                merged_pdf.insert_pdf(page_doc)
                page_doc.close()
                
            merged_pdf.save(output_pdf_path)
            merged_pdf.close()
            output_files.append(output_pdf_path)
        else:
            # Guardar archivos individuales por cada página
            base_dir = os.path.dirname(output_pdf_path)
            base_name = os.path.splitext(os.path.basename(output_pdf_path))[0]
            
            for idx, (name, pdf_bytes) in enumerate(pdf_pages_bytes):
                file_path = os.path.join(base_dir, f"{base_name}_{name}.pdf")
                with open(file_path, "wb") as f:
                    f.write(pdf_bytes)
                output_files.append(file_path)
                
        if progress_callback:
            progress_callback("Conversión finalizada con éxito.", 1.0)
            
        return output_files
        
    finally:
        # Asegurar limpieza del archivo DXF temporal
        if os.path.exists(temp_dxf_path):
            try:
                os.remove(temp_dxf_path)
            except Exception:
                pass

def get_preview_image(dxf_path, item_type, item_value, color_mode="color"):
    """
    Renderiza un layout o un encuadre de plano del Espacio Modelo
    a una imagen de vista previa en formato PIL Image.
    """
    import fitz
    from PIL import Image
    import io
    import math
    from ezdxf.addons.drawing import Frontend, RenderContext, layout
    from ezdxf.addons.drawing.pymupdf import PyMuPdfBackend
    from ezdxf.addons.drawing.config import Configuration, ColorPolicy, BackgroundPolicy
    
    doc = safe_read_dxf(dxf_path)
    ctx = RenderContext(doc)
    backend = PyMuPdfBackend()
    
    draw_config = Configuration(
        background_policy=BackgroundPolicy.WHITE,
        color_policy=ColorPolicy.BLACK if color_mode == "monochrome" else ColorPolicy.COLOR
    )
    
    if item_type == "layout":
        lay_obj = doc.layout(item_value)
        Frontend(ctx, backend, config=draw_config).draw_layout(lay_obj)
        try:
            page = layout.Page.from_dxf_layout(lay_obj)
            if page.width <= 1e-2 or page.height <= 1e-2 or math.isnan(page.width) or math.isnan(page.height):
                page = layout.Page(297, 210, layout.Units.mm)
        except Exception:
            page = layout.Page(297, 210, layout.Units.mm)
        pdf_bytes = backend.get_pdf_bytes(page)
    else:  # sheet (BoundingBox2d)
        msp = doc.modelspace()
        Frontend(ctx, backend, config=draw_config).draw_layout(msp)
        sheet_box = item_value
        w = sheet_box.extmax.x - sheet_box.extmin.x
        h = sheet_box.extmax.y - sheet_box.extmin.y
        is_landscape = w > h
        page_w, page_h = (297, 210) if is_landscape else (210, 297)
        page = layout.Page(page_w, page_h, layout.Units.mm, margins=layout.Margins.all(5))
        pdf_bytes = backend.get_pdf_bytes(page, render_box=sheet_box)
        
    # Abrir el PDF generado en memoria y renderizarlo a imagen
    pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_obj = pdf_doc.load_page(0)
    # Escalar a 2.0x (144 DPI) para obtener buena resolución
    pix = page_obj.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
    png_bytes = pix.tobytes("png")
    pdf_doc.close()
    
    # Cargar en PIL
    image = Image.open(io.BytesIO(png_bytes))
    return image
