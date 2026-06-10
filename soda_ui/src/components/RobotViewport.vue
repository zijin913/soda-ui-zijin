<template>
  <div class="robot-stage-3d" ref="canvasContainer">
    <!-- Decorative background glow -->
    <div class="glow-overlay"></div>

    <!-- Limit Toast -->
    <div class="limit-toast" :class="{ visible: showLimitToast }">
      <span>{{ limitToastMessage }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls';
import URDFLoader from 'urdf-loader';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';

const props = defineProps({
  pointCloudData: { default: null },
  showPointCloud: { type: Boolean, default: true },
  mode: { type: String, default: 'realtime' },
  dualMode: { type: Boolean, default: false }
});

const emit = defineEmits(['joint-limit-loaded']);

const JOINT_CONTROL_HZ = 30;
let jointControlTimer = null;
let accumulatedDeltaAngle = 0;

const canvasContainer = ref(null);
const showLimitToast = ref(false); // Toast state
const limitToastMessage = ref('');
let limitToastTimer = null;

let scene, camera, renderer, controls, loader;
let raycaster, pointer;
let robotModel = null;
let robotModels = {};  // { left: model, right: model } for dual mode
let draggingSide = null;  // Track which arm is being dragged in dual mode
let pointCloudPoints = null;
let pointCloudGeometry = null;
let pointCloudMaterial = null;
let currentBufferSize = 0; // Track current buffer capacity
const currentHelpers = new THREE.Group();
let selectedMeshes = [];
let draggingJoint = null;
let isDragging = false;
const dragStartPoint = { x: 0, y: 0 };
let initialJointAngle = 0;
const currentJointAngles = ref({}); // Store real-time joint angles

// Per-joint render smoothing. Telemetry arrives at ~30 Hz (10 Hz during
// teleop) and used to snap setJointValue() directly, so the 60 fps render
// showed discrete steps ("一段一段"). Instead we store the latest telemetry
// value as a target and ease the displayed angle toward it every animation
// frame, turning low-rate state updates into continuous motion.
// stateKey -> { model, jointObj, mimicObjs, target, displayed }
const jointSmoothing = {};
// Exponential-smoothing rate (1/s). Higher = snappier (less lag, more
// stepping); lower = smoother (more lag). ~22 gives a ~45 ms time constant.
const JOINT_SMOOTHING_RATE = 22;
let lastSmoothTime = 0;

// Gripper joints that should not be controlled via dragging
let gripperJointNames = [];

// Control disabled in replay mode
watch(() => props.mode, (newMode) => {
  console.log('Mode changed to:', newMode);
});

// Helper to show toast
const triggerLimitToast = (message) => {
  limitToastMessage.value = message;
  showLimitToast.value = true;
  if (limitToastTimer) clearTimeout(limitToastTimer);
  limitToastTimer = setTimeout(() => {
    showLimitToast.value = false;
  }, 1500);
};

const initScene = () => {
  scene = new THREE.Scene();
  scene.background = null;

  camera = new THREE.PerspectiveCamera(45, canvasContainer.value.clientWidth / canvasContainer.value.clientHeight, 0.1, 100);
  camera.position.set(2, 2, 2);
  camera.up.set(0, 0, 1);

  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setSize(canvasContainer.value.clientWidth, canvasContainer.value.clientHeight);
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.useLegacyLights = false;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  canvasContainer.value.appendChild(renderer.domElement);

  const pmremGenerator = new THREE.PMREMGenerator(renderer);
  pmremGenerator.compileEquirectangularShader();
  scene.environment = pmremGenerator.fromScene(new RoomEnvironment(), 0.04).texture;

  const ambientLight = new THREE.AmbientLight(0xffffff, 0.4);
  scene.add(ambientLight);
  const directionalLight = new THREE.DirectionalLight(0xffffff, 1.0);
  directionalLight.position.set(5, 7, 10);
  scene.add(directionalLight);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;

  raycaster = new THREE.Raycaster();
  pointer = new THREE.Vector2();
  scene.add(currentHelpers);

  // URDF Loader
  const manager = new THREE.LoadingManager();
  loader = new URDFLoader(manager);
  const metalMaterial = new THREE.MeshStandardMaterial({ color: 0xc0c0c0, roughness: 0.2, metalness: 1.0 });

  // Mesh paths inside URDFs use './meshes/...' relative to their URDF.
  // The URDFLoader resolves them via the working URL's parent path. We override
  // here only to strip the './' prefix so the loader can resolve correctly
  // against the URDF's own URL (which is what we want regardless of which
  // {arm}_{gripper} directory we're loading from).
  manager.setURLModifier((url) => {
    // urdf-loader passes the resolved absolute URL of the mesh; pass through.
    return url;
  });

  // Material is applied in loadSingleURDF

  const loadSingleURDF = (urdfUrl, side = null, position = null) => {
    loader.load(urdfUrl, robot => {
      if (side) {
        robotModels[side] = robot;
        // Also set robotModel to first loaded for backward compat
        if (!robotModel) robotModel = robot;
      } else {
        robotModel = robot;
      }
      scene.add(robot);

      // Position handling:
      //   - dual_mode: server returns explicit XYZ position per arm (in left-arm
      //     base frame, from extrinsics.json), use it directly.
      //   - single arm: center the model.
      if (position !== null) {
        robot.position.set(position[0], position[1], position[2]);
      } else {
        const box = new THREE.Box3().setFromObject(robot);
        const center = box.getCenter(new THREE.Vector3());
        robot.position.sub(center);
      }

      // Apply material
      robot.traverse((child) => {
        if (child.isMesh) {
          child.material = metalMaterial;
          child.castShadow = true;
          child.receiveShadow = true;
          child.userData.originalMaterial = metalMaterial;
        }
      });

      // Extract and emit joint limits (from first loaded model)
      if (!side || side === 'left') {
        const limit = {};
        if (robot.joints) {
          for (const [name, joint] of Object.entries(robot.joints)) {
            if (joint.limit) {
              limit[name] = { lower: joint.limit.lower, upper: joint.limit.upper };
            }
          }
        }
        emit('joint-limit-loaded', limit);
      }
    });
  };

  const loadURDF = async () => {
    try {
      const response = await fetch('http://localhost:8080/urdf');
      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
      const data = await response.json();

      if (data.dual_mode) {
        // Server provides per-arm position (left arm at origin, right arm at
        // right_base_in_left from hand-eye extrinsics, e.g. [0, -0.448, 0]).
        const leftPos = data.left.position || [0.0, 0.0, 0.0];
        const rightPos = data.right.position || [0.0, -0.448, 0.0];
        loadSingleURDF(data.left.url, 'left', leftPos);
        loadSingleURDF(data.right.url, 'right', rightPos);
      } else {
        loadSingleURDF(data.url);
      }
    } catch (error) {
      console.error('Failed to load URDF:', error);
    }
  };

  const fetchGripperJoints = async () => {
    try {
      const response = await fetch('http://localhost:8080/api/joints/gripper');
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      gripperJointNames = data.joints || [];
      rebuildMimicMap();
    } catch (error) {
      console.error('Failed to fetch gripper joints:', error);
      gripperJointNames = [];
      rebuildMimicMap();
    }
  };

  loadURDF();
  fetchGripperJoints();

  const animate = () => {
    requestAnimationFrame(animate);

    // Ease every joint toward its latest telemetry target so 30 Hz state
    // updates render as continuous motion. Frame-rate independent: alpha is
    // derived from elapsed time, so the feel is the same at 30/60/144 fps.
    const now = performance.now();
    const dt = lastSmoothTime ? Math.min((now - lastSmoothTime) / 1000, 0.1) : 0;
    lastSmoothTime = now;
    const alpha = dt > 0 ? 1 - Math.exp(-JOINT_SMOOTHING_RATE * dt) : 1;
    for (const key in jointSmoothing) {
      const e = jointSmoothing[key];
      const diff = e.target - e.displayed;
      if (Math.abs(diff) < 1e-5) continue;
      e.displayed += diff * alpha;
      if (Math.abs(e.target - e.displayed) < 1e-5) e.displayed = e.target;
      e.jointObj.setJointValue(e.displayed);
      for (const m of e.mimicObjs) m.setJointValue(e.displayed);
    }

    controls.update();
    renderer.render(scene, camera);
  };
  animate();

  window.addEventListener('resize', onWindowResize);
  renderer.domElement.addEventListener('pointerdown', onPointerDown);
  renderer.domElement.addEventListener('wheel', onWheel, { passive: false });
  window.addEventListener('pointerup', onPointerUp);
};


const findJointByName = (model, name) => {
  let result = null;
  model.traverse((child) => {
    if (child.isURDFJoint && child.urdfName === name) {
      result = child;
    }
  });
  return result;
};

const sendJointCommand = (jointName, deltaAngle, side = null) => {
  if (window.socket && window.socket.readyState === WebSocket.OPEN) {
    const msg = { type: 'joint_command', joint_name: jointName, delta_angle: deltaAngle };
    if (side) msg.side = side;
    window.socket.send(JSON.stringify(msg));
  }
};

// Mimic joint definitions: which joints follow the driven gripper joint.
// Auto-derived from the gripper joint list (excluding the driver).
// gp100 parallel-linkage has 5 mimics; gr100 lobster claw has 1.
const MIMIC_JOINTS = {};
const rebuildMimicMap = () => {
  // Driver is always 'gripper_left_joint_1'; everything else mimics it.
  const driver = 'gripper_left_joint_1';
  const mimics = gripperJointNames.filter(n => n !== driver);
  MIMIC_JOINTS[driver] = mimics;
};

const handleJointStateUpdate = (event) => {
  const jointStates = event.detail;

  jointStates.forEach(joint => {
    const jointName = joint.name;
    const angle = joint.angle;
    const side = joint.side;  // 'left', 'right', or undefined

    // Determine target model
    let targetModel;
    if (side && robotModels[side]) {
      targetModel = robotModels[side];
    } else {
      targetModel = robotModel;
    }
    if (!targetModel) return;

    // Update local state map (keyed by side+name for dual mode)
    const stateKey = side ? `${side}_${jointName}` : jointName;

    // While the user is actively dragging this joint, local prediction owns
    // its target — ignore the round-trip-delayed telemetry value so the two
    // don't fight and jitter. Telemetry resumes for it on pointer-up.
    if (isDragging && draggingJoint) {
      const dragKey = draggingSide ? `${draggingSide}_${draggingJoint.urdfName}` : draggingJoint.urdfName;
      if (stateKey === dragKey) return;
    }

    currentJointAngles.value[stateKey] = angle;

    // Register/update the smoothing target. The actual setJointValue() runs
    // in the animate loop, easing toward this target. Joint object lookups
    // are cached per stateKey so we don't traverse the model every frame.
    let entry = jointSmoothing[stateKey];
    if (!entry || entry.model !== targetModel) {
      const jointObj = findJointByName(targetModel, jointName);
      if (!jointObj || !jointObj.setJointValue) return;
      const mimicObjs = (MIMIC_JOINTS[jointName] || [])
        .map(name => findJointByName(targetModel, name))
        .filter(j => j && j.setJointValue);
      // Snap on first sight so the model doesn't sweep from 0 at startup.
      jointObj.setJointValue(angle);
      mimicObjs.forEach(m => m.setJointValue(angle));
      jointSmoothing[stateKey] = { model: targetModel, jointObj, mimicObjs, target: angle, displayed: angle };
    } else {
      entry.target = angle;
    }
  });
};

const updatePointCloud = (data) => {
  // Support both old format (array) and new format ({ points, colors })
  let points, colors;
  if (Array.isArray(data)) {
    points = data;
    colors = null;
  } else if (data && data.points) {
    points = data.points;
    colors = data.colors;
  } else {
    return;
  }

  if (!points || points.length === 0) return;

  const numPoints = points.length;
  const hasColors = colors && colors.length >= numPoints;

  // Check if we need to resize buffer (only grow, with 20% margin)
  const needsResize = numPoints > currentBufferSize;
  const newBufferSize = needsResize ? Math.ceil(numPoints * 1.2) : currentBufferSize;

  // Initialize or resize geometry
  if (!pointCloudGeometry || needsResize) {
    // Clean up old geometry if resizing
    if (pointCloudGeometry) {
      pointCloudGeometry.dispose();
    }

    pointCloudGeometry = new THREE.BufferGeometry();
    const positions = new Float32Array(newBufferSize * 3);
    const colorArray = new Float32Array(newBufferSize * 3);

    pointCloudGeometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    pointCloudGeometry.setAttribute('color', new THREE.BufferAttribute(colorArray, 3));
    pointCloudGeometry.setDrawRange(0, 0);

    currentBufferSize = newBufferSize;

    // Create material once
    if (!pointCloudMaterial) {
      pointCloudMaterial = new THREE.PointsMaterial({
        size: 0.01,
        sizeAttenuation: true,
        vertexColors: true
      });
    }

    // Update or create Points object
    if (pointCloudPoints) {
      pointCloudPoints.geometry = pointCloudGeometry;
    } else {
      pointCloudPoints = new THREE.Points(pointCloudGeometry, pointCloudMaterial);
      pointCloudPoints.frustumCulled = false;
      scene.add(pointCloudPoints);
    }
  }

  // Update buffer data (no allocation)
  const posAttr = pointCloudGeometry.getAttribute('position');
  const colorAttr = pointCloudGeometry.getAttribute('color');

  for (let i = 0; i < numPoints; i++) {
    posAttr.array[i * 3] = points[i][0];
    posAttr.array[i * 3 + 1] = points[i][1];
    posAttr.array[i * 3 + 2] = points[i][2];

    if (hasColors) {
      colorAttr.array[i * 3] = colors[i][0];
      colorAttr.array[i * 3 + 1] = colors[i][1];
      colorAttr.array[i * 3 + 2] = colors[i][2];
    } else {
      // Default green color
      colorAttr.array[i * 3] = 0;
      colorAttr.array[i * 3 + 1] = 1;
      colorAttr.array[i * 3 + 2] = 0;
    }
  }

  posAttr.needsUpdate = true;
  colorAttr.needsUpdate = true;
  pointCloudGeometry.setDrawRange(0, numPoints);
  pointCloudPoints.visible = props.showPointCloud;
};

watch(() => props.pointCloudData, (newData) => {
  if (newData) {
    updatePointCloud(newData);
  }
});

watch(() => props.showPointCloud, (newValue) => {
  if (pointCloudPoints) {
    pointCloudPoints.visible = newValue;
  }
});
const onPointerDown = (event) => {
  if (!robotModel || event.button !== 0) return;

  // Disable control in replay mode
  if (props.mode === 'replay') {
    console.log('Control disabled in replay mode');
    return;
  }

  const rect = canvasContainer.value.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

  raycaster.setFromCamera(pointer, camera);

  // In dual mode, raycast against all models
  let intersects = [];
  draggingSide = null;
  if (Object.keys(robotModels).length > 0) {
    for (const [side, model] of Object.entries(robotModels)) {
      const hits = raycaster.intersectObject(model, true);
      hits.forEach(h => { h._side = side; });
      intersects.push(...hits);
    }
    intersects.sort((a, b) => a.distance - b.distance);
  } else if (robotModel) {
    intersects = raycaster.intersectObject(robotModel, true);
  }

  if (intersects.length > 0) {
    const hitObject = intersects[0].object;
    draggingSide = intersects[0]._side || null;
    const hitModelRoot = draggingSide ? robotModels[draggingSide] : robotModel;

    let targetLink = hitObject;
    while (targetLink && targetLink !== hitModelRoot) {
      if (targetLink.type === 'URDFLink') break;
      targetLink = targetLink.parent;
    }
    if (!targetLink || targetLink === hitModelRoot) targetLink = hitObject.parent;

    highlightLink(targetLink);
    clearHelpers();
    addAxesHelper(targetLink);

    const targetJoint = targetLink.parent;

    if (targetJoint && targetJoint.isURDFJoint) {
      addJointDirectionHelper(targetLink, targetJoint);

      if (targetJoint.jointType === 'revolute' || targetJoint.jointType === 'continuous') {
        const isGripperJoint = gripperJointNames.includes(targetJoint.urdfName);

        if (!isGripperJoint) {
          draggingJoint = targetJoint;
          isDragging = true;
          // Use real-time angle from backend
          const angleKey = draggingSide ? `${draggingSide}_${draggingJoint.urdfName}` : draggingJoint.urdfName;
          initialJointAngle = currentJointAngles.value[angleKey] || 0;
          accumulatedDeltaAngle = 0;
          controls.enabled = false;

          jointControlTimer = setInterval(() => {
            if (accumulatedDeltaAngle !== 0) {
              sendJointCommand(draggingJoint.urdfName, accumulatedDeltaAngle, draggingSide);
              accumulatedDeltaAngle = 0;
            }
          }, 1000 / JOINT_CONTROL_HZ);
        }
      }
    }
  } else {
    resetHighlight();
    clearHelpers();
    draggingJoint = null;
  }
};

const onWheel = (event) => {
  if (!isDragging || !draggingJoint) return;

  event.preventDefault();

  const degreesPerScroll = 1;
  const angleDelta = (event.deltaY / 100) * degreesPerScroll * (Math.PI / 180);

  // Use current initial angle (which tracks the latest local state)
  const potentialNewAngle = initialJointAngle - angleDelta;
  let clampedAngle = potentialNewAngle;

  if (draggingJoint.limit) {
    if (potentialNewAngle < draggingJoint.limit.lower) clampedAngle = draggingJoint.limit.lower;
    if (potentialNewAngle > draggingJoint.limit.upper) clampedAngle = draggingJoint.limit.upper;
  }

  // Determine actual change allowed
  const actualChange = clampedAngle - initialJointAngle;

  // Check if blocked (trying to move but stuck)
  if (Math.abs(angleDelta) > 1e-6 && Math.abs(actualChange) < 1e-6) {
    // Only trigger if we are actively trying to push past the limit
    // i.e., angleDelta is pushing further in the direction of the limit
    const isPushingLower = angleDelta > 0 && draggingJoint.limit && Math.abs(initialJointAngle - draggingJoint.limit.lower) < 1e-4;
    const isPushingUpper = angleDelta < 0 && draggingJoint.limit && Math.abs(initialJointAngle - draggingJoint.limit.upper) < 1e-4;

    if (isPushingLower) {
        triggerLimitToast('Joint at minimum limit');
    } else if (isPushingUpper) {
        triggerLimitToast('Joint at maximum limit');
    }
  }

  initialJointAngle = clampedAngle;
  // Accumulate only the allowed change to send to backend
  accumulatedDeltaAngle += actualChange;

  // Optimistic local update: move the rendered joint the instant the user
  // scrolls instead of waiting for the backend round-trip + 30 Hz telemetry.
  // That open-loop round-trip is what made control feel choppy ("一段一段").
  // The command is still sent at JOINT_CONTROL_HZ for the real robot; the
  // animate loop eases the display toward this target, and telemetry takes
  // over again on pointer-up (see the drag guard in handleJointStateUpdate).
  const stateKey = draggingSide ? `${draggingSide}_${draggingJoint.urdfName}` : draggingJoint.urdfName;
  const entry = jointSmoothing[stateKey];
  if (entry) entry.target = clampedAngle;
  currentJointAngles.value[stateKey] = clampedAngle;
};

const onPointerUp = () => {
  if (isDragging) {
    if (jointControlTimer) {
      clearInterval(jointControlTimer);
      jointControlTimer = null;
    }
    if (accumulatedDeltaAngle !== 0) {
      sendJointCommand(draggingJoint.urdfName, accumulatedDeltaAngle, draggingSide);
      accumulatedDeltaAngle = 0;
    }
    isDragging = false;
    draggingJoint = null;
    draggingSide = null;
    controls.enabled = true;
  }
};

// --- Helper functions ---

const highlightLink = (linkObject) => {
  resetHighlight();

  const traverseVisualsOnly = (object) => {
    if (object.isMesh && !object.isCustomHelper) {
      // Only emissive-capable materials can glow
      if (object.material && object.material.emissive) {
        const newMaterial = object.material.clone();
        newMaterial.emissive.setHex(0x1A5E4A);
        newMaterial.emissiveIntensity = 0.8;
        newMaterial.color.setHex(0x88ccaa);
        object.material = newMaterial;
        selectedMeshes.push(object);
      }
    }

    // Recurse into children, but stop at part boundaries.
    if (object.children) {
      for (const child of object.children) {
        // Key logic: a 'URDFJoint' or 'URDFLink' child marks the start of the
        // next part, so skip it — don't recurse in (we only want to highlight
        // the meshes of the currently selected link).
        // Note: in urdf-loader a Joint is typically a child of a Link.
        if (child.isURDFJoint || child.isURDFLink || child.type === 'URDFJoint' || child.type === 'URDFLink') {
          continue;
        }

        // Otherwise (usually Visual, Collision, Group, etc.) keep recursing for meshes.
        traverseVisualsOnly(child);
      }
    }
  };

  // Start from the currently selected link.
  traverseVisualsOnly(linkObject);
};

const resetHighlight = () => {
  if (selectedMeshes.length > 0) {
    selectedMeshes.forEach(mesh => {
      mesh.material.dispose();
      if (mesh.userData.originalMaterial) {
        mesh.material = mesh.userData.originalMaterial;
      }
    });
    selectedMeshes = [];
  }
};

const disableRaycast = (obj) => {
  obj.raycast = () => { };
  obj.traverse(child => { child.raycast = () => { }; });
};

const createLabelSprite = (text, color) => {
  const canvas = document.createElement('canvas');
  const size = 64;
  canvas.width = size; canvas.height = size;
  const context = canvas.getContext('2d');
  context.font = 'bold 48px Arial';
  context.textAlign = 'center';
  context.textBaseline = 'middle';
  context.fillStyle = color;
  context.fillText(text, size / 2, size / 2);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const material = new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false });
  const sprite = new THREE.Sprite(material);
  sprite.scale.set(0.05, 0.05, 1);
  sprite.isCustomHelper = true;
  return sprite;
};

