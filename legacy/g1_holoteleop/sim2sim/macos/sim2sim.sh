## VR --------------------------------------------------------
# sim2sim

#1. teleop bridge

conda activate gmr
cd /Users/velix/Workspace/Projects/Tools/HoloTeleop/sim2real/teleop
bash teleop_pose_50hz.sh

#2. sim2sim simulator

cd /Users/velix/Workspace/Projects/Tools/HoloTeleop/sim2sim
uv run mjpython run_sim2sim.py \
  --xml_path assets/g1/g1.xml \
  --show-reference-ghost

#3. deploy.py controller

cd /Users/velix/Workspace/Projects/Tools/HoloTeleop/sim2sim
uv run run_deploy.py \
    --sim2sim \
    --net lo0 \
    --enable-dex3-hands \
    --dex3-teleop-hands \
    --policy-path \
    assets/ckpts/G1TRACKING-06-04_13-20/policy.onnx

## motion --------------------------------------------------------

cd /Users/velix/Workspace/Projects/Tools/HoloTeleop/sim2sim
uv run mjpython run_sim2sim.py --xml_path assets/g1/g1.xml --show-reference-ghost

cd /Users/velix/Workspace/Projects/Tools/HoloTeleop/sim2sim
uv run run_deploy.py \
  --sim2sim \
  --net lo0 \
  --motion-source udp \
  --policy-path \
  assets/ckpts/G1TRACKING-06-07_11-15/policy.onnx

cd /Users/velix/Workspace/Projects/Tools/HoloTeleop/sim2sim
uv run run_motion_select.py

## select motion --------------------------------------------------------

cd /Users/velix/Workspace/Projects/Tools/HoloTeleop/sim2sim
uv run mjpython run_sim2sim.py --xml_path assets/g1/g1.xml --show-reference-ghost

cd /Users/velix/Workspace/Projects/Tools/HoloTeleop/sim2sim
uv run run_deploy.py \
  --sim2sim \
  --net lo0 \
  --motion-source udp \
  --policy-path \
  assets/ckpts/G1TRACKING-03-16_14-15_0315.2/policy.onnx


cd /Users/velix/Workspace/Projects/Tools/HoloTeleop/sim2sim
uv run run_motion_select.py \
  /Users/velix/Workspace/Projects/Tools/HoloTeleop/sim2real/assets/data/corl/A_person_notices_a_small_bag_on_the_ground_beside_their_left_foot/gen_fsq_0019_A_person_notices_a_small_bag_on_the_ground_beside_their_left_foot.npz
