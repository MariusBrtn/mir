# Architecture de MIR

*Document de conception — version du 21/10/2026 (soir) (première version le 15/10). La partie 4 (couches et interfaces) a été validée le 18/10 ; les interfaces encore « à définir » le seront une par une. Le 21/10 : la couche tâche existe, c'est **MIR Flow** (partie 4.4), cinquième étape de l'application.*

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

### 2.4 Activités autonomes et jeux (MIR Flow)

Des activités longues qui mêlent perception, décision et compétences apprises, autour de jeux avec des humains : cache-cache, loup, « 1-2-3 soleil », partie de nerf avec des balles en mousse. Elles se construisent dans MIR Flow (partie 4.4), en assemblant des compétences (politiques apprises, consignes, scripts), des capteurs, de la vision, de la logique et, si besoin, un modèle de langage.

Premier exemple réalisé le 20/10/2026 : un **cache-cache** sur le robot `mobile_camera` (le robot mobile à lidar, avec une caméra à l'avant sur un coude 90°). La politique RL d'errance fait se promener le robot ; une chaîne « En continu » (Caméra → Vision) cherche une balle ; l'action s'arrête dès que la balle est vue. Scène « Rue avec une balle » (`robots/mobile_camera/scenes/rue_balle.json`).

Cet exemple montre la mécanique, pas encore l'intérêt de l'approche : une seule politique RL aurait pu le faire. MIR Flow devient nécessaire pour les tâches à plusieurs phases et à règles (un vrai jeu avec des tours et des scores), pour combiner des compétences de natures différentes (navigation RL + saisie ACT + consignes), pour garantir des règles de sécurité écrites (pas apprises), pour l'interaction avec des humains (LLM) et pour changer d'objectif sans réentraîner. Démonstrateurs visés : un robot qui **rapporte un objet**, un jeu à règles comme **« 1-2-3 soleil »**.

Deuxième exemple, réalisé le 21/10/2026 : une **cartographie par SLAM** sur `test_mobile`, entièrement écrite dans des nœuds Script Python, en faisant comme en réel (sans utiliser la position exacte que connaît la simulation), pour pouvoir passer au robot réel sans rien changer. La politique d'errance explore ; une chaîne « En continu » (5 Hz) enchaîne Mesure lidar → Mesure servos (positions des roues) → odométrie → recalage ICP → carte (grille d'occupation) → Scope. Voir le bilan en partie 10.

### 2.5 Ce dont chaque activité a besoin

| Activité | Description seule | Robot (réel ou simulé) | Données |
|---|:---:|:---:|:---:|
| MGD/MGI, cinématique, statique, dynamique | ✓ | | |
| Consignes, PID, essais, mesures | | ✓ | essais |
| Trajectoires, téléopération | | ✓ | |
| Collecte de données | | ✓ | datasets |
| Entraînement | | | datasets |
| Inférence, évaluation | | ✓ | modèle |
| Activités autonomes (MIR Flow) | | ✓ | modèles, graphe |

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

### 3.3 Mettre en service un module capteur (ESP32)

*Ajout du 21/10/2026.* Les capteurs autres que la caméra (lidar, météo, plus tard IMU) sont des modules ESP32 qui parlent à MIR en Wi-Fi ; la caméra est sur un Raspberry Pi. Avant d'être détecté à l'assemblage, un module ESP32 doit avoir le firmware MIR et connaître le réseau Wi-Fi du PC. L'outil **Paramètres avancés → Module capteur ESP32** (`mir_robot_editor/capteurs/`) s'en charge. Il s'appuie sur `mir_esp_deploy` et `esp32_sensor` sans les modifier : mêmes binaires, même protocole série (`EspSensor`), même provisioning Bluetooth (`BleProvisioner`).

