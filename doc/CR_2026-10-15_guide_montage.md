# CR du 15/10/2026 : guide de montage, servos non détectés

## En bref

**Cause très probable : un défaut du guide de montage (logiciel), pas du matériel.**
Pendant le montage, le guide met chaque servo détecté « de côté » sur un ID réservé (200, 201…). Quand on quitte le
guide avant la fin, seuls les servos **entièrement terminés** (calibrés et sens validé) reprennent leur ID
définitif. Un servo **détecté mais pas terminé reste sur 200 ou 201**. Au guide suivant, un autre servo reçoit à son
tour l'ID 200 : en branchant le premier, on a **deux servos à l'ID 200**. Ils répondent ensemble, leurs réponses se
mélangent et **tout le bus devient muet** tant que les deux sont branchés. C'est ce que montre le journal.

À ne pas faire en attendant la correction : relancer le guide de montage sur les servos de ce soir.

## Ce que montre le journal (`logs/mir.log`, lignes « guide de montage »)

| Heure | Événement |
|---|---|
| 21:51:49 | servo (ID 2) détecté → mis à **200** ; guide quitté avant la fin → **reste à 200** |
| 21:58:10 | autre servo (ID 2) détecté → mis à **200** aussi |
| 21:58:35 | deuxième module branché : le bus ne répond plus du tout (`[]`), même le servo à 200 |
| 22:03:28 | (robot `bras_follower_cam`) un servo répond à 200 |
| 22:06–22:10 | ancienne carte (`…5B3D0492331`) : **aucun servo ne répond**, sur aucun ID ni aucune vitesse, même avec un seul module et un servo neuf → **non expliqué**, voir ci-dessous |
| 22:15:59 | nouvelle carte (`…5B141123301`) : servo **ID 21** détecté (un servo du **bras leader**) → mis à 200 |
| 22:16:43 | servo ID 3 détecté → mis à **200** ; guide quitté → **reste à 200** |
| 22:17:22 | servo ID 4 détecté → mis à **201** ; deux servos à 200 et 201 : **la détection fonctionne** |
| 22:23:43 | nouveau guide : le servo laissé à **201** est pris → mis à **200** |
| 22:24:39 | branchement du servo resté à 200 depuis 22:16 → deux servos à 200 → bus muet (`[]`) ; il revient quand on retire le module |
| 22:30:39 | un autre servo (ID 5) branché à la place → détecté normalement (→ 201) |

À l'oral : « je débranche le deuxième module → le premier réapparaît ». La carte n'est donc pas grillée, et c'est
cohérent avec un doublon d'ID.

## État probable des servos (à vérifier demain)

- Un ou plusieurs servos sont restés sur **200** ou **201** (IDs réservés du guide).
- Le servo du bras leader qui avait l'**ID 21** a été changé par le guide : **la config `bras_leader` ne correspond
  plus** tant qu'il n'a pas retrouvé l'ID 21.
- Les servos du follower ont peut-être aussi changé d'ID (anciens ID 2, 3, 4, 5 vus dans le journal).

## À faire demain, dans l'ordre

1. **Inventaire, sans rien écrire** : application fermée, **un seul module à la fois** sur le socle :
   ```
   cd mir/mir_user_scripts/demos
   python diagnostic_bus_servos.py /dev/cu.usbmodem5B141123301
   ```
   Noter l'ID de chaque servo (module par module).
2. **Ancienne carte** (`/dev/cu.usbmodem5B3D0492331`) : la retester avec un seul servo dont on connaît l'ID, avec
   `--tous-baudrates`. Si rien ne répond, vérifier l'alimentation et la carte. C'est le seul point que le doublon
   d'ID n'explique pas.
3. **Corriger le guide** (Claude) avant de le réutiliser :
   - remettre à son ID définitif (ou à son ID d'origine) **tout servo mis de côté**, même si son module n'est pas
     terminé, quand on quitte le guide ;
   - au démarrage du guide, **chercher les servos restés sur un ID réservé** (200 à 253) et les signaler ou les
     remettre en ordre ;
   - garder dans le journal l'**ID d'origine** de chaque servo, pour pouvoir revenir en arrière.
4. **Remettre les servos à leur ID** : petit outil, à écrire, pour un module seul sur le socle (écrire l'ID voulu, puis
   le vérifier avec le diagnostic). En priorité, le servo du leader → ID 21.
5. Reprendre le montage de `bras_4ddl_cam` avec le guide corrigé.

## Ce qui a été changé ce soir dans le code

- Recherche des servos **un ID à la fois** (le ping général de LeRobot ne marche pas avec plusieurs servos : leurs
  réponses se mélangent) : `mir_robot_editor/assemblage/bus.py`.
- Recherche en arrière-plan, verrou sur le port série.
- IDs « mis de côté » pendant le montage (200 + rang du moteur), ID définitifs à la fin : c'est ce mécanisme qui a
  le défaut décrit plus haut.
- Script de diagnostic en lecture seule : `mir_user_scripts/demos/diagnostic_bus_servos.py`.

## Hypothèses écartées ou affaiblies

- **Branchement sous tension** : tu as déjà branché et débranché des modules sous tension sans problème ; et la carte
  revient dès qu'on retire le deuxième module. Écartée comme cause principale.
- **Carte USB grillée** : écartée pour la nouvelle carte. Ouverte pour l'ancienne (point 2).
