# 低姿态 Motion Tracking 访谈问题答复

本文根据现有代码、Git 历史、训练配置和部署脚本整理。核心算法、最终模型链路和部署配置可以从仓库确认；个人贡献归属、部分设计动机、最终 PICO 安装包以及实机视频对应关系仍需相关负责人补充确认。

## 一、低姿态优化核心算法

### 1. 低姿态具体修改

最终比赛模型相对原始 tracker 主要进行了以下修改：

- 数据集调整为 `bones-seed/amass_new/pico_vr = 0.8/0.1/0.1`。其中 `pico_vr` 包含团队针对比赛采集的弯腰、下蹲、下跪和低位伸手等遥操动作。
- 增加 `head + left hand + right hand` 三点局部跟踪 reward。
- 增加 `feet_acc`，并将 `action_rate_l2` 提高到 `0.1`，用于抑制足端和动作输出抖动。
- 对 foot air-time reward 增加根据参考高度变化的低姿态 gating。
- 关闭原来的 `body_z_termination` 和 `gravity_dir_termination`，改用 pelvis、手脚末端、足端 XYZ 和 root 姿态误差终止。
- 使用平滑后的 reference root height，在低姿态阶段放宽 termination threshold。
- 最终版本没有增加 root-xy 或低姿态 phase observation；`target_root_z` 是原框架已有观测。

最终冻结配置位于：

`training/outputs/2026-06-06/05-12-33-G1TRACKING-ppo/.hydra/config.yaml`

Git 历史只能看到统一提交账号，无法据此确认具体个人负责人。

### 2. Sparse local tracking 与 SONIC 的关系

参考对象是 NVIDIA GEAR-SONIC：

- 代码：https://github.com/NVlabs/GR00T-WholeBodyControl
- 论文：https://arxiv.org/abs/2511.07820

与 SONIC 一致的总体思路包括：

- 在机器人局部坐标系中计算 sparse body-point tracking。
- 使用 pelvis、手腕、脚踝等关键点描述局部人体目标。
- 根据参考 root height 调整低姿态 termination。
- 使用 anchor、end-effector、foot 和 orientation tracking error 判断 episode 是否失败。

主要区别包括：

- 我们是在现有 motion-tracking 框架中重新实现和适配，并非直接复用 SONIC reward 代码。
- SONIC 的稀疏点定义偏向 `torso/wrist/ankle`；最终比赛模型使用实际的 `head_mimic + hand_mimic` 三点。
- 我们增加了 reference-height-dependent foot air-time gating。
- SONIC 还使用 `motion_time_out` 等机制，我们没有完整照搬其 termination 系统。

因此，论文中更准确的表述是“参考并适配 SONIC 的 sparse local tracking 与 tracking-error termination”，不应写成完全复现或完全原创。

### 3. 最终 sparse tracking 配置

最终比赛版本使用三点局部跟踪：

```yaml
local_3point_patterns:
  - head_mimic
  - left_hand_mimic
  - right_hand_mimic

tracking_vr_3point_local:
  weight: 0.5
  std: 0.12
```

最终模型为 `G1TRACKING-06-07_11-15`，不是五点或两点版本。

### 4. Reference-height-dependent termination

最终启用的 termination 包括：

- `anchor_z_tracking_termination`
- `ee_z_tracking_termination`
- `foot_xyz_tracking_termination`
- `root_rot_tracking_termination`

对应参数为：

- Reference height EMA：`alpha = 0.05`
- 低姿态判断高度：`0.5 m`
- 正常姿态 anchor/EE z threshold：`0.15 m`
- 低姿态 anchor/EE z threshold：`0.75 m`
- Foot XYZ threshold：`0.2 m`
- Root rotation threshold：`0.2`

该机制的作用不是直接奖励机器人下跪，而是避免下跪和起身过程中因短时跟踪误差过早 reset，使策略能够经历并学习完整的低姿态动作。由于该设计与 SONIC 高度接近，应归类为团队完成的框架适配，不宜独立声称为原创算法。

### 5. Foot reward gating

最终调制以下两个 reward：

- `feet_air_time_ref`
- `feet_air_time_ref_dense`

调制公式为：

$$
g(h)=s_{\min}+(1-s_{\min})
\operatorname{clip}\left(\frac{h-h_l}{h_h-h_l},0,1\right)
$$

$$
r_{\mathrm{gated}}=g(h)r_{\mathrm{airtime}}
$$

最终参数为：

- `gate_low = 0.55 m`
- `gate_high = 0.72 m`
- `low_scale = 0.2`

参考高度低于 `0.55 m` 时保留 20% air-time reward；高于 `0.72 m` 时恢复完整权重；中间区域线性插值。设计目的是兼顾正常行走和下跪：行走时继续学习合理的抬脚节奏，低姿态时减少 air-time reward 引起的不必要小脚步。

当前本地 SONIC 代码中没有发现相同 gating，但是否可以定义为团队原创，仍需负责人确认并进行更完整的相关工作检索。

### 6. 其他低姿态优化

有意增加或调整的低姿态设计包括：

- 三点 head/hand local tracking。
- Adaptive anchor/EE termination。
- Foot air-time height gating。
- `feet_acc` 和更强的 action smoothness。
- 比赛针对性的低姿态遥操数据。

原始 tracking framework 已有的内容包括：

- Root、joint 和 keypoint pose/velocity tracking。
- `target_root_z` observation。
- 基础 air-time、joint-limit 和 action-rate reward。
- Teacher/student 训练框架。

## 二、实验和论文验证

### 7. 原始 tracker 的低姿态失败

现有实机观察包括：

- 下跪和地面拾取困难。
- 手和头无法降低到足够低的位置。
- 下跪后起身容易突然前冲。
- 小范围移动容易产生碎步和频繁位置修正。
- 单纯 body-height termination 容易提前结束低姿态动作。

