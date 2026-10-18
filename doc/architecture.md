# Architecture de MIR

*Document de conception — version du 18/10/2026 (première version le 15/10). La partie 4 (couches et interfaces) a été validée le 18/10 ; les interfaces encore « à définir » le seront une par une.*

## 1. Ce qu'est MIR

MIR est une plateforme pédagogique pour expérimenter en robotique et en IA, construite autour de **modules physiques** (servos, pince, caméra, capteurs, lidar) qui s'assemblent par pogo pins. Elle couvre un fil continu, des sciences de l'ingénieur jusqu'au robot learning : construire un robot, le commander, le mesurer, le téléopérer, collecter des données, entraîner des modèles et les évaluer. Tout cela **en réel ou en simulé**.

MIR s'appuie sur LeRobot (interface robot, format de dataset, politiques apprises) et sur MuJoCo (simulation). Son originalité est l'intégration : des modules physiques maîtrisés, une description unique du robot et une interface graphique qui guide l'élève, sans l'empêcher de coder.

### Principe directeur

> **Un robot décrit une seule fois · une seule boucle observation → décision → action · un backend réel ou simulé · des briques Python pour tout ce que l'élève doit comprendre.**

Presque tous les usages se ramènent à « quelque chose qui décide de l'action à partir de l'observation ». Seule cette chose change d'un usage à l'autre :

| Ce qui décide | Usage |
|---|---|
| Une consigne fixe, un échelon, une rampe | Robotique de base, réponse indicielle |
| Un PID, un générateur de trajectoire, un MGI | Commande, trajectoires |
| Un humain (clavier, souris, joystick, second robot) | Téléopération |
| Un réseau appris (MLP, ACT, diffusion, VLA, politique RL) | Robot learning |
| Un algorithme de l'élève | SLAM, navigation |

C'est aussi une progression pédagogique : *j'écris la loi de commande* → *un humain décide* → *la machine apprend à décider*.

### Ambition : rester ouvert sur l'état de l'art

Le robot learning avance très vite (modèles vision-langage-action, world models, planificateurs à base de modèles de langage). MIR ne cherche pas à **implémenter** ces modèles, mais à pouvoir les **brancher** dès qu'ils sortent, sans être réécrit. C'est son point fort visé.

Pour cela, MIR garde des **interfaces stables et compatibles avec l'écosystème** (LeRobot, Hugging Face, MuJoCo), et sa valeur propre reste ce que les autres n'ont pas : des modules physiques, leur jumeau simulé, une interface pédagogique et la colle entre les trois.

MIR ne se limite pas non plus à des tâches de quelques secondes : à terme, il doit permettre de programmer des **activités longues**, qui enchaînent des compétences et prennent des décisions (partie 4.4).

## 2. Use cases

### 2.1 Parcours de référence : bras 4 ddl avec pince et caméra (élève de CPGE SII)

1. **Concevoir le modèle** du robot à partir du catalogue de modules, sans matériel.
2. **Travailler en simulation** tout de suite, hors ligne.
3. **Assembler le robot physique**, guidé module par module ; la configuration se complète (ID, calibration).
4. **Robotique de base** : consignes en position, en vitesse ou en boucle ouverte ; réglage du PID ; essais (réponse à un échelon) ; mesures de position, vitesse, courant et couple ; post-traitement en Python.
5. **Modélisation** : modèles géométriques direct et inverse, trajectoires ; études de cinématique, de statique et de dynamique en simulation.
6. **Téléopération** avec la modalité de son choix, dont une partie est codée par l'élève.
7. **Datasets** : enregistrer, visualiser, éditer.
8. **Apprentissage** : entraîner un modèle (MLP, ACT, diffusion, VLA), lancer l'inférence, évaluer.

Toutes les étapes, sauf l'assemblage physique, doivent être faisables en réel comme en simulé.

### 2.2 Robot mobile 4 roues avec lidar

Même chaîne, avec des moteurs en mode vitesse, l'odométrie, le lidar et des briques propres au mobile : SLAM et navigation codés par l'élève.

### 2.3 Quadrupède entraîné par RL

Apprentissage de la marche par renforcement en simulation, puis transfert vers le réel. C'est un **horizon** : le passage du simulé au réel est un sujet à part entière.

### 2.4 Ce dont chaque activité a besoin

