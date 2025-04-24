#!/bin/bash

set -e  # Script bricht bei Fehler ab

ENV_NAME="tabascal-test"

# Aktiviere conda in bash
eval "$(conda shell.bash hook)"

echo "🔁 Wechsle ins base-Environment..."
conda activate base

echo "🔨 Baue das Paket..."
conda build recipe --channel conda-forge

# Paketpfad ermitteln
PKG_PATH=$(conda build recipe --output)

if [ ! -f "$PKG_PATH" ]; then
    echo "❌ Paket wurde nicht gebaut: $PKG_PATH"
    exit 1
fi

echo "✅ Paket gebaut: $PKG_PATH"

# Alte Umgebung löschen, falls vorhanden
if conda info --envs | grep -q "^$ENV_NAME"; then
    echo "🧹 Entferne alte Umgebung: $ENV_NAME"
    conda remove -n "$ENV_NAME" --all -y
fi

# Neue Umgebung erstellen und tabascal installieren
echo "📦 Erstelle neue Umgebung: $ENV_NAME"
conda create -n "$ENV_NAME" --use-local tabascal -y

# spacetrack mit pip installieren
echo "🌐 Installiere spacetrack via pip..."
conda run -n "$ENV_NAME" pip install spacetrack

# Test: sim-vis --help
echo "🚀 Teste sim-vis --help:"
conda run -n "$ENV_NAME" sim-vis --help

echo "✅ Alles erledigt! Aktiviere die Umgebung mit:"
echo "   conda activate $ENV_NAME"
