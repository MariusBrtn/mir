# MIR 

Modular Intelligent Robot

> **MIR** is an open-source modular robotics platform for education, research and experimentation.


<p align="center">
  <a href="https://youtube.com/shorts/KHZeTSOmVA4">
    <img src="./assets/screen_video.png" width="300" alt="Watch the MIR introduction">
  </a>
</p>

<p align="center">
  <em>Build robots in just a few clicks.</em>
</p>

Designed around interchangeable hardware modules, MIR makes it possible to build different robots while sharing a common hardware and software architecture. 
The platform is compatible with the LeRobot ecosystem for robot learning, while remaining suitable for more traditional robotics applications such as kinematics, control, teleoperation, perception and navigation.

<p align="center">
  <img src="assets/module.png" width="350">
</p>

## Examples
The same hardware modules can be used to build different robotic systems, including :

- Robot arms
- Mobile platform with Lidar
- Quadruped

## Why a modular platform ?

Traditional educational robots are often designed for a single purpose. MIR follows a different approach : the same hardware modules can be reused to build different robotic systems. This allows students, teachers and researchers to explore a wide range of robotics topics without redesigning the platform.

<p align="center">
  <img src="assets/configs.png" width="600">
</p>


## Project status

This repository documents the development of MIR from its first functional prototype.


## Software

The MIR application lets you build a robot from its modules, simulate it (MuJoCo), drive it, record demonstrations,
and train models (behavior cloning, LeRobot policies such as ACT, reinforcement learning with Stable-Baselines3),
on the real robot or in simulation.

| Folder | Content |
|---|---|
| `mir_robot_editor/` | the MIR application (user interface) |
| `mir_robot/` | `mirRobot`, the single entry point to the robot (real or simulated), training and policies |
| `mir_sim/` | module catalog, MuJoCo model of the robot, simulated devices |
| `mir_devices/` | drivers for the real hardware (Feetech servo bus, cameras, ESP32, lidar) |
| `robots/` | example robots: configuration, scenes, scripts, training scripts |
| `doc/` | documentation (architecture, installation, hardware) |
| `cad/`, `assets/` | 3D models (STL) and pictures of the modules |

### Installation

MIR uses [uv](https://docs.astral.sh/uv/) (Python 3.12 and exact package versions are installed automatically):

```bash
git clone https://github.com/MariusBrtn/mir.git
cd mir
uv sync          # creates the .venv environment
uv run mir       # starts MIR
uv run pytest    # runs the tests (simulation only, no hardware needed)
```

More details in [`doc/`](doc/) (in French).

## Authors

MIR is designed and developed by **Marius Bertin** and **Michel Bertin**.

## Citation

This project uses [LeRobot](https://github.com/huggingface/lerobot) by Hugging Face. If you use this project, please cite:

```bibtex
@misc{cadene2024lerobot,
    author = {Cadene, Remi and Alibert, Simon and Soare, Alexander and Gallouedec, Quentin and Zouitine, Adil and Palma, Steven and Kooijmans, Pepijn and Aractingi, Michel and Shukor, Mustafa and Aubakirova, Dana and Russi, Martino and Capuano, Francesco and Pascal, Caroline and Choghari, Jade and Moss, Jess and Wolf, Thomas},
    title = {LeRobot: State-of-the-art Machine Learning for Real-World Robotics in Pytorch},
    howpublished = "\url{https://github.com/huggingface/lerobot}",
    year = {2024}
}
```

## License

MIR is released under the Apache License 2.0.

This project is intended to encourage learning, research and collaboration. Commercial use is permitted under the terms of the Apache 2.0 License.

See the [LICENSE](LICENSE) file for details.

New hardware modules, documentation and software will be added progressively.

