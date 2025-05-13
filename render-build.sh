#!/usr/bin/env bash

echo "📥 Descargando Stockfish..."

# Crear carpeta para el ejecutable
mkdir -p bin

# Descargar y descomprimir el binario para Linux (moderno, sin AVX2 para mayor compatibilidad)
wget https://github.com/official-stockfish/Stockfish/releases/download/sf_17.1/stockfish-ubuntu-x86-64-avx2.zip -O bin/stockfish.zip
unzip bin/stockfish.zip -d bin/
chmod +x bin/stockfish

echo "✅ Stockfish instalado en ./bin/stockfish"

