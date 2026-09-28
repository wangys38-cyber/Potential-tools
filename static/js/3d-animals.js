/**
 * Three.js 3D 动物渲染模块
 * 为首页五张卡片创建灵动的3D动物
 * 
 * 动物类型：
 * - owl: 猫头鹰 (CR智能分析 - 智慧)
 * - bird: 小鸟 (邮件助手 - 传递)
 * - whale: 鲸鱼 (智能知识库 - 渊博)
 * - cow: 小牛 (牛马笔记 - 勤劳)
 * - fox: 狐狸 (研发知识图谱 - 聪明)
 */

(function() {
  'use strict';

  // 动物颜色配置（与卡片渐变色匹配）
  const ANIMAL_COLORS = {
    owl: { body: 0x8b5cf6, belly: 0xc4b5fd, accent: 0x6d28d9 },
    bird: { body: 0xec4899, belly: 0xfbcfe8, accent: 0xdb2777 },
    whale: { body: 0x3b82f6, belly: 0xbfdbfe, accent: 0x2563eb },
    cow: { body: 0x10b981, belly: 0xbbf7d0, accent: 0x059669 },
    fox: { body: 0x06b6d4, belly: 0xa5f3fc, accent: 0x0891b2 }
  };

  /**
   * 创建3D动物
   * @param {HTMLElement} container - 容器元素
   * @param {string} type - 动物类型
   * @param {object} options - 配置选项
   */
  function create3DAnimal(container, type, options = {}) {
    const width = options.width || 100;
    const height = options.height || 100;
    const scale = options.scale || 1;
    const colors = ANIMAL_COLORS[type] || ANIMAL_COLORS.owl;

    // 创建canvas
    const canvas = document.createElement('canvas');
    canvas.width = width * 2; // 2x for retina
    canvas.height = height * 2;
    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';
    canvas.style.display = 'block';
    container.appendChild(canvas);

    // Three.js 场景
    const scene = new THREE.Scene();
    
    // 相机
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
    camera.position.set(0, 0.5, 5);
    camera.lookAt(0, 0, 0);

    // 渲染器
    const renderer = new THREE.WebGLRenderer({ 
      canvas: canvas, 
      antialias: true, 
      alpha: true 
    });
    renderer.setSize(width * 2, height * 2);
    renderer.setPixelRatio(1);
    renderer.setClearColor(0x000000, 0);

    // 灯光
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
    scene.add(ambientLight);

    const mainLight = new THREE.DirectionalLight(0xffffff, 0.8);
    mainLight.position.set(2, 3, 4);
    scene.add(mainLight);

    const rimLight = new THREE.DirectionalLight(colors.body, 0.4);
    rimLight.position.set(-2, 1, -2);
    scene.add(rimLight);

    // 创建动物组
    const animalGroup = new THREE.Group();
    animalGroup.scale.setScalar(scale);
    scene.add(animalGroup);

    // 根据类型创建动物
    let animalParts = {};
    switch(type) {
      case 'owl':
        animalParts = createOwl(colors, animalGroup);
        break;
      case 'bird':
        animalParts = createBird(colors, animalGroup);
        break;
      case 'whale':
        animalParts = createWhale(colors, animalGroup);
        break;
      case 'cow':
        animalParts = createCow(colors, animalGroup);
        break;
      case 'fox':
        animalParts = createFox(colors, animalGroup);
        break;
      default:
        animalParts = createOwl(colors, animalGroup);
    }

    // 动画状态
    let isHovering = false;
    let animationId = null;
    let time = 0;

    // 动画循环
    function animate() {
      animationId = requestAnimationFrame(animate);
      time += 0.016;

      // 呼吸动画
      const breathe = Math.sin(time * 2) * 0.03;
      animalGroup.scale.setScalar(scale * (1 + breathe));

      // 轻微摇摆
      animalGroup.rotation.y = Math.sin(time * 0.8) * 0.1;
      animalGroup.rotation.x = Math.sin(time * 0.6) * 0.05;

      // 悬停时的动画
      if (isHovering) {
        animalGroup.position.y = Math.sin(time * 3) * 0.1;
        animalGroup.rotation.y += 0.02;
      } else {
        animalGroup.position.y *= 0.95;
      }

      // 特定部位动画
      if (animalParts.update) {
        animalParts.update(time, isHovering);
      }

      renderer.render(scene, camera);
    }

    // 启动动画
    animate();

    // 交互事件
    container.addEventListener('mouseenter', () => { isHovering = true; });
    container.addEventListener('mouseleave', () => { isHovering = false; });

    // 可见性检测（不可见时暂停渲染）
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
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

    // 返回控制对象
    return {
      destroy: function() {
        if (animationId) cancelAnimationFrame(animationId);
        observer.disconnect();
        renderer.dispose();
        container.removeChild(canvas);
      },
      setHover: function(value) { isHovering = value; }
    };
  }

  // ========== 动物创建函数 ==========

  /**
   * 创建猫头鹰
   */
  function createOwl(colors, group) {
    const parts = {};

    // 身体（椭圆球）
    const bodyGeo = new THREE.SphereGeometry(0.8, 32, 32);
    bodyGeo.scale(1, 1.2, 0.9);
    const bodyMat = new THREE.MeshPhongMaterial({ 
      color: colors.body, 
      shininess: 80,
      specular: 0x444444
    });
    const body = new THREE.Mesh(bodyGeo, bodyMat);
    body.position.y = -0.2;
    group.add(body);
    parts.body = body;

    // 肚子（浅色）
    const bellyGeo = new THREE.SphereGeometry(0.55, 32, 32);
    bellyGeo.scale(0.9, 1.1, 0.5);
    const bellyMat = new THREE.MeshPhongMaterial({ 
      color: colors.belly, 
      shininess: 60 
    });
    const belly = new THREE.Mesh(bellyGeo, bellyMat);
    belly.position.set(0, -0.3, 0.5);
    group.add(belly);

    // 头部
    const headGeo = new THREE.SphereGeometry(0.65, 32, 32);
    const headMat = new THREE.MeshPhongMaterial({ 
      color: colors.body, 
      shininess: 80 
    });
    const head = new THREE.Mesh(headGeo, headMat);
    head.position.y = 0.7;
    group.add(head);
    parts.head = head;

    // 耳朵（羽毛角）
    const earGeo = new THREE.ConeGeometry(0.2, 0.4, 8);
    const earMat = new THREE.MeshPhongMaterial({ color: colors.accent });
    const leftEar = new THREE.Mesh(earGeo, earMat);
    leftEar.position.set(-0.35, 1.2, 0);
    leftEar.rotation.z = 0.3;
    group.add(leftEar);
    const rightEar = new THREE.Mesh(earGeo, earMat);
    rightEar.position.set(0.35, 1.2, 0);
    rightEar.rotation.z = -0.3;
    group.add(rightEar);

    // 眼睛（大眼白+黑瞳）
    const eyeWhiteGeo = new THREE.SphereGeometry(0.22, 24, 24);
    const eyeWhiteMat = new THREE.MeshPhongMaterial({ color: 0xffffff, shininess: 100 });
    const leftEye = new THREE.Mesh(eyeWhiteGeo, eyeWhiteMat);
    leftEye.position.set(-0.22, 0.75, 0.55);
    group.add(leftEye);
    const rightEye = new THREE.Mesh(eyeWhiteGeo, eyeWhiteMat);
    rightEye.position.set(0.22, 0.75, 0.55);
    group.add(rightEye);

    // 瞳孔
    const pupilGeo = new THREE.SphereGeometry(0.1, 16, 16);
    const pupilMat = new THREE.MeshPhongMaterial({ color: 0x1a1a2e });
    const leftPupil = new THREE.Mesh(pupilGeo, pupilMat);
    leftPupil.position.set(-0.22, 0.75, 0.72);
    group.add(leftPupil);
    const rightPupil = new THREE.Mesh(pupilGeo, pupilMat);
    rightPupil.position.set(0.22, 0.75, 0.72);
    group.add(rightPupil);
    parts.pupils = [leftPupil, rightPupil];

    // 眼睛高光
    const highlightGeo = new THREE.SphereGeometry(0.03, 8, 8);
    const highlightMat = new THREE.MeshBasicMaterial({ color: 0xffffff });
    const leftHighlight = new THREE.Mesh(highlightGeo, highlightMat);
    leftHighlight.position.set(-0.19, 0.78, 0.8);
    group.add(leftHighlight);
    const rightHighlight = new THREE.Mesh(highlightGeo, highlightMat);
    rightHighlight.position.set(0.25, 0.78, 0.8);
    group.add(rightHighlight);

    // 喙
    const beakGeo = new THREE.ConeGeometry(0.08, 0.2, 8);
    const beakMat = new THREE.MeshPhongMaterial({ color: 0xf59e0b });
    const beak = new THREE.Mesh(beakGeo, beakMat);
    beak.position.set(0, 0.55, 0.65);
    beak.rotation.x = Math.PI / 2;
    group.add(beak);

    // 翅膀
    const wingGeo = new THREE.SphereGeometry(0.4, 16, 16);
    wingGeo.scale(0.4, 1, 0.8);
    const wingMat = new THREE.MeshPhongMaterial({ color: colors.accent });
    const leftWing = new THREE.Mesh(wingGeo, wingMat);
    leftWing.position.set(-0.7, -0.1, 0);
    leftWing.rotation.z = 0.3;
    group.add(leftWing);
    const rightWing = new THREE.Mesh(wingGeo, wingMat);
    rightWing.position.set(0.7, -0.1, 0);
    rightWing.rotation.z = -0.3;
    group.add(rightWing);
    parts.wings = [leftWing, rightWing];

    // 更新动画
    parts.update = function(time, isHovering) {
      // 眨眼
      const blink = Math.sin(time * 0.5) > 0.98 ? 0.1 : 1;
      leftEye.scale.y = blink;
      rightEye.scale.y = blink;
      leftPupil.scale.y = blink;
      rightPupil.scale.y = blink;

      // 翅膀微动
      const wingFlap = Math.sin(time * 3) * 0.1;
      leftWing.rotation.z = 0.3 + wingFlap;
      rightWing.rotation.z = -0.3 - wingFlap;

      // 头部微动
      head.rotation.y = Math.sin(time * 0.7) * 0.15;
    };

    return parts;
  }

  /**
   * 创建小鸟
   */
  function createBird(colors, group) {
    const parts = {};

    // 身体
    const bodyGeo = new THREE.SphereGeometry(0.7, 32, 32);
    bodyGeo.scale(1.1, 0.9, 1);
    const bodyMat = new THREE.MeshPhongMaterial({ color: colors.body, shininess: 80 });
    const body = new THREE.Mesh(bodyGeo, bodyMat);
    body.position.y = 0;
    group.add(body);
    parts.body = body;

    // 肚子
    const bellyGeo = new THREE.SphereGeometry(0.45, 32, 32);
    bellyGeo.scale(1, 0.8, 0.6);
    const bellyMat = new THREE.MeshPhongMaterial({ color: colors.belly });
    const belly = new THREE.Mesh(bellyGeo, bellyMat);
    belly.position.set(0, -0.1, 0.5);
    group.add(belly);

    // 头部
    const headGeo = new THREE.SphereGeometry(0.5, 32, 32);
    const headMat = new THREE.MeshPhongMaterial({ color: colors.body, shininess: 80 });
    const head = new THREE.Mesh(headGeo, headMat);
    head.position.set(0, 0.6, 0.2);
    group.add(head);
    parts.head = head;

    // 眼睛
    const eyeGeo = new THREE.SphereGeometry(0.12, 16, 16);
    const eyeMat = new THREE.MeshPhongMaterial({ color: 0xffffff, shininess: 100 });
    const leftEye = new THREE.Mesh(eyeGeo, eyeMat);
    leftEye.position.set(-0.18, 0.65, 0.6);
    group.add(leftEye);
    const rightEye = new THREE.Mesh(eyeGeo, eyeMat);
    rightEye.position.set(0.18, 0.65, 0.6);
    group.add(rightEye);

    // 瞳孔
    const pupilGeo = new THREE.SphereGeometry(0.06, 12, 12);
    const pupilMat = new THREE.MeshPhongMaterial({ color: 0x1a1a2e });
    const leftPupil = new THREE.Mesh(pupilGeo, pupilMat);
    leftPupil.position.set(-0.18, 0.65, 0.7);
    group.add(leftPupil);
    const rightPupil = new THREE.Mesh(pupilGeo, pupilMat);
    rightPupil.position.set(0.18, 0.65, 0.7);
    group.add(rightPupil);

    // 喙
    const beakGeo = new THREE.ConeGeometry(0.1, 0.25, 8);
    const beakMat = new THREE.MeshPhongMaterial({ color: 0xf59e0b });
    const beak = new THREE.Mesh(beakGeo, beakMat);
    beak.position.set(0, 0.5, 0.7);
    beak.rotation.x = Math.PI / 2;
    group.add(beak);

    // 翅膀（大翅膀）
    const wingGeo = new THREE.SphereGeometry(0.5, 16, 16);
    wingGeo.scale(0.3, 1, 1.2);
    const wingMat = new THREE.MeshPhongMaterial({ color: colors.accent, shininess: 60 });
    const leftWing = new THREE.Mesh(wingGeo, wingMat);
    leftWing.position.set(-0.6, 0.1, 0);
    leftWing.rotation.z = 0.5;
    group.add(leftWing);
    const rightWing = new THREE.Mesh(wingGeo, wingMat);
    rightWing.position.set(0.6, 0.1, 0);
    rightWing.rotation.z = -0.5;
    group.add(rightWing);
    parts.wings = [leftWing, rightWing];

    // 尾巴
    const tailGeo = new THREE.ConeGeometry(0.25, 0.5, 8);
    const tailMat = new THREE.MeshPhongMaterial({ color: colors.accent });
    const tail = new THREE.Mesh(tailGeo, tailMat);
    tail.position.set(0, -0.1, -0.8);
    tail.rotation.x = -Math.PI / 2;
    group.add(tail);

    // 头顶羽毛
    const crestGeo = new THREE.ConeGeometry(0.08, 0.3, 8);
    const crestMat = new THREE.MeshPhongMaterial({ color: colors.accent });
    for (let i = 0; i < 3; i++) {
      const crest = new THREE.Mesh(crestGeo, crestMat);
      crest.position.set((i - 1) * 0.12, 1.05, 0.1);
      crest.rotation.x = -0.2;
      group.add(crest);
    }

    parts.update = function(time, isHovering) {
      // 翅膀扇动
      const flap = Math.sin(time * 5) * 0.4;
      leftWing.rotation.z = 0.5 + flap;
      rightWing.rotation.z = -0.5 - flap;

      // 上下浮动
      body.position.y = Math.sin(time * 2) * 0.1;
      head.position.y = 0.6 + Math.sin(time * 2) * 0.1;

      // 头部微动
      head.rotation.y = Math.sin(time * 0.8) * 0.2;
    };

    return parts;
  }

  /**
   * 创建鲸鱼
   */
  function createWhale(colors, group) {
    const parts = {};

    // 身体（大椭圆）
    const bodyGeo = new THREE.SphereGeometry(1, 32, 32);
    bodyGeo.scale(1.5, 0.8, 0.9);
    const bodyMat = new THREE.MeshPhongMaterial({ color: colors.body, shininess: 80 });
    const body = new THREE.Mesh(bodyGeo, bodyMat);
    body.position.y = 0;
    group.add(body);
    parts.body = body;

    // 肚子（白色）
    const bellyGeo = new THREE.SphereGeometry(0.7, 32, 32);
    bellyGeo.scale(1.3, 0.5, 0.7);
    const bellyMat = new THREE.MeshPhongMaterial({ color: colors.belly });
    const belly = new THREE.Mesh(bellyGeo, bellyMat);
    belly.position.set(0, -0.3, 0.3);
    group.add(belly);

    // 头部（稍微大一点的球）
    const headGeo = new THREE.SphereGeometry(0.7, 32, 32);
    headGeo.scale(1, 0.9, 1.1);
    const headMat = new THREE.MeshPhongMaterial({ color: colors.body, shininess: 80 });
    const head = new THREE.Mesh(headGeo, headMat);
    head.position.set(0.9, 0.1, 0);
    group.add(head);
    parts.head = head;

    // 眼睛
    const eyeGeo = new THREE.SphereGeometry(0.1, 16, 16);
    const eyeMat = new THREE.MeshPhongMaterial({ color: 0xffffff, shininess: 100 });
    const eye = new THREE.Mesh(eyeGeo, eyeMat);
    eye.position.set(1.2, 0.25, 0.5);
    group.add(eye);

    const pupilGeo = new THREE.SphereGeometry(0.05, 12, 12);
    const pupilMat = new THREE.MeshPhongMaterial({ color: 0x1a1a2e });
    const pupil = new THREE.Mesh(pupilGeo, pupilMat);
    pupil.position.set(1.25, 0.25, 0.58);
    group.add(pupil);

    // 微笑
    const smileGeo = new THREE.TorusGeometry(0.15, 0.02, 8, 16, Math.PI);
    const smileMat = new THREE.MeshPhongMaterial({ color: 0x1a1a2e });
    const smile = new THREE.Mesh(smileGeo, smileMat);
    smile.position.set(1.3, 0.05, 0.5);
    smile.rotation.z = Math.PI;
    group.add(smile);

    // 尾巴
    const tailGeo = new THREE.ConeGeometry(0.4, 0.6, 8);
    const tailMat = new THREE.MeshPhongMaterial({ color: colors.accent });
    const tail = new THREE.Mesh(tailGeo, tailMat);
    tail.position.set(-1.3, 0, 0);
    tail.rotation.z = Math.PI / 2;
    group.add(tail);
    parts.tail = tail;

    // 尾鳍
    const finGeo = new THREE.ConeGeometry(0.3, 0.5, 8);
    const finMat = new THREE.MeshPhongMaterial({ color: colors.accent });
    const topFin = new THREE.Mesh(finGeo, finMat);
    topFin.position.set(0, 0.7, 0);
    topFin.rotation.z = Math.PI;
    group.add(topFin);

    // 胸鳍
    const pectoralGeo = new THREE.SphereGeometry(0.25, 16, 16);
    pectoralGeo.scale(0.4, 0.2, 1);
    const pectoralMat = new THREE.MeshPhongMaterial({ color: colors.accent });
    const leftPectoral = new THREE.Mesh(pectoralGeo, pectoralMat);
    leftPectoral.position.set(0.2, -0.4, 0.6);
    leftPectoral.rotation.x = 0.5;
    group.add(leftPectoral);
    const rightPectoral = new THREE.Mesh(pectoralGeo, pectoralMat);
    rightPectoral.position.set(0.2, -0.4, -0.6);
    rightPectoral.rotation.x = -0.5;
    group.add(rightPectoral);
    parts.pectorals = [leftPectoral, rightPectoral];

    // 喷水孔
    const blowholeGeo = new THREE.CylinderGeometry(0.08, 0.08, 0.05, 16);
    const blowholeMat = new THREE.MeshPhongMaterial({ color: colors.accent });
    const blowhole = new THREE.Mesh(blowholeGeo, blowholeMat);
    blowhole.position.set(0.5, 0.75, 0);
    group.add(blowhole);

    parts.update = function(time, isHovering) {
      // 尾巴摆动
      tail.rotation.y = Math.sin(time * 2) * 0.3;
      
      // 身体浮动
      body.position.y = Math.sin(time * 1.5) * 0.1;
      head.position.y = 0.1 + Math.sin(time * 1.5) * 0.1;

      // 胸鳍微动
      const pectoralMove = Math.sin(time * 2) * 0.1;
      leftPectoral.rotation.x = 0.5 + pectoralMove;
      rightPectoral.rotation.x = -0.5 - pectoralMove;
    };

    return parts;
  }

  /**
   * 创建小牛
   */
  function createCow(colors, group) {
    const parts = {};

    // 身体
    const bodyGeo = new THREE.SphereGeometry(0.8, 32, 32);
    bodyGeo.scale(1.3, 0.9, 0.9);
    const bodyMat = new THREE.MeshPhongMaterial({ color: colors.body, shininess: 60 });
    const body = new THREE.Mesh(bodyGeo, bodyMat);
    body.position.y = 0;
    group.add(body);
    parts.body = body;

    // 肚子
    const bellyGeo = new THREE.SphereGeometry(0.5, 32, 32);
    bellyGeo.scale(1.2, 0.7, 0.7);
    const bellyMat = new THREE.MeshPhongMaterial({ color: colors.belly });
    const belly = new THREE.Mesh(bellyGeo, bellyMat);
    belly.position.set(0, -0.3, 0.4);
    group.add(belly);

    // 头部
    const headGeo = new THREE.SphereGeometry(0.55, 32, 32);
    const headMat = new THREE.MeshPhongMaterial({ color: colors.body, shininess: 60 });
    const head = new THREE.Mesh(headGeo, headMat);
    head.position.set(0.8, 0.4, 0);
    group.add(head);
    parts.head = head;

    // 口鼻
    const snoutGeo = new THREE.SphereGeometry(0.3, 24, 24);
    snoutGeo.scale(1, 0.8, 1.2);
    const snoutMat = new THREE.MeshPhongMaterial({ color: colors.belly, shininess: 40 });
    const snout = new THREE.Mesh(snoutGeo, snoutMat);
    snout.position.set(1.15, 0.25, 0);
    group.add(snout);

    // 鼻孔
    const nostrilGeo = new THREE.SphereGeometry(0.04, 8, 8);
    const nostrilMat = new THREE.MeshPhongMaterial({ color: 0x1a1a2e });
    const leftNostril = new THREE.Mesh(nostrilGeo, nostrilMat);
    leftNostril.position.set(1.35, 0.3, 0.1);
    group.add(leftNostril);
    const rightNostril = new THREE.Mesh(nostrilGeo, nostrilMat);
    rightNostril.position.set(1.35, 0.3, -0.1);
    group.add(rightNostril);

    // 眼睛
    const eyeGeo = new THREE.SphereGeometry(0.1, 16, 16);
    const eyeMat = new THREE.MeshPhongMaterial({ color: 0xffffff, shininess: 100 });
    const leftEye = new THREE.Mesh(eyeGeo, eyeMat);
    leftEye.position.set(0.95, 0.55, 0.35);
    group.add(leftEye);
    const rightEye = new THREE.Mesh(eyeGeo, eyeMat);
    rightEye.position.set(0.95, 0.55, -0.35);
    group.add(rightEye);

    const pupilGeo = new THREE.SphereGeometry(0.05, 12, 12);
    const pupilMat = new THREE.MeshPhongMaterial({ color: 0x1a1a2e });
    const leftPupil = new THREE.Mesh(pupilGeo, pupilMat);
    leftPupil.position.set(1.0, 0.55, 0.42);
    group.add(leftPupil);
    const rightPupil = new THREE.Mesh(pupilGeo, pupilMat);
    rightPupil.position.set(1.0, 0.55, -0.42);
    group.add(rightPupil);

    // 角
    const hornGeo = new THREE.ConeGeometry(0.08, 0.35, 8);
    const hornMat = new THREE.MeshPhongMaterial({ color: 0xf5f5f4, shininess: 40 });
    const leftHorn = new THREE.Mesh(hornGeo, hornMat);
    leftHorn.position.set(0.65, 0.95, 0.25);
    leftHorn.rotation.z = -0.5;
    group.add(leftHorn);
    const rightHorn = new THREE.Mesh(hornGeo, hornMat);
    rightHorn.position.set(0.65, 0.95, -0.25);
    rightHorn.rotation.z = -0.5;
    group.add(rightHorn);

    // 耳朵
    const earGeo = new THREE.SphereGeometry(0.15, 16, 16);
    earGeo.scale(0.5, 1, 0.3);
    const earMat = new THREE.MeshPhongMaterial({ color: colors.accent });
    const leftEar = new THREE.Mesh(earGeo, earMat);
    leftEar.position.set(0.5, 0.6, 0.45);
    leftEar.rotation.z = 0.5;
    group.add(leftEar);
    const rightEar = new THREE.Mesh(earGeo, earMat);
    rightEar.position.set(0.5, 0.6, -0.45);
    rightEar.rotation.z = -0.5;
    group.add(rightEar);
    parts.ears = [leftEar, rightEar];

    // 腿
    const legGeo = new THREE.CylinderGeometry(0.12, 0.15, 0.5, 16);
    const legMat = new THREE.MeshPhongMaterial({ color: colors.accent });
    const legPositions = [
      [-0.4, -0.6, 0.35], [0.4, -0.6, 0.35],
      [-0.4, -0.6, -0.35], [0.4, -0.6, -0.35]
    ];
    legPositions.forEach(pos => {
      const leg = new THREE.Mesh(legGeo, legMat);
      leg.position.set(pos[0], pos[1], pos[2]);
      group.add(leg);
    });

    // 尾巴
    const tailGeo = new THREE.CylinderGeometry(0.03, 0.05, 0.5, 8);
    const tailMat = new THREE.MeshPhongMaterial({ color: colors.accent });
    const tail = new THREE.Mesh(tailGeo, tailMat);
    tail.position.set(-1.1, 0.2, 0);
    tail.rotation.z = 0.5;
    group.add(tail);
    parts.tail = tail;

    parts.update = function(time, isHovering) {
      // 尾巴摇摆
      tail.rotation.z = 0.5 + Math.sin(time * 3) * 0.3;
      
      // 耳朵微动
      const earMove = Math.sin(time * 2) * 0.1;
      leftEar.rotation.z = 0.5 + earMove;
      rightEar.rotation.z = -0.5 - earMove;

      // 头部微动
      head.rotation.y = Math.sin(time * 0.6) * 0.1;
    };

    return parts;
  }

  /**
   * 创建狐狸
   */
  function createFox(colors, group) {
    const parts = {};

    // 身体
    const bodyGeo = new THREE.SphereGeometry(0.7, 32, 32);
    bodyGeo.scale(1.4, 0.8, 0.8);
    const bodyMat = new THREE.MeshPhongMaterial({ color: colors.body, shininess: 80 });
    const body = new THREE.Mesh(bodyGeo, bodyMat);
    body.position.y = 0;
    group.add(body);
    parts.body = body;

    // 肚子
    const bellyGeo = new THREE.SphereGeometry(0.45, 32, 32);
    bellyGeo.scale(1.3, 0.6, 0.6);
    const bellyMat = new THREE.MeshPhongMaterial({ color: colors.belly });
    const belly = new THREE.Mesh(bellyGeo, bellyMat);
    belly.position.set(0, -0.25, 0.35);
    group.add(belly);

    // 头部（尖脸）
    const headGeo = new THREE.SphereGeometry(0.5, 32, 32);
    headGeo.scale(1, 0.9, 1.1);
    const headMat = new THREE.MeshPhongMaterial({ color: colors.body, shininess: 80 });
    const head = new THREE.Mesh(headGeo, headMat);
    head.position.set(0.85, 0.35, 0);
    group.add(head);
    parts.head = head;

    // 口鼻（尖）
    const snoutGeo = new THREE.ConeGeometry(0.2, 0.5, 16);
    const snoutMat = new THREE.MeshPhongMaterial({ color: colors.belly, shininess: 40 });
    const snout = new THREE.Mesh(snoutGeo, snoutMat);
    snout.position.set(1.25, 0.2, 0);
    snout.rotation.z = -Math.PI / 2;
    group.add(snout);

    // 鼻子
    const noseGeo = new THREE.SphereGeometry(0.08, 16, 16);
    const noseMat = new THREE.MeshPhongMaterial({ color: 0x1a1a2e, shininess: 100 });
    const nose = new THREE.Mesh(noseGeo, noseMat);
    nose.position.set(1.5, 0.2, 0);
    group.add(nose);

    // 眼睛（狡黠的眼睛）
    const eyeGeo = new THREE.SphereGeometry(0.1, 16, 16);
    const eyeMat = new THREE.MeshPhongMaterial({ color: 0xffffff, shininess: 100 });
    const leftEye = new THREE.Mesh(eyeGeo, eyeMat);
    leftEye.position.set(1.0, 0.5, 0.3);
    group.add(leftEye);
    const rightEye = new THREE.Mesh(eyeGeo, eyeMat);
    rightEye.position.set(1.0, 0.5, -0.3);
    group.add(rightEye);

    const pupilGeo = new THREE.SphereGeometry(0.05, 12, 12);
    const pupilMat = new THREE.MeshPhongMaterial({ color: 0x1a1a2e });
    const leftPupil = new THREE.Mesh(pupilGeo, pupilMat);
    leftPupil.position.set(1.05, 0.5, 0.37);
    group.add(leftPupil);
    const rightPupil = new THREE.Mesh(pupilGeo, pupilMat);
    rightPupil.position.set(1.05, 0.5, -0.37);
    group.add(rightPupil);

    // 大耳朵（三角形）
    const earGeo = new THREE.ConeGeometry(0.2, 0.5, 4);
    const earMat = new THREE.MeshPhongMaterial({ color: colors.body, shininess: 60 });
    const leftEar = new THREE.Mesh(earGeo, earMat);
    leftEar.position.set(0.6, 0.85, 0.3);
    leftEar.rotation.z = -0.3;
    group.add(leftEar);
    const rightEar = new THREE.Mesh(earGeo, earMat);
    rightEar.position.set(0.6, 0.85, -0.3);
    rightEar.rotation.z = -0.3;
    group.add(rightEar);
    parts.ears = [leftEar, rightEar];

    // 耳朵内部（粉色）
    const innerEarGeo = new THREE.ConeGeometry(0.12, 0.35, 4);
    const innerEarMat = new THREE.MeshPhongMaterial({ color: colors.belly });
    const leftInnerEar = new THREE.Mesh(innerEarGeo, innerEarMat);
    leftInnerEar.position.set(0.6, 0.82, 0.3);
    leftInnerEar.rotation.z = -0.3;
    group.add(leftInnerEar);
    const rightInnerEar = new THREE.Mesh(innerEarGeo, innerEarMat);
    rightInnerEar.position.set(0.6, 0.82, -0.3);
    rightInnerEar.rotation.z = -0.3;
    group.add(rightInnerEar);

    // 大尾巴（蓬松）
    const tailGeo = new THREE.SphereGeometry(0.35, 24, 24);
    tailGeo.scale(0.8, 0.8, 1.8);
    const tailMat = new THREE.MeshPhongMaterial({ color: colors.body, shininess: 60 });
    const tail = new THREE.Mesh(tailGeo, tailMat);
    tail.position.set(-1.0, 0.2, 0);
    tail.rotation.z = 0.5;
    group.add(tail);
    parts.tail = tail;

    // 尾巴尖（白色）
    const tailTipGeo = new THREE.SphereGeometry(0.2, 16, 16);
    const tailTipMat = new THREE.MeshPhongMaterial({ color: colors.belly });
    const tailTip = new THREE.Mesh(tailTipGeo, tailTipMat);
    tailTip.position.set(-1.4, 0.4, 0);
    group.add(tailTip);

    // 腿
    const legGeo = new THREE.CylinderGeometry(0.1, 0.12, 0.45, 16);
    const legMat = new THREE.MeshPhongMaterial({ color: colors.accent });
    const legPositions = [
      [-0.35, -0.55, 0.3], [0.35, -0.55, 0.3],
      [-0.35, -0.55, -0.3], [0.35, -0.55, -0.3]
    ];
    legPositions.forEach(pos => {
      const leg = new THREE.Mesh(legGeo, legMat);
      leg.position.set(pos[0], pos[1], pos[2]);
      group.add(leg);
    });

    parts.update = function(time, isHovering) {
      // 尾巴摇摆（大尾巴）
      tail.rotation.z = 0.5 + Math.sin(time * 2.5) * 0.4;
      tailTip.position.x = -1.4 + Math.sin(time * 2.5) * 0.1;
      tailTip.position.y = 0.4 + Math.cos(time * 2.5) * 0.1;
      
      // 耳朵微动
      const earMove = Math.sin(time * 1.5) * 0.1;
      leftEar.rotation.z = -0.3 + earMove;
      rightEar.rotation.z = -0.3 - earMove;

      // 头部微动（狡黠的点头）
      head.rotation.y = Math.sin(time * 0.8) * 0.15;
      head.rotation.x = Math.sin(time * 1.2) * 0.05;
    };

    return parts;
  }

  // 导出到全局
  window.create3DAnimal = create3DAnimal;
  window.ANIMAL_TYPES = ['owl', 'bird', 'whale', 'cow', 'fox'];

})();
