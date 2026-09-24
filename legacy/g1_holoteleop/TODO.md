# GroundTrack 三组实验 TODO

本 TODO 只负责完成三张实验表格：

1. General Motion Tracking 主实验表；
2. Dedicated Low-Posture 专项实验表；
3. GroundTrack Ablation 消融实验表。

固定评估数据：

```text
Manifest:
benchmarks/g1_tracking/benchmark_manifest_v1.json

Manifest SHA-256:
22a770dbe8f881e5f37e1001934b727f116f790f54350742fa9e2c22692e3c1e

General Set:       1024 motions
Low-Posture Set:   1024 independent motions
Evaluation seed:   0
Trials per motion: 1
```

baseline 路径和当前状态见：

```text
baselines/README.md
```

---

## 1. 总执行顺序

### 立即执行

1. [ ] 释放训练需要的 GPU 0--7，启动第一个消融模型的八卡三阶段训练。
2. [ ] 与消融训练并行，按 `baselines/README.md` 依次完成五个 baseline 的
   Gate A native 复现和 reference/execution 可视化。
3. [ ] 只有 Gate A 通过后才实现该方法的统一 adapter。
4. [ ] adapter 完成后，使用 General 前 4 条和 Low-Posture 前 4 条完成
   Gate B 统一闭环可视化。
5. [ ] 只有 Gate A 和 Gate B 都通过的 baseline，才可在 GPU 7 上运行正式
   General 和 Low-Posture evaluator。

### 每个消融模型训练完成后

1. [ ] 找到 finetune `checkpoint_final.pt`。
2. [ ] 导出 `policy.pt` 和 `policy.onnx`。
3. [ ] 如果还有下一个 variant，先启动下一个八卡训练。
4. [ ] 在下一组训练稳定后，用 GPU 7 跑刚导出模型的 General Set。
5. [ ] General 完成后继续跑 Low-Posture Set。
6. [ ] 将两个结果填入消融表。

### 四个消融完成后

1. [ ] 补齐尚未通过 Gate A/Gate B 的 TWIST2、Any2Track、MOSAIC、SONIC、
   Humanoid-GPT；不能跳过可视化直接评估。
2. [ ] 每个已通过两级门槛的 baseline 分别跑 General 和 Low-Posture。
3. [ ] 填完 General 主表。
4. [ ] 填完 Low-Posture 专项表。
5. [ ] 检查三张表不存在缺失值后结束实验。

八卡训练会使用 GPU 0--7，但 evaluator 显存占用较小，可以共享 GPU 7
并行运行。固定一次只启动一个 evaluator，General 完成后再运行
Low-Posture。

baseline 复现是主实验和专项实验的硬门槛，但不阻塞彼此独立的消融训练；
因此八卡消融训练与 baseline native 复现可以同时推进。

并行流水线：

| 八卡训练任务 | 同时进行的评估任务 |
|---|---|
| 第 1 个消融 | Baseline Gate A native 复现与可视化；GroundTrack 结果复核 |
| 第 2 个消融 | 第 1 个消融的 General/Low；Baseline Gate A/Gate B |
| 第 3 个消融 | 第 2 个消融的 General/Low；已验收 baseline 的正式评估 |
| 第 4 个消融 | 第 3 个消融的 General/Low；继续 baseline 正式评估 |
| 四个训练完成 | 第 4 个消融的 General/Low；补齐剩余结果 |

训练过程中评估的规则：

- [ ] 开始八卡训练前先停止 GPU 7 上的 `gpu_hog.py`；
- [ ] 等八卡训练稳定后，再在 GPU 7 启动 evaluator；
- [ ] 同一时间只运行一个 General 或 Low-Posture evaluator；
- [ ] 若显存逼近上限或训练出现 OOM，先停止 evaluator，保留训练；
- [ ] evaluator 结束后确认训练的 8 个 rank 仍然正常。

---

## 2. GPU 占卡和释放

### 2.1 查看 GPU

```bash
nvidia-smi \
  --query-gpu=index,memory.used,memory.total,utilization.gpu \
  --format=csv,noheader

nvidia-smi \
  --query-compute-apps=pid,gpu_uuid,used_memory \
  --format=csv,noheader
```

只停止自己启动的进程。遇到无法确认归属的 PID，不直接 kill。

### 2.2 安全占卡

`/root/gpu_hog.py` 会产生 multiprocessing worker。使用独立 process
group，并保存 leader PID：

