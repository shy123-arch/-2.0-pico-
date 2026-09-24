# 天轶 2.0 PICO 遥操作

这是从现有宇树 G1 工程中独立出来的天轶 2.0 遥操作代码树。它保留了已经验证过的
PICO/XRoboToolkit 输入方式，但不再使用 Unitree SDK、G1 29 自由度关节表、G1
tracking policy 或 GMR 的 `unitree_g1` 目标模型。

当前版本完成了：

- PICO 双手、头显、按钮和摇杆的版本化 UDP 传输；
- 右手 A 启动/重新标定、左手 X 暂停、左手 X+Y 软件急停；
- 相对锚点映射，避免启动瞬间跳变；
- 基于天轶 URDF 的可选 Pinocchio 双臂 IK；
- 关节限位、速度限幅、单周期步长限幅、PICO/反馈双看门狗；
- 对 X-Humanoid `ros2_bridge_msgs/ArmCtrl` 和 `RobotState` 的适配层；
- 底盘摇杆和夹爪通道（默认关闭，待真机确认话题）；
- dry-run、模拟 PICO 输入、配置校验和机器人状态检查工具。
- 一键式 Linux/ROS 2 本地仿真启动，以及 RViz 双臂目标可视化。

## 重要状态

公开的 X-Humanoid 示例确认了天工 3.0 的 `/arm/cmd`、`/robot_state` 和
`ros2_bridge_msgs` 消息格式，但没有公开证明天轶 2.0 使用完全相同的电机编号、
URDF、末端帧或底盘/夹爪话题。因此模板默认：

```yaml
dry_run: true
hardware_verified: false
```

在模板仍有 `CHANGE_ME` 或 `motor_id: -1` 时，代码会拒绝进入硬件输出模式。
这不是报错绕不过去，而是防止把天工或 G1 的编号误发给天轶。

## 数据链路

```text
PICO + XRoboToolkit App
  -> XRoboToolkit PC Service / Python callback
  -> pico_streamer (PC, UDP latest-state)
  -> robot_node (Tianyi ROS 2 computer)
     -> anchor calibration
     -> URDF dual-arm IK
     -> joint/velocity/watchdog safety gates
     -> ros2_bridge_msgs/ArmCtrl -> /arm/cmd
```

## 1. PC 侧准备

沿用原 G1 工程中已经安装好的 XRoboToolkit PC Service 和修订版
`xrobotoolkit_sdk`。安装本包后启动：

```bash
python -m pip install -e .
pico_streamer --help
```

用模拟输入先检查网络：

```bash
pico_streamer --host <TIANYI_IP> --port 28810 --mock
```

接入真实 PICO：

```bash
pico_streamer --host <TIANYI_IP> --port 28810
```

PICO 和机器人必须在同一可达网络。不要把 PICO App 的 PC Service 地址填成机器人
地址；PICO App 仍连接运行 XRoboToolkit PC Service 的电脑。

## 2. Linux 本地仿真

推荐在 Ubuntu 24.04 + ROS 2 Jazzy 环境中先跑本地仿真。安装 ROS 2 后，确认具备
`colcon`、`rviz2`、`geometry_msgs`、`visualization_msgs`：

```bash
mkdir -p ~/tianyi2_ws/src
cd ~/tianyi2_ws/src
git clone https://github.com/shy123-arch/-2.0-pico-.git tianyi2-pico-teleop
cd ~/tianyi2_ws
rosdep install --from-paths src/tianyi2-pico-teleop/tianyi2_pico_teleop \
  --ignore-src -r -y
colcon build --symlink-install --packages-select tianyi2_pico_teleop
source install/setup.bash
ros2 launch tianyi2_pico_teleop local_sim.launch.py
```

RViz 会显示一个明确标注为 `SCHEMATIC` 的轮式躯干、两条示意机械臂，以及模拟
PICO 控制器驱动的左右末端目标。启动约一秒后，模拟器会自动产生一次右手 A 键
上升沿完成锚点标定，此后两个末端目标应连续运动。

无图形界面的 Linux 主机可关闭 RViz，只验证节点与话题：

```bash
ros2 launch tianyi2_pico_teleop local_sim.launch.py rviz:=false
ros2 topic echo /tianyi2_teleop/left_target
```

也可以执行仓库中的 `scripts/run_local_sim.sh`。这套仿真用于验证
PICO/UDP/状态机/锚点映射/ROS 话题链路；由于没有经过厂家确认的天轶 2.0 URDF，
它不包含精确关节 IK、碰撞、重力或执行器动力学。取得真机 URDF 后，再接入
Gazebo/Isaac Sim 或厂家仿真环境。

## 3. 机器人侧编译

以下命令假定天轶环境也提供 X-Humanoid `xos` 工作空间；必须先在真机上确认：

```bash
source ~/xos/setup.bash
cd ~/xos/src
git clone https://github.com/shy123-arch/-2.0-pico-.git tianyi2-pico-teleop
cd ~/xos
colcon build --packages-select tianyi2_pico_teleop
source install/setup.bash
```

复制模板并只修改副本：

```bash
cp src/tianyi2-pico-teleop/tianyi2_pico_teleop/config/tianyi2.template.yaml \
   ~/tianyi2_pico.yaml
```

先运行配置检查和 dry-run：

```bash
validate_config ~/tianyi2_pico.yaml
robot_node --config ~/tianyi2_pico.yaml
```

dry-run 会发布以下目标，便于用 RViz 或 `ros2 topic echo` 检查坐标方向：

- `/tianyi2_teleop/left_target`
- `/tianyi2_teleop/right_target`

## 4. 补齐天轶硬件契约

严格执行 [`docs/HARDWARE_CHECKLIST.md`](docs/HARDWARE_CHECKLIST.md)：

1. 确认 `/arm/cmd` 与 `/robot_state` 在天轶上真实存在且消息类型一致；
2. 用 `inspect_robot_state` 记录双臂 14 个真实电机 ID；
3. 从机器人本机取得匹配当前固件的 URDF；
4. 填入 URDF 关节名、左右末端 frame、厂家关节限位；
5. 吊架/急停/安全员到位后，才设置 `hardware_verified: true` 和 `dry_run: false`。

## 操作按键

| PICO 输入 | 行为 |
|---|---|
| 右手 A | 捕获当前手柄与机器人末端锚点，开始或重新开始 |
| 左手 X | 暂停并保持当前位置，底盘速度清零 |
| 左手 X + Y | 软件急停锁存；必须在机器人侧调用 reset 服务 |
| 左/右 grip | 对应夹爪 0..1 指令，仅在配置启用后发布 |
| 左摇杆 | 底盘前后/横移，仅在配置启用后发布 |
| 右摇杆左右 | 底盘旋转，仅在配置启用后发布 |

软件急停不能替代机器人实体急停按钮。

## 本地测试

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

已知边界和当前证据见 [`docs/INTEGRATION_STATUS.md`](docs/INTEGRATION_STATUS.md)。
