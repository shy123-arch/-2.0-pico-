# 天轶 2.0 PICO 遥操作

本仓库包含两棵彼此独立的代码树：

- [`legacy/g1_holoteleop`](legacy/g1_holoteleop)：之前的宇树 G1 + PICO/GMR
  源码基线，仅用于追溯和对比；首个提交已标记 `g1-original-baseline`。
- [`tianyi2_pico_teleop`](tianyi2_pico_teleop)：新建的天轶 2.0 + PICO ROS 2
  遥操作实现，不依赖 Unitree SDK 或 G1 tracking policy。

请从[天轶使用说明](tianyi2_pico_teleop/README.md)开始。原版快照的内容和排除项见
[`BASELINE_G1.md`](BASELINE_G1.md)。

当前天轶代码已经具备 PICO 数据链路、锚点标定、URDF 双臂 IK、安全状态机、
X-Humanoid ROS 2 消息适配，以及可一键启动的本地 RViz 运动链路仿真；但天轶本体的电机 ID、URDF、底盘与
夹爪话题必须在真机上核对后才能解除硬件锁。

在 Ubuntu/ROS 2 环境中构建后，可直接运行：

```bash
ros2 launch tianyi2_pico_teleop local_sim.launch.py
```

该仿真使用模拟 PICO 数据和示意双臂模型验证完整通信、标定与目标映射链路，不是
天轶 2.0 的精确运动学或动力学模型。