```bash
export HOG_GPU_LIST=7
export HOG_NAME=gpu7
export HOG_PID_FILE="/tmp/${USER}_gpu_hog_${HOG_NAME}.pid"
export HOG_LOG="/tmp/${USER}_gpu_hog_${HOG_NAME}.log"

if [ -s "$HOG_PID_FILE" ] && kill -0 "$(cat "$HOG_PID_FILE")" 2>/dev/null; then
  echo "gpu_hog already running: PID $(cat "$HOG_PID_FILE")"
else
  setsid /usr/bin/python3 /root/gpu_hog.py \
    --gpus "$HOG_GPU_LIST" \
    --target-ratio 0.55 \
    --max-steps 0 \
    >"$HOG_LOG" 2>&1 < /dev/null &
  echo "$!" > "$HOG_PID_FILE"
  echo "started gpu_hog: PID $(cat "$HOG_PID_FILE")"
fi
```

约 5 秒后检查：

```bash
sleep 5
nvidia-smi \
  --query-gpu=index,memory.used,memory.total,utilization.gpu \
  --format=csv,noheader
```

需要占多张已分配的 GPU 时，将 `HOG_GPU_LIST` 写成逗号分隔形式，例如
`6,7`。

### 2.3 安全停止占卡

```bash
export HOG_NAME=gpu7
export HOG_PID_FILE="/tmp/${USER}_gpu_hog_${HOG_NAME}.pid"

if [ ! -s "$HOG_PID_FILE" ]; then
  echo "missing PID file: $HOG_PID_FILE"
else
  HOG_PID="$(cat "$HOG_PID_FILE")"
  HOG_PGID="$(ps -o pgid= -p "$HOG_PID" 2>/dev/null | tr -d ' ')"

  if [ -z "$HOG_PGID" ]; then
    echo "gpu_hog is not running"
  elif [ "$HOG_PGID" != "$HOG_PID" ]; then
    echo "refuse to kill unexpected process group"
    echo "PID=$HOG_PID PGID=$HOG_PGID"
    exit 1
  else
    kill -TERM -- "-$HOG_PGID" 2>/dev/null || true

    for _ in 1 2 3 4 5; do
      kill -0 -- "-$HOG_PGID" 2>/dev/null || break
      sleep 1
    done

    if kill -0 -- "-$HOG_PGID" 2>/dev/null; then
      kill -KILL -- "-$HOG_PGID"
    fi
  fi

  rm -f "$HOG_PID_FILE"
fi
```

验证占卡进程和显存已经释放：

```bash
ps -eo pid,ppid,pgid,sid,stat,cmd |
  grep -E 'gpu_hog.py|multiprocessing.spawn|spawn_main' |
  grep -v grep || true

nvidia-smi \
  --query-gpu=index,memory.used,memory.total,utilization.gpu \
  --format=csv,noheader
```

不要使用下面的全局清理命令：

```text
pkill -9 -f gpu_hog.py
ps aux | grep multiprocessing | ... | kill -9
/root/gpu_hog.py --kill
```

这些命令可能误杀节点上其他用户或其他训练任务的 multiprocessing
worker。若旧占卡任务外层还有 `while true` 自动重启 wrapper，必须先通过
`ps -eo pid,ppid,pgid,sid,cmd` 确认准确 process group，再停止整个 wrapper
process group；只杀 Python 子进程会被重新拉起。

### 2.4 切换到八卡训练

```bash
export CUDA_VISIBLE_DEVICES=0,1,2,3,4,5,6,7
export NPROC=8
```

启动训练前确认：

- [ ] 自己的 GPU hog 已全部停止；
- [ ] GPU 0--7 显存满足训练要求；
- [ ] GPU 0--7 没有其他用户的计算任务；
- [ ] `CUDA_VISIBLE_DEVICES` 为 `0,1,2,3,4,5,6,7`；
- [ ] `NPROC=8`。

---

## 3. 消融实验：先开始八卡训练

### 3.0 Full 对照模型的原始训练指令

消融对比的 Full 模型固定为：

```text
sim2real/assets/ckpts/G1TRACKING-06-07_11-15
```

`policy.json` 指向：

```text
training/outputs/2026-06-06/05-12-33-G1TRACKING-ppo/
wandb/run-20260606_051339-track_medium_long_finetune_0604.1/
files/checkpoint_final.pt
```

W&B metadata 和各阶段 `cfg.yaml` 保存了原始训练链：

