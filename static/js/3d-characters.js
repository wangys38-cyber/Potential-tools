/**
 * 首页卡片3D角色渲染模块
 * 五个角色：云朵、机器人、星球、向日葵、爱心
 * 基于Three.js r160
 */

function create3DCharacter(container, type, options) {
  options = options || {};
  var width = options.width || 100;
  var height = options.height || 100;
  var scale = options.scale || 1.2;

  // 创建canvas
  var canvas = document.createElement('canvas');
  canvas.width = width * 2;
  canvas.height = height * 2;
  canvas.style.width = width + 'px';
  canvas.style.height = height + 'px';
  canvas.style.display = 'block';
  container.appendChild(canvas);

  // Three.js 场景
  var scene = new THREE.Scene();
  
  // 相机
  var camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
  camera.position.set(0, 0.3, 5);
  camera.lookAt(0, 0, 0);

  // 渲染器
  var renderer = new THREE.WebGLRenderer({ 
    canvas: canvas, 
    antialias: true, 
    alpha: true 
  });
  renderer.setSize(width * 2, height * 2);
  renderer.setPixelRatio(1);
  renderer.setClearColor(0x000000, 0);

  // 灯光
  var ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
  scene.add(ambientLight);

  var mainLight = new THREE.DirectionalLight(0xffffff, 0.9);
  mainLight.position.set(2, 3, 4);
  scene.add(mainLight);

  var rimLight = new THREE.DirectionalLight(0x88ccff, 0.4);
  rimLight.position.set(-2, 1, -2);
  scene.add(rimLight);

  // 创建角色组
  var characterGroup = new THREE.Group();
  characterGroup.scale.setScalar(scale);
  scene.add(characterGroup);

  // 动画状态
  var isHovering = false;
  var animationId = null;
  var time = 0;
  var blinkTimer = 0;
  var isBlinking = false;

  // 眼睛引用（用于眨眼动画）
  var leftEye = null;
  var rightEye = null;

  // 根据类型创建角色
  switch(type) {
    case 'cloud':
      createCloud(characterGroup);
      break;
    case 'robot':
      createRobot(characterGroup);
      break;
    case 'planet':
      createPlanet(characterGroup);
      break;
    case 'sunflower':
      createSunflower(characterGroup);
      break;
    case 'heart':
      createHeart(characterGroup);
      break;
    default:
      createCloud(characterGroup);
  }

  // 创建云朵角色
  function createCloud(group) {
    // 云朵主体（多个球体组合）
    var cloudMaterial = new THREE.MeshPhongMaterial({ 
      color: 0xffffff, 
      shininess: 80,
      specular: 0xdddddd
    });

    var cloudGroup = new THREE.Group();
    
    // 主体
    var mainBody = new THREE.Mesh(
      new THREE.SphereGeometry(0.8, 32, 32),
      cloudMaterial
    );
    mainBody.position.set(0, -0.1, 0);
    mainBody.scale.set(1.2, 0.9, 1);
    cloudGroup.add(mainBody);

    // 左球
    var leftBall = new THREE.Mesh(
      new THREE.SphereGeometry(0.55, 32, 32),
      cloudMaterial
    );
    leftBall.position.set(-0.7, 0, 0.1);
    cloudGroup.add(leftBall);

    // 右球
    var rightBall = new THREE.Mesh(
      new THREE.SphereGeometry(0.55, 32, 32),
      cloudMaterial
    );
    rightBall.position.set(0.7, 0, 0.1);
    cloudGroup.add(rightBall);

    // 上球
    var topBall = new THREE.Mesh(
      new THREE.SphereGeometry(0.5, 32, 32),
      cloudMaterial
    );
    topBall.position.set(0, 0.5, 0);
    cloudGroup.add(topBall);

    group.add(cloudGroup);

    // 皇冠
    var crownMaterial = new THREE.MeshPhongMaterial({ 
      color: 0xffd700, 
      shininess: 100,
      specular: 0xffee88
    });

    var crownGroup = new THREE.Group();
    crownGroup.position.set(0, 0.9, 0);

    // 皇冠底座
    var crownBase = new THREE.Mesh(
      new THREE.CylinderGeometry(0.35, 0.4, 0.15, 32),
      crownMaterial
    );
    crownGroup.add(crownBase);

    // 皇冠尖
    for (var i = 0; i < 5; i++) {
      var angle = (i / 5) * Math.PI * 2;
      var spike = new THREE.Mesh(
        new THREE.ConeGeometry(0.08, 0.25, 8),
        crownMaterial
      );
      spike.position.set(
        Math.cos(angle) * 0.3,
        0.15,
        Math.sin(angle) * 0.3
      );
      crownGroup.add(spike);
    }

    group.add(crownGroup);

    // 眼睛
    leftEye = createEye(-0.3, 0, 0.7);
    rightEye = createEye(0.3, 0, 0.7);
    group.add(leftEye);
    group.add(rightEye);

    // 微笑
    var smile = createSmile(0, -0.25, 0.75);
    group.add(smile);

    // 腮红
    var blushMaterial = new THREE.MeshPhongMaterial({ 
      color: 0xffb6c1, 
      transparent: true, 
      opacity: 0.6 
    });
    var leftBlush = new THREE.Mesh(
      new THREE.SphereGeometry(0.15, 16, 16),
      blushMaterial
    );
    leftBlush.position.set(-0.55, -0.15, 0.6);
    leftBlush.scale.set(1, 0.6, 0.3);
    group.add(leftBlush);

    var rightBlush = leftBlush.clone();
    rightBlush.position.x = 0.55;
    group.add(rightBlush);
  }

  // 创建机器人角色
  function createRobot(group) {
    // 机器人身体
    var bodyMaterial = new THREE.MeshPhongMaterial({ 
      color: 0xe8f4ff, 
      shininess: 90,
      specular: 0xffffff
    });

    var blueMaterial = new THREE.MeshPhongMaterial({ 
      color: 0x6bb6ff, 
      shininess: 80 
    });

    // 头部
    var head = new THREE.Mesh(
      new THREE.BoxGeometry(1.1, 0.9, 0.8),
      bodyMaterial
    );
    head.position.set(0, 0.2, 0);
    group.add(head);

    // 头部圆角（用小球装饰）
    var cornerPositions = [
      [-0.55, 0.65, 0.4], [0.55, 0.65, 0.4],
      [-0.55, -0.25, 0.4], [0.55, -0.25, 0.4]
    ];
    cornerPositions.forEach(function(pos) {
      var corner = new THREE.Mesh(
        new THREE.SphereGeometry(0.12, 16, 16),
        bodyMaterial
      );
      corner.position.set(pos[0], pos[1], pos[2]);
      group.add(corner);
    });

    // 天线
    var antenna = new THREE.Mesh(
      new THREE.CylinderGeometry(0.03, 0.03, 0.3, 8),
      blueMaterial
    );
    antenna.position.set(0, 0.85, 0);
    group.add(antenna);

    var antennaBall = new THREE.Mesh(
      new THREE.SphereGeometry(0.1, 16, 16),
      new THREE.MeshPhongMaterial({ color: 0xff6b6b, shininess: 100 })
    );
    antennaBall.position.set(0, 1.05, 0);
    group.add(antennaBall);

    // 眼睛（大屏幕）
    var eyeScreenMaterial = new THREE.MeshPhongMaterial({ 
      color: 0x1a1a2e, 
      shininess: 100,
      emissive: 0x0a0a15
    });

    var eyeScreen = new THREE.Mesh(
      new THREE.BoxGeometry(0.8, 0.45, 0.05),
      eyeScreenMaterial
    );
    eyeScreen.position.set(0, 0.25, 0.42);
    group.add(eyeScreen);

    // 眼睛（屏幕内的大眼睛）
    leftEye = createEye(-0.18, 0.25, 0.48, 0.12);
    rightEye = createEye(0.18, 0.25, 0.48, 0.12);
    group.add(leftEye);
    group.add(rightEye);

    // 身体
    var body = new THREE.Mesh(
      new THREE.BoxGeometry(0.8, 0.5, 0.6),
      blueMaterial
    );
    body.position.set(0, -0.5, 0);
    group.add(body);

    // 身体按钮
    var buttonMaterial = new THREE.MeshPhongMaterial({ color: 0xffffff, shininess: 100 });
    var button1 = new THREE.Mesh(
      new THREE.CylinderGeometry(0.06, 0.06, 0.05, 16),
      buttonMaterial
    );
    button1.rotation.x = Math.PI / 2;
    button1.position.set(-0.15, -0.45, 0.32);
    group.add(button1);

    var button2 = button1.clone();
    button2.position.x = 0.15;
    group.add(button2);

    // 手臂
    var armMaterial = new THREE.MeshPhongMaterial({ color: 0xe8f4ff, shininess: 80 });
    var leftArm = new THREE.Mesh(
      new THREE.CylinderGeometry(0.08, 0.08, 0.4, 16),
      armMaterial
    );
    leftArm.position.set(-0.55, -0.4, 0);
    leftArm.rotation.z = 0.3;
    group.add(leftArm);

    var rightArm = leftArm.clone();
    rightArm.position.x = 0.55;
    rightArm.rotation.z = -0.3;
    group.add(rightArm);
  }

  // 创建星球角色
  function createPlanet(group) {
    // 星球主体
    var planetMaterial = new THREE.MeshPhongMaterial({ 
      color: 0x6bb6ff, 
      shininess: 80,
      specular: 0xaaddff
    });

    var planet = new THREE.Mesh(
      new THREE.SphereGeometry(0.75, 32, 32),
      planetMaterial
    );
    planet.position.set(0, 0, 0);
    group.add(planet);

    // 星球高光
    var highlightMaterial = new THREE.MeshPhongMaterial({ 
      color: 0xaaddff, 
      transparent: true, 
      opacity: 0.5,
      shininess: 100
    });
    var highlight = new THREE.Mesh(
      new THREE.SphereGeometry(0.3, 32, 32),
      highlightMaterial
    );
    highlight.position.set(-0.25, 0.25, 0.5);
    highlight.scale.set(1, 0.8, 0.3);
    group.add(highlight);

    // 光环
    var ringMaterial = new THREE.MeshPhongMaterial({ 
      color: 0x88ccff, 
      transparent: true, 
      opacity: 0.7,
      shininess: 100,
      side: THREE.DoubleSide
    });

    var ring = new THREE.Mesh(
      new THREE.RingGeometry(0.9, 1.1, 64),
      ringMaterial
    );
    ring.rotation.x = Math.PI / 2.5;
    ring.rotation.z = 0.2;
    group.add(ring);

    // 光环内圈
    var innerRing = new THREE.Mesh(
      new THREE.RingGeometry(0.95, 1.0, 64),
      new THREE.MeshPhongMaterial({ 
        color: 0xffffff, 
        transparent: true, 
        opacity: 0.8,
        side: THREE.DoubleSide
      })
    );
    innerRing.rotation.x = Math.PI / 2.5;
    innerRing.rotation.z = 0.2;
    group.add(innerRing);

    // 星星装饰
    var starMaterial = new THREE.MeshPhongMaterial({ 
      color: 0xffd700, 
      shininess: 100,
      emissive: 0x443300
    });

    var starPositions = [
      [0.9, 0.5, 0.3, 0.12],
      [-0.8, 0.4, 0.4, 0.08],
      [0.5, -0.6, 0.5, 0.1],
      [-0.6, -0.5, 0.3, 0.07]
    ];

    starPositions.forEach(function(pos) {
      var star = createStar(starMaterial);
      star.position.set(pos[0], pos[1], pos[2]);
      star.scale.setScalar(pos[3]);
      group.add(star);
    });

    // 眼睛
    leftEye = createEye(-0.22, 0.1, 0.65, 0.14);
    rightEye = createEye(0.22, 0.1, 0.65, 0.14);
    group.add(leftEye);
    group.add(rightEye);

    // 微笑
    var smile = createSmile(0, -0.15, 0.7, 0.25);
    group.add(smile);

    // 腮红
    var blushMaterial = new THREE.MeshPhongMaterial({ 
      color: 0xff9999, 
      transparent: true, 
      opacity: 0.5 
    });
    var leftBlush = new THREE.Mesh(
      new THREE.SphereGeometry(0.12, 16, 16),
      blushMaterial
    );
    leftBlush.position.set(-0.45, -0.05, 0.55);
    leftBlush.scale.set(1, 0.6, 0.3);
    group.add(leftBlush);

    var rightBlush = leftBlush.clone();
    rightBlush.position.x = 0.45;
    group.add(rightBlush);
  }

  // 创建向日葵角色
  function createSunflower(group) {
    // 花瓣
    var petalMaterial = new THREE.MeshPhongMaterial({ 
      color: 0xffd700, 
      shininess: 60,
      specular: 0xffee88
    });

    var petalGroup = new THREE.Group();
    var petalCount = 12;

    for (var i = 0; i < petalCount; i++) {
      var angle = (i / petalCount) * Math.PI * 2;
      var petal = new THREE.Mesh(
        new THREE.SphereGeometry(0.25, 16, 16),
        petalMaterial
      );
      petal.position.set(
        Math.cos(angle) * 0.55,
        Math.sin(angle) * 0.55,
        0
      );
      petal.scale.set(0.5, 1.2, 0.3);
      petal.rotation.z = angle;
      petalGroup.add(petal);
    }

    group.add(petalGroup);

    // 花心
    var centerMaterial = new THREE.MeshPhongMaterial({ 
      color: 0x8b4513, 
      shininess: 40
    });

    var center = new THREE.Mesh(
      new THREE.SphereGeometry(0.45, 32, 32),
      centerMaterial
    );
    center.position.set(0, 0, 0.1);
    center.scale.set(1, 1, 0.5);
    group.add(center);

    // 花心纹理（小点）
    var dotMaterial = new THREE.MeshPhongMaterial({ color: 0x5c2e0e });
    for (var j = 0; j < 15; j++) {
      var dotAngle = Math.random() * Math.PI * 2;
      var dotRadius = Math.random() * 0.3;
      var dot = new THREE.Mesh(
        new THREE.SphereGeometry(0.03, 8, 8),
        dotMaterial
      );
      dot.position.set(
        Math.cos(dotAngle) * dotRadius,
        Math.sin(dotAngle) * dotRadius,
        0.35
      );
      group.add(dot);
    }

    // 眼睛
    leftEye = createEye(-0.15, 0.05, 0.4, 0.1);
    rightEye = createEye(0.15, 0.05, 0.4, 0.1);
    group.add(leftEye);
    group.add(rightEye);

    // 微笑
    var smile = createSmile(0, -0.1, 0.45, 0.2);
    group.add(smile);

    // 叶子
    var leafMaterial = new THREE.MeshPhongMaterial({ 
      color: 0x228b22, 
      shininess: 50 
    });

    var leaf = new THREE.Mesh(
      new THREE.SphereGeometry(0.3, 16, 16),
      leafMaterial
    );
    leaf.position.set(-0.7, -0.5, -0.2);
    leaf.scale.set(0.6, 1.2, 0.2);
    leaf.rotation.z = -0.5;
    group.add(leaf);

    var leaf2 = leaf.clone();
    leaf2.position.set(0.7, -0.6, -0.2);
    leaf2.rotation.z = 0.5;
    group.add(leaf2);
  }

  // 创建爱心角色
  function createHeart(group) {
    // 爱心主体
    var heartMaterial = new THREE.MeshPhongMaterial({ 
      color: 0xff6b9d, 
      shininess: 80,
      specular: 0xffaacc
    });

    var heartGroup = new THREE.Group();

    // 爱心由两个球体和一个圆锥组合
    var leftLobe = new THREE.Mesh(
      new THREE.SphereGeometry(0.45, 32, 32),
      heartMaterial
    );
    leftLobe.position.set(-0.3, 0.25, 0);
    leftLobe.scale.set(1, 1.1, 0.8);
    heartGroup.add(leftLobe);

    var rightLobe = leftLobe.clone();
    rightLobe.position.x = 0.3;
    heartGroup.add(rightLobe);

    // 爱心底部（圆锥）
    var bottom = new THREE.Mesh(
      new THREE.ConeGeometry(0.65, 0.8, 32),
      heartMaterial
    );
    bottom.position.set(0, -0.35, 0);
    bottom.rotation.x = Math.PI;
    bottom.scale.set(1, 1, 0.8);
    heartGroup.add(bottom);

    group.add(heartGroup);

    // 小角
    var hornMaterial = new THREE.MeshPhongMaterial({ 
      color: 0xff4488, 
      shininess: 100 
    });

    var leftHorn = new THREE.Mesh(
      new THREE.ConeGeometry(0.1, 0.25, 8),
      hornMaterial
    );
    leftHorn.position.set(-0.35, 0.7, 0);
    leftHorn.rotation.z = 0.3;
    group.add(leftHorn);

    var rightHorn = leftHorn.clone();
    rightHorn.position.x = 0.35;
    rightHorn.rotation.z = -0.3;
    group.add(rightHorn);

    // 眼睛
    leftEye = createEye(-0.2, 0.1, 0.5, 0.12);
    rightEye = createEye(0.2, 0.1, 0.5, 0.12);
    group.add(leftEye);
    group.add(rightEye);

    // 微笑
    var smile = createSmile(0, -0.1, 0.55, 0.2);
    group.add(smile);

    // 小爱心装饰
    var smallHeartMaterial = new THREE.MeshPhongMaterial({ 
      color: 0xff99bb, 
      shininess: 80 
    });

    var smallHeart = new THREE.Group();
    var sh1 = new THREE.Mesh(
      new THREE.SphereGeometry(0.08, 16, 16),
      smallHeartMaterial
    );
    sh1.position.set(-0.05, 0.03, 0);
    smallHeart.add(sh1);
    var sh2 = sh1.clone();
    sh2.position.x = 0.05;
    smallHeart.add(sh2);
    var sh3 = new THREE.Mesh(
      new THREE.ConeGeometry(0.08, 0.1, 8),
      smallHeartMaterial
    );
    sh3.position.set(0, -0.05, 0);
    sh3.rotation.x = Math.PI;
    smallHeart.add(sh3);

    smallHeart.position.set(0.6, 0.5, 0.2);
    smallHeart.scale.setScalar(0.8);
    group.add(smallHeart);
  }

  // 创建眼睛
  function createEye(x, y, z, size) {
    size = size || 0.12;
    var eyeGroup = new THREE.Group();
    eyeGroup.position.set(x, y, z);

    // 眼白
    var eyeWhite = new THREE.Mesh(
      new THREE.SphereGeometry(size, 24, 24),
      new THREE.MeshPhongMaterial({ color: 0xffffff, shininess: 100 })
    );
    eyeWhite.scale.set(1, 1.2, 0.5);
    eyeGroup.add(eyeWhite);

    // 瞳孔
    var pupil = new THREE.Mesh(
      new THREE.SphereGeometry(size * 0.55, 16, 16),
      new THREE.MeshPhongMaterial({ color: 0x1a1a2e, shininess: 100 })
    );
    pupil.position.set(0, 0, size * 0.4);
    pupil.scale.set(1, 1.1, 0.6);
    eyeGroup.add(pupil);

    // 高光
    var highlight = new THREE.Mesh(
      new THREE.SphereGeometry(size * 0.2, 8, 8),
      new THREE.MeshPhongMaterial({ color: 0xffffff, shininess: 100 })
    );
    highlight.position.set(size * 0.2, size * 0.2, size * 0.7);
    eyeGroup.add(highlight);

    eyeGroup.userData = { eyeWhite: eyeWhite, pupil: pupil };
    return eyeGroup;
  }

  // 创建微笑
  function createSmile(x, y, z, width) {
    width = width || 0.2;
    var smileGroup = new THREE.Group();
    smileGroup.position.set(x, y, z);

    var points = [];
    for (var i = 0; i <= 20; i++) {
      var t = (i / 20) * Math.PI;
      points.push(new THREE.Vector3(
        Math.cos(t) * width,
        -Math.sin(t) * width * 0.6,
        0
      ));
    }

    var curve = new THREE.CatmullRomCurve3(points);
    var geometry = new THREE.TubeGeometry(curve, 20, 0.02, 8, false);
    var material = new THREE.MeshPhongMaterial({ color: 0x1a1a2e, shininess: 50 });
    var smile = new THREE.Mesh(geometry, material);
    smileGroup.add(smile);

    return smileGroup;
  }

  // 创建星星
  function createStar(material) {
    var starGroup = new THREE.Group();
    var shape = new THREE.Shape();
    
    var outerRadius = 1;
    var innerRadius = 0.4;
    var points = 5;

    for (var i = 0; i < points * 2; i++) {
      var radius = (i % 2 === 0) ? outerRadius : innerRadius;
      var angle = (i / (points * 2)) * Math.PI * 2 - Math.PI / 2;
      var x = Math.cos(angle) * radius;
      var y = Math.sin(angle) * radius;
      if (i === 0) {
        shape.moveTo(x, y);
      } else {
        shape.lineTo(x, y);
      }
    }
    shape.closePath();

    var extrudeSettings = { depth: 0.2, bevelEnabled: true, bevelThickness: 0.1, bevelSize: 0.1, bevelSegments: 3 };
    var geometry = new THREE.ExtrudeGeometry(shape, extrudeSettings);
    geometry.center();

    var star = new THREE.Mesh(geometry, material);
    starGroup.add(star);

    return starGroup;
  }

  // 动画循环
  function animate() {
    animationId = requestAnimationFrame(animate);
    time += 0.016;

    // 呼吸动画
    var breathe = Math.sin(time * 2) * 0.03;
    characterGroup.scale.setScalar(scale * (1 + breathe));

    // 轻微摇摆
    characterGroup.rotation.y = Math.sin(time * 0.8) * 0.1;
    characterGroup.rotation.x = Math.sin(time * 0.6) * 0.05;

    // 眨眼动画
    blinkTimer += 0.016;
    if (blinkTimer > 3 + Math.random() * 2) {
      isBlinking = true;
      blinkTimer = 0;
    }

    if (isBlinking) {
      if (leftEye && rightEye) {
        leftEye.scale.y = Math.max(0.1, leftEye.scale.y - 0.15);
        rightEye.scale.y = Math.max(0.1, rightEye.scale.y - 0.15);
        if (leftEye.scale.y <= 0.15) {
          isBlinking = false;
        }
      }
    } else {
      if (leftEye && rightEye) {
        leftEye.scale.y = Math.min(1, leftEye.scale.y + 0.1);
        rightEye.scale.y = Math.min(1, rightEye.scale.y + 0.1);
      }
    }

    // 悬停时加速旋转
    if (isHovering) {
      characterGroup.rotation.y += 0.02;
      characterGroup.position.y = Math.sin(time * 3) * 0.1;
    } else {
      characterGroup.position.y = 0;
    }

    renderer.render(scene, camera);
  }

  // 鼠标悬停交互
  container.addEventListener('mouseenter', function() {
    isHovering = true;
  });

  container.addEventListener('mouseleave', function() {
    isHovering = false;
  });

  // 性能优化：不可见时暂停渲染
  var observer = new IntersectionObserver(function(entries) {
    entries.forEach(function(entry) {
      if (entry.isIntersecting) {
        if (!animationId) animate();
      } else {
        if (animationId) {
          cancelAnimationFrame(animationId);
          animationId = null;
        }
      }
    });
  }, { threshold: 0.1 });

  observer.observe(container);

  // 启动动画
  animate();

  // 返回控制对象
  return {
    destroy: function() {
      if (animationId) cancelAnimationFrame(animationId);
      observer.disconnect();
      scene.traverse(function(obj) {
        if (obj.geometry) obj.geometry.dispose();
        if (obj.material) {
          if (Array.isArray(obj.material)) {
            obj.material.forEach(function(m) { m.dispose(); });
          } else {
            obj.material.dispose();
          }
        }
      });
      renderer.dispose();
      if (canvas.parentNode) canvas.parentNode.removeChild(canvas);
    }
  };
}
