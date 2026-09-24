## VR --------------------------------------------------------
# sim2sim

#1. teleop bridge

conda activate gmr
cd /home/velix/project/HoloTeleop/sim2real/teleop
bash teleop_pose_50hz.sh

#2. sim2sim 仿真器

cd /home/velix/project/HoloTeleop/sim2real
source $HOME/.local/bin/env
uv run src/sim2sim.py \
  --xml_path assets/g1/g1.xml \
  --show-reference-ghost

#3. deploy.py 控制器

cd /home/velix/project/HoloTeleop/sim2real
source $HOME/.local/bin/env
uv run src/deploy.py \
    --net lo \
    --sim2sim \
    --enable-dex3-hands \
    --dex3-teleop-hands \
    --policy-path \
    assets/ckpts/G1TRACKING-06-04_13-20/policy.onnx

## motion --------------------------------------------------------

cd /home/velix/project/HoloTeleop/sim2real
source $HOME/.local/bin/env
uv run src/sim2sim.py --xml_path assets/g1/g1.xml --show-reference-ghost

cd /home/velix/project/HoloTeleop/sim2real
source $HOME/.local/bin/env
uv run src/deploy.py \
  --net lo \
  --sim2sim \
  --policy-path \
  assets/ckpts/G1TRACKING-03-16_14-15_0315.2/policy.onnx

cd /home/velix/project/HoloTeleop/sim2real
source $HOME/.local/bin/env
uv run src/motion_select.py

## select motion --------------------------------------------------------

cd /home/velix/project/HoloTeleop/sim2real
source $HOME/.local/bin/env
uv run src/sim2sim.py --xml_path assets/g1/g1.xml --show-reference-ghost

cd /home/velix/project/HoloTeleop/sim2real
source $HOME/.local/bin/env
uv run src/deploy.py \
  --net lo \
  --sim2sim \
  --motion-source udp \
  --policy-path \
  assets/ckpts/G1TRACKING-03-16_14-15_0315.2/policy.onnx


cd /home/velix/project/HoloTeleop/sim2real
source $HOME/.local/bin/env
uv run src/motion_select.py \
  /home/velix/project/HoloTeleop/sim2real/assets/data/corl/A_person_notices_a_small_bag_on_the_ground_beside_their_left_foot/gen_fsq_0019_A_person_notices_a_small_bag_on_the_ground_beside_their_left_foot.npz