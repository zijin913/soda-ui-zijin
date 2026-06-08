# LeRobot Dataset Format Specification (v3.0)

The LeRobot dataset is a structured storage format designed for Robot Learning, built on top of Hugging Face's `datasets` library, aiming to balance storage efficiency with ease of use.

## 1. Directory Structure
The dataset is named after its repository ID (repo_id), with the following internal structure:

```text
dataset_name/
├── meta/
│   ├── info.json          # Core metadata: includes FPS, feature definitions (Features), statistics, etc.
│   ├── stats.json         # Statistics for each modality (mean, standard deviation, max/min), used for data normalization
│   ├── episodes.parquet   # Episode metadata: records the starting index and length of each episode
│   └── tasks.parquet      # Task descriptions: records the language instruction corresponding to each episode
├── data/
│   └── chunk-000/
│       └── file-000.parquet # Actual numerical data: includes timestamps, states, actions, etc.
└── videos/
    ├── observation.images.main/
    │   └── chunk-000/
    │       └── file-000.mp4 # Video data: observation image sequence
    └── ...
```

## 2. Detailed Explanation of Core Files

### meta/info.json
Defines the global configuration of the dataset. Key fields:
- `fps`: Capture frequency (e.g., 30).
- `features`: Defines the type and dimension of each data column.
  - `dtype: "video"`: Linked to the MP4 files under `videos/`.
  - `dtype: "out_of_group"`: Stored as numerical vectors (e.g., state, action).
- `total_episodes`: Total number of episodes.
- `total_frames`: Total number of frames.

### data/*.parquet
Each row represents one frame of data, typically containing:
- `timestamp`: Timestamp of the current frame.
- `frame_index`: Frame index within the current episode.
- `episode_index`: Index of the episode it belongs to.
- `observation.state`: Robot state vector.
- `action`: Robot action vector (in SODA, this usually corresponds to target_joint_angles).

### videos/*.mp4
To save space, LeRobot encodes image sequences as videos. Each video segment corresponds to the consecutive frames within a data chunk.

## 3. Mapping from SODA to LeRobot
In the SODA system:
- **Observation**: Joint angles (`joint_angles`), camera images (`camera_front`).
- **Action**: Target joint angles or increments.
- **State**: The complete robot pose.
