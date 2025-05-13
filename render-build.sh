#!/usr/bin/env bash

echo "📥 Descargando Stockfish..."

# Crear carpeta para el ejecutable
mkdir -p bin

# Descargar el binario de Stockfish (sin AVX2 para mayor compatibilidad)
curl -L -o bin/stockfish.tar.gz https://github.com/official-stockfish/Stockfish/releases/download/sf_17/stockfish-ubuntu-x86-64-avx2.tar.gz

# Descomprimir el archivo tar.gz
tar -xzf bin/stockfish.tar.gz -C bin/

# Hacer ejecutable el archivo binario
chmod +x bin/stockfish

echo "✅ Stockfish instalado en ./bin/stockfish"

