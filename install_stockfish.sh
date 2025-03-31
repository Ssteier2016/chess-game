#!/bin/bash
# Actualiza los paquetes e instala Stockfish desde los repositorios de Ubuntu
apt-get update
apt-get install -y stockfish
# Copia el binario instalado a la ruta esperada por el código
cp /usr/games/stockfish /opt/render/project/src/stockfish
# Verifica la instalación
/opt/render/project/src/stockfish --version || echo "Error al ejecutar Stockfish"