const addAxesHelper = (linkObject) => {
  const axisLength = 0.15;
  const axesHelper = new THREE.AxesHelper(axisLength);
  axesHelper.material.depthTest = false;
  axesHelper.renderOrder = 999;
  axesHelper.traverse(c => { if (c.isLine) c.material.depthTest = false; });

  const labelOffset = axisLength + 0.03;
  const labelX = createLabelSprite('X', '#ff3333'); labelX.position.set(labelOffset, 0, 0); axesHelper.add(labelX);
  const labelY = createLabelSprite('Y', '#33ff33'); labelY.position.set(0, labelOffset, 0); axesHelper.add(labelY);
  const labelZ = createLabelSprite('Z', '#3333ff'); labelZ.position.set(0, 0, labelOffset); axesHelper.add(labelZ);

  axesHelper.isCustomHelper = true;
  disableRaycast(axesHelper);

  linkObject.add(axesHelper);
  window.lastHelperParent = linkObject;
};

const clearHelpers = () => {
  if (window.lastHelperParent) {
    const oldHelpers = window.lastHelperParent.children.filter(c => c.isCustomHelper);
    oldHelpers.forEach(h => {
      window.lastHelperParent.remove(h);
      if (h.geometry) h.geometry.dispose();
      if (h.material) {
        if (Array.isArray(h.material)) h.material.forEach(m => m.dispose());
        else h.material.dispose();
      }
    });
    window.lastHelperParent = null;
  }
};

