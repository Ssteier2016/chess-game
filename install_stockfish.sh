#!/bin/bash
# Descarga Stockfish 16 (ajustá la versión si querés)
curl -Lo /opt/render/project/src/stockfish https://github.com/official-stockfish/Stockfish/releases/download/sf_16/stockfish-ubuntu-x86-64
# Dale permisos de ejecución
chmod +x /opt/render/project/src/stockfish
