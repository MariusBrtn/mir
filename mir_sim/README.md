# mir_sim — simulation MuJoCo des robots MIR

## Principe

```
catalog/<type>.json   un fichier par module MIR (servo, socle, jonction, pince, caméra...)
STL/*.stl             les maillages exportés de la CAO
```

Un robot est décrit **dans sa configuration** (le même fichier JSON que pour le robot réel), par une section
`structure` : quels modules du catalogue, branchés sur quels connecteurs. Le modèle de simulation en est
déduit : aucune mesure à saisir, la géométrie vient des connecteurs des modules.

`mirRobot` reçoit une `SimDevicesFactory` au lieu de la fabrique par défaut : les scripts
existants (téléop, ACT...) tournent sans modification, avec la même config JSON que le vrai robot.

```python
from mir_sim.sim_devices_factory import SimDevicesFactory
robot = mirRobot(config, devices_factory=SimDevicesFactory(scene="scene_de.json"))
```

- `python -m mir_sim.view_robot config.json [--scene scene.json]` : viewer 3D interactif du robot
- `teleoperation_sim.py` (dans `mir_user_scripts/bras_leader_follower_cam/`) : leader réel -> bras simulé, ou `--sliders`
- `SimWorld.step(n)` : avance la physique sans temps réel (pour le RL)

## Structure d'un robot (section `structure` de la config)

```json
"structure": {
    "modules": {
        "socle":   {"type": "mir_socle", "fixed": true},
        "servo_1": {"type": "mir_servo", "on": "socle.dessus", "connector": "rotor", "motor": "joint_1", "direction": -1},
        "servo_2": {"type": "mir_servo", "on": "servo_1.stator", "connector": "rotor", "motor": "joint_2"},
        "camera":  {"type": "mir_camera", "on": "pince.camera", "connector": "embout", "sensors": {"objectif": "cam_1"}}
    }
}
```

| champ | rôle |
|---|---|
| `type` | module du catalogue (nom du fichier dans `catalog/`) |
| `fixed` | sur le module racine (celui sans `on`) : `true` = c'est le bâti, fixé au monde ; sinon le robot est libre (robot mobile) |
| `on` | `"<module>.<connecteur>"` sur lequel ce module est branché |
| `connector` | connecteur de ce module utilisé pour ce branchement |
| `motor` | moteur de la config qui entraîne l'articulation du module (`"motors": {articulation: moteur}` s'il en a plusieurs) ; sans moteur, les pièces sont solidaires |
| `direction` | `-1` si le moteur réel tourne dans l'autre sens que la simu |
| `zero_offset_deg` | angle simu correspondant au 0° du moteur réel (= milieu de la plage calibrée) |
| `sensors` | `{capteur du module: capteur de la config}`, ex. `{"objectif": "cam_1"}` |

Les modules détectés mais pas encore branchés sont rangés dans `"unplaced"` (même format, sans `on` ni
`connector`) : la découverte du matériel y met un module par moteur (servo ou pince, choisi à la découverte) et
par caméra, et l'éditeur de structure les y prend pour les placer. Ils ne sont pas construits en simulation.

Un module peut être branché par n'importe lequel de ses connecteurs : un servo branché par son **rotor** a son
**stator** mobile (le sens du moteur est conservé). Un mâle ne se branche que sur une femelle ; la structure est
vérifiée (genres, connecteurs déjà pris, moteurs et capteurs présents dans la config) avant la construction.

Les plages articulaires viennent de la calibration de la config robot (0° = milieu de `range_min..range_max`,
comme dans lerobot), le couple max de `torque_limit`, la vitesse de `position_mode_velocity`.

**Réglage de `direction` / `zero_offset_deg`** : téléopère le robot simulé et compare avec le robot réel,
articulation par articulation.

## Scène (propre à une tâche, facultative)

Fichier JSON à côté des scripts de la tâche (ex. `scene_de.json`) : position du robot sur la table
(`robot`: `pos`, `euler_deg`), `table`, caméras fixes (`cameras`) et objets (`objects`).

## Module du catalogue (`catalog/<type>.json`)

Tout est exprimé dans le repère de la CAO du module (en mm avec `"unit_scale": 0.001`), articulations à zéro.

| champ | rôle |
|---|---|
| `parts` | pièces rigides `{nom: {"mass", "geoms"}}` (ex. `stator`, `rotor`) |
| `joints` | articulations `{nom: {"parent", "child", "pos", "axis"}}` entre deux pièces |
| `connectors` | baïonnettes `{nom: {"part", "gender": "male"/"female", "pos", "zaxis", "xaxis"}}` : z sort du module, détrompeur côté -x |
| `sensors` | capteurs `{nom: {"type": "camera", "part", "pos", "zaxis", "xaxis", "fovy"}}` (la caméra regarde selon -z, haut de l'image selon +y) |
| `contact_pairs` | paires de géométries nommées du module qui doivent pouvoir se toucher (ex. mors d'une pince) |

Géométries : un STL `"visual_only": true` pour l'affichage, des formes simples `"collision_only": true` pour les
contacts (l'enveloppe convexe d'un STL concave est trop grossière). `"stiff_contact": true` sur une surface de
préhension (contact raide, sinon un objet léger s'enfonce dans les mors). Pour colorer une zone d'un STL à part
(ex. bague de douille beige) : `"select": {"axis": [1, 0, 0], "max": -30.05}` ne garde que la partie dont la
projection sur `axis` (unités du STL) est entre `min` et `max`, les triangles sont coupés sur le plan.

Ajouter un module = ajouter un fichier dans `catalog/` (et ses STL) : les robots existants ne sont pas touchés.
