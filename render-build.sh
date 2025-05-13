#!/usr/bin/env bash

echo "📥 Descargando Stockfish..."

# Crear carpeta para el ejecutable
mkdir -p bin

# Descargar y descomprimir el binario para Linux (moderno, sin AVX2 para mayor compatibilidad)
curl -L -o bin/stockfish.zip https://github.com/official-stockfish/Stockfish/releases/download/sf_17/stockfish-ubuntu-x86-64-avx2.tar
unzip bin/stockfish.zip -d bin/
chmod +x bin/stockfish

echo "✅ Stockfish instalado en ./bin/stockfish"