```bash
# TRAIN: 8 × A800, 8192 envs, seed 0
torchrun --nproc_per_node=8 scripts/train.py \
  task=G1/G1_tracking \
  +exp=train \
  total_frames=20000_000_000 \
  wandb.id=track_medium_long_train_0604.1

# ADAPT
torchrun --nproc_per_node=8 scripts/train.py \
  task=G1/G1_tracking \
  +exp=adapt \
  total_frames=5000_000_000 \
  checkpoint_path=/mnt/data/cpfs/Jensen/project/teleop/HoloTeleop/training/outputs/2026-06-04/18-33-57-G1TRACKING-ppo/wandb/run-20260604_183455-track_medium_long_train_0604.1/files/checkpoint_final.pt \
  wandb.id=track_medium_long_adapt_0604.1

# FINETUNE
torchrun --nproc_per_node=8 scripts/train.py \
  task=G1/G1_tracking \
  +exp=finetune \
  total_frames=20000_000_000 \
  checkpoint_path=/mnt/data/cpfs/Jensen/project/teleop/HoloTeleop/training/outputs/2026-06-06/00-57-25-G1TRACKING-ppo/wandb/run-20260606_005832-track_medium_long_adapt_0604.1/files/checkpoint_final.pt \
  wandb.id=track_medium_long_finetune_0604.1
```

Full 原始配置确认：

```text
num_envs = 8192
seed = 0
bones/amass/pico = 0.8/0.1/0.1
tracking_vr_3point_local.weight = 0.5
body/anchor/EE adaptive termination = true
feet_air_time_ref.ref_height_gate = true
feet_air_time_ref_dense.ref_height_gate = true
```

Full checkpoint SHA-256：

```text
train:
bea97e8bf7a9be07e3a123905fa2bb20320627a6abc8b7e07e5b90dce401c777

adapt:
69b46c5e2139cdfcfd7bc96c91050f7600fd64fcae3b99b3b1a56069f6e

finetune:
9a7aeef455582fcfa780c20116dff515e8b298cb6c3ff51dcad0a8181d2074f9
```

因此四个消融严格复用这套 20B/5B/20B 八卡训练流程，只增加各自唯一的
Hydra override。

### 3.1 需要重新训练的模型

Full 使用当前最终模型，不需要先重复训练。下面四个模型分别从 train 阶段
重新开始，全部使用 8 卡：

| 顺序 | Variant | 唯一训练修改 | 状态 |
|---:|---|---|---|
| 1 | w/o task-specific low-posture data | `bones/amass/pico = 0.9/0.1/0.0` | [ ] 未训练 |
| 2 | w/o head--hand tracking | `tracking_vr_3point_local.weight=0.0` | [ ] 未训练 |
| 3 | w/o adaptive termination | body/anchor/EE adaptive flags 均为 false | [ ] 未训练 |
| 4 | w/o height-aware foot gating | 两个 foot reward 的 `ref_height_gate=false` | [ ] 未训练 |

统一设置：

```text
Training seed: 0
GPUs:          8
train:         20B frames
adapt:          5B frames
finetune:      20B frames
```

四个 variant 除表中的唯一修改外，网络、数据、训练 seed、三阶段预算和其余
配置都保持一致。

### 3.2 每个 variant 的 Hydra overrides

```text
wo_low_pose_data:
  task.command.dataset.path_weights=[0.9,0.1,0.0]

wo_head_hand:
  task.reward.tracking.tracking_vr_3point_local.weight=0.0

wo_adaptive_termination:
  task.command.body_z_terminate_adaptive=false
  task.command.anchor_z_terminate_adaptive=false
  task.command.ee_z_terminate_adaptive=false

wo_foot_gating:
  task.reward.loco.feet_air_time_ref.ref_height_gate=false
  task.reward.loco.feet_air_time_ref_dense.ref_height_gate=false
```

override 必须在 train、adapt、finetune 三个阶段重复传入。

### 3.3 八卡三阶段训练模板

可执行 wrapper 已写好：

```text
training/run_ablation_long.sh
```

四组配置已经通过真实 `scripts/train.py --cfg job` 入口验证。依次运行：

```bash
cd /mnt/data/cpfs/Jensen/project/teleop/HoloTeleop

bash training/run_ablation_long.sh wo_low_pose_data 0
bash training/run_ablation_long.sh wo_head_hand 0
bash training/run_ablation_long.sh wo_adaptive_termination 0
bash training/run_ablation_long.sh wo_foot_gating 0
```

一次只启动一个。wrapper 会自动串行完成 train、adapt、finetune，查找上一
阶段 checkpoint，并保存 checkpoint 路径和 SHA-256。