| Activité | Description seule | Robot (réel ou simulé) | Données |
|---|:---:|:---:|:---:|
| MGD/MGI, cinématique, statique, dynamique | ✓ | | |
| Consignes, PID, essais, mesures | | ✓ | essais |
| Trajectoires, téléopération | | ✓ | |
| Collecte de données | | ✓ | datasets |
| Entraînement | | | datasets |
| Inférence, évaluation | | ✓ | modèle |

## 3. Cycle de vie d'un robot

Le fichier de configuration se remplit **en deux temps**. La description vient avant le matériel.

### 3.1 Concevoir le modèle (hors ligne)

L'élève assemble en 3D des modules du catalogue (`mir_sim/catalog`). Cela produit la **structure** (modules, branchements, noms des articulations) et la partie de la configuration qui ne dépend pas du matériel.

La simulation est utilisable aussitôt, avec les **plages par défaut fournies par chaque module du catalogue** : ±90° pour un servo, une plage propre à la pince (à mesurer et à ajouter dans `mir_pince.json`).

### 3.2 Assembler le robot physique (assistant guidé)

Les modules se fixent par pogo pins : **brancher = fixer**. L'assistant suit l'ordre de la structure et, pour chaque module :

1. **La 3D met en surbrillance** l'emplacement du module suivant ; l'élève le place.
2. **Détection.**
   - *Servo* : un servo neuf est en ID 1. **L'ID 1 est réservé au « module neuf » et n'est jamais attribué**, ce qui garantit que le servo en ID 1 est celui qu'on vient d'ajouter. MIR lui écrit son ID définitif, choisi automatiquement dans l'ordre de la structure.
   - *Module capteur* : il s'allume seul à l'installation et n'a pas de LED. MIR attend sa détection réseau (démarrage, connexion au point d'accès, découverte), avec un indicateur de progression, un délai maximal et un bouton « Réessayer ». Comme on place les modules un par un, le nouveau module détecté est celui de l'étape.
3. **Retour immédiat** : pour un servo, la position mesurée anime l'articulation en 3D ; pour un capteur, ses données s'affichent en direct (image de la caméra, nuage du lidar, valeurs…). L'élève confirme que c'est le bon module, au bon endroit, dans le bon sens.
4. **Calibration obligatoire** du servo, dès qu'il est en place : milieu, min et max à la main, puis enregistrement. La calibration est ainsi faite moteur par moteur.
5. Module suivant.

Cas particuliers :
- Un servo réutilisé (ID différent de 1) est accepté s'il n'entre pas en conflit avec un ID déjà attribué ; sinon, on demande de le brancher seul pour le réinitialiser.
- On peut **recalibrer une seule articulation** plus tard, au cas où un module ajouté ensuite réduirait la course d'un module précédent.

À la fin, la description et le matériel sont **associés et vérifiés**. La simulation reprend automatiquement les plages calibrées (déjà en place dans `model_builder.py`).

### 3.3 Contenu du fichier de configuration

