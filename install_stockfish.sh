#!/bin/bash
# Intenta instalar Stockfish desde los repositorios de Ubuntu
apt-get update
apt-get install -y stockfish || echo "No se pudo instalar Stockfish con apt-get, intentando descarga manual"
# Verifica si se instaló correctamente
if [ -f /usr/games/stockfish ]; then
    cp /usr/games/stockfish /opt/render/project/src/stockfish
else
    # Si falla, descarga manualmente desde GitHub
    curl -Lo /opt/render/project/src/stockfish https://github.com/official-stockfish/Stockfish/releases/download/sf_16/stockfish-ubuntu-x86-64
    chmod +x /opt/render/project/src/stockfish
fi
# Verifica la instalación
/opt/render/project/src/stockfish --version || echo "Error al ejecutar Stockfish"