const addJointDirectionHelper = (linkObject, joint) => {
  const type = joint.jointType;
  const axisVector = joint.axis;
  if (type === 'fixed') return;

  const material = new THREE.MeshBasicMaterial({
    color: 0xF1C947, transparent: true, opacity: 0.8, side: THREE.DoubleSide, depthTest: false
  });

  let helperMesh;
  if (type === 'revolute' || type === 'continuous') {
    const geometry = new THREE.TorusGeometry(0.2, 0.005, 16, 64);
    helperMesh = new THREE.Mesh(geometry, material);

    const arrowHelper = new THREE.ArrowHelper(
      axisVector.clone().normalize(), new THREE.Vector3(0, 0, 0), 0.35, 0xF1C947, 0.08, 0.06
    );
    arrowHelper.line.material.depthTest = false;
    arrowHelper.cone.material.depthTest = false;
    arrowHelper.isCustomHelper = true;
    disableRaycast(arrowHelper);
    linkObject.add(arrowHelper);

  } else if (type === 'prismatic') {
    const geometry = new THREE.CylinderGeometry(0.01, 0.01, 0.5, 8);
    helperMesh = new THREE.Mesh(geometry, material);
  }

  if (helperMesh) {
    helperMesh.renderOrder = 999;
    helperMesh.isCustomHelper = true;
    disableRaycast(helperMesh);
    const defaultNormal = (type === 'prismatic') ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(0, 0, 1);
    helperMesh.quaternion.setFromUnitVectors(defaultNormal, axisVector.clone().normalize());
    linkObject.add(helperMesh);
  }
};

