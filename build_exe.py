import os
import sys
import PyInstaller.__main__

def build():
    # Asegurar que estamos trabajando en el directorio raíz del script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    print("=== Iniciando compilación de PrintMyBlueprint ===")
    
    # Argumentos de PyInstaller:
    # - app.py: Script principal.
    # --name: Nombre del ejecutable final.
    # --onefile: Empaquetar todo en un único archivo ejecutable (portable).
    # --noconsole: Ocultar la consola de comandos en Windows (ejecución 100% GUI).
    # --add-data: Incluye la carpeta del convertidor LibreDWG y sus DLLs.
    # --clean: Limpiar compilaciones previas y caché.
    args = [
        'app.py',
        '--name=PrintMyBlueprint',
        '--onefile',
        '--noconsole',
        '--icon=app_icon.ico',
        '--add-data=libredwg_bin;libredwg_bin',
        '--add-data=app_icon.ico;.',
        '--clean'
    ]

    print(f"Ejecutando PyInstaller con argumentos: {args}")
    try:
        PyInstaller.__main__.run(args)
        print("\n=== Compilación finalizada con éxito ===")
        print("El archivo ejecutable portable se encuentra en la carpeta 'dist/PrintMyBlueprint.exe'")
    except Exception as e:
        print(f"\nERROR durante la compilación: {e}")
        sys.exit(1)

if __name__ == "__main__":
    build()