- **Le réseau Wi-Fi est saisi une fois** et mémorisé sur le PC. macOS masque le nom du réseau courant sans autorisation de localisation, MIR ne le pré-remplit donc pas.
- **Par câble USB** : MIR lit les réseaux du module, met le nouveau en principal et l'ancien en secours, remet l'IP du réseau principal en automatique (une IP fixe de l'ancien réseau empêcherait de rejoindre le nouveau), puis redémarre le module.
- **En Bluetooth**, dans les 60 s après l'allumage : seul le réseau principal est remplacé ; l'ancien est perdu et une IP fixe ne peut pas être corrigée (limite du firmware). Seuls les firmwares postérieurs au 22/09/2026 émettent en Bluetooth.
- **Installer le firmware** (câble) : flash par `esptool`, puis type de capteur, nom du module et réseau Wi-Fi en une seule opération.
- Dans tous les cas, MIR **vérifie que le module répond** sur le réseau (découverte UDP, par son nom) avant d'annoncer la réussite.

Tests : `tests/test_esp32.py` (module factice). Pas encore essayé sur le vrai lidar : le sien a un firmware sans Bluetooth et doit être mis à jour une fois par câble.

### 3.4 Contenu du fichier de configuration

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
  Tâche          enchaîner des compétences, décider, gérer les échecs     MIR Flow (21/10)
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
| **Tâche** | graphe MIR Flow : chaîne principale, chaînes en continu, interruptions (partie 4.4) | idées des arbres de comportement et de `ros2_control` | première version le 21/10 |
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
8. **`get_observation()` et `send_action()` ne se redéfinissent pas.** Ce sont les deux méthodes de base de MIR : aucune couche ne leur ajoute d'argument ni ne les expose telles quelles à un modèle de langage. Un LLM agit à travers des compétences nommées (partie 4.4).
9. **Une seule source d'observation par activité.** Pendant une activité, un seul endroit appelle `get_observation()` à fréquence fixe et exécute l'action en cours ; tous les consommateurs lisent la dernière observation publiée. C'est la boucle robot de MIR Flow (partie 4.4) : même observation pour tous, et jamais deux fils sur le bus moteur.

#### Paquets

| Paquet | Rôle |
|---|---|
| `mir_devices` | Pilotes du matériel réel (bus moteur, caméras, ESP32, lidar, découverte réseau) |
| `mir_sim` | Catalogue de modules, construction du modèle MuJoCo, appareils simulés |
| `mir_robot` | `mirRobot` et `mirRobotConfig` : le point d'entrée unique |
| `mir_flow` | MIR Flow : graphe, boucle robot, exécution des nœuds, perception (MediaPipe), nœud LLM (OpenAI), contexte du robot, clé API |
| `mir_robot_editor` | L'interface graphique |
| `mir_esp_deploy`, `esp32_sensor` | Outil d'origine de déploiement des ESP32 et leur firmware (PlatformIO) ; repris par l'outil Module capteur ESP32 (partie 3.3), sans modification |
| `mir_pi_sensors` | Serveurs caméra et lidar du Raspberry Pi, et leur script de déploiement |
| `mir_utils` | Outils transverses (UI de base, enregistrement, métriques, concurrence) |
| `mir_user_scripts` | Exemples et scripts d'élèves |

Dossiers de travail (hors paquets) : `robots/<nom>/` (configuration `robot.json`, `teleop/`, `scripts/`, `essais/`, `flows/flow.json` pour MIR Flow) et `scenes/` (scènes de simulation, voir 4.3).

### 4.3 Scènes

Une **scène** décrit l'environnement simulé : sol ou table, position de départ du robot, objets (formes simples ou objets 3D texturés), caméras fixes, éclairage. Elle n'appartient pas à un robot : n'importe quel robot peut être posé dans n'importe quelle scène. Les scènes sont des fichiers de `mir/scenes/` (table de travail, arène, dé à attraper…) ; la scène se choisit dans l'application, en simulé seulement. Par défaut : la table pour un robot fixé au sol, l'arène pour un robot mobile.

*Réalisé le 19/10/2026* : les scènes sont pour l'instant rangées **par robot** (`robots/<robot>/scenes/*.json`), car leur posture de départ et leurs zones de placement dépendent de la portée du bras (ramassage du dé, insertion dans la boîte, bac à sable). La scène se choisit dans l'en-tête, en simulé ; « Replacer la scène » remet le robot en posture de départ et replace les objets, au hasard s'ils ont des règles de placement (`placement`, `in_gripper`), les mêmes que celles des générateurs de démonstrations automatiques. Dans toutes les vues 3D, les objets se déplacent à la souris. Des scènes communes à tous les robots (`mir/scenes/`) restent possibles.

Le réalisme utile dépend du capteur : la géométrie suffit pour le lidar et la navigation, la physique compte pour l'asservissement, l'apparence seulement pour l'apprentissage sur images. Pour ce dernier, la priorité est de **faire varier** la scène (éclairage, couleurs, position des objets) plutôt que de la copier parfaitement ; des objets ou une pièce scannés (maillages texturés) pourront s'y ajouter sans changer d'outil.

### 4.4 Activités longues : la couche tâche (MIR Flow)

Les systèmes récents sont **hiérarchiques** : en bas, des compétences courtes (« attraper le dé », « errer sans rien percuter ») ; au-dessus, une couche qui décide quoi faire ensuite, dans quel ordre, et que faire en cas d'échec ou d'événement. Dans MIR, cette couche est **MIR Flow** (réalisé du 20 au 21/10/2026), la cinquième étape de l'application : un éditeur de graphe dans l'esprit de n8n, qui assemble des compétences apprises, du contrôle classique, de la perception, de la logique et des modèles de langage.

#### Principe

Un graphe contient trois sortes de chaînes, qui partagent les mêmes **données du flux** :

| Chaîne | Commence par | Comportement |
|---|---|---|
| **Principale** | Départ | Séquentielle : un nœud se termine, le programme passe au suivant par la sortie qu'il a choisie (suite, oui/non, encore/fini, interrompu). Relier une sortie à un nœud précédent fait une boucle. C'est la « tâche ». |
| **En continu** | En continu | Tourne en boucle à sa fréquence pendant tout le programme, à côté de la chaîne principale. Lecture et calcul seulement (capteurs, vision, scripts, conditions), jamais d'action. C'est la « perception ». |
| **Interruption** | Interruption | Dès que sa condition devient vraie, la chaîne principale est interrompue (l'action en cours s'arrête) et le programme continue par cette chaîne. Pour les événements du jeu et la sécurité. |

**Données du flux** (le « blackboard » des roboticiens) : chaque nœud range son résultat sous son nom (`vision.nombre`, `errance.duree`…), lisible par n'importe quel nœud : conditions, messages, scripts, LLM. Chaque nœud reçoit aussi en **entrée** le résultat du nœud précédent (`entree`), comme dans n8n.

Une action peut s'interrompre elle-même : **« Arrêter quand »** est une condition vérifiée à chaque tour de l'action (ex. `vision.nombre > 0`, sur des données tenues à jour par une chaîne en continu) ; si elle devient vraie, l'action sort par « interrompu ».

#### Nœuds (version minimale du 21/10)

| Catégorie | Nœuds |
|---|---|
| Déroulement | Départ, En continu, Interruption, Attendre, Répéter (boucle), Fin |
| Percevoir | Mesure (source au choix : caméra → image brute, lidar → points [angle, distance], servos → position, vitesse… ; et l'instant de la mesure), Vision (objets reconnus dans l'image du nœud précédent) |
| Décider | Condition (oui/non), Script Python (`traiter(entree, donnees)`), LLM |
| Agir | Action : une compétence — consigne fixe, mini script ou politique apprise (RL, ACT…) |
| Communiquer | Message, Scope (affiche en direct une donnée : image, nuage lidar, courbes, trajectoire) |

Choix faits avec l'utilisateur :
- **Une Mesure par source, une seule lecture du robot.** On peut mettre plusieurs nœuds Mesure (caméra, lidar, codeurs des servos) ; tous lisent la même observation de la boucle robot (ajouté le 21/10 pour le SLAM, qui demande l'odométrie).
- **Capteurs bruts, traitement explicite.** Les Mesures donnent les données brutes ; tout traitement se fait dans un Script Python ou un nœud de perception. MIR ne fournit pas d'attributs spécialisés (pas de « distance devant » toute faite).
- **Nœuds selon la configuration.** La Mesure ne propose que les sources du robot ; Vision n'apparaît que si le robot a une caméra.
- **Une action est une `Commande`** (partie 6.1) exécutée par la boucle habituelle : consigne, script et politique entraînée ont la même forme. Sa **durée est réglée dans le nœud** (exacte pour une consigne, maximale pour un script ou une politique qui peuvent finir d'eux-mêmes).
- **Vision** : détecteur EfficientDet-Lite0 de MediaPipe (Google, licence Apache-2.0), 80 catégories d'objets du jeu COCO, téléchargé une fois (7 Mo). En simulation, une balle jaune est reconnue (« sports ball ») ; un humain fait de formes simples ne l'est pas. MediaPipe demande `opencv-contrib-python`, écarté par `override-dependencies` dans le `pyproject.toml` racine pour garder l'OpenCV de LeRobot.

#### Le nœud LLM

Un modèle de langage (OpenAI, compte de l'utilisateur ; clé dans le trousseau du système, jamais dans un fichier) qui agit **uniquement à travers les nœuds branchés sous lui comme outils** (losange « Outils », comme les outils d'un agent n8n). Il voit le nom et la description de chaque outil, sans paramètre : tout est réglé dans les nœuds (y compris la durée d'une action). Il répond dans la discussion de MIR Flow, et peut aussi être une étape du programme (message « Dans le flux », avec des `{…}` remplacés par les données). Une description du robot, générée à partir de sa configuration et du modèle MuJoCo (sens des roues, effet des articulations, pince, capteurs), peut lui être donnée.

Une première version, où le LLM appelait directement `get_observation` et `send_action` avec des arguments ajoutés, a été abandonnée : ces deux méthodes restent la base de MIR (règle 8).

#### Boucle robot unique

Pendant un programme, une seule **boucle robot** (`mir_flow/robot_loop.py`) parle au robot : elle appelle `get_observation()` à fréquence fixe (celle de l'action en cours, sinon 30 Hz), publie la dernière observation, et exécute l'action en cours (`send_action()`). Tous les nœuds lisent cette observation (règle 9). Seul l'arrêt d'urgence passe directement. La boucle tourne **toujours dans le même fil** : le rendu de la caméra simulée garde un contexte OpenGL verrouillé par le fil qui l'a créé (MuJoCo sur macOS), et un nouveau fil à chaque lancement bloquait la caméra au deuxième lancement (corrigé le 21/10).

#### Interface

Bibliothèque de nœuds à gauche (clic : ajouté à côté du nœud choisi et relié ; ou glisser sur le graphe) ; réglages dans une fenêtre ouverte par un **double-clic**, en trois colonnes **Entrée | Réglages | Sortie** qui montrent les données du dernier passage dans le nœud (images en vignette), mises à jour en direct pendant l'exécution ; liens aimantés ; boucles tracées en U sous les nœuds ; Ctrl+Z, zoom, clic droit pour supprimer. Pendant l'exécution, le graphe est en lecture seule et le nœud en cours est entouré. Couleurs des catégories dans la charte (`theme.FLOW_*`), à l'écart des couleurs d'état. Le graphe est enregistré dans `robots/<robot>/flows/flow.json`.

#### Positionnement

Chaque élément a un équivalent dans l'industrie et la recherche : chaîne principale et conditions ↔ arbres de comportement et machines à états (BehaviorTree.CPP, Nav2, SMACH) ; chaînes en continu ↔ nœuds de perception ROS 2 ; données du flux ↔ blackboard ; boucle robot ↔ `ros2_control` ; actions ↔ bibliothèque de compétences ; nœud LLM ↔ planificateurs sur compétences (SayCan). MIR Flow en est une **version pédagogique fidèle** : les notions sont transférables. Ce n'est pas un outil industriel : réactivité moins générale qu'un arbre de comportement (pas de priorités imbriquées), données non horodatées, pas d'actions parallèles, pas de temps réel, pas de sous-flux ni d'enregistrement-rejeu.

MIR Flow ne remplace pas l'apprentissage : un comportement court et réactif (errer, saisir) s'apprend mieux qu'il ne se dessine. MIR Flow **assemble** ces compétences apprises avec des règles, de la perception et des modèles de langage.

### 4.5 Ouverture vers les modèles avancés

| Famille | Ce qu'il faut à MIR pour l'accueillir |
|---|---|
| Modèles écrits par l'élève (MLP, CNN en PyTorch, behavior cloning) | données LeRobotDataset + fiche de préparation + interface compétence (partie 6.4) |
| Politiques apprises (ACT, diffusion…) | données LeRobotDataset + interface compétence |
| Modèles vision-langage-action (π0, SmolVLA…) | idem, plus l'inférence éventuellement sur une autre machine (règle 7) |
| World models | des données en quantité, réelles et simulées, au format standard |
| Apprentissage par renforcement | le monde simulé sous forme d'environnement Gym (`reset`, `step`) |
| Planificateurs à base de modèles de langage | des compétences nommées : le nœud LLM de MIR Flow et ses outils (4.4) |

### 4.6 Dépendance à LeRobot

LeRobot est en version 0.x : il ne promet pas de stabilité d'une version à l'autre, et a déjà changé en 2025 le format des datasets (v2.1 → v3.0) et la forme des politiques (« processors »). MIR s'en protège ainsi (décidé le 18/10/2026) :

1. **Version figée** dans les `pyproject.toml` (`lerobot[feetech]==0.5.1`, `mujoco==3.6.0`), et toutes les autres dépendances dans `uv.lock` (depuis le 18/10). Une mise à jour est une décision, prise par exemple entre deux années scolaires ; tous les postes d'une classe ont le même environnement.
2. **Un seul point de contact par domaine** : le bus moteur dans `mir_devices` (les types utilisés ailleurs passent par `mir_devices/lerobot_types.py`), l'interface robot dans `mir_robot`, et demain un module unique pour les datasets et un pour les politiques. L'éditeur et les scripts des élèves n'importent pas LeRobot directement.
3. **Un test de compatibilité en simulé** : `python tests/test_lerobot.py` (fait le 18/10 pour les données : création, ajout, suppression, relecture, DataLoader ; à compléter par l'entraînement et les politiques). À lancer avant toute mise à jour ; seul le bus moteur réel se vérifie sur le matériel.
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

*Fait le 18/10/2026* : `mir_robot/donnees.py` (seul point de contact avec l'API des datasets LeRobot : `FormatDataset`, `DatasetMIR`) et l'étape « Collecter des données ». Observations cochées à la main (par défaut : angles, vitesses des roues, caméras et lidars) ; actions = consignes réellement envoyées par la téléopération (après bornage aux butées) ; le lidar est enregistré en `observation.<lidar>` (tableau 400 × 2) ; conditions de chaque épisode dans `meta/mir.json`.

### Expérience

Notion à préciser : un dossier qui regroupe la configuration, la scène, les essais, les datasets, les modèles et les logs d'un même travail. Les scènes vivent dans `mir/scenes/` ; une expérience en garderait une copie, comme de la configuration.

## 8. Interface par étapes

*État au 18/10/2026* : les étapes sont dans l'en-tête, comme les espaces de travail d'un logiciel de CAO (plus de colonne à gauche) ; l'en-tête porte aussi le robot ouvert (menu), le choix Réel/Simulé (liseré rouge ou ardoise sous l'en-tête), la connexion et l'unique arrêt d'urgence. Quatre étapes, **Configurer le robot** → **Piloter** → **Collecter des données** → **Entraîner un modèle** (fait le 19/10 : dataset, scripts d'entraînement PyTorch ou LeRobot, modèles entraînés). « Évaluer » est retiré pour l'instant. Piloter regroupe les **modalités de commande** du robot, présentées comme des cartes : **Essais**, **Téléopération**, **Scripts** et **IA** (fait le 19/10 : un modèle entraîné, PyTorch ou LeRobot, pilote le robot réel ou simulé). Le déploiement d'une politique est une façon de plus de commander le robot (couche compétence), au même titre que la téléopération : il est donc dans Piloter, pas dans une étape à part. « Entraîner un modèle » couvre tout ce qui produit une politique ou un modèle : behavior cloning écrit à la main, ACT, diffusion, réglage fin d'un VLA, et plus tard RL en simulation et world models.

*Ajout du 20-21/10/2026* : une cinquième étape, **MIR Flow** (couche tâche, partie 4.4), qui assemble les compétences des étapes précédentes (politiques entraînées, consignes, scripts) avec des capteurs, de la vision, de la logique et un modèle de langage.

### Historique (15/10)


Une colonne à gauche suit le parcours, plutôt qu'une icône par fonction. Une barre du haut minimale : ouvrir, enregistrer, connecter, Réel/Simulé.

| Étape | Contenu | Vues existantes concernées |
|---|---|---|
| **Robot** | concevoir le modèle, assembler, calibrer, configurer les capteurs | `structure_editor`, `scan_devices`, `motor_configuration`, `calibration`, `sensor_configuration` |
| **Piloter** | trois onglets (état au 18/10) : **Essais** (sollicitation, réglages du moteur, courbes), **Téléopération** (modalité au choix, codable ; vue de la caméra et du lidar), **Scripts** (petit environnement de programmation : éditeur, console, figures) ; une seule activité à la fois sur le robot | `essais`, `teleop`, `scripts`, `observations_widget`, `mujoco_widget` |
| **Modéliser** | MGD/MGI, trajectoires, études méca | à créer |
| **Collecter des données** | *fait le 18/10* : démonstrations en téléopération (durée fixe, compte à rebours, téléop active entre deux démonstrations pour remettre le robot en position), revue puis Valider ou Recommencer, épisodes revus dans l'appli ou dans le visualiseur LeRobot, suppression ; datasets dans `robots/<robot>/datasets/<nom>/` | `collecte`, module `mir_robot/donnees.py` |
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

Fait les 20-21/10/2026 : la couche **tâche** (MIR Flow, partie 4.4), avant l'interface compétence unifiée ; le robot `mobile_camera` (coude 90° ajouté au catalogue) et un premier cache-cache en simulation.

#### Bilan au 21/10/2026 (MIR Flow)

**Ce qui existe.** L'étape MIR Flow (partie 4.4) : 14 types de nœuds (Départ, En continu, Interruption, Attendre, Répéter, Fin ; Mesure, Vision ; Condition, Script Python, LLM ; Action ; Message, Scope), une boucle robot unique, les données du flux, « Arrêter quand », le LLM et ses outils. L'interface : bibliothèque de nœuds, réglages au double-clic en trois colonnes (Données disponibles et Entrée | Réglages | Sortie du dernier passage), liens aimantés, en S ou en U, Ctrl+Z, graphe en lecture seule pendant l'exécution, discussion masquée sans nœud LLM, éditeur Python avec coloration, fenêtres Scope. Robot `mobile_camera` et coude 90° au catalogue. Tests : `tests/test_flow.py` (17 tests), 97 tests en tout.

**Deux applications réalisées en simulation :**
- **cache-cache** (`mobile_camera`) : errance RL + Mesure caméra → Vision (« sports ball ») ; l'action s'arrête quand la balle est vue ;
- **SLAM** (`test_mobile`) : odométrie à partir des positions angulaires des roues (« dépliées » entre −180° et +180° ; plus juste que les vitesses, arrondies au tr/min), carte en grille d'occupation (« log-odds »), recalage ICP. Sur 90 s d'errance dans la rue encombrée (mesuré pour le développement uniquement) : odométrie seule, 2 à 3 m d'erreur et 80 à 170° de cap ; avec l'ICP, 20 à 30 cm et 8 à 10°.

**Ce que ces applications ont fait ajouter** (règle : on ne code que ce qu'une application rend nécessaire) :
- le nœud **Mesure** (source au choix : caméra, lidar, servos ; et l'instant de la mesure), qui remplace Caméra et Lidar : le SLAM avait besoin des codeurs des roues ;
- le nœud **Scope**, pour voir la carte, le lidar, des courbes ou une trajectoire en direct ;
- la liste des **données disponibles**, pour retrouver et insérer un nom (`carte.image`, `donnees["carte"]["image"]`).

**Leçons techniques :**
- l'**ICP seul se trompe quand le robot tourne beaucoup entre deux scans** ; une recherche grossière de l'angle (±20° autour de l'odométrie, degré par degré) avant l'ICP règle le problème ;
- en rotation, le robot à quatre roues fixes **dérape** : la voie effective (0,55 m) vaut plus du double de la voie géométrique (0,25 m) ; en réel, elle s'étalonne (dix tours sur place) ;
- le recalage scan sur scan **dérive lentement** : dans une salle carrée et vide, les murs finissent par se dédoubler. La correction est connue (recalage sur la carte déjà construite, puis fermeture de boucle) ; laissée de côté pour l'instant ;
- la boucle robot doit tourner **toujours dans le même fil** (contexte OpenGL de la caméra simulée, verrouillé par son fil sous macOS) ;
- un affichage (Scope) ne doit jamais arrêter le programme : une expression fautive s'affiche dans sa fenêtre.

**Points d'attention :**
- les modèles entraînés ne sont pas dans le dépôt (`robots/*/modeles/*/` est ignoré) : sur une autre machine, la politique d'errance de `test_mobile` et `mobile_camera` est à réentraîner ou à copier ;
- un seul graphe par robot (`robots/<robot>/flows/flow.json`) : le SLAM a été fait sur `test_mobile` pour ne pas effacer le cache-cache de `mobile_camera` ;
- rien n'est encore essayé sur le robot réel.

Suite proposée le 21/10/2026 pour MIR Flow :
1. **un démonstrateur qui justifie l'approche** : un robot qui rapporte un objet (navigation RL + saisie ACT + consignes) ou un jeu à règles (« 1-2-3 soleil ») ;
2. **un essai sur le robot réel** (caméra en réseau, lidar ESP32, détection d'une vraie personne ; le SLAM tel quel) ;
3. *(SLAM)* recalage sur la carte et fermeture de boucle, si une application en a besoin ; plusieurs graphes par robot, si le besoin se confirme ;
4. **horodater les données du flux** (âge d'une mesure ; les Mesures donnent déjà leur instant) ;
5. **les sous-flux** (regrouper « chercher la balle » en un nœud réutilisable) ;
6. plus tard : priorités entre interruptions, actions parallèles sur des actionneurs différents, fréquence propre à chaque capteur dans la boucle robot (utile pour une politique rapide avec caméra) ;
7. idée pédagogique : faire le même jeu en RL de bout en bout et avec MIR Flow, et comparer.

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
- **Interface compétence** : forme exacte (méthode `select_action` de LeRobot ou équivalent ; comment une compétence signale sa fin et sa réussite). MIR Flow utilise pour l'instant la `Commande` de MIR (fin par `terminer()`, durée, « Arrêter quand ») ; une compétence ne rend pas encore compte de sa réussite.
- **Quatre façons d'écrire du code** : onglet Scripts, nœud Script Python, mini script d'une action, Commande. À unifier, ou au moins à expliquer (qui sert à quoi).
- **MIR Flow et l'échelle** : un vrai jeu fera 30 à 50 nœuds ; sous-flux et priorités entre interruptions à concevoir.
- **MIR Flow : comportements asynchrones et discrets** (discussion du 21/10/2026). La séparation chaîne principale séquentielle / chaînes en continu est la séparation classique « flux de contrôle pour la tâche, flux de données pour la perception » (architectures en couches, Nav2). Différence avec un arbre de comportement : la chaîne principale n'est pas réévaluée en permanence, elle n'est réactive que par « Arrêter quand » et les interruptions. Ce qui manque, au regard des statecharts (Harel : événements en file, régions parallèles, hiérarchie) et des arbres de comportement (Parallèle, décorateurs) :

  | Besoin | Exemple | État au 21/10 |
  |---|---|---|
  | Perception lente à côté | VLM, détection lourde | couvert (chaîne en continu) |
  | Événement qui dure | personne visible, obstacle proche | couvert (Interruption, « Arrêter quand ») |
  | Événement bref | clap, bouton, ordre vocal, balle qui touche | peut être manqué : rien ne retient un événement passé |
  | Décision lente pendant que le robot agit | le LLM réfléchit pendant l'errance | non : un nœud LLM bloque la chaîne principale |
  | Actions simultanées | la base cherche, la tourelle vise | non |
  | Délai sur une phase entière | « abandonner au bout de 2 min » | non : seule une action a une durée ; pas d'horloge dans les données |
  | Modes du jeu | attente → recherche → fin → recommencer | faisable, mais vite confus |

  Ajouts proposés, sans changer de modèle (ordre à choisir) :
  1. **Événements retenus** : un événement bref est noté dans les données avec son heure et reste en attente jusqu'à ce qu'une Interruption ou une Condition le traite ; une **horloge** (`temps`) et l'**âge** de chaque mesure dans les données.
  2. **Nœud « En parallèle »**, rejoint par « attendre toutes les branches » ou « la première qui finit arrête les autres » : actions simultanées et décisions asynchrones ; refus de deux branches qui commandent les mêmes actionneurs.
  3. **Sous-flux** : un nœud qui contient un graphe (« phase de recherche »), avec son délai maximal et ses interruptions ; c'est la hiérarchie des statecharts, pour écrire les modes d'un jeu.
  4. **Délai maximal et nouvelle tentative** sur une action ou un sous-flux (« essayer 3 fois », « abandonner au bout de 2 min »).
- **Coude 90°** : orientation de la douille déduite du STL pour qu'une caméra regarde vers l'extérieur ; à vérifier sur la pièce réelle.
- **Humains en simulation** : le détecteur ne reconnaît pas des formes simples ; il faudrait des maillages texturés réalistes dans les scènes (pas encore pris en charge).
- **Modules capteurs** : déploiement de la caméra sur Raspberry Pi à simplifier comme celui des ESP32 (carte SD à préparer, nom `pi2` écrit en dur dans `deploy.py`, `rsync` absent sous Windows) ; Wi-Fi des établissements (découverte UDP souvent bloquée : un routeur dédié à MIR ?) ; garder l'ancien réseau en secours aussi en Bluetooth (modification du firmware, à voir avec son auteur) ; capteur IMU à ajouter au firmware.
- **Inférence distante** : politique lourde sur une autre machine, avec quelle latence acceptable.
- **Données** : où stocker les datasets (dossier du robot, d'une expérience, Hub Hugging Face).
- **RL** : forme de l'environnement gymnasium construit à partir de la description.
- **Expérience** : structure exacte du dossier.