const onWindowResize = () => {
  if (!canvasContainer.value) return;
  camera.aspect = canvasContainer.value.clientWidth / canvasContainer.value.clientHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(canvasContainer.value.clientWidth, canvasContainer.value.clientHeight);
};

onMounted(() => {
  initScene();
  window.addEventListener('mujoco-joint-states', handleJointStateUpdate);
  window.addEventListener('point-cloud-update', (e) => updatePointCloud(e.detail));
});

onUnmounted(() => {
  window.removeEventListener('resize', onWindowResize);
  window.removeEventListener('mujoco-joint-states', handleJointStateUpdate);
  if (pointCloudPoints) {
    scene.remove(pointCloudPoints);
  }
  if (pointCloudGeometry) {
    pointCloudGeometry.dispose();
  }
  if (pointCloudMaterial) {
    pointCloudMaterial.dispose();
  }
  if (renderer && renderer.domElement) {
    renderer.domElement.removeEventListener('wheel', onWheel);
  }
  if (jointControlTimer) {
    clearInterval(jointControlTimer);
    jointControlTimer = null;
  }
});
</script>

<style scoped>
.robot-stage-3d {
  flex: 1;
  position: relative;
  overflow: hidden;
  display: flex;
}

.glow-overlay {

  position: absolute;

  bottom: -10%;

  left: 50%;

  transform: translateX(-50%);

  width: 80%;

  height: 20%;

  pointer-events: none;

}



.limit-toast {

  position: absolute;

  top: 20px;

  left: 50%;

  transform: translateX(-50%) translateY(-20px);

  background: rgba(255, 50, 50, 0.8);

  color: white;

  padding: 8px 16px;

  border-radius: 8px;

  font-weight: bold;

  font-size: 14px;

  backdrop-filter: blur(4px);

  opacity: 0;

  transition: opacity 0.3s, transform 0.3s;

  pointer-events: none;

  z-index: 1000;

}



.limit-toast.visible {

  opacity: 1;

  transform: translateX(-50%) translateY(0);

}

</style>