下面保留手动训练模板用于排查问题。将 `VARIANT_ID` 和
`VARIANT_OVERRIDES` 替换成上一节的对应值。

```bash
cd /mnt/data/cpfs/Jensen/project/teleop/HoloTeleop/training

export MEMPATH=/mnt/data/cpfs/Jensen/project/teleop/dataset
export CUDA_VISIBLE_DEVICES=0,1,2,3,4,5,6,7
export NPROC=8
export TRAIN_SEED=0
export VARIANT_ID=wo_low_pose_data

# 下面的 VARIANT_OVERRIDES 是文档占位符，运行时替换成实际 Hydra 参数。

uv run torchrun --nproc_per_node="$NPROC" scripts/train.py \
  task=G1/G1_tracking +exp=train \
  seed="$TRAIN_SEED" \
  total_frames=20000_000_000 \
  wandb.id="ablation_${VARIANT_ID}_seed${TRAIN_SEED}_train" \
  VARIANT_OVERRIDES

export TRAIN_CKPT=/absolute/path/to/train/checkpoint_final.pt

uv run torchrun --nproc_per_node="$NPROC" scripts/train.py \
  task=G1/G1_tracking +exp=adapt \
  seed="$TRAIN_SEED" \
  total_frames=5000_000_000 \
  checkpoint_path="$TRAIN_CKPT" \
  wandb.id="ablation_${VARIANT_ID}_seed${TRAIN_SEED}_adapt" \
  VARIANT_OVERRIDES

export ADAPT_CKPT=/absolute/path/to/adapt/checkpoint_final.pt

uv run torchrun --nproc_per_node="$NPROC" scripts/train.py \
  task=G1/G1_tracking +exp=finetune \
  seed="$TRAIN_SEED" \
  total_frames=20000_000_000 \
  checkpoint_path="$ADAPT_CKPT" \
  wandb.id="ablation_${VARIANT_ID}_seed${TRAIN_SEED}_finetune" \
  VARIANT_OVERRIDES
```

建议为每个 variant 写一个独立 shell wrapper，把三阶段串起来并用 `nohup`
启动。必须记录 wrapper PID、日志、三个阶段的 checkpoint 路径和最终退出码。

训练状态：

| Variant | Train | Adapt | Finetune | Export | General Eval | Low Eval |
|---|---|---|---|---|---|---|
| w/o task-specific low-posture data | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| w/o head--hand tracking | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| w/o adaptive termination | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| w/o height-aware foot gating | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |

### 3.4 训练完成后导出

```bash
cd /mnt/data/cpfs/Jensen/project/teleop/HoloTeleop/training

export VARIANT_ID=wo_low_pose_data
export FINAL_CKPT=/absolute/path/to/finetune/checkpoint_final.pt
export EXPORT_DIR=/mnt/data/cpfs/Jensen/project/teleop/HoloTeleop/output/paper_experiments/ablation/${VARIANT_ID}/seed_0/export

uv run scripts/export_deploy.py \
  checkpoint_path="$FINAL_CKPT" \
  task=G1/G1_tracking \
  export_dir="$EXPORT_DIR"

sha256sum "$FINAL_CKPT" "$EXPORT_DIR/policy.pt" "$EXPORT_DIR/policy.onnx"
```

### 3.5 消融评估

每个导出策略必须使用统一的 Full evaluation task。不要使用消融 checkpoint
mode 恢复其 training-time termination。

正确：

```text
--task G1/G1_tracking --onnx_policy /path/to/policy.pt
```

不要用于正式消融对比：

```text
--checkpoint /path/to/ablation/checkpoint_final.pt
```

General：

```bash
cd /mnt/data/cpfs/Jensen/project/teleop/HoloTeleop/training

export VARIANT_ID=wo_low_pose_data
export POLICY_PT=/absolute/path/to/export/policy.pt
export OUTPUT_JSON=../output/paper_experiments/ablation/${VARIANT_ID}/seed_0/general.json

mkdir -p "$(dirname "$OUTPUT_JSON")"

CUDA_VISIBLE_DEVICES=0 \
MPLCONFIGDIR=/tmp/matplotlib \
.venv/bin/python scripts/eval_metrics.py \
  --task G1/G1_tracking \
  --onnx_policy "$POLICY_PT" \
  --metric_profile general \
  --benchmark_manifest ../benchmarks/g1_tracking/benchmark_manifest_v1.json \
  --benchmark_split general \
  --max_steps 1000 \
  --seed 0 \
  --output_json "$OUTPUT_JSON"
```

