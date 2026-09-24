/**
 * Parse .npz files in the browser without Python/bridge.
 * Supports formats: dof_pos, joint_pos+body_pos_w, joint_pos+root_pos
 */
import JSZip from 'jszip';
import { load as loadNpy } from 'npyjs';

// Isaac Lab joint order → MT/dataset order (from bridge.py)
const ISAAC_JOINT_ORDER = [
  'left_hip_pitch_joint', 'right_hip_pitch_joint', 'waist_yaw_joint',
  'left_hip_roll_joint', 'right_hip_roll_joint', 'waist_roll_joint',
  'left_hip_yaw_joint', 'right_hip_yaw_joint', 'waist_pitch_joint',
  'left_knee_joint', 'right_knee_joint',
  'left_shoulder_pitch_joint', 'right_shoulder_pitch_joint',
  'left_ankle_pitch_joint', 'right_ankle_pitch_joint',
  'left_shoulder_roll_joint', 'right_shoulder_roll_joint',
  'left_ankle_roll_joint', 'right_ankle_roll_joint',
  'left_shoulder_yaw_joint', 'right_shoulder_yaw_joint',
  'left_elbow_joint', 'right_elbow_joint',
  'left_wrist_roll_joint', 'right_wrist_roll_joint',
  'left_wrist_pitch_joint', 'right_wrist_pitch_joint',
  'left_wrist_yaw_joint', 'right_wrist_yaw_joint',
];
const MT_JOINT_ORDER = [
  'left_hip_pitch_joint', 'left_hip_roll_joint', 'left_hip_yaw_joint',
  'left_knee_joint', 'left_ankle_pitch_joint', 'left_ankle_roll_joint',
  'right_hip_pitch_joint', 'right_hip_roll_joint', 'right_hip_yaw_joint',
  'right_knee_joint', 'right_ankle_pitch_joint', 'right_ankle_roll_joint',
  'waist_yaw_joint', 'waist_roll_joint', 'waist_pitch_joint',
  'left_shoulder_pitch_joint', 'left_shoulder_roll_joint', 'left_shoulder_yaw_joint',
  'left_elbow_joint', 'left_wrist_roll_joint', 'left_wrist_pitch_joint', 'left_wrist_yaw_joint',
  'right_shoulder_pitch_joint', 'right_shoulder_roll_joint', 'right_shoulder_yaw_joint',
  'right_elbow_joint', 'right_wrist_roll_joint', 'right_wrist_pitch_joint', 'right_wrist_yaw_joint',
];
const ISAAC_TO_MT = MT_JOINT_ORDER.map((j) => ISAAC_JOINT_ORDER.indexOf(j));

function reshape(arr, shape) {
  if (!arr || !shape || shape.length === 0) return null;
  const total = shape.reduce((a, b) => a * b, 1);
  if (arr.length !== total) return null;
  const src = Array.isArray(arr) ? arr : Array.from(arr);
  if (shape.length === 1) return src;
  if (shape.length === 2) {
    const [rows, cols] = shape;
    const out = [];
    for (let r = 0; r < rows; r++) {
      out.push(src.slice(r * cols, (r + 1) * cols));
    }
    return out;
  }
  if (shape.length === 3) {
    const [d0, d1, d2] = shape;
    const out = [];
    for (let i = 0; i < d0; i++) {
      const slice = [];
      for (let j = 0; j < d1; j++) {
        const start = (i * d1 + j) * d2;
        slice.push(src.slice(start, start + d2));
      }
      out.push(slice);
    }
    return out;
  }
  return src;
}

async function parseNpyFromZip(zip, name) {
  const file = zip.file(name);
  if (!file) return null;
  const buf = await file.async('arraybuffer');
  const parsed = await loadNpy(buf);
  if (!parsed?.data || !parsed?.shape) return null;
  const arr = reshape(parsed.data, parsed.shape);
  return arr;
}

/**
 * Parse .npz ArrayBuffer and return web clip { joint_pos, root_pos, root_quat }.
 * @param {ArrayBuffer} buffer - raw .npz file bytes
 * @returns {Promise<{ joint_pos: number[][], root_pos: number[][], root_quat: number[][] }>}
 */
export async function parseNpzToClip(buffer) {
  const zip = await JSZip.loadAsync(buffer);
  const names = Object.keys(zip.files).filter((n) => !n.endsWith('/'));

  const data = {};
  for (const name of names) {
    const key = name.replace(/\.npy$/, '');
    const arr = await parseNpyFromZip(zip, name);
    if (arr != null) data[key] = arr;
  }

  const keys = Object.keys(data);

  let dofPos;
  let rootPos;
  let rootQuatWxyz;

  if (keys.includes('dof_pos')) {
    dofPos = data.dof_pos;
    rootPos = data.root_pos;
    const rootXyzw = data.root_rot;
    if (!rootXyzw) throw new Error('npz missing root_rot');
    rootQuatWxyz = rootXyzw.map((row) => row.length >= 4 ? [row[3], row[0], row[1], row[2]] : row);
  } else if (keys.includes('joint_pos') && keys.includes('body_pos_w')) {
    const jointIsaac = data.joint_pos;
    rootPos = data.body_pos_w.map((row) => row[0]);
    const bodyQuatWxyz = data.body_quat_w.map((row) => row[0]);
    const rootXyzw = bodyQuatWxyz.map(([w, x, y, z]) => [x, y, z, w]);
    rootQuatWxyz = bodyQuatWxyz;
    dofPos = jointIsaac.map((row) => ISAAC_TO_MT.map((i) => row[i]));
  } else if (keys.includes('joint_pos') && keys.includes('root_pos')) {
    const jointIsaac = data.joint_pos;
    rootPos = data.root_pos;
    const rootRot = data.root_rot;
    if (!rootRot) throw new Error('npz missing root_rot');
    const rootXyzw = rootRot.map(([w, x, y, z]) => [x, y, z, w]);
    rootQuatWxyz = rootRot;
    dofPos = jointIsaac.map((row) => ISAAC_TO_MT.map((i) => row[i]));
  } else {
    throw new Error(`Unsupported npz format. Keys: ${keys.join(', ')}`);
  }

  if (!dofPos || !rootPos || !rootQuatWxyz) {
    throw new Error('Failed to extract motion arrays from npz');
  }

  return {
    joint_pos: dofPos,
    root_pos: rootPos,
    root_quat: rootQuatWxyz,
  };
}
