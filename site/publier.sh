#!/bin/bash
# Met le site en ligne sur https://mir-edu.fr. Dans VS Code : Cmd+Maj+B (tâche « Publier le site »), ou dans un
# terminal : site/publier.sh
#
# 1. fabrique le site (quarto render → _site/) ;
# 2. l'envoie sur la branche gh-pages de GitHub, que mir-edu.fr affiche (en ligne une minute plus tard) ;
# 3. enregistre aussi les pages (.qmd, images) sur GitHub, branche main.
# Les vidéos (*.mp4, dossier videos/) ne sont pas mises en ligne.
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"            # quarto et uv, installés par uv tool

DEPOT=github            # le dépôt de Marius (github.com/MariusBrtn/mir) ; « origin » est celui de son papa
racine=$(git rev-parse --show-toplevel)

etape() { printf '\n\033[1;34m==> %s\033[0m\n' "$1"; }
echec() { printf '\n\033[1;31m✗ %s\033[0m\n' "$1" >&2; exit 1; }

# ------------------------------------------------------------------ fabrication
etape "1/3  Fabrication du site"
quarto render || echec "Quarto n'a pas pu fabriquer le site (voir les messages ci-dessus) : rien n'est mis en ligne."

# ------------------------------------------------------------------ mise en ligne
etape "2/3  Mise en ligne"
temp=$(mktemp -d)
trap 'git -C "$racine" worktree remove --force "$temp/pages" 2>/dev/null; rm -rf "$temp"' EXIT
git fetch -q "$DEPOT" gh-pages || echec "GitHub ne répond pas : vérifiez la connexion internet."
git worktree add -q --detach "$temp/pages" "$DEPOT/gh-pages"
rsync -a --delete --exclude .git --exclude '*.mp4' _site/ "$temp/pages/"
git -C "$temp/pages" add -A
if git -C "$temp/pages" diff --cached --quiet; then
    echo "Le site en ligne est déjà à jour."
else
    git -C "$temp/pages" commit -q -m "Site internet de MIR : mise à jour du $(date '+%d/%m/%Y à %H:%M')"
    git -C "$temp/pages" push -q "$DEPOT" HEAD:gh-pages || echec "GitHub a refusé la mise en ligne."
    echo "Envoyé."
fi

# ------------------------------------------------------------------ sauvegarde des pages
etape "3/3  Sauvegarde des pages sur GitHub"
git add -A -- . ':(exclude)videos'
if git diff --cached --quiet -- .; then
    echo "Les pages sont déjà enregistrées."
else
    git commit -q -m "Site : mise à jour du $(date '+%d/%m/%Y à %H:%M')" -- . ':(exclude)videos'
    git push -q || echo "⚠ Pages enregistrées sur cet ordinateur mais pas sur GitHub : demander à Claude."
fi

printf '\n\033[1;32m✓ En ligne sur https://mir-edu.fr dans une minute environ.\033[0m\n'
echo "  (si l'ancienne version s'affiche encore : Cmd+Maj+R dans le navigateur)"
