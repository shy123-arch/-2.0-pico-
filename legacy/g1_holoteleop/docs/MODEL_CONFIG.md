# Tracker Model Config

This document records the current PPO tracker model size.

## Current Model

The current tracker uses the medium model:

```python
latent_dim = 384
encoder_priv = [768]
adapt_module = [768, 768]
actor = [1536, 768, 768]
critic = [1536, 768, 768]
```

This replaces the previous small model:

```python
latent_dim = 256
encoder_priv = [512]
adapt_module = [512, 512]
actor = [1024, 512, 512]
critic = [1024, 512, 512]
```

## Parameter Count

With the current G1 tracking observation/action dimensions:

```text
policy obs dim = 1590
priv obs dim   = 4558
critic input   = 6151
action dim     = 29
```

Approximate parameter counts:

| Model | Training params | Deployed student params |
|---|---:|---:|
| Small, 256/512/1024 | 16.16M | 3.91M |
| Medium, 384/768/1536 | 26.80M | 6.94M |

The deployed student policy is roughly 1.78x larger than before, but the deployment interface is unchanged:

```text
in_keys = ["policy"]
input dim = 1590
```

No sim2real code change is required after export as long as `policy.json` still reports a single `policy` input.

## Training Plan

For the medium model, use the long training schedule:

```text
train:    20B frames
adapt:     5B frames
finetune: 20B frames
```

The finetune stage can be tested halfway. With 8 GPUs, `num_envs=8192`, and `train_every=32`, 10B global finetune frames is around iteration 4768. Since the default `save_interval` is 150 iterations, use the nearest saved checkpoint:

```text
checkpoint_4800.pt
```

That checkpoint is slightly after 10B global finetune frames and can be exported for an intermediate sim2real test while the full 20B finetune continues.

Do not change dataset, reward, or termination at the same time if the goal is to isolate the effect of model capacity.
