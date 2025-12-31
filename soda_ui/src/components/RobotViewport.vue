<template>
  <div class="robot-stage-3d" ref="canvasContainer">
    <!-- 装饰性的底层光效 -->
    <div class="glow-overlay"></div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls';
import URDFLoader from 'urdf-loader';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';

const props = defineProps({
  pointCloudData: { type: Array, default: null },
  showPointCloud: { type: Boolean, default: true }
});

const canvasContainer = ref(null);
let scene, camera, renderer, controls, loader;
let raycaster, pointer;
let robotModel = null;
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

// Three.js Logic (保持原有的大部分代码，略微精简)
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

  manager.setURLModifier((url) => {
    if (url.startsWith('./')) {
      return `http://localhost:8080/assets/l6y_gp100/${url.substring(2)}`;
    }
    return url;
  });

  manager.onLoad = () => {
    if (robotModel) {
      robotModel.traverse((child) => {
        if (child.isMesh) {
          child.material = metalMaterial;
          child.castShadow = true;
          child.receiveShadow = true;
          child.userData.originalMaterial = metalMaterial;
        }
      });
    }
  };

  const loadURDF = async () => {
    try {
      const response = await fetch('http://localhost:8080/urdf');
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      const urdfUrl = data.url;
      loader.load(urdfUrl, robot => {
        robotModel = robot;
        scene.add(robot);
        const box = new THREE.Box3().setFromObject(robot);
        const center = box.getCenter(new THREE.Vector3());
        robot.position.sub(center);
      });
    } catch (error) {
      console.error('Failed to load URDF:', error);
    }
  };

  loadURDF();

  const animate = () => {
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
  };
  animate();

  window.addEventListener('resize', onWindowResize);
  renderer.domElement.addEventListener('pointerdown', onPointerDown);
  window.addEventListener('pointermove', onPointerMove);
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

const sendJointCommand = (jointName, angle) => {
  fetch('http://localhost:8080/api/joint/set', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      joint_name: jointName,
      angle: angle
    })
  }).catch(error => console.error('Failed to send joint command:', error));
};

// Mimic joint definitions for GP100 gripper parallel linkage
const MIMIC_JOINTS = {
  'gripper_left_joint_1': [
    'gripper_left_joint_2',
    'gripper_left_helper_joint',
    'gripper_right_joint_1',
    'gripper_right_joint_2',
    'gripper_right_helper_joint'
  ]
};

const handleJointStateUpdate = (event) => {
  if (!robotModel) return;

  const jointStates = event.detail;

  jointStates.forEach(joint => {
    const jointName = joint.name;
    const angle = joint.angle;

    const jointObj = findJointByName(robotModel, jointName);
    if (jointObj && jointObj.setJointValue) {
      jointObj.setJointValue(angle);
    }

    // Handle mimic joints (parallel linkage)
    if (MIMIC_JOINTS[jointName]) {
      MIMIC_JOINTS[jointName].forEach(mimicName => {
        const mimicJoint = findJointByName(robotModel, mimicName);
        if (mimicJoint && mimicJoint.setJointValue) {
          mimicJoint.setJointValue(angle);
        }
      });
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
  if (!robotModel) return;

  const rect = canvasContainer.value.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

  raycaster.setFromCamera(pointer, camera);
  // 此时辅助线已经 disableRaycast 了，不会挡路
  const intersects = raycaster.intersectObject(robotModel, true);

  if (intersects.length > 0) {
    const hitObject = intersects[0].object;

    // 寻找 Link
    let targetLink = hitObject;
    while (targetLink && targetLink !== robotModel) {
      if (targetLink.type === 'URDFLink') break;
      targetLink = targetLink.parent;
    }
    if (!targetLink || targetLink === robotModel) targetLink = hitObject.parent;

    // 选中逻辑
    highlightLink(targetLink);
    clearHelpers();
    addAxesHelper(targetLink);

    // 获取对应的 Joint (通常 Link 的 parent 就是 Joint)
    const targetJoint = targetLink.parent;

    if (targetJoint && targetJoint.isURDFJoint) {
      addJointDirectionHelper(targetLink, targetJoint);

      // === 准备拖拽 ===
      // 只有旋转关节才允许拖拽 (fixed 无法动)
      if (targetJoint.jointType === 'revolute' || targetJoint.jointType === 'continuous') {
        draggingJoint = targetJoint;
        isDragging = true;
        dragStartPoint.x = event.clientX;
        dragStartPoint.y = event.clientY;

        // 读取当前角度 (urdf-loader 通常会在 joint 上挂载 angle 属性或 setJointValue 方法)
        // 我们这里使用 joint.angle (getter)
        initialJointAngle = draggingJoint.angle || 0;

        // 关键：禁用 OrbitControls，防止拖拽时旋转视角
        controls.enabled = false;
      }
    }
  } else {
    // 点击空白
    resetHighlight();
    clearHelpers();
    draggingJoint = null;
  }
};

// --- 2. 移动：计算角度并更新 ---
const onPointerMove = (event) => {
  if (!isDragging || !draggingJoint) return;

  const deltaX = event.clientX - dragStartPoint.x;
  const sensitivity = 0.01;
  const angleDelta = deltaX * sensitivity;
  let newAngle = initialJointAngle + angleDelta;

  if (draggingJoint.limits) {
    if (newAngle < draggingJoint.limits.lower) newAngle = draggingJoint.limits.lower;
    if (newAngle > draggingJoint.limits.upper) newAngle = draggingJoint.limits.upper;
  }

  sendJointCommand(draggingJoint.urdfName, newAngle);
};

// --- 3. 抬起：结束拖拽 ---
const onPointerUp = () => {
  if (isDragging) {
    isDragging = false;
    draggingJoint = null;
    // 恢复视角控制
    controls.enabled = true;
  }
};

// --- 辅助功能 (保持之前的修复版本) ---

const highlightLink = (linkObject) => {
  // 1. 先清除之前的高亮
  resetHighlight();

  // 2. 定义一个递归函数，专门控制遍历深度
  const traverseVisualsOnly = (object) => {
    // A. 处理当前的 Mesh
    if (object.isMesh && !object.isCustomHelper) {
      // 检查材质是否支持发光
      if (object.material && object.material.emissive) {
        const newMaterial = object.material.clone();
        newMaterial.emissive.setHex(0x1A5E4A);
        newMaterial.emissiveIntensity = 0.8;
        newMaterial.color.setHex(0x88ccaa);
        object.material = newMaterial;
        selectedMeshes.push(object);
      }
    }

    // B. 继续遍历子节点，但要设置“路障”
    if (object.children) {
      for (const child of object.children) {
        // === 关键逻辑 ===
        // 如果子节点是 'URDFJoint' 或 'URDFLink'，说明要进入下一个部件了，
        // 我们直接跳过，不再递归进去。
        // 注意：urdf-loader 中 Joint 通常是 Link 的子节点
        if (child.isURDFJoint || child.isURDFLink || child.type === 'URDFJoint' || child.type === 'URDFLink') {
          continue;
        }

        // 否则（通常是 Visual, Collision, Group 等），继续递归查找 Mesh
        traverseVisualsOnly(child);
      }
    }
  };

  // 从当前选中的 Link 开始执行
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
</style>