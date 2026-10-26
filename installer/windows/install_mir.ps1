# Installe MIR sur Windows (PC 64 bits), ou le met à jour. Dans PowerShell :
#     powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/MariusBrtn/mir/main/installer/windows/install_mir.ps1 | iex"
#
# - installe uv s'il manque (sans droits administrateur) ;
# - télécharge MIR dans %USERPROFILE%\MIR et installe ses paquets (dossier MIR\.venv, quelques Go) ;
# - crée le raccourci MIR dans le menu Démarrer et sur le Bureau, puis lance MIR.
# Relancer la même commande met MIR à jour : le dossier robots\ (le travail de l'élève) n'est pas touché.
#
# Pour essayer l'installateur avant publication (variables facultatives) :
#     $env:MIR_SOURCE = "C:\chemin\vers\mir"  (dossier ou .zip local)   $env:MIR_DIR = "..."   $env:MIR_NO_OPEN = "1"
#     powershell -ExecutionPolicy ByPass -File installer\windows\install_mir.ps1
#
# Compatible avec Windows PowerShell 5.1 (celui de Windows 10 et 11). Lancé par « irm | iex » : jamais de exit, qui
# fermerait la fenêtre de l'élève avant qu'il lise le message ; les erreurs passent par throw.

function Install-MIR {
    $ErrorActionPreference = "Stop"
    $ProgressPreference = "SilentlyContinue"        # sinon Invoke-WebRequest est très lent sous PowerShell 5.1
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    $branche = if ($env:MIR_BRANCH) { $env:MIR_BRANCH } else { "main" }
    $source = if ($env:MIR_SOURCE) { $env:MIR_SOURCE } else { "https://github.com/MariusBrtn/mir/archive/refs/heads/$branche.zip" }
    $mirDir = if ($env:MIR_DIR) { $env:MIR_DIR } else { Join-Path $HOME "MIR" }
    # robots créés à la première installation (simulés tant qu'on ne les construit pas) : bras 4 ddl avec caméra,
    # robot mobile avec lidar
    $robotsDeDepart = @("bras_4ddl_cam_V2", "test_mobile")

    function Etape($texte) { Write-Host ""; Write-Host "==> $texte" -ForegroundColor Blue }
    # commande externe (uv, tar, robocopy) : sous PowerShell 5.1, avec « Stop », ce qu'elle écrit sur la sortie
    # d'erreur (la progression de uv, par exemple) arrêterait le script ; on juge sur son code de retour
    function Externe([scriptblock]$commande) {
        $ErrorActionPreference = "Continue"
        & $commande
    }

    # -------------------------------------------------------------- vérifications
    $arch = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
    if ($arch -ne "AMD64") { throw "MIR demande un PC 64 bits Intel ou AMD (ce PC : $arch)." }
    if (Test-Path (Join-Path $mirDir ".git")) {
        throw "$mirDir est un dépôt git : mettez-le à jour avec « git pull » puis « uv sync »."
    }
    $libreGo = [math]::Floor((Get-Item $HOME).PSDrive.Free / 1GB)
    if ($libreGo -lt 6) { throw "Il faut au moins 6 Go libres (il en reste $libreGo Go)." }

    # -------------------------------------------------------------- uv
    Etape "1/4  Outil d'installation uv"
    $env:Path = "$HOME\.local\bin;$env:Path"
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Write-Host "uv est déjà installé ($(uv --version))."
    } else {
        # dans un PowerShell à part : l'installateur de uv ne doit pas changer les réglages de celui-ci
        Externe { powershell -NoProfile -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex" }
        if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "uv n'a pas pu être installé." }
    }

    # -------------------------------------------------------------- téléchargement
    Etape "2/4  Téléchargement de MIR"
    $temp = Join-Path ([IO.Path]::GetTempPath()) ("mir-" + [guid]::NewGuid())
    New-Item -ItemType Directory $temp | Out-Null
    try {
        if (Test-Path $source -PathType Container) {
            Write-Host "Copie depuis $source"
            $sourceDir = $source
        } else {
            $zip = Join-Path $temp "mir.zip"
            if (Test-Path $source -PathType Leaf) {
                Copy-Item $source $zip
            } else {
                Write-Host $source
                try { Invoke-WebRequest $source -OutFile $zip -UseBasicParsing }
                catch { throw "Téléchargement impossible : vérifiez la connexion internet ($($_.Exception.Message))." }
            }
            $dezip = Join-Path $temp "zip"
            New-Item -ItemType Directory $dezip | Out-Null
            Externe { tar -xf $zip -C $dezip }          # tar.exe (Windows 10 et 11) : bien plus rapide qu'Expand-Archive
            if ($LASTEXITCODE -ne 0) { Expand-Archive $zip $dezip -Force }
            $projet = Get-ChildItem $dezip -Recurse -Depth 2 -Filter pyproject.toml |
                      Sort-Object { $_.FullName.Length } | Select-Object -First 1
            if (-not $projet) { throw "Le téléchargement ne contient pas MIR." }
            $sourceDir = $projet.DirectoryName
        }
        if (-not ((Test-Path "$sourceDir\pyproject.toml") -and (Test-Path "$sourceDir\uv.lock"))) {
            throw "Le téléchargement ne contient pas MIR."
        }

        New-Item -ItemType Directory $mirDir -Force | Out-Null
        # le code est remplacé ; robots\ est le dossier de l'élève : au départ, seulement deux robots, avec leur seule
        # configuration (pas de graphe MIR Flow, de script ni de modèle). Un robot déjà présent n'est jamais touché.
        Externe { robocopy $sourceDir $mirDir /E /NFL /NDL /NJH /NJS /NP `
            /XD .git .venv logs __pycache__ .pytest_cache *.egg-info (Join-Path $sourceDir "robots") } | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "La copie de MIR dans $mirDir a échoué." }    # robocopy : 0 à 7 = réussite
        foreach ($robot in $robotsDeDepart) {
            $config = Join-Path $sourceDir "robots\$robot\robot.json"
            $cible = Join-Path $mirDir "robots\$robot"
            if (-not (Test-Path $cible) -and (Test-Path $config)) {
                New-Item -ItemType Directory $cible -Force | Out-Null
                Copy-Item $config $cible
            }
        }
    } finally {
        Remove-Item $temp -Recurse -Force -ErrorAction SilentlyContinue
    }
    Write-Host "MIR est dans $mirDir"

    # -------------------------------------------------------------- paquets
    Etape "3/4  Installation des paquets (Python, PyTorch, MuJoCo, LeRobot...) : 5 à 15 minutes la première fois"
    # Python téléchargé par uv plutôt qu'un Python déjà installé sur le PC : même version pour tous les élèves
    $env:UV_PYTHON_PREFERENCE = "only-managed"
    $pyvenv = Join-Path $mirDir ".venv\pyvenv.cfg"
    if ((Test-Path $pyvenv) -and -not (Select-String -Path $pyvenv -SimpleMatch (uv python dir) -Quiet)) {
        Write-Host "Environnement créé avec un autre Python : il est refait."
        Remove-Item (Join-Path $mirDir ".venv") -Recurse -Force
    }
    Push-Location $mirDir
    try { Externe { uv sync } } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw "L'installation des paquets a échoué (voir les messages ci-dessus)." }

    # -------------------------------------------------------------- raccourcis
    Etape "4/4  Raccourcis MIR"
    # pythonw : pas de fenêtre de console ; lancer_mir.pyw envoie la sortie dans logs\application.log
    $pythonw = Join-Path $mirDir ".venv\Scripts\pythonw.exe"
    $lanceur = Join-Path $mirDir "installer\windows\lancer_mir.pyw"
    $shell = New-Object -ComObject WScript.Shell
    $raccourcis = @(
        (Join-Path ([Environment]::GetFolderPath("Programs")) "MIR.lnk"),     # menu Démarrer
        (Join-Path ([Environment]::GetFolderPath("Desktop")) "MIR.lnk")
    )
    foreach ($chemin in $raccourcis) {
        $raccourci = $shell.CreateShortcut($chemin)
        $raccourci.TargetPath = $pythonw
        $raccourci.Arguments = "`"$lanceur`""
        $raccourci.WorkingDirectory = $mirDir
        $raccourci.IconLocation = "$(Join-Path $mirDir 'installer\windows\MIR.ico'),0"
        $raccourci.Description = "MIR : robots modulaires"
        $raccourci.Save()
    }

    Write-Host ""
    Write-Host "MIR est installé." -ForegroundColor Green
    Write-Host "  Raccourci   : menu Démarrer et Bureau (« MIR »)"
    Write-Host "  Dossier     : $mirDir (robots, scripts, datasets)"
    Write-Host "  Mise à jour : relancez la même commande d'installation."
    if (-not $env:MIR_NO_OPEN) {
        Start-Process $pythonw -ArgumentList "`"$lanceur`"" -WorkingDirectory $mirDir
    }
}

try {
    Install-MIR
} catch {
    Write-Host ""
    Write-Host "Echec : $($_.Exception.Message)" -ForegroundColor Red
}
