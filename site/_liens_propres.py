"""
Après chaque génération du site (Quarto, post-render) : les liens vers « …/index.html » deviennent « …/ », pour des
adresses propres (https://mir-edu.fr/prise-en-main/ plutôt que …/prise-en-main/index.html), dans les pages et dans
l'index de la recherche (search.json).
"""
import os
import re
from pathlib import Path

LIEN = re.compile(r'(href="[^"#]*?)index\.html(#[^"]*)?"')

sortie = Path(os.environ.get("QUARTO_PROJECT_OUTPUT_DIR", "_site"))
for page in sortie.rglob("*.html"):
    texte = page.read_text(encoding="utf-8")
    # « index.html » seul devient « ./ » (un lien vide recharge la page sans en changer)
    propre = LIEN.sub(lambda m: (m.group(1) if m.group(1) != 'href="' else 'href="./') + (m.group(2) or "") + '"',
                      texte)
    if propre != texte:
        page.write_text(propre, encoding="utf-8")

# résultats de la recherche : « prise-en-main/index.html#… » -> « prise-en-main/#… »
recherche = sortie / "search.json"
if recherche.exists():
    texte = recherche.read_text(encoding="utf-8")
    propre = re.sub(r'"href": "([^"#]*?)index\.html', lambda m: f'"href": "{m.group(1) or "./"}', texte)
    if propre != texte:
        recherche.write_text(propre, encoding="utf-8")
