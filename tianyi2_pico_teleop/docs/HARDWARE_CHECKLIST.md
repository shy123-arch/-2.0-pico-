# 天轶 2.0 真机接入检查表

在任何一项未知时保持 `dry_run: true`。

## A. ROS 2 与消息契约

在机器人本机执行：

```bash
source ~/xos/setup.bash
ros2 topic list | sort
ros2 topic type /arm/cmd
ros2 topic type /robot_state
ros2 interface show ros2_bridge_msgs/msg/ArmCtrl
ros2 interface show ros2_bridge_msgs/msg/MotorCtrl
ros2 interface show ros2_bridge_msgs/msg/RobotState
```

预期只是候选值：`/arm/cmd`、`/robot_state`、`ros2_bridge_msgs/msg/ArmCtrl`。
如果天轶输出不同，以真机结果为准并修改适配层，不能强行复用天工接口。

## B. 双臂电机 ID

机器人静止、控制程序未接管时运行：

```bash
inspect_robot_state --topic /robot_state
```

记录所有手臂电机 ID。一次只由厂家允许的调试方式轻微移动一个关节，建立
`URDF joint name -> motor ID` 对照。不要使用天工示例中的 21 号关节推断天轶编号。

## C. URDF 与关节限制

- 从机器人本机或厂家交付包取得与当前硬件版本一致的 URDF；
- 确认左右各 7 个关节在 URDF 中均为单自由度关节；
- 确认左右夹爪末端 frame；
- 把厂家给出的软限位收紧后写入 YAML，不要用模板里的 `-1..1`；
- 运行 `validate_config <yaml> --hardware`，必须通过。

## D. 空载 dry-run

```bash
robot_node --config ~/tianyi2_pico.yaml
ros2 topic echo /tianyi2_teleop/left_target
ros2 topic echo /tianyi2_teleop/right_target
```

检查手柄向前、向上、向外移动时两个 target 的方向；检查旋转方向和左右手没有互换。

## E. 首次硬件输出

- 机器人使用厂家认可的支撑/吊架；
- 实体急停按钮可立即触达；
- 一人操作 PICO，一人独立看护急停；
- 关闭底盘和夹爪：`base.enabled: false`、`grippers.enabled: false`；
- 把每关节 `max_velocity_rad_s` 和 `global_max_step_rad` 设为保守值；
- 先只启用一侧手臂（可暂时在配置和代码中限制），再启用双臂；
- 右手 A 标定后只做厘米级缓慢动作；
- 验证左手 X、数据断流、ROS 反馈断流都会进入 HOLD；
- 最后才逐步开放工作空间和速度。

## F. 仍需厂家确认

- 天轶 2.0 是否与天工 3.0 共用 `ros2_bridge_msgs`；
- 位置模式是否允许 50 Hz 连续目标更新；
- `cur` 字段对当前电机驱动的单位和安全范围；
- 底盘速度话题、坐标正方向和最大速度；
- 已安装夹爪/灵巧手的控制消息；
- 是否需要先调用控制权、模式切换或使能服务。