Low-Posture：

```bash
cd /mnt/data/cpfs/Jensen/project/teleop/HoloTeleop/training

export VARIANT_ID=wo_low_pose_data
export POLICY_PT=/absolute/path/to/export/policy.pt
export OUTPUT_JSON=../output/paper_experiments/ablation/${VARIANT_ID}/seed_0/low_posture.json

mkdir -p "$(dirname "$OUTPUT_JSON")"

CUDA_VISIBLE_DEVICES=0 \
MPLCONFIGDIR=/tmp/matplotlib \
.venv/bin/python scripts/eval_metrics.py \
  --task G1/G1_tracking \
  --onnx_policy "$POLICY_PT" \
  --metric_profile low_posture \
  --benchmark_manifest ../benchmarks/g1_tracking/benchmark_manifest_v1.json \
  --benchmark_split low_posture \
  --low_root_height_threshold 0.5 \
  --pose_position_threshold 0.05 \
  --pose_angle_threshold_deg 15 \
  --max_steps 1000 \
  --seed 0 \
  --output_json "$OUTPUT_JSON"
```

每个结果必须满足：

- [ ] `num_episodes == 1024`；
- [ ] split 正确；
- [ ] manifest SHA-256 正确；
- [ ] 未使用 `--benchmark_limit`；
- [ ] 没有 NaN/Inf。

### 3.6 消融表

| Variant | General Succ. | General Foot Skate | Low Succ. | Root-Z MAE | Head Pose Acc. | Hand Pose Acc. |
|---|---:|---:|---:|---:|---:|---:|
| w/o task-specific low-posture data | -- | -- | -- | -- | -- | -- |
| w/o head--hand tracking | -- | -- | -- | -- | -- | -- |
| w/o adaptive termination | -- | -- | -- | -- | -- | -- |
| w/o height-aware foot gating | -- | -- | -- | -- | -- | -- |
| GroundTrack Full | 90.63 | 82.29 | 83.89 | 64.31 | 76.53 | 58.23 |

完成条件：

- [ ] 四个消融模型均完成八卡 train/adapt/finetune；
- [ ] 四个模型均导出；
- [ ] 四个模型均完成两套 1024-motion 评估；
- [ ] 消融表所有 `--` 均被结果替换。

---

## 4. General Motion Tracking 主实验

### 4.1 方法

| Method | 路径/模型 | Native 可视化 | Adapter 可视化 | General Eval |
|---|---|---|---|---|
| TWIST2 | `baselines/TWIST2/assets/ckpts/twist2_1017_20k.onnx` | [ ] | [ ] | [ ] |
| Any2Track | `baselines/OpenTrack`，缺正式 generalist v2 checkpoint | [ ] | [ ] | [ ] |
| MOSAIC | `baselines/MOSAIC`，缺正式 GMT checkpoint | [ ] | [ ] | [ ] |
| SONIC | `/mnt/data/cpfs/Jensen/project/teleop/third_party/GR00T-WholeBodyControl`，release 权重/LFS 数据未落全 | [ ] | [ ] | [ ] |
| Humanoid-GPT | `/mnt/data/cpfs/Jensen/project/teleop/Humanoid-GPT/storage/ckpts/pns_wo_priv216.onnx` | [ ] | [ ] | [ ] |
| GroundTrack | `G1TRACKING-06-07_11-15/policy.pt` | N/A | [x] | [x] |

### 4.2 每个 baseline 的固定步骤

1. [ ] 记录 repository commit 和 dirty 状态。
2. [ ] 确认论文对应 checkpoint，排除 Git LFS pointer，并记录 SHA-256。
3. [ ] 在原仓库用官方 example motion 跑 native closed-loop inference。
4. [ ] 保存同步 reference/executed-robot 视频并按
   `baselines/README.md` 完成 Gate A 人工验收。
5. [ ] Gate A 通过后实现 observation/history adapter，并输出统一 G1 29D
   joint-position target。
6. [ ] 用 General 前 4 条 motion 和 Low-Posture 前 4 条 motion 录制统一
   closed-loop 视频，完成 Gate B。
7. [ ] Gate B 通过后跑 General 1024 条。
8. [ ] 保存 JSON、日志、命令和可视化验收 metadata。

baseline native evaluator 的结果不填入本表；必须使用固定 manifest 和统一
runner/evaluator。reference-only replay、策略静止站立或只成功加载 checkpoint
均不算复现成功。

