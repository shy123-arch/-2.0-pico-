import os
import sys

import sys
import time
import argparse
import yaml
import struct
import threading
import signal
from pathlib import Path
from multiprocessing import Value

import numpy as np
import mujoco
import mujoco.viewer
from pathlib import Path

from sshkeyboard import listen_keyboard, stop_listening
from unitree_sdk2py.core.channel import ChannelPublisher, ChannelSubscriber, ChannelFactoryInitialize
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_ as LowStateHG
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowCmd_ as LowCmdHG
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import HandCmd_ as HandCmdHG
from unitree_sdk2py.idl.unitree_go.msg.dds_ import SportModeState_
from unitree_sdk2py.idl.default import unitree_go_msg_dds__SportModeState_
from unitree_sdk2py.idl.default import unitree_hg_msg_dds__LowCmd_, unitree_hg_msg_dds__LowState_
from unitree_sdk2py.utils.crc import CRC

from common.utils import DictToClass, RuntimeReferenceUDPServer, Timer
from common.remote_controller import KeyMap
from common.joint_mapper import create_real_to_mujoco_mapper
from common.dex3_hand import DEFAULT_KD as DEX3_DEFAULT_KD
from common.dex3_hand import DEFAULT_KP as DEX3_DEFAULT_KP
from common.dex3_hand import get_hand_pose

from paths import ASSETS_DIR, to_assets_path

np.set_printoptions(formatter={'float': lambda x: "{0:0.2f}".format(x)})

Keyboard2Joystick = {
    'a': 'A',
    's': 'start',
    'x': 'select',
    'u': 'up',
    'd': 'down'
}


