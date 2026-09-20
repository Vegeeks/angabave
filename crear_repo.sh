#!/usr/bin/env bash
# Deja ANGABAVE publicado en GitHub con Pages encendido.
#
#   ./crear_repo.sh [nombre-del-repo] [public|private]
#
# Por defecto: angabave, público (Pages gratis necesita repo público).
set -euo pipefail

NOMBRE="${1:-angabave}"
VISIBILIDAD="${2:-public}"

echo "==> Revisando herramientas"
if ! git --version >/dev/null 2>&1; then
  echo "git no funciona todavía. Corre esto y vuelve a intentar:" >&2
  echo "    sudo xcodebuild -license accept" >&2
  exit 1
fi
if ! gh auth status >/dev/null 2>&1; then
  echo "Falta autenticar GitHub. Corre: gh auth login" >&2
  exit 1
fi
CUENTA="$(gh api user --jq .login)"
echo "    git $(git --version | awk '{print $3}') · GitHub como $CUENTA"

echo "==> Preparando el repositorio local"
if [ ! -d .git ]; then
  git init -q -b main
fi
git add -A
if git diff --staged --quiet; then
  echo "    sin cambios que registrar"
else
  git commit -q -m "ANGABAVE: portal de la quiniela NFL 2026"
  echo "    commit listo"
fi

echo "==> Creando $CUENTA/$NOMBRE ($VISIBILIDAD) y subiendo"
if gh repo view "$CUENTA/$NOMBRE" >/dev/null 2>&1; then
  echo "    el repositorio ya existía; solo subo"
  git remote get-url origin >/dev/null 2>&1 || \
    git remote add origin "https://github.com/$CUENTA/$NOMBRE.git"
  git push -u origin main
else
  gh repo create "$NOMBRE" \
    --"$VISIBILIDAD" \
    --source=. \
    --remote=origin \
    --description "ANGABAVE · Quiniela NFL 2026" \
    --push
fi

echo "==> Encendiendo GitHub Pages"
gh api --method POST "repos/$CUENTA/$NOMBRE/pages" -f build_type=workflow >/dev/null 2>&1 \
  || gh api --method PUT "repos/$CUENTA/$NOMBRE/pages" -f build_type=workflow >/dev/null 2>&1 \
  || echo "    (ya estaba encendido, o enciéndelo a mano en Settings > Pages > Source: GitHub Actions)"

echo "==> Primera publicación"
gh workflow run actualizar.yml --repo "$CUENTA/$NOMBRE" >/dev/null 2>&1 \
  && echo "    workflow disparado" \
  || echo "    dispáralo a mano en la pestaña Actions"

echo
echo "Listo."
echo "  Repositorio: https://github.com/$CUENTA/$NOMBRE"
echo "  Sitio:       https://$CUENTA.github.io/$NOMBRE/"
echo "  Imagen:      https://$CUENTA.github.io/$NOMBRE/tabla.png"
echo
echo "La primera publicación tarda un par de minutos. Revisa la pestaña Actions."
