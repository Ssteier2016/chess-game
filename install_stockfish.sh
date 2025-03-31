#!/bin/bash
# Instala las herramientas necesarias para compilar
apt-get update
apt-get install -y git make g++
# Clona el repositorio de Stockfish
git clone https://github.com/official-stockfish/Stockfish.git /tmp/stockfish-src
cd /tmp/stockfish-src/src
# Compila Stockfish
make -j build ARCH=x86-64
# Copia el binario compilado a la ruta esperada
cp stockfish /opt/render/project/src/stockfish
# Verifica
/opt/render/project/src/stockfish --version || echo "Error al ejecutar Stockfish"
# Limpia los archivos temporales
rm -rf /tmp/stockfish-src
