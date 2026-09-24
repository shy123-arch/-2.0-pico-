# 控制方式：
# 右手 B：开始录制
# 左手 Y：停止并保存
# 键盘 r：开始录制
# 键盘 p：停止并保存
# 键盘 q：保存并退出

conda activate gmr
cd /home/velix/project/HoloTeleop/sim2real/teleop
PICO_RECORD_OUTPUT_DIR=/home/velix/project/HoloTeleop/data/pico_records bash teleop_pose_50hz.sh


# MuJoCo 播放脚本
cd /home/velix/project/HoloTeleop/sim2real
source $HOME/.local/bin/env

# raw + GMR 一起播放，默认找最新的一对
uv run teleop/replay_pico_gmr_mujoco.py --mode both --index -5 --loop

# 只看 raw PICO 骨架
uv run teleop/replay_pico_gmr_mujoco.py --mode raw --loop

# 只看 GMR/MT 机器人动作
uv run teleop/replay_pico_gmr_mujoco.py --mode gmr --loop


# 转成训练 raw motion npz
# 输入：/home/velix/project/HoloTeleop/data/gmr_records/gmr_mt_*.npz
# 输出：/home/velix/project/HoloTeleop/data/training_raw/teleop_*.npz
cd /home/velix/project/HoloTeleop/sim2real
.venv/bin/python ../training/scripts/data_process/convert_teleop_gmr_to_motion_npz.py --overwrite


# 转成训练实际读取的 memmap dataset
# 输出：/home/velix/project/HoloTeleop/training/dataset/real_vr
cd /home/velix/project/HoloTeleop/training
UV_CACHE_DIR=/tmp/uv-cache uv run python scripts/data_process/generate_dataset.py \
  --dataset-root ../data/training_raw \
  --mem-path dataset/real_vr


# VLA session 录制数据转普通 MT npz
# 输入目录格式：
#   session_xxx/
#     video.h264 或 video.h265
#     video_timestamps.csv
#     reference.npz
#     state.npz
#     action.npz
#     metadata.yaml
# 输出：
#   session_xxx/reference_motion.npz  # tracker 实际输入的参考动作
#   session_xxx/state_motion.npz      # 真机实际状态转成的动作
cd /home/velix/project/HoloTeleop/sim2real
source $HOME/.local/bin/env
SESSION_DIR=/home/velix/Downloads/session_20260524_170607
uv run src/session_to_motion_npz.py "$SESSION_DIR" --source both


# VLA session 逐帧播放，不跑 tracker，不跑 sim2sim 物理仿真
cd /home/velix/project/HoloTeleop/sim2real
source $HOME/.local/bin/env
SESSION_DIR=/home/velix/Downloads/session_20260524_170607

# 播放 tracker 实际输入的参考动作
uv run python teleop/replay_pico_gmr_mujoco.py \
  --mode gmr \
  --gmr-record "$SESSION_DIR/reference_motion.npz" \
  --loop

# 播放真机实际状态
uv run python teleop/replay_pico_gmr_mujoco.py \
  --mode gmr \
  --gmr-record "$SESSION_DIR/state_motion.npz" \
  --loop