| Section | Remplie par |
|---|---|
| `structure` | Conception du modèle |
| `motor_bus.motors` (noms, modèle, mode, P/I/D, vitesse, couple max) | Conception (valeurs par défaut), puis réglages de l'élève |
| `motor_bus.motors.*.id`, `motor_port` | Assemblage |
| `motor_bus.calibration` | Assemblage (calibration à l'ajout de chaque servo) |
| `sensors` (IP, résolution, rotation d'image…) | Conception (type), puis assemblage (adresse) |
| `observations` | Choix de l'élève |

## 4. Architecture en couches

### 4.1 Les couches et leurs interfaces

MIR est organisé en cinq couches, posées sur la description du robot. Chacune a **une interface simple et stable** : une nouveauté (un modèle, un planificateur, un simulateur) s'ajoute comme un module de plus dans une couche, sans refonte des autres.

```
  Tâche          enchaîner des compétences, décider, gérer les échecs     à définir
 ─────────────────────────────────────────────────────────────────────────────────
  Compétence     action = politique(observation), sur quelques secondes   en partie
                 consigne · PID · téléop · script · MLP · ACT · VLA
 ─────────────────────────────────────────────────────────────────────────────────
  Données        épisodes enregistrés : LeRobotDataset                     à faire
                 (essais de mesure : DataRecorder)                         fait
 ─────────────────────────────────────────────────────────────────────────────────
  Robot          connect · get_observation · send_action · disconnect     fait
        ├── Réel    →  mir_devices (bus Feetech, caméras, ESP32, lidar)
        └── Simulé  →  mir_sim (appareils simulés sur MuJoCo)
 ─────────────────────────────────────────────────────────────────────────────────
  Monde simulé   robot + scène (mir/scenes) ; environnement Gym pour le RL  en partie
 ─────────────────────────────────────────────────────────────────────────────────
  Description    catalogue de modules + structure + configuration          fait
```

| Couche | Interface | Compatible avec | État au 18/10 |
|---|---|---|---|
| **Robot** | `get_observation()` / `send_action()` | `Robot` de LeRobot | fait |
| **Données** | LeRobotDataset (épisodes, images, actions, métadonnées) | Hub Hugging Face, outils LeRobot | à faire : étape Collecter |
| **Compétence** | `action = politique(observation)` | politiques LeRobot (`select_action`) | en partie : téléop, scripts |
| **Tâche** | enchaînement de compétences (partie 4.4) | — | à définir |
| **Monde simulé** | scène + robot ; plus tard `reset()` / `step()` | Gymnasium, MuJoCo | en partie : scènes à sortir du code |

Les **données** sont la pièce maîtresse : les modèles appris, les modèles de fondation et les world models s'entraînent tous sur des données. Un format standard permet de réutiliser celles des autres et de partager les siennes.

Dans la couche **compétence**, tout a la même forme, du PID au VLA : c'est ce qui permet de passer d'une loi de commande écrite par l'élève à un modèle appris sans rien changer autour.

### 4.2 Règles et paquets

1. **Tout passe par `mirRobot`.** Pilotage, essais, téléop, collecte et inférence n'utilisent que `get_observation()` et `send_action()`, qu'ils soient lancés depuis l'interface ou depuis un script. Seuls les outils de mise en service (assemblage, ID, calibration, réglage des registres) accèdent directement au matériel.
2. **Réel et simulé sont interchangeables.** Le simulé est le même `mirRobot`, construit avec les appareils simulés de `mir_sim` : aucune activité ne doit savoir sur quel backend elle tourne.
3. **La préparation des observations est déclarée une fois** dans la configuration (rotation et taille d'image…) et appliquée par `mirRobot`, jamais recopiée dans chaque script. Les erreurs du diagnostic ACT (division par 255, préparation d'image dupliquée) venaient de là.
4. **L'interface et les scripts utilisent les mêmes briques.** Une téléop ou un modèle écrit pour l'interface se lance aussi en script, et inversement.
5. **Le vocabulaire du code générique reste générique** (`mir_devices`, éditeur) : pas de « leader/follower » ni de cas d'usage précis. Ces notions vivent dans les briques et dans les exemples.
6. **Brancher plutôt que réimplémenter.** Un modèle, un format ou un outil de l'écosystème s'utilise par son interface standard ; MIR n'en écrit pas sa propre version.
7. **Le robot appartient à l'application.** Un script ou une politique peut tourner dans un autre processus, voire sur une autre machine (par exemple une politique lourde sur un serveur à carte graphique), mais passe par l'interface robot de l'application : l'arrêt d'urgence, la vue 3D et l'affichage des capteurs restent toujours dans MIR. C'est déjà le cas des scripts élèves (`mir_robot/script.py`).

#### Paquets

| Paquet | Rôle |
|---|---|
| `mir_devices` | Pilotes du matériel réel (bus moteur, caméras, ESP32, lidar, découverte réseau) |
| `mir_sim` | Catalogue de modules, construction du modèle MuJoCo, appareils simulés |
| `mir_robot` | `mirRobot` et `mirRobotConfig` : le point d'entrée unique |
| `mir_robot_editor` | L'interface graphique |
| `mir_utils` | Outils transverses (UI de base, enregistrement, métriques, concurrence) |
| `mir_user_scripts` | Exemples et scripts d'élèves |

Dossiers de travail (hors paquets) : `robots/<nom>/` (configuration `robot.json`, `teleop/`, `scripts/`, `essais/`) et `scenes/` (scènes de simulation, voir 4.3).

### 4.3 Scènes

Une **scène** décrit l'environnement simulé : sol ou table, position de départ du robot, objets (formes simples ou objets 3D texturés), caméras fixes, éclairage. Elle n'appartient pas à un robot : n'importe quel robot peut être posé dans n'importe quelle scène. Les scènes sont des fichiers de `mir/scenes/` (table de travail, arène, dé à attraper…) ; la scène se choisit dans l'application, en simulé seulement. Par défaut : la table pour un robot fixé au sol, l'arène pour un robot mobile.

Le réalisme utile dépend du capteur : la géométrie suffit pour le lidar et la navigation, la physique compte pour l'asservissement, l'apparence seulement pour l'apprentissage sur images. Pour ce dernier, la priorité est de **faire varier** la scène (éclairage, couleurs, position des objets) plutôt que de la copier parfaitement ; des objets ou une pièce scannés (maillages texturés) pourront s'y ajouter sans changer d'outil.

### 4.4 Activités longues : la couche tâche

Les systèmes récents sont **hiérarchiques** : en bas, des compétences courtes (« attraper le dé », « aller jusqu'au mur ») ; au-dessus, une couche qui décide quoi faire ensuite, dans quel ordre, et que faire en cas d'échec. Dans MIR, cette couche se construira en trois niveaux, du plus pédagogique au plus avancé :

1. **Un script Python** qui enchaîne les compétences avec des conditions et des boucles (l'onglet Scripts le permet presque déjà).
2. **Une machine à états ou un arbre de comportement**, lisibles et proches de ce qu'utilise l'industrie.
3. **Un modèle de langage (LLM ou VLM) planificateur**, qui choisit la compétence suivante à partir de la caméra et d'un objectif exprimé en langage naturel.

Condition commune : des compétences **nommées, lançables, qui signalent leur fin et leur réussite**. C'est ce qu'il faut définir avant de construire cette couche.

### 4.5 Ouverture vers les modèles avancés

| Famille | Ce qu'il faut à MIR pour l'accueillir |
|---|---|
| Modèles écrits par l'élève (MLP, CNN en PyTorch, behavior cloning) | données LeRobotDataset + fiche de préparation + interface compétence (partie 6.4) |
| Politiques apprises (ACT, diffusion…) | données LeRobotDataset + interface compétence |
| Modèles vision-langage-action (π0, SmolVLA…) | idem, plus l'inférence éventuellement sur une autre machine (règle 7) |
| World models | des données en quantité, réelles et simulées, au format standard |
| Apprentissage par renforcement | le monde simulé sous forme d'environnement Gym (`reset`, `step`) |
| Planificateurs à base de modèles de langage | des compétences nommées (4.4) |

### 4.6 Dépendance à LeRobot

LeRobot est en version 0.x : il ne promet pas de stabilité d'une version à l'autre, et a déjà changé en 2025 le format des datasets (v2.1 → v3.0) et la forme des politiques (« processors »). MIR s'en protège ainsi (décidé le 18/10/2026) :

1. **Version figée** dans `requirements.txt` (`lerobot[feetech]==0.5.1`, avec MuJoCo). Une mise à jour est une décision, prise par exemple entre deux années scolaires ; tous les postes d'une classe ont le même environnement.
2. **Un seul point de contact par domaine** : le bus moteur dans `mir_devices` (les types utilisés ailleurs passent par `mir_devices/lerobot_types.py`), l'interface robot dans `mir_robot`, et demain un module unique pour les datasets et un pour les politiques. L'éditeur et les scripts des élèves n'importent pas LeRobot directement.
3. **Un test de compatibilité en simulé** (à écrire avec l'étape Collecter) : construire le robot, enregistrer deux épisodes, relire le dataset, faire un pas d'entraînement, faire tourner une politique. À lancer avant toute mise à jour ; seul le bus moteur réel se vérifie sur le matériel.
4. **Versions notées** (LeRobot, MIR) avec chaque dataset et chaque modèle, en plus des conditions d'enregistrement.

Point de vigilance : `mirFeetechMotorsBus` hérite de `FeetechMotorsBus` et appelle ses méthodes internes (`_read`, `_write`) ; c'est l'endroit le plus exposé à un changement de LeRobot.

## 5. Réel, simulé et jumeau numérique

Risque identifié : que les élèves confondent jumeau numérique et simulation. Choix de conception : **l'élève n'a qu'un seul choix à faire, Réel ou Simulé**.

- **Simulé** : MuJoCo calcule le mouvement ; la vue 3D montre la simulation.
- **Réel** : la vue 3D reproduit le robot réel à partir des positions mesurées. Elle peut afficher la consigne en transparence, ce qui rend visible l'erreur de suivi.

Le jumeau n'est donc **pas un mode, c'est une vue**, c'est-à-dire un simple affichage : il ne calcule rien et ne pilote rien, il montre l'état du robot. Concrètement, c'est la même fenêtre 3D (`mujoco_widget`) dans les deux cas ; seule change l'origine des positions affichées : *« la 3D montre toujours ton robot ; en réel elle le recopie, en simulé elle le calcule. »* Un code couleur constant (par exemple un bandeau rouge « RÉEL » et bleu « SIMULÉ ») évite les confusions et les accidents.

Tout ce qui relève du simulé fonctionne **hors ligne**, sans robot connecté.

**On ne se connecte qu'au robot réel.** En simulé, il n'y a pas de bouton « Connecter » : le robot simulé est construit dès qu'un robot avec une structure est ouvert, et reconstruit automatiquement après chaque modification de la structure ou de la configuration. Un bouton « Remettre à zéro » le replace dans sa position de départ.

## 6. Briques Python

L'interface gère la mécanique (connexion, boucle, cadence, enregistrement, affichage) ; l'élève code la partie intéressante dans un petit fichier qui respecte une classe de base. MIR détecte les briques présentes et les propose dans une liste. Elles s'utilisent de la même façon en script.

*Mise à jour du 18/10 : la téléopération utilise désormais des classes de périphérique façon LeRobot (`Teleoperator.get_action(observation)`, dossier `mir_robot/teleop/`), et les élèves écrivent aussi des scripts libres (onglet Scripts : `robot.get_observation()`, `robot.send_action()`, `boucle()`, figures matplotlib dans l'application). Commandes, téléopérations et scripts seront rapprochés dans l'interface « compétence » (partie 4.1) au moment de la définir.*

### 6.1 Commandes

Une **commande** est ce qui choisit, à chaque tour de boucle, l'action à envoyer au robot à partir de son observation : consigne, trajectoire, téléop ou modèle appris. Elles ont toutes la même forme (`mir_robot/commande.py`) :

```python
from mir_robot.commande import Commande

class MaCommande(Commande):
    nom = "Ma commande"
    description = "Ce que fait la commande"

    def demarrer(self, robot):        # facultatif : robot.actions, robot.observations, robot.fps
        ...
    def action(self, observation):    # renvoie {"joint_1.position": 30.0, ...} ou None
        ...
    def arreter(self):                # facultatif
        ...
```

MIR trouve les commandes dans `mir_robot/commandes/` (fournies) et `mir_user_scripts/commandes/` (utilisateur), appelle `action()` à la cadence choisie, vérifie les noms des actions et borne les valeurs aux plages des moteurs avant `send_action()`. En script : `executer(robot, MaCommande(), fps=30)`. La commande peut demander l'arrêt avec `self.terminer()`.

Pour les modèles appris, une seconde forme décrit le réseau lui-même, par exemple `Modele.construire(n_entrees, n_sorties)` ; l'entraînement et l'inférence sont gérés par MIR et LeRobot.

### 6.2 Briques d'analyse

*Retirées de l'interface le 18/10/2026 (le code de base est conservé dans `mir_robot/essai.py`) : l'analyse reste le travail de l'élève, en script.*

Elles servent au post-traitement d'un essai, directement dans l'application (pas d'export CSV : l'export servait justement à faire ce post-traitement en Python).

```python
def analyser(essai):
    t, theta = essai.t, essai["epaule.position"]
    ...                                       # identification, temps de réponse…
    return {"tau": tau, "t5%": t5}, figure    # valeurs et figure affichées par MIR
```

On peut appliquer la même analyse à un essai réel et à un essai simulé, puis comparer.

### 6.3 Éditeur intégré

Les briques s'écrivent dans un **éditeur Python intégré** à l'application (base existante : `mir_utils/ui/code_editor.py`). Partout où l'on choisit une brique dans une liste, on peut aussi en créer une nouvelle à partir d'un modèle ou modifier celle qui est choisie. Le fichier s'ouvre avec les imports MIR déjà en place et la classe de base à compléter. L'éditeur arrive avec les premières briques, pas avant.

### 6.4 Modèles écrits à la main (behavior cloning)

Exigence pédagogique (18/10/2026) : les élèves doivent pouvoir **coder eux-mêmes** un modèle de behavior cloning en PyTorch (MLP, CNN), pas seulement utiliser ACT ou un VLA.

**Un modèle = des poids + une fiche de préparation.** La fiche (noms des entrées et des sorties, taille des images, statistiques de normalisation) est calculée à partir du dataset et enregistrée avec le modèle. MIR l'applique à l'entraînement et sur le robot : la préparation n'est jamais recopiée à la main (cause des erreurs du diagnostic ACT, règle 3).

Trois niveaux :
1. **J'écris le réseau** : l'élève écrit sa classe `nn.Module` (`forward(image, etat)`) ; MIR entraîne et affiche les courbes de perte.
2. **J'écris aussi l'entraînement** : MIR fournit les données prêtes (tenseurs) et l'enregistrement du modèle avec sa fiche ; l'élève écrit sa boucle d'entraînement (onglet Scripts).
3. **Modèles de LeRobot** (ACT, diffusion, SmolVLA…) sur le même dataset.

Dans les trois cas, le modèle entraîné devient une **compétence** : on le choisit dans une liste et il pilote le robot réel ou simulé (observation → fiche → réseau → action). La seule classe écrite par l'élève est la classe PyTorch.

## 7. Enregistrements : essais et datasets

| | **Essai** | **Dataset** |
|---|---|---|
| Sert à | mesurer, identifier, comparer réel et simulé | entraîner un modèle |
| Contenu | grandeurs scalaires à haute fréquence | épisodes avec images |
| Format | `DataRecorder` de `mir_utils.metrics` (.npz) | LeRobotDataset |
| Vue | courbes, curseurs, briques d'analyse | lecture d'épisodes, édition, visualisation |

### Essai

*Fait (15/10/2026)* : onglet Piloter → Essais. Noyau dans `mir_robot/essai.py` (`Sollicitation`, `Essai`, `lancer_essai`, `Analyse`), sollicitations fournies dans `mir_robot/commandes/sollicitations.py` (échelon, rampe, sinus, créneau), analyses dans `mir_robot/analyses/` et `mir_user_scripts/analyses/`. Chaque essai est enregistré dans `data/essais/` avec ses conditions (réel ou simulé, robot, sollicitation, réglages du moteur, date). En simulation, P/I/D ne sont pas simulés (asservissement idéal) : la vitesse et le couple max le sont.

Un essai suit le modèle des logiciels de systèmes didactiques : *je définis la sollicitation (échelon, rampe, sinus) → je lance → j'obtiens les courbes → j'analyse*. Il s'appuie sur `DataRecorder`, qui réserve sa mémoire à l'avance, horodate et sauvegarde des métadonnées. Il faut le compléter avec :

1. **les consignes** (actions) à côté des mesures ;
2. **les conditions de l'essai** dans les métadonnées : réel ou simulé, sollicitation, P/I/D, date ;
3. une surcouche `Essai` pour un accès simple (`essai.t`, `essai["epaule.position"]`).

### Dataset

Format LeRobot, pour rester compatible avec ses outils d'entraînement et de visualisation. Même forme que le script de collecte existant (`mir_user_scripts/bras_leader_follower_cam/dataset_interface.py`) : `observation.state`, `observation.images.<caméra>`, `action`. La cadence de la collecte s'appuie sur `PeriodWaiterSafeForJitter` (`mir_utils/period_waiters.py`) : en cas de retard, le tick manqué est sauté au lieu d'enchaîner deux mesures en rafale, ce qui garde les images sur une grille régulière, comme le suppose LeRobot (fréquence fixe). Les **conditions d'enregistrement** (éclairage, réel ou simulé, version de la configuration) sont tracées : leur absence a fait échouer le diagnostic ACT.

### Expérience

Notion à préciser : un dossier qui regroupe la configuration, la scène, les essais, les datasets, les modèles et les logs d'un même travail. Les scènes vivent dans `mir/scenes/` ; une expérience en garderait une copie, comme de la configuration.

## 8. Interface par étapes

Une colonne à gauche suit le parcours, plutôt qu'une icône par fonction. Une barre du haut minimale : ouvrir, enregistrer, connecter, Réel/Simulé.

| Étape | Contenu | Vues existantes concernées |
|---|---|---|
| **Robot** | concevoir le modèle, assembler, calibrer, configurer les capteurs | `structure_editor`, `scan_devices`, `motor_configuration`, `calibration`, `sensor_configuration` |
| **Piloter** | trois onglets (état au 18/10) : **Essais** (sollicitation, réglages du moteur, courbes), **Téléopération** (modalité au choix, codable ; vue de la caméra et du lidar), **Scripts** (petit environnement de programmation : éditeur, console, figures) ; une seule activité à la fois sur le robot | `essais`, `teleop`, `scripts`, `observations_widget`, `mujoco_widget` |
| **Modéliser** | MGD/MGI, trajectoires, études méca | à créer |
| **Collecter** | enregistrer, visualiser et éditer des datasets | à créer |
| **Apprendre** | choisir ou écrire un modèle, entraîner | à créer |
| **Évaluer** | inférence en réel ou simulé, analyse | à créer |

Le monitor est à revoir en s'inspirant des logiciels des systèmes didactiques de TP (type Maxpid, Control'X), de Dynamixel Wizard et de PlotJuggler, autour de la notion d'essai.

## 9. Ce que MIR ne construit pas

- **Pas de middleware à la ROS.** ROS est avant tout une infrastructure (des processus qui s'échangent des messages, du réseau, des outils de lancement et de configuration) : puissante mais lourde, et c'est ce que LeRobot a choisi d'éviter. MIR **emprunte les idées, pas l'infrastructure** : pas de bus de messages général ni de « nœuds » à configurer ; une application qui possède le robot et une interface Python minimale. Si un jour il faut parler à ROS, ce sera par un pont vers ROS 2.
- **Pas de nouveau framework d'apprentissage** : LeRobot pour l'imitation (ACT, diffusion, VLA) et des bibliothèques existantes pour le RL.
- **Pas de moteur physique** : MuJoCo.

La valeur de MIR est la couche d'intégration : modules physiques, description unique, Réel/Simulé, briques pédagogiques et interface.

**Règle de tri** : une fonctionnalité n'entre dans MIR que si elle sert une étape d'un parcours.

## 10. Priorités

1. **Bras 4 ddl de bout en bout**, en réel et en simulé : conception → assemblage guidé → pilotage et essais → téléop → dataset → ACT.
2. **Robot mobile** : valide que le noyau est bien générique (moteurs en vitesse, lidar, SLAM).
3. **Quadrupède en RL** : horizon.

Ordre validé le 15/10/2026 :
1. Robot : « Nouveau robot » à partir de la structure, robot simulé toujours disponible (fait) ;
2. Piloter → Essais ;
3. Piloter → Téléopération ;
4. Piloter → Robotique.

Suite décidée le 18/10/2026 :
1. ce document (vision en couches) ;
2. **Collecter** : enregistrement de démonstrations au format LeRobotDataset, en réel et en simulé ;
3. **interface « compétence »**, reprise de celle des politiques LeRobot ;
4. ensuite seulement, la couche **tâche** ;
5. en parallèle, quand c'est utile : scènes dans `mir/scenes/` (prérequis de la collecte en simulé), chaîne réelle du robot mobile (guide de montage des roues et du lidar).

Premiers chantiers proposés le 15/10 pour le parcours 1 (en grande partie faits) :
- plages par défaut dans le catalogue (±90°, pince) ;
- assistant d'assemblage (ID + retour en direct + calibration par module) ;
- commandes : noyau (fait), choix de la commande dans le monitor à la place d'`actions_widget`, éditeur intégré ;
- essais (consignes + conditions dans `DataRecorder`) et briques d'analyse.

## 11. Questions ouvertes

- **Plage de la pince** : valeur à mesurer.
- **Fidélité de la simulation des registres** : régler le PID ou passer en vitesse ou en position, c'est modifier les registres du servo (déjà possible depuis l'éditeur). Pour qu'un essai simulé soit comparable au réel, les servos simulés doivent tenir compte de ces registres (P/I/D, mode, vitesse, couple max). Il reste à mesurer à quel point.
- **Fréquence maximale d'un essai** : limitée par le bus et le wifi, à mesurer.
- **Robot mobile** : roues décrites par une articulation `"mode": "velocity"` du catalogue (réglé le 18/10) ; reste l'odométrie, l'avant du lidar et le guide de montage des roues et du lidar.
- **Interface compétence** : forme exacte (méthode `select_action` de LeRobot ou équivalent ; comment une compétence signale sa fin et sa réussite).
- **Couche tâche** : machine à états ou arbre de comportement, et leur représentation dans l'interface.
- **Inférence distante** : politique lourde sur une autre machine, avec quelle latence acceptable.
- **Données** : où stocker les datasets (dossier du robot, d'une expérience, Hub Hugging Face).
- **RL** : forme de l'environnement gymnasium construit à partir de la description.
- **Expérience** : structure exacte du dossier.
