"""
Après chaque génération du site (Quarto, post-render) : copie dans le site les vidéos du dossier videos/ que les pages
utilisent (src et poster des balises <video>). Les autres vidéos de videos/ (anciennes, en préparation) ne sont pas
mises en ligne.
"""
import os
import re
import shutil
from pathlib import Path

VIDEO = re.compile(r'(?:src|poster)="(?:\.\./)*videos/([^"/]+)"')

sortie = Path(os.environ.get("QUARTO_PROJECT_OUTPUT_DIR", "_site"))
utilisees = {nom for page in sortie.rglob("*.html") for nom in VIDEO.findall(page.read_text(encoding="utf-8"))}
shutil.rmtree(sortie / "videos", ignore_errors=True)
for nom in sorted(utilisees):
    source = Path("videos") / nom
    if not source.exists():
        print(f"⚠ vidéo introuvable : {source} (relancer site/tutos/enregistrer_tuto.py)")
        continue
    (sortie / "videos").mkdir(exist_ok=True)
    shutil.copy2(source, sortie / "videos" / nom)