仓库中存在 checkpoint 和离线评估结果，但没有完整整理“失败视频、模型、配置和实机日志”的对应关系。论文使用这些结论前，需要补充比赛录像或实机测试记录。

### 8. Baseline 对比

现有版本可以组成近似对比：

| 版本 | 主要特征 |
|---|---|
| `03-16` | 原始 tracker 基线 |
| `05-22` | 无 sparse local reward，使用较早的 termination |
| `05-23` | 五点 sparse tracking 和 adaptive termination |
| `05-28` | 三点 head+hands |
| `06-07` | 三点、adaptive termination 和 foot gating 的最终版本 |

这些版本的训练时长、数据和模型容量并非完全相同，只适合作为开发版本对比，不能直接视为严格消融实验。

### 9. Ablation

已有近似消融版本：

- `05-27`：关闭 local tracking 和 air-time。
- `05-28`：三点 local tracking，无 air-time gating。
- `05-31`：只跟踪双手。
- `06-01`：三点 tracking，低姿态完全关闭 air-time。
- `06-02/06-07`：三点 tracking，低姿态保留 20% air-time。

可以使用这些版本做初步分析。论文中的严格消融应统一数据、随机种子、模型容量、训练帧数和评估动作后重新训练。

### 10. 低姿态评估指标

建议使用：

- 低姿态动作完成率和 fall rate。
- Pelvis/root height MAE 和最低可达高度。
- Head/hand local-frame MPJPE。
- 站立到下跪再到站立的完整过渡成功率。
- Foot skate、contact switch 和 reposition distance。
- 起身阶段的 root 前冲距离。
- 地面物品拾取成功率。
- 实机多次重复成功率。

## 三、最终模型和版本

### 11. 最终比赛模型链路

```text
W&B run:
track_medium_long_finetune_0604.1

Checkpoint:
training/outputs/2026-06-06/05-12-33-G1TRACKING-ppo/
wandb/run-20260606_051339-track_medium_long_finetune_0604.1/
files/checkpoint_final.pt

ONNX export:
sim2real/assets/ckpts/G1TRACKING-06-07_11-15/policy.onnx

Deployment launcher:
scripts/real_vr.sh
```

最终模型为单一 `policy` 输入，观测维度为 `1590`。

### 12. Root-xy 是否进入最终结果

Root-xy 没有进入最终比赛模型。

`G1_tracking_rootxy.yaml` 是单独实验路径，会把 `target_pos_b_obs` 加入 policy，使输入维度变为 `1623`。最终 `G1TRACKING-06-07_11-15` 模型输入为 `1590`，因此：

- 最终训练没有使用 root-xy observation。
- 最终部署没有使用 root-xy policy。
- 比赛模型没有使用 root-xy。
- 不建议写入论文主方法，可以作为未采用的探索实验。

## 四、系统和比赛证据

### 13. 最终实机证据

目前能够从仓库确认最终 checkpoint 和 launcher，但尚未完整归档：

- 每场比赛对应的模型版本。
- 最终机器人 session log。
- 模型与比赛视频时间戳的对应关系。
- 每个 run 的详细遥测数据。

已知比赛结果是 20 分钟内完成 4 个 run：前三个 run 均完成全部 9 件物品；第四个 run 在机器人温度升高、控制卡顿后完成 7 件物品。视频和裁判记录仍需负责人补充归档。

### 14. 安全机制

当前 `real_vr.sh` 关闭了：

- q-error limiter。
- 机器人端温度语音警告。

代码中没有记录关闭原因，需要现场负责人确认。可能与低姿态大关节偏差导致误触发有关，但目前只能作为推测，不能作为正式结论。

仍然启用的保护包括：

- VR 数据超时检测和 action hold。
- 通信自动重连。
- 非法 observation/action 检查。
- Action clipping。
- 停止后的 damping。
- PICO 温度和状态遥测。
- 手动暂停、停止和远程关闭。

### 15. PICO / Dex3 配置

PICO 4 Ultra：

- 使用头部、左右控制器和身体 tracking。
- PICO 运行 XRoboToolkit 客户端。
- PC 运行 XRoboToolkit 接收端和 GMR。
- 视频使用 H.264/TCP 无线传输。
- 最终 APK 和 build hash 没有在仓库中明确记录，需要现场确认。

Dex3-1：

- 最终 launcher 启用 `--enable-dex3-hands --dex3-teleop-hands`。
- Trigger/grip 被映射为手指开合程度。
- 控制命令通过 Unitree DDS 发布到左右 Dex3 hand。

### 16. 系统贡献归属

| 模块 | 建议归属 |
|---|---|
| Motion-tracking、PPO、teacher/student | 上游训练基础 |
| SONIC sparse tracking 思路 | 参考方法 |
| 三点配置与低姿态 reward 组合 | 团队设计与适配 |
| Adaptive termination | 参考 SONIC 后的框架适配 |
| Foot air-time height gating | 团队实现，原创性待确认 |
| 低姿态及比赛遥操数据 | 团队采集与整理 |
| GMR retargeting 算法 | 上游基础 |
| GMR 与 PICO/机器人桥接 | 团队工程适配 |
| XRoboToolkit 基础功能 | 上游基础 |
| PICO 状态、视频和 fail-safe 改动 | 团队工程开发 |
| ONNX 导出与部署集成 | 团队工程开发 |
| Unitree DDS 接口 | Unitree 上游接口 |
| Dex3 映射、部署和控制逻辑 | 团队工程开发 |

由于相关 Git 提交主要使用统一账号，目前无法从提交记录确认具体个人负责人。个人贡献归属、关闭安全功能的原因、最终 PICO build 和实机视频对应关系，仍需相关负责人补充确认。
