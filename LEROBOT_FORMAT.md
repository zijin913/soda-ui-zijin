# LeRobot 数据集格式说明 (v3.0)

LeRobot 数据集是为机器人学习（Robot Learning）设计的结构化存储格式，基于 Hugging Face 的 `datasets` 库构建，旨在兼顾存储效率与易用性。

## 1. 目录结构
数据集以仓库 ID (repo_id) 命名，内部结构如下：

```text
dataset_name/
├── meta/
│   ├── info.json          # 核心元数据：包含 FPS、特征定义 (Features)、统计信息等
│   ├── stats.json         # 各模态的统计信息（均值、标准差、最大/最小值），用于数据归一化
│   ├── episodes.parquet   # 剧集元数据：记录每个 episode 的起始索引和长度
│   └── tasks.parquet      # 任务描述：记录每个 episode 对应的语言指令
├── data/
│   └── chunk-000/
│       └── file-000.parquet # 实际数值数据：包含时间戳、状态、动作等
└── videos/
    ├── observation.images.main/
    │   └── chunk-000/
    │       └── file-000.mp4 # 视频数据：观测图像序列
    └── ...
```

## 2. 核心文件详解

### meta/info.json
定义了数据集的全局配置。关键字段：
- `fps`: 采集频率（如 30）。
- `features`: 定义每个数据列的类型和维度。
  - `dtype: "video"`: 关联到 `videos/` 下的 MP4 文件。
  - `dtype: "out_of_group"`: 存储为数值向量（如状态、动作）。
- `total_episodes`: 总剧集数。
- `total_frames`: 总帧数。

### data/*.parquet
每一行代表一帧数据，通常包含：
- `timestamp`: 当前帧的时间戳。
- `frame_index`: 当前剧集内的帧序号。
- `episode_index`: 所属剧集的索引。
- `observation.state`: 机器人状态向量。
- `action`: 机器人动作向量（在 SODA 中通常对应 target_joint_angles）。

### videos/*.mp4
为了节省空间，LeRobot 将图像序列编码为视频。每一段视频对应一个数据块 (chunk) 中的连续帧。

## 3. SODA 到 LeRobot 的映射
在 SODA 系统中：
- **观测 (Observation)**: 关节角度 (`joint_angles`)、相机画面 (`camera_front`)。
- **动作 (Action)**: 目标关节角度或增量。
- **状态 (State)**: 完整的机器人位姿。
