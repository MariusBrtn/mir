# Architecture de MIR

*Document de conception — version de travail du 15/10/2026, à valider avant de coder.*

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

```
  Interface par étapes                  Scripts Python
 ─────────────────────────────────────────────────────────────────────
  Commandes              consigne · trajectoire · téléop · modèle appris  
  Briques d'analyse      post-traitement d'un essai · évaluation
  Outils de modèle       MGD/MGI · cinématique · statique · dynamique
  Données                essais (DataRecorder) · datasets (LeRobot)
  Apprentissage          LeRobot (imitation) · RL (MuJoCo + gymnasium)
 ─────────────────────────────────────────────────────────────────────
  mirRobot               connect · get_observation · send_action · disconnect
        ├── Réel    →  mir_devices (bus Feetech, caméras, ESP32, lidar)
        └── Simulé  →  mir_sim (appareils simulés sur MuJoCo)
 ─────────────────────────────────────────────────────────────────────
  Description du robot   catalogue de modules + structure + configuration
```

### Règles

1. **Tout passe par `mirRobot`.** Pilotage, essais, téléop, collecte et inférence n'utilisent que `get_observation()` et `send_action()`, qu'ils soient lancés depuis l'interface ou depuis un script. Seuls les outils de mise en service (assemblage, ID, calibration, réglage des registres) accèdent directement au matériel.
2. **Réel et simulé sont interchangeables.** Le simulé est le même `mirRobot`, construit avec les appareils simulés de `mir_sim` : aucune activité ne doit savoir sur quel backend elle tourne.
3. **La préparation des observations est déclarée une fois** dans la configuration (rotation et taille d'image…) et appliquée par `mirRobot`, jamais recopiée dans chaque script. Les erreurs du diagnostic ACT (division par 255, préparation d'image dupliquée) venaient de là.
4. **L'interface et les scripts utilisent les mêmes briques.** Une téléop ou un modèle écrit pour l'interface se lance aussi en script, et inversement.
5. **Le vocabulaire du code générique reste générique** (`mir_devices`, éditeur) : pas de « leader/follower » ni de cas d'usage précis. Ces notions vivent dans les briques et dans les exemples.

### Paquets

| Paquet | Rôle |
|---|---|
| `mir_devices` | Pilotes du matériel réel (bus moteur, caméras, ESP32, lidar, découverte réseau) |
| `mir_sim` | Catalogue de modules, construction du modèle MuJoCo, appareils simulés |
| `mir_robot` | `mirRobot` et `mirRobotConfig` : le point d'entrée unique |
| `mir_robot_editor` | L'interface graphique |
| `mir_utils` | Outils transverses (UI de base, enregistrement, métriques, concurrence) |
| `mir_user_scripts` | Exemples et scripts d'élèves |

À créer au fil de l'eau : un emplacement pour les **briques** (classes de base et briques fournies), les **outils de modèle** (MGD/MGI…) et la gestion des **essais**.

## 5. Réel, simulé et jumeau numérique

Risque identifié : que les élèves confondent jumeau numérique et simulation. Choix de conception : **l'élève n'a qu'un seul choix à faire, Réel ou Simulé**.

- **Simulé** : MuJoCo calcule le mouvement ; la vue 3D montre la simulation.
- **Réel** : la vue 3D reproduit le robot réel à partir des positions mesurées. Elle peut afficher la consigne en transparence, ce qui rend visible l'erreur de suivi.

Le jumeau n'est donc **pas un mode, c'est une vue**, c'est-à-dire un simple affichage : il ne calcule rien et ne pilote rien, il montre l'état du robot. Concrètement, c'est la même fenêtre 3D (`mujoco_widget`) dans les deux cas ; seule change l'origine des positions affichées : *« la 3D montre toujours ton robot ; en réel elle le recopie, en simulé elle le calcule. »* Un code couleur constant (par exemple un bandeau rouge « RÉEL » et bleu « SIMULÉ ») évite les confusions et les accidents.

Tout ce qui relève du simulé fonctionne **hors ligne**, sans robot connecté.

**On ne se connecte qu'au robot réel.** En simulé, il n'y a pas de bouton « Connecter » : le robot simulé est construit dès qu'un robot avec une structure est ouvert, et reconstruit automatiquement après chaque modification de la structure ou de la configuration. Un bouton « Remettre à zéro » le replace dans sa position de départ.

## 6. Briques Python

L'interface gère la mécanique (connexion, boucle, cadence, enregistrement, affichage) ; l'élève code la partie intéressante dans un petit fichier qui respecte une classe de base. MIR détecte les briques présentes et les propose dans une liste. Elles s'utilisent de la même façon en script.

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

Format LeRobot, pour rester compatible avec ses outils d'entraînement et de visualisation. Les **conditions d'enregistrement** (éclairage, réel ou simulé, version de la configuration) sont tracées : leur absence a fait échouer le diagnostic ACT.

### Expérience

Notion à préciser : un dossier qui regroupe la configuration, la scène, les essais, les datasets, les modèles et les logs d'un même travail.

## 8. Interface par étapes

Une colonne à gauche suit le parcours, plutôt qu'une icône par fonction. Une barre du haut minimale : ouvrir, enregistrer, connecter, Réel/Simulé.

| Étape | Contenu | Vues existantes concernées |
|---|---|---|
| **Robot** | concevoir le modèle, assembler, calibrer, configurer les capteurs | `structure_editor`, `scan_devices`, `motor_configuration`, `calibration`, `sensor_configuration` |
| **Piloter** | trois sous-parties : **Essais** (sollicitation paramétrable, registres P/I/D, analyse), **Robotique** (MGD/MGI, trajectoires, vue 3D), **Téléopération** (modalité au choix, codable) ; une seule boucle de mesures et un seul REC | `robot_monitor` (devient la base d'Essais), `observations_widget`, `mujoco_widget` |
| **Modéliser** | MGD/MGI, trajectoires, études méca | à créer |
| **Collecter** | enregistrer, visualiser et éditer des datasets | à créer |
| **Apprendre** | choisir ou écrire un modèle, entraîner | à créer |
| **Évaluer** | inférence en réel ou simulé, analyse | à créer |

Le monitor est à revoir en s'inspirant des logiciels des systèmes didactiques de TP (type Maxpid, Control'X), de Dynamixel Wizard et de PlotJuggler, autour de la notion d'essai.

## 9. Ce que MIR ne construit pas

- **Pas de middleware à la ROS** : un seul processus, une seule boucle.
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

Premiers chantiers proposés pour le parcours 1 :
- plages par défaut dans le catalogue (±90°, pince) ;
- assistant d'assemblage (ID + retour en direct + calibration par module) ;
- commandes : noyau (fait), choix de la commande dans le monitor à la place d'`actions_widget`, éditeur intégré ;
- essais (consignes + conditions dans `DataRecorder`) et briques d'analyse.

## 11. Questions ouvertes

- **Plage de la pince** : valeur à mesurer.
- **Fidélité de la simulation des registres** : régler le PID ou passer en vitesse ou en position, c'est modifier les registres du servo (déjà possible depuis l'éditeur). Pour qu'un essai simulé soit comparable au réel, les servos simulés doivent tenir compte de ces registres (P/I/D, mode, vitesse, couple max). Il reste à mesurer à quel point.
- **Fréquence maximale d'un essai** : limitée par le bus et le wifi, à mesurer.
- **Robot mobile** : comment décrire les roues (rotation continue) et l'odométrie dans la structure.
- **RL** : forme de l'environnement gymnasium construit à partir de la description.
- **Expérience** : structure exacte du dossier.