class Sim2sim:
    def __init__(self, args, config):
        self.args = args
        self.config = config

        self.pub_freq = 200
        self.pub_dt = 1. / self.pub_freq
        self.low_level_freq = 500
        self.low_level_dt = 1. / self.low_level_freq

        # Initialize model and data
        # Resolve XML path (absolute or under assets)
        xml_candidate = Path(args.xml_path)
        if not xml_candidate.is_absolute():
            # try relative to ASSETS_DIR
            under_assets = ASSETS_DIR / xml_candidate
            model_path = os.path.abspath(str(under_assets if under_assets.exists() else xml_candidate))
        else:
            model_path = str(xml_candidate)
        self.model = mujoco.MjModel.from_xml_path(model_path)
        self.model.opt.timestep = self.low_level_dt
        self.data = mujoco.MjData(self.model)

        self.ctrl_lower = self.model.actuator_ctrlrange[:, 0]
        self.ctrl_upper = self.model.actuator_ctrlrange[:, 1]
        self.mujoco_joint_qpos_adrs = self._joint_qpos_adrs(self.config.mujoco_joint_names)
        self.mujoco_joint_qvel_adrs = self._joint_qvel_adrs(self.config.mujoco_joint_names)
        self.mujoco_actuator_ids = self._actuator_ids_for_joints(self.config.mujoco_joint_names)
        self.ctrl_lower_real = self.ctrl_lower[self.mujoco_actuator_ids]
        self.ctrl_upper_real = self.ctrl_upper[self.mujoco_actuator_ids]
        self.hand_joint_names = [
            "left_hand_thumb_0_joint", "left_hand_thumb_1_joint", "left_hand_thumb_2_joint",
            "left_hand_middle_0_joint", "left_hand_middle_1_joint", "left_hand_index_0_joint", "left_hand_index_1_joint",
            "right_hand_thumb_0_joint", "right_hand_thumb_1_joint", "right_hand_thumb_2_joint",
            "right_hand_index_0_joint", "right_hand_index_1_joint", "right_hand_middle_0_joint", "right_hand_middle_1_joint",
        ]
        self.hand_joint_qpos_adrs = self._joint_qpos_adrs(self.hand_joint_names, required=False)
        self.hand_joint_qvel_adrs = self._joint_qvel_adrs(self.hand_joint_names, required=False)
        self.hand_actuator_ids = self._actuator_ids_for_joints(self.hand_joint_names, required=False)
        self.hand_default_qpos = self._default_hand_qpos()
        self.hand_cmd_target_qpos = self.hand_default_qpos.copy()
        self.hand_cmd_kp = np.concatenate([DEX3_DEFAULT_KP, DEX3_DEFAULT_KP]).astype(np.float64)
        self.hand_cmd_kd = np.concatenate([DEX3_DEFAULT_KD, DEX3_DEFAULT_KD]).astype(np.float64)
        self.hand_cmd_lock = threading.Lock()
        # Initialize joint mapper for Real -> Mujoco conversion
        self.real_to_mujoco_mapper = create_real_to_mujoco_mapper(
            self.config.real_joint_names,
            self.config.mujoco_joint_names
        )
        mapping_info = self.real_to_mujoco_mapper.get_mapping_info()
        print(f"Real->Mujoco mapping: {mapping_info['mapped_joints']}/{mapping_info['from_space_size']} joints mapped")
        if mapping_info['unmapped_from_joints']:
            print(f"Unmapped Real joints: {mapping_info['unmapped_from_joints']}")
        if mapping_info['unmapped_to_joints']:
            print(f"Unmapped Mujoco joints: {mapping_info['unmapped_to_joints']}")

        # Set initial position
        self.data.qpos[self.mujoco_joint_qpos_adrs] = self.real_to_mujoco_mapper.map_state_to_from(self.config.default_qpos_real)
        if len(self.hand_joint_qpos_adrs):
            self.data.qpos[self.hand_joint_qpos_adrs] = self.hand_default_qpos
        self.data.qvel[:] = 0.
        mujoco.mj_forward(self.model, self.data)

        # Low level commands (in Real space)
        self.__ptargets_real = np.zeros(len(self.config.real_joint_names))
        self.__kp_real = np.zeros(len(self.config.real_joint_names))
        self.__kd_real = np.zeros(len(self.config.real_joint_names))

        self.low_cmd = None
        self.low_state = unitree_hg_msg_dds__LowState_()
        self.state_pub = ChannelPublisher(self.config.lowstate_topic, LowStateHG)
        self.state_pub.Init()
        self.odom_state = unitree_go_msg_dds__SportModeState_()
        self.odom_pub = ChannelPublisher("rt/odommodestate", SportModeState_)
        self.odom_pub.Init()
        self.state_pub_thread = threading.Thread(target=self.state_pub_handler, daemon=False)
        self.cmd_sub = ChannelSubscriber(self.config.lowcmd_topic, LowCmdHG)
        self.cmd_sub.Init(self.cmd_sub_handler)
        self.left_hand_cmd_sub = ChannelSubscriber("rt/dex3/left/cmd", HandCmdHG)
        self.left_hand_cmd_sub.Init(self.left_hand_cmd_handler)
        self.right_hand_cmd_sub = ChannelSubscriber("rt/dex3/right/cmd", HandCmdHG)
        self.right_hand_cmd_sub.Init(self.right_hand_cmd_handler)
        self.is_alive = True
        self._closing = False
        self.simulate_joystick_thread = threading.Thread(
            target=self._listen_keyboard,
            daemon=True
        )
        self.policy_queried = False
        self.loop_count = Value('i', 0)

        self.render_gui = bool(getattr(self.config, "render_gui", False))

        # MuJoCo viewer
        self.viewer = None
        self.renderer = None
        self._viewer_tick = 0
        self.viewer_decim = max(1, self.low_level_freq // 30)  # Default 30 fps for viewer
        self._runtime_reference_server = None
        self._runtime_reference_payload = None
        self.imu_lin_acc_adr, self.imu_lin_acc_dim = self._resolve_sensor_slice("imu_lin_acc")
        if self.imu_lin_acc_adr is None or self.imu_lin_acc_dim < 3:
            raise ValueError("Missing required MuJoCo sensor 'imu_lin_acc' (accelerometer, dim>=3) in loaded XML.")

        self.p_loop_rate = None

        # Interrupt handler for graceful exit
        signal.signal(signal.SIGINT, self.close)
        if getattr(self.args, "show_reference_ghost", False):
            self._runtime_reference_server = RuntimeReferenceUDPServer("127.0.0.1", 28564)
            self._runtime_reference_server.start()

    def count_loop_rate(self, loop_count):
        count_loop_timer = Timer(1.)
        while self.is_alive:
            print(f'Loop rate: {loop_count.value} Hz')
            loop_count.value = 0
            count_loop_timer.sleep()

    def on_press(self, key):
        print(f'Key pressed: {key}')
        joystick_btn = Keyboard2Joystick.get(key, None)
        if joystick_btn is None:
            return
        joystick_idx = getattr(KeyMap, joystick_btn, None)
        if joystick_idx is None:
            return
        self.low_state.wireless_remote[0] = joystick_idx
        self.state_pub.Write(self.low_state)

    def on_release(self, key):
        time.sleep(0.1)
        self.low_state.wireless_remote[0] = 0
        self.state_pub.Write(self.low_state)

    def _listen_keyboard(self):
        try:
            listen_keyboard(on_press=self.on_press, on_release=self.on_release)
        except RuntimeError as exc:
            if self._closing or not self.is_alive:
                return
            print(f"[sim2sim] keyboard listener stopped: {exc}")
        except Exception as exc:
            if self._closing or not self.is_alive:
                return
            print(f"[sim2sim] keyboard listener stopped: {exc}")

    def cmd_sub_handler(self, msg):
        self.low_cmd = msg
        self.policy_queried |= self.low_cmd.reserve[0]
        for i in range(len(self.config.real_joint_names)):
            self.__ptargets_real[i] = msg.motor_cmd[i].q
            self.__kp_real[i] = msg.motor_cmd[i].kp
            self.__kd_real[i] = msg.motor_cmd[i].kd

    def left_hand_cmd_handler(self, msg):
        with self.hand_cmd_lock:
            for i in range(7):
                self.hand_cmd_target_qpos[i] = msg.motor_cmd[i].q
                self.hand_cmd_kp[i] = max(DEX3_DEFAULT_KP[i], msg.motor_cmd[i].kp)
                self.hand_cmd_kd[i] = max(DEX3_DEFAULT_KD[i], msg.motor_cmd[i].kd)

    def right_hand_cmd_handler(self, msg):
        with self.hand_cmd_lock:
            offset = 7
            for i in range(7):
                self.hand_cmd_target_qpos[offset + i] = msg.motor_cmd[i].q
                self.hand_cmd_kp[offset + i] = max(DEX3_DEFAULT_KP[i], msg.motor_cmd[i].kp)
                self.hand_cmd_kd[offset + i] = max(DEX3_DEFAULT_KD[i], msg.motor_cmd[i].kd)

    def state_pub_handler(self):
        timer = Timer(self.pub_dt)
        while self.is_alive:
            low_state = self.low_state
            joint_qpos_mujoco = self.data.qpos[self.mujoco_joint_qpos_adrs]
            joint_qvel_mujoco = self.data.qvel[self.mujoco_joint_qvel_adrs]
            joint_torque_mujoco = self.data.ctrl[self.mujoco_actuator_ids].copy()

            joint_qpos_real = self.real_to_mujoco_mapper.map_state_to_from(joint_qpos_mujoco)
            joint_qvel_real = self.real_to_mujoco_mapper.map_state_to_from(joint_qvel_mujoco)
            joint_torque_real = self.real_to_mujoco_mapper.map_state_to_from(joint_torque_mujoco)

            for i in range(len(self.config.real_joint_names)):
                low_state.motor_state[i].q = joint_qpos_real[i]
                low_state.motor_state[i].dq = joint_qvel_real[i]
                low_state.motor_state[i].tau_est = joint_torque_real[i]

            low_state.imu_state.quaternion = self.data.qpos[3:7].copy() # Mujoco is wxyz
            low_state.imu_state.gyroscope = self.data.qvel[3:6].copy()
            low_state.imu_state.accelerometer = self.data.sensordata[self.imu_lin_acc_adr : self.imu_lin_acc_adr + 3].copy()
            low_state.tick = 1
            low_state.crc = CRC().Crc(low_state)
            self.state_pub.Write(low_state)
            self.odom_state.position = self.data.qpos[:3].astype(float).tolist()
            self.odom_state.velocity = self.data.qvel[:3].astype(float).tolist()
            self.odom_state.yaw_speed = float(self.data.qvel[5])
            self.odom_pub.Write(self.odom_state)

            timer.sleep()

    def wait_for_high_cmd(self):
        print(f'Waiting for high level controller...')
        while self.low_cmd is None:
            continue
        print(f'Connected to high level')
        print(f'Press "s" to move to default pose')
        running_zero_cmd = True
        while running_zero_cmd:
            running_zero_cmd = self.low_state.wireless_remote[0] != KeyMap.start

    def simulate_gantry(self):
        print(
            f'''Moving to default pose...\n'''
            f'''Press "a" after the robot is in default pose to being control loop'''
        )
        timer = Timer(self.low_level_dt)
        while True:
            ptargets_mujoco = self.real_to_mujoco_mapper.map_action_from_to(self.__ptargets_real)
            # gantry pose
            self.data.qpos[:7] = [0, 0, 2, 0.707, 0.0, 0.0, 0.707]
            self.data.qpos[self.mujoco_joint_qpos_adrs] = ptargets_mujoco
            if len(self.hand_joint_qpos_adrs):
                self.data.qpos[self.hand_joint_qpos_adrs] = self.hand_default_qpos
            mujoco.mj_forward(self.model, self.data)

            if not self._viewer_sync():
                break

            running_default_pos = self.low_state.wireless_remote[0] != KeyMap.A and self.low_state.wireless_remote[0] != KeyMap.B and self.low_state.wireless_remote[0] != KeyMap.X
            if not running_default_pos:
                break
            timer.sleep()

    def simulate_control(self):
        print(f'Running control loop...')
        self.data.qpos[2] = 0.78
        self.data.qpos[3:7] = [0.707, 0.0, 0.0, 0.707]  # Neutral orientation (wxyz)
        if len(self.hand_joint_qpos_adrs):
            self.data.qpos[self.hand_joint_qpos_adrs] = self.hand_default_qpos
        mujoco.mj_forward(self.model, self.data)

        timer = Timer(self.low_level_dt)
        time_start = time.time()
        loop_count = self.loop_count

        while self.is_alive:
            if not self.policy_queried:
                timer.sleep()
                time_start = time.time()
                continue

            ptargets_mujoco = self.real_to_mujoco_mapper.map_action_from_to(self.__ptargets_real)
            kp_mujoco = self.real_to_mujoco_mapper.map_action_from_to(self.__kp_real)
            kd_mujoco = self.real_to_mujoco_mapper.map_action_from_to(self.__kd_real)

            qpos_mujoco = self.data.qpos[self.mujoco_joint_qpos_adrs]
            qvel_mujoco = self.data.qvel[self.mujoco_joint_qvel_adrs]
            ctrl = kp_mujoco * (ptargets_mujoco - qpos_mujoco) + kd_mujoco * (0 - qvel_mujoco)
            ctrl = np.clip(ctrl, self.ctrl_lower_real, self.ctrl_upper_real)
            self.data.ctrl[:] = 0.0
            self.data.ctrl[self.mujoco_actuator_ids] = ctrl
            self._hold_hand_open()

            seconds = loop_count.value * self.low_level_dt
            
            # Limit external forces applied via viewer to 30N
            self._limit_external_forces(max_force=30.0)
            
            mujoco.mj_step(self.model, self.data)

            if not self._viewer_sync():
                break

            if loop_count.value % 200 == 0:
                seconds_real = time.time() - time_start
                print(f'Time: {seconds:.2f}, Time real: {seconds_real:.2f}, Height: {self.data.qpos[2]:.2f}')

            loop_count.value += 1
            timer.sleep()

        self.close()

    def _limit_external_forces(self, max_force=30.0):
        for i in range(self.model.nbody):
            # Get the force vector (first 3 components)
            force = self.data.xfrc_applied[i, :3]
            force_magnitude = np.linalg.norm(force)
            
            # If force exceeds max_force, clip it
            if force_magnitude > max_force:
                self.data.xfrc_applied[i, :3] = force * (max_force / force_magnitude)

    def _viewer_sync(self) -> bool:
        if self.viewer is None:
            return True
        if not self.viewer.is_running():
            self.is_alive = False
            return False
        self._viewer_tick += 1
        if (self._viewer_tick % self.viewer_decim) == 0:
            self.viewer.cam.lookat[:] = self.data.qpos[:3]
            if self._runtime_reference_server is not None and hasattr(self.viewer, "user_scn"):
                self._draw_reference_ghost(self.viewer.user_scn)
            self.viewer.sync()
        return True

    def _refresh_runtime_reference(self):
        if self._runtime_reference_server is None:
            return
        latest = self._runtime_reference_server.get_latest()
        if latest is None:
            return
        self._runtime_reference_payload = latest

    def _draw_reference_ghost(self, scene):
        if scene is None or not hasattr(scene, "geoms"):
            return
        self._refresh_runtime_reference()
        payload = self._runtime_reference_payload
        if payload is None:
            if hasattr(scene, "ngeom"):
                scene.ngeom = 0
            return

        try:
            body_pos = np.asarray(payload["body_pos"], dtype=np.float32)
            edges = [tuple(e) for e in payload.get("edges", [])]
            motion_name = str(payload.get("motion_name", "unknown"))
        except Exception:
            return
        if body_pos.ndim != 2 or body_pos.shape[1] != 3:
            return

        scene.ngeom = 0
        identity = np.eye(3, dtype=np.float32).reshape(-1)
        point_rgba = np.array([0.1, 0.9, 1.0, 0.6], dtype=np.float32)
        line_rgba = np.array([0.1, 0.9, 1.0, 0.28], dtype=np.float32)
        max_geoms = scene.maxgeom

        for idx in range(body_pos.shape[0]):
            if scene.ngeom >= max_geoms:
                break
            geom = scene.geoms[scene.ngeom]
            mujoco.mjv_initGeom(
                geom,
                mujoco.mjtGeom.mjGEOM_SPHERE,
                np.array([0.018, 0.0, 0.0], dtype=np.float32),
                body_pos[idx].astype(np.float32),
                identity,
                point_rgba,
            )
            scene.ngeom += 1

        for a, b in edges:
            if scene.ngeom >= max_geoms:
                break
            geom = scene.geoms[scene.ngeom]
            mujoco.mjv_initGeom(
                geom,
                mujoco.mjtGeom.mjGEOM_CAPSULE,
                np.array([0.01, 0.0, 0.0], dtype=np.float32),
                np.zeros(3, dtype=np.float32),
                identity,
                line_rgba,
            )
            mujoco.mjv_connector(
                geom,
                mujoco.mjtGeom.mjGEOM_CAPSULE,
                0.01,
                body_pos[a].astype(np.float64),
                body_pos[b].astype(np.float64),
            )
            scene.ngeom += 1

        if getattr(self, "_last_runtime_reference_name", None) != motion_name:
            print(f"[sim2sim] Runtime reference ghost: {motion_name}")
            self._last_runtime_reference_name = motion_name

    def _joint_ids(self, joint_names, required=True):
        ids = []
        for name in joint_names:
            jid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, name)
            if jid < 0:
                if required:
                    raise ValueError(f"MuJoCo joint not found: {name}")
                continue
            ids.append(jid)
        return np.asarray(ids, dtype=np.int32)

    def _joint_qpos_adrs(self, joint_names, required=True):
        joint_ids = self._joint_ids(joint_names, required=required)
        return np.asarray([self.model.jnt_qposadr[jid] for jid in joint_ids], dtype=np.int32)

    def _joint_qvel_adrs(self, joint_names, required=True):
        joint_ids = self._joint_ids(joint_names, required=required)
        return np.asarray([self.model.jnt_dofadr[jid] for jid in joint_ids], dtype=np.int32)

    def _actuator_ids_for_joints(self, joint_names, required=True):
        ids = []
        for name in joint_names:
            jid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, name)
            if jid < 0:
                if required:
                    raise ValueError(f"MuJoCo joint not found for actuator lookup: {name}")
                continue
            actuator_id = -1
            for aid in range(self.model.nu):
                if int(self.model.actuator_trnid[aid, 0]) == jid:
                    actuator_id = aid
                    break
            if actuator_id < 0:
                if required:
                    raise ValueError(f"MuJoCo actuator not found for joint: {name}")
                continue
            ids.append(actuator_id)
        return np.asarray(ids, dtype=np.int32)

    def _hold_hand_open(self):
        if not len(self.hand_actuator_ids):
            return
        qpos = self.data.qpos[self.hand_joint_qpos_adrs]
        qvel = self.data.qvel[self.hand_joint_qvel_adrs]
        with self.hand_cmd_lock:
            target = self.hand_cmd_target_qpos.copy()
            kp = self.hand_cmd_kp.copy()
            kd = self.hand_cmd_kd.copy()
        ctrl = (10.0 * kp) * (target - qpos) + (1.5 * kd) * (0.0 - qvel)
        lower = self.ctrl_lower[self.hand_actuator_ids]
        upper = self.ctrl_upper[self.hand_actuator_ids]
        self.data.ctrl[self.hand_actuator_ids] = np.clip(ctrl, lower, upper)

    def _default_hand_qpos(self):
        if not len(self.hand_joint_qpos_adrs):
            return np.zeros(0, dtype=np.float64)

        left_q, right_q = get_hand_pose("closed_fist")
        targets = np.concatenate([left_q, right_q]).astype(np.float64)
        targets = targets[: len(self.hand_joint_qpos_adrs)]

        joint_ids = self._joint_ids(self.hand_joint_names, required=False)
        if len(joint_ids):
            ranges = self.model.jnt_range[joint_ids]
            limited = np.asarray(self.model.jnt_limited[joint_ids], dtype=bool)
            targets[limited] = np.clip(targets[limited], ranges[limited, 0], ranges[limited, 1])
        return targets

    def _resolve_sensor_slice(self, sensor_name: str):
        sid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_SENSOR, sensor_name)
        if sid < 0:
            return None, 0
        return int(self.model.sensor_adr[sid]), int(self.model.sensor_dim[sid])

    def run(self):
        self.state_pub_thread.start()
        self.simulate_joystick_thread.start()

        if self.render_gui:
            self.renderer = mujoco.Renderer(self.model)

            with mujoco.viewer.launch_passive(
                self.model,
                self.data,
                show_left_ui=False,
                show_right_ui=False,
            ) as viewer:
                self.viewer = viewer
                self.viewer.cam.lookat[:] = self.data.qpos[:3]
                self.viewer.cam.distance = 4.0
                self.viewer.cam.elevation = -20
                self.viewer.cam.azimuth = 135
                try:
                    self.wait_for_high_cmd()
                    self.simulate_gantry()
                    self.simulate_control()
                finally:
                    self.viewer = None
        else:
            self.wait_for_high_cmd()
            self.simulate_gantry()
            self.simulate_control()

    def close(self, *args):
        if self._closing:
            return
        self._closing = True
        self.is_alive = False

        try:
            stop_listening()
        except Exception:
            pass
        if self.p_loop_rate is not None:
            self.p_loop_rate.terminate()
        if self._runtime_reference_server is not None:
            self._runtime_reference_server.stop()

        if self.state_pub_thread.is_alive() and threading.current_thread() is not self.state_pub_thread:
            self.state_pub_thread.join(timeout=1.0)
        if self.simulate_joystick_thread.is_alive() and threading.current_thread() is not self.simulate_joystick_thread:
            self.simulate_joystick_thread.join(timeout=1.0)
        sys.exit(0)


if __name__ == "__main__":
    try:
        import multiprocessing as mp
        if mp.get_start_method(allow_none=True) is None:
            mp.set_start_method('spawn', force=True)
    except Exception:
        pass

    parser = argparse.ArgumentParser()
    default_xml = ASSETS_DIR / "g1" / "g1.xml"
    parser.add_argument("--xml_path", type=str, default=str(default_xml))
    parser.add_argument("--show-reference-ghost", action="store_true")
    parser.add_argument("--ghost-motion", type=str, default=None)
    args = parser.parse_args()

    config_path = Path(ASSETS_DIR).parents[0] / "config" / "controller.yaml"
    config = DictToClass(yaml.load(open(str(config_path), 'r'), Loader=yaml.FullLoader))
    ChannelFactoryInitialize(0, 'lo') #"lo" means local network.

    Sim2sim(args, config).run()