### 4.3 General 结果检查

```bash
jq '{
  profile: .metric_profile,
  episodes: .num_episodes,
  split: .benchmark.split,
  motion_count: .benchmark.motion_count,
  manifest: .benchmark.manifest_sha256,
  success: .success_rate,
  mpjpe: .mpjpe_mm_mean,
  mpjve: .mpjve_mm_frame_mean,
  root_drift: .root_drift_xy_mean_m,
  foot_skate: .foot_skate_mm_s_mean,
  joint_violation: .joint_violation_rate
}' /path/to/general.json
```

### 4.4 General 主表

| Method | Succ. | MPJPE | MPJVE | Root Drift | Foot Skate | Joint Viol. |
|---|---:|---:|---:|---:|---:|---:|
| TWIST2 | -- | -- | -- | -- | -- | -- |
| Any2Track | -- | -- | -- | -- | -- | -- |
| MOSAIC | -- | -- | -- | -- | -- | -- |
| SONIC | -- | -- | -- | -- | -- | -- |
| Humanoid-GPT | -- | -- | -- | -- | -- | -- |
| GroundTrack | 90.63 | 24.36 | 4.85 | 0.409 | 82.29 | 0.228 |

完成条件：

- [ ] 五个 baseline 均通过 native reference/execution 可视化；
- [ ] 五个 baseline 均通过统一 adapter 的 General/Low 可视化；
- [ ] 五个 baseline 均使用统一 runner 完成1024条 General 评估；
- [ ] 六个方法的结果文件都通过 manifest/episode 检查；
- [ ] 主表所有 `--` 均被结果替换。

---

## 5. Dedicated Low-Posture 专项实验

Low-Posture 使用独立的固定 1024-motion split，不从 General 运行结果中临时
筛选。

### 5.1 每个 baseline 的固定步骤

1. [ ] 使用与 General 完全相同的 checkpoint 和 adapter revision。
2. [ ] 用 Low-Posture 前 4 条 motion 做 closed-loop smoke test。
3. [ ] 跑 Low-Posture 1024 条。
4. [ ] 保存 JSON 和日志。
5. [ ] 检查 `num_metric_episodes` 和 `num_low_frames`。

### 5.2 Low-Posture 结果检查

```bash
jq '{
  profile: .metric_profile,
  episodes: .num_episodes,
  metric_episodes: .num_metric_episodes,
  low_frames: .num_low_frames,
  split: .benchmark.split,
  motion_count: .benchmark.motion_count,
  manifest: .benchmark.manifest_sha256,
  success: .lp_success_rate,
  mpjpe: .mpjpe_mm_mean,
  mpjve: .mpjve_mm_frame_mean,
  root_z: .root_z_mae_mm_mean,
  head: .head_pose_accuracy,
  hand: .hand_pose_accuracy
}' /path/to/low_posture.json
```

### 5.3 Low-Posture 专项表

| Method | Succ. | MPJPE | MPJVE | Root-Z MAE | Head Pose Acc. | Hand Pose Acc. |
|---|---:|---:|---:|---:|---:|---:|
| TWIST2 | -- | -- | -- | -- | -- | -- |
| Any2Track | -- | -- | -- | -- | -- | -- |
| MOSAIC | -- | -- | -- | -- | -- | -- |
| SONIC | -- | -- | -- | -- | -- | -- |
| Humanoid-GPT | -- | -- | -- | -- | -- | -- |
| GroundTrack | 83.89 | 48.83 | 6.39 | 64.31 | 76.53 | 58.23 |

完成条件：

- [ ] 五个 baseline 均完成1024条 Low-Posture 评估；
- [ ] 每个方法使用与 General 相同的 checkpoint/adapter；
- [ ] 六个方法的结果文件都通过 manifest/episode 检查；
- [ ] 专项表所有 `--` 均被结果替换。

---

## 6. 最终完成检查

### 消融表

- [ ] 四个消融模型完成八卡重新训练。
- [ ] 四个消融模型完成 General 和 Low-Posture 评估。
- [ ] 5 行 × 6 个指标全部有值。

### General 主表

- [ ] GroundTrack + 五个 baseline 全部完成。
- [ ] 6 行 × 6 个指标全部有值。

### Low-Posture 专项表

- [ ] GroundTrack + 五个 baseline 全部完成。
- [ ] 6 行 × 6 个指标全部有值。

三张表全部填满后，本 TODO 完成。
