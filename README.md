# PrintMyBlueprint 🗺️

**PrintMyBlueprint** es una herramienta de escritorio portable para Windows diseñada para procesar archivos de planos **DWG** y dividirlos/convertirlos de manera automática e inteligente en páginas **PDF individuales o combinadas**. 

Esta aplicación es ideal para ingenieros, arquitectos y diseñadores que necesitan extraer hojas y formatos de planos del Espacio Modelo (Model Space) o Pestañas de Presentación (Layouts) de forma masiva y sin depender de licencias costosas de CAD.

---

## 🚀 Características Clave

*   **Detección e Ingesta DWG**: Conversión automática a DXF local y lectura robusta con tolerancia a archivos corruptos o dañados.
*   **Reconstrucción Geométrica Avanzada (Espacio Modelo)**: 
    *   Detecta márgenes e inserciones de bloques de rótulos.
    *   *Nuevo motor inteligente*: Reconstruye rectángulos de hojas completas a partir de segmentos de líneas sueltas (`LINE`), calculando cruces y tolerancias de escala dinámicas.
*   **Filtrado de Rectángulos Anidados (Concéntricos)**: Identifica y agrupa los marcos dobles de los rótulos (hoja de papel vs. margen interno) y conserva únicamente la hoja exterior para evitar páginas duplicadas.
*   **Visualizador de Planos en Tiempo Real**: Pestaña dedicada con un motor gráfico vectorial a ráster de alta resolución (144 DPI) para previsualizar los planos en pantalla antes de exportar.
*   **Modos de Color y Fondo**:
    *   Fuerza el fondo a blanco limpio para un ploteado estándar.
    *   Permite alternar entre impresión **A Color** original o **Blanco y Negro (Monocromo)** técnico.
*   **Checklist de Selección Manual**: Panel interactivo con checkboxes para seleccionar con precisión qué hojas o pestañas se desean procesar.
*   **Diseño Premium**: Interfaz moderna basada en CustomTkinter con un elegante tema oscuro acentuado en verde CAD (Emerald Green).

---

## 🛠️ Cómo Utilizar la Aplicación

1.  **Ejecución**: Abre el archivo portable `PrintMyBlueprint.exe`.
2.  **Carga de Archivo**: Haz clic en **Seleccionar Archivo DWG** en el panel lateral y busca tu archivo de plano `.dwg`.
3.  **Configuración de Origen**:
    *   Si los planos están dibujados directamente en el área principal de trabajo, selecciona **Espacio Modelo (Model Space)**.
    *   Si están configurados en hojas de papel de AutoCAD, selecciona **Pestañas de Presentación (Layouts)**.
4.  **Ajustes de Salida**:
    *   Selecciona si deseas guardar todas las hojas en un solo PDF multipágina o en archivos PDF individuales.
    *   Elige la orientación de papel preferida (Auto, Horizontal o Vertical).
    *   Configura el color de las líneas (A Color o Blanco y Negro).
5.  **Revisión y Selección**:
    *   En el panel derecho se listarán los planos detectados. Puedes marcar o desmarcar individualmente cada uno de ellos.
    *   Dirígete a la pestaña **Visualizador de Planos** si deseas previsualizar la hoja seleccionada presionando el botón **Ver Plano**.
6.  **Conversión**: Presiona el botón **Convertir a PDF** y los archivos listos para imprimir se generarán en la carpeta destino seleccionada.

---

## 💻 Pila Tecnológica (Tech Stack)

*   **GUI**: [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) (UI moderna basada en Tkinter).
*   **Parser de CAD**: [ezdxf](https://github.com/mozman/ezdxf) (Auditoría, reparación y lectura geométrica).
*   **Conversor DWG**: [LibreDWG](https://www.gnu.org/software/libredwg/) (GNU LibreDWG para decodificar DWG binario).
*   **Renderizador de PDF / Imágenes**: [PyMuPDF (fitz)](https://github.com/pymupdf/PyMuPDF) (Motor vectorial de renderizado y visualización).
*   **Empaquetado**: [PyInstaller](https://pyinstaller.org/) (Compilación standalone sin dependencias externas).

---

## 📝 Licencia

Este proyecto está disponible para uso personal y profesional. LibreDWG está sujeto a la licencia GPLv3.
