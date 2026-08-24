"""
HLD 生成器蓝图
基于 OD Excel 需求文档，自动生成每个 Feature 的高层设计文档（HLD）
支持 GPS/Fitness 增强分支、Mermaid 时序图/状态机、批量 ZIP 下载
"""
import io
import zipfile
import re
from flask import Blueprint, request, jsonify, send_file
from datetime import datetime

bp_hld = Blueprint('hld', __name__, url_prefix='/hld')

# ==================== 常量配置 ====================

# GPS/Fitness 增强 Feature 关键词（命中即视为增强 Feature）
GPS_FITNESS_KEYWORDS = [
    'gps', 'gnss', '定位', '导航', '轨迹', '运动', 'fitness', 'workout',
    '跑步', '骑行', '游泳', '心率', '血氧', 'spo2', '睡眠', '压力',
    '训练', '计步', '卡路里', '距离', '配速', '步频', '步幅',
    'elpo', '多频', '双频', '卫星', 'nmea', 'pvt',
    'polar', '算法', '运动模式', '户外运动', '室内运动',
    '健康', 'health', 'wellness', 'recovery', '恢复',
]

# 术语库（自动收集相关术语）
TERM_DATABASE = {
    'RTOS': '实时操作系统（Real-Time Operating System）',
    'HAL': '硬件抽象层（Hardware Abstraction Layer）',
    'BLE': '低功耗蓝牙（Bluetooth Low Energy）',
    'RTL': '从右到左排版（Right-To-Left）',
    'ICU': '国际化组件库（International Components for Unicode）',
    'i18n': '国际化（Internationalization）',
    'LRU': '最近最少使用缓存策略（Least Recently Used）',
    'GPS': '全球定位系统（Global Positioning System）',
    'GNSS': '全球导航卫星系统（Global Navigation Satellite System）',
    'ELPO': '低功耗定位（Embedded Low Power Positioning）',
    'PVT': '位置速度时间解算（Position Velocity Time）',
    'NMEA': '国家海洋电子协会协议（National Marine Electronics Association）',
    'SpO2': '血氧饱和度（Peripheral Oxygen Saturation）',
    'HR': '心率（Heart Rate）',
    'ODM': '原始设计制造商（Original Design Manufacturer）',
    'HLD': '高层设计（High-Level Design）',
    'LLD': '低层设计（Low-Level Design）',
    'OD': '需求定义文档（Output Definition）',
    'Moto': '摩托罗拉专有协议/品牌',
    'Companion App': '手机端配套应用',
    'Watch Firmware': '手表端固件',
    'OTA': '空中升级（Over-The-Air）',
    'WDT': '看门狗定时器（Watchdog Timer）',
    'RTC': '实时时钟（Real-Time Clock）',
    'SPI': '串行外设接口（Serial Peripheral Interface）',
    'I2C': '集成电路总线（Inter-Integrated Circuit）',
    'UART': '通用异步收发器（Universal Asynchronous Receiver/Transmitter）',
    'DMA': '直接内存访问（Direct Memory Access）',
    'ISR': '中断服务程序（Interrupt Service Routine）',
    'FS': '文件系统（File System）',
    'KV': '键值存储（Key-Value Store）',
    'MQTT': '消息队列遥测传输（Message Queuing Telemetry Transport）',
    'JSON': 'JavaScript 对象表示法（JavaScript Object Notation）',
    'CSV': '逗号分隔值（Comma-Separated Values）',
}

# ==================== OD 解析 ====================

def parse_od_excel(file_storage):
    """解析 OD Excel 文件，返回 Feature 列表"""
    try:
        import pandas as pd
    except ImportError:
        return None, "pandas 未安装"

    try:
        # 读取所有 sheet
        xls = pd.ExcelFile(file_storage)
        all_features = []

        for sheet_name in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=sheet_name)
            if df.empty:
                continue

            # 标准化列名（小写、去空格）
            df.columns = [str(c).strip().lower() for c in df.columns]

            # 查找关键列
            col_map = find_columns(df.columns)
            if not col_map.get('name'):
                continue

            for idx, row in df.iterrows():
                feature = extract_feature(row, col_map, sheet_name)
                if feature:
                    all_features.append(feature)

        return all_features, None
    except Exception as e:
        return None, f"解析失败: {str(e)}"


def find_columns(columns):
    """查找 OD 表格中的关键列"""
    col_map = {}
    for col in columns:
        col_lower = col.lower()
        if any(k in col_lower for k in ['feature', 'name', '名称', '功能', '需求名称']):
            if 'name' not in col_map:
                col_map['name'] = col
        elif any(k in col_lower for k in ['priority', '优先级']):
            col_map['priority'] = col
        elif any(k in col_lower for k in ['category', '分类', '类别']):
            col_map['category'] = col
        elif any(k in col_lower for k in ['watch', 'firmware', '手表', '固件', 'rtos']):
            col_map['watch'] = col
        elif any(k in col_lower for k in ['companion', 'app', '手机', '配套']):
            col_map['companion'] = col
        elif any(k in col_lower for k in ['i18n', '国际化', 'language', '语言']):
            col_map['i18n'] = col
        elif any(k in col_lower for k in ['note', '备注', '说明']):
            col_map['notes'] = col
        elif any(k in col_lower for k in ['tool', 'health', 'fitness', 'system', 'oobe']):
            if 'category' not in col_map:
                col_map['category'] = col
    return col_map


def extract_feature(row, col_map, sheet_name):
    """从一行数据中提取 Feature 信息"""
    name = str(row.get(col_map.get('name', ''), '')).strip()

    # 过滤无效行
    if not name or name.lower() in ['nan', 'none', 'tbd', 'n/a', 'na', '-', '—']:
        return None
    if len(name) < 2:
        return None
    # 过滤纯标题行（全大写且短）
    if name.isupper() and len(name) < 10:
        return None

    priority = str(row.get(col_map.get('priority', ''), '')).strip()
    if priority.lower() in ['nan', 'none', '']:
        priority = 'P2'

    category = str(row.get(col_map.get('category', ''), '')).strip()
    if category.lower() in ['nan', 'none', '']:
        category = sheet_name

    watch_req = str(row.get(col_map.get('watch', ''), '')).strip()
    companion_req = str(row.get(col_map.get('companion', ''), '')).strip()
    i18n_req = str(row.get(col_map.get('i18n', ''), '')).strip()
    notes = str(row.get(col_map.get('notes', ''), '')).strip()

    # 清理 nan
    for val in [watch_req, companion_req, i18n_req, notes]:
        if val.lower() == 'nan':
            val = ''

    # 判断是否为 GPS/Fitness 增强 Feature
    is_enhanced = check_enhanced(name, watch_req, companion_req, category)

    # 判断类型
    feature_type = determine_type(name, watch_req, notes)

    # 判断覆盖层
    covered_layer = determine_layer(watch_req, companion_req)

    return {
        'name': name,
        'priority': priority.upper() if priority else 'P2',
        'category': category,
        'watch_req': watch_req,
        'companion_req': companion_req,
        'i18n_req': i18n_req,
        'notes': notes,
        'is_enhanced': is_enhanced,
        'type': feature_type,
        'covered_layer': covered_layer,
    }


def check_enhanced(name, watch_req, companion_req, category):
    """判断是否为 GPS/Fitness 增强 Feature"""
    text = f"{name} {watch_req} {companion_req} {category}".lower()
    return any(kw in text for kw in GPS_FITNESS_KEYWORDS)


def determine_type(name, watch_req, notes):
    """判断 Feature 类型"""
    text = f"{name} {watch_req} {notes}".lower()
    if any(k in text for k in ['重构', 'refactor', '优化', 'optimize', '重构', '迁移', 'migrate']):
        return 'Refactor'
    if any(k in text for k in ['基础', '底层', 'framework', '基础能力', '平台', '驱动', 'driver', 'hal', '中间件', 'middleware']):
        return 'Foundation'
    return 'Feature'


def determine_layer(watch_req, companion_req):
    """判断覆盖层"""
    has_watch = bool(watch_req and watch_req.lower() != 'nan')
    has_companion = bool(companion_req and companion_req.lower() != 'nan')
    if has_watch and has_companion:
        return 'Watch Firmware (RTOS) + Companion App（跨端）'
    elif has_watch:
        return 'Watch Firmware (RTOS)'
    elif has_companion:
        return 'Companion App'
    return 'Watch Firmware (RTOS)'


# ==================== HLD 生成 ====================

def generate_hld(feature, feature_id):
    """生成单个 Feature 的 HLD Markdown"""
    name = feature['name']
    priority = feature['priority']
    category = feature['category']
    is_enhanced = feature['is_enhanced']
    feature_type = feature['type']
    covered_layer = feature['covered_layer']

    # 文件名
    safe_name = re.sub(r'[\\/:*?"<>|]', '_', name)[:50]
    filename = f"{feature_id}_{safe_name}_HLD.md"

    # 收集术语
    terms = collect_terms(feature)

    # 生成各章节
    sections = []

    # 标题
    sections.append(f"# {name} — HLD\n")

    # 1. 文档信息
    sections.append(generate_doc_info(feature, feature_id, terms))

    # 2. 背景与目标
    sections.append(generate_background(feature))

    # 3. 需求与约束
    sections.append(generate_requirements(feature))

    # 4. 概要设计方案
    sections.append(generate_design(feature))

    # 5. LLD 级细节设计
    sections.append(generate_lld_detail(feature))

    # 6. 测试验收关键点
    sections.append(generate_testing(feature))

    # 7. 引用参考
    sections.append(generate_references())

    return '\n'.join(sections), filename


def generate_doc_info(feature, feature_id, terms):
    """生成文档信息章节"""
    lines = []
    lines.append("## 1. 文档信息\n")

    # 元数据表格
    lines.append("| 项目 | 内容 |")
    lines.append("|------|------|")
    lines.append(f"| Feature ID | {feature_id} |")
    lines.append(f"| Feature Name | {feature['name']} |")
    lines.append(f"| Priority | {feature['priority']} |")
    lines.append(f"| Type | {feature['type']} |")
    lines.append(f"| Covered Layer | {feature['covered_layer']} |")
    lines.append(f"| Category | {feature['category']} |")
    lines.append(f"| Document Type | HLD |")
    lines.append(f"| Generated Date | {datetime.now().strftime('%Y-%m-%d')} |")
    lines.append("")

    # 修订历史
    lines.append("### 1.1 修订历史\n")
    lines.append("| 版本 | 日期 | 修订人 | 修订内容 |")
    lines.append("|------|------|--------|----------|")
    lines.append(f"| V1.0 | {datetime.now().strftime('%Y-%m-%d')} | HLD Generator | 初始版本，基于 OD 需求生成 |")
    if feature['is_enhanced']:
        lines.append(f"| V1.1 | {datetime.now().strftime('%Y-%m-%d')} | HLD Generator | GPS/Fitness 深度增强：追加量化约束、模块框图、专项异常与测试用例 |")
    lines.append("")

    # 术语与定义
    if terms:
        lines.append("### 1.2 术语与定义\n")
        lines.append("| 缩写 | 全称 | 说明 |")
        lines.append("|------|------|------|")
        for term in sorted(terms):
            if term in TERM_DATABASE:
                full_name = TERM_DATABASE[term].split('（')[0] if '（' in TERM_DATABASE[term] else term
                desc = TERM_DATABASE[term]
                lines.append(f"| {term} | {full_name} | {desc} |")
        lines.append("")

    return '\n'.join(lines)


def collect_terms(feature):
    """收集 Feature 相关术语"""
    text = f"{feature['name']} {feature['watch_req']} {feature['companion_req']} {feature['i18n_req']} {feature['notes']}".upper()
    terms = set()
    for term in TERM_DATABASE:
        if term.upper() in text:
            terms.add(term)
    # 通用术语
    terms.update(['HLD', 'OD', 'ODM'])
    if feature['i18n_req']:
        terms.update(['i18n', 'RTL', 'ICU'])
    if feature['covered_layer'].find('Companion') >= 0:
        terms.add('BLE')
    if feature['is_enhanced']:
        terms.update(['GPS', 'GNSS', 'HAL', 'LRU'])
    return terms


def generate_background(feature):
    """生成背景与目标章节"""
    lines = []
    lines.append("## 2. 背景与目标\n")

    # 业务背景
    lines.append("### 2.1 业务背景\n")
    bg_text = f"本 Feature「{feature['name']}」来源于 OD 需求定义文档，归属 {feature['category']} 分类。"
    if feature['watch_req']:
        bg_text += f" 手表端需实现：{feature['watch_req'][:200]}。"
    if feature['companion_req']:
        bg_text += f" 手机端配套应用需支持：{feature['companion_req'][:200]}。"
    lines.append(bg_text)
    lines.append("")

    # 设计目标
    lines.append("### 2.2 设计目标\n")
    lines.append(f"- 实现 OD 中定义的「{feature['name']}」全部功能需求")
    lines.append("- 满足跨端（Watch Firmware / Companion App）数据交互与状态同步")
    if feature['i18n_req']:
        lines.append("- 支持国际化：多语言、RTL 镜像、翻译膨胀适配、计量单位本地化")
    if feature['is_enhanced']:
        lines.append("- 满足 GPS/Fitness 增强约束：低功耗、高可靠性、离线可用、异常自愈")
    lines.append("- 模块间低耦合，便于后续 LLD 阶段细化实现")
    lines.append("")

    # 范围说明
    lines.append("### 2.3 范围说明\n")
    lines.append("- 本文档覆盖 HLD 设计，定义模块职责、数据流、状态流转、接口定义、数据结构、核心算法")
    lines.append("- 包含 LLD 级细节：模块接口、数据结构、伪代码、错误码、内存规划")
    lines.append("- 所有需求均溯源 OD，不新增 OD 未定义的产品行为")
    lines.append("")

    return '\n'.join(lines)


def generate_requirements(feature):
    """生成需求与约束章节"""
    lines = []
    lines.append("## 3. 需求与约束\n")

    # 3.1 功能性需求
    lines.append("### 3.1 功能性需求\n")
    lines.append("| 子功能ID | 功能描述 | 归属层级/系统 | 依赖关系/前置条件 |")
    lines.append("|----------|----------|---------------|-------------------|")

    req_id = 0
    # Watch Firmware 需求
    if feature['watch_req'] and feature['watch_req'].lower() != 'nan':
        reqs = split_requirements(feature['watch_req'])
        for req in reqs:
            req_id += 1
            deps = derive_dependencies(req, feature)
            lines.append(f"| F-{req_id:02d}-01 | {req} | Watch Firmware (RTOS) | {deps} |")

    # Companion App 需求
    if feature['companion_req'] and feature['companion_req'].lower() != 'nan':
        reqs = split_requirements(feature['companion_req'])
        for req in reqs:
            req_id += 1
            deps = derive_dependencies(req, feature)
            lines.append(f"| F-{req_id:02d}-01 | {req} | Companion App | {deps} |")

    # i18n 需求
    if feature['i18n_req'] and feature['i18n_req'].lower() != 'nan':
        req_id += 1
        lines.append(f"| F-{req_id:02d}-01 | 国际化支持：{feature['i18n_req'][:150]} | 跨端 | ICU 国际化库、多语言资源包 |")

    if req_id == 0:
        lines.append("| F-01-01 | 基础功能实现（详见 OD 原文） | Watch Firmware | 系统初始化完成 |")

    lines.append("")

    # 3.2 约束性需求
    lines.append("### 3.2 约束性需求\n")

    # 通用约束
    lines.append("#### 通用约束\n")
    lines.append("- **国际化约束**：所有 UI 文本需支持翻译膨胀 30% 布局；长文本启用 marquee 跑马灯；RTL 语言自动镜像布局；支持多数字系统（阿拉伯文/波斯文）；计量单位本地化（公制/英制）")
    lines.append("- **性能约束**：UI 响应延迟 ≤ 200ms；模块初始化 ≤ 500ms；内存泄漏率为 0")
    lines.append("- **可靠性约束**：异常场景下不得导致系统重启；关键数据持久化存储；BT 断开后自动重连")
    lines.append("- **安全约束**：敏感数据加密存储；跨端通信走 BLE 加密通道；用户数据不明文落盘")
    lines.append("")

    # GPS/Fitness 增强约束
    if feature['is_enhanced']:
        lines.append("#### GPS/Fitness 增强约束（量化指标）\n")
        lines.append("| 约束项 | 指标要求 | 说明 |")
        lines.append("|--------|----------|------|")
        lines.append("| RAM 占用 | ≤ 32KB | 业务模块运行时内存峰值 |")
        lines.append("| ROM 占用 | ≤ 128KB | 代码+常量存储占用 |")
        lines.append("| 平均功耗 | ≤ 5mA | 连续工作状态下平均电流 |")
        lines.append("| GPS 首次定位 | ≤ 30s（冷启动）/ ≤ 5s（热启动） | TTFF 指标 |")
        lines.append("| 定位精度 | ≤ 5m（开阔场景） | CEP50 精度 |")
        lines.append("| 传感器采样率 | 配置可配，默认 1Hz~50Hz | 心率/加速度/GPS 等 |")
        lines.append("| 存储 LRU 容量 | 可配置，默认 7 天数据 | 离线数据环形缓存 |")
        lines.append("| 数据同步时延 | ≤ 10s（BT 连接后） | 离线数据上传 |")
        lines.append("| 算法处理时延 | ≤ 100ms/帧 | 实时算法处理 |")
        lines.append("| 低电量保护 | ≤ 10% 自动降采样 | 功耗保护策略 |")
        lines.append("")

    return '\n'.join(lines)


def split_requirements(text):
    """将需求文本拆分为子需求"""
    # 按分号、句号、换行分割
    parts = re.split(r'[；;\n]', text)
    reqs = []
    for part in parts:
        part = part.strip()
        if part and len(part) > 5 and part.lower() != 'nan':
            # 技术化改写：去掉产品口语
            tech = tech_rewrite(part)
            reqs.append(tech[:200])
    if not reqs:
        reqs.append(tech_rewrite(text[:200]))
    return reqs[:5]  # 最多5条


def tech_rewrite(text):
    """将产品口语需求技术化改写"""
    replacements = {
        '用户可以': '系统支持',
        '用户能够': '系统支持',
        '点击': '触发',
        '展示': '渲染',
        '显示': '渲染',
        '提醒': '通知',
        '记录': '持久化存储',
        '保存': '持久化存储',
        '同步': '跨端数据同步',
        '连接': '建立连接',
        '断开': '连接断开',
        '设置': '配置',
        '修改': '更新配置',
        '删除': '移除',
        '添加': '新增',
        '查看': '查询并渲染',
        '分享': '数据导出与分享',
        '导出': '数据导出',
        '导入': '数据导入',
        '搜索': '检索',
        '筛选': '过滤',
        '排序': '排序',
        '统计': '聚合统计',
        '分析': '数据分析',
        '报告': '生成报告',
        '图表': '可视化图表',
        '进度': '进度状态',
        '状态': '状态管理',
    }
    result = text
    for old, new in replacements.items():
        result = result.replace(old, new)
    return result


def derive_dependencies(req, feature):
    """推导依赖关系"""
    deps = []
    text = req.lower()
    if any(k in text for k in ['传感器', '心率', '血氧', '加速度', 'gps', '定位']):
        deps.append('传感器 HAL 驱动')
    if any(k in text for k in ['蓝牙', 'ble', '同步', '连接', 'companion', 'app']):
        deps.append('BT 协议栈 / BLE')
    if any(k in text for k in ['存储', '保存', '记录', '历史', '数据']):
        deps.append('存储服务 / KV / FS')
    if any(k in text for k in ['振动', '马达', '提醒', '通知']):
        deps.append('振动服务 / 马达驱动')
    if any(k in text for k in ['显示', '屏幕', 'ui', '界面', '渲染']):
        deps.append('UI 渲染引擎 / Framebuffer')
    if any(k in text for k in ['国际化', 'i18n', '语言', '翻译', 'rtl']):
        deps.append('ICU 国际化库')
    if any(k in text for k in ['音频', '声音', '喇叭', '播放']):
        deps.append('音频服务 / Codec')
    if any(k in text for k in ['电源', '电量', '充电', '低电']):
        deps.append('电源管理 / PMU')
    if any(k in text for k in ['时间', '时钟', '闹钟', '定时']):
        deps.append('RTC / 定时器服务')
    if feature['is_enhanced']:
        deps.append('算法适配器')
    if not deps:
        deps.append('系统服务 / 消息总线')
    return '、'.join(deps[:4])


def generate_design(feature):
    """生成概要设计方案章节"""
    lines = []
    lines.append("## 4. 概要设计方案\n")

    # 4.1 系统概述与总体架构
    lines.append("### 4.1 系统概述与总体架构\n")
    lines.append(f"本 Feature「{feature['name']}」采用模块化设计，核心模块包括：UI 交互层、业务 Service 层、HAL/驱动层、跨端通信层。")
    lines.append("")
    lines.append("**数据流概述**：")
    lines.append("1. 用户通过 UI 触发操作，UI 层将事件传递给业务 Service")
    lines.append("2. 业务 Service 处理业务逻辑，调用 HAL/驱动层访问硬件")
    lines.append("3. 需要跨端同步时，通过 BT 协议栈与 Companion App 交互")
    lines.append("4. 关键数据通过存储服务持久化，异常时触发自愈策略")
    lines.append("")

    # GPS/Fitness 增强：模块框图
    if feature['is_enhanced']:
        lines.append("**模块分层架构图（GPS/Fitness 增强）**：\n")
        lines.append("```mermaid")
        lines.append("graph TD")
        lines.append("    UI[\"UI / i18n引擎\"] --> Service[\"业务Service\"]")
        lines.append("    Service --> Algo[\"算法适配器\"]")
        lines.append("    Algo --> HAL[\"HAL / GPS驱动\"]")
        lines.append("    HAL --> Sensor[\"传感器 / GPS硬件\"]")
        lines.append("    Service --> Storage[\"存储服务 / LRU\"]")
        lines.append("    Service --> BT[\"BT协议栈\"]")
        lines.append("    BT <--> App[\"CompanionApp\"]")
        lines.append("    Storage --> BT")
        lines.append("```")
        lines.append("")

    # 4.2 方案设计
    lines.append("### 4.2 方案设计\n")
    lines.append("**业务流程（高层逻辑）**：")
    lines.append("")
    lines.append("1. **初始化阶段**：系统启动时，业务 Service 完成模块注册、依赖注入、状态恢复；HAL 层完成硬件初始化；存储服务加载持久化数据")
    lines.append("2. **正常数据流**：用户交互 → UI 事件 → 业务 Service 处理 → HAL/驱动访问 → 结果回调 UI 渲染 → 关键数据持久化 → 跨端同步（如需）")
    lines.append("3. **用户交互路径**：UI 层负责输入采集与输出渲染，业务逻辑全部在 Service 层，UI 与业务通过事件/回调解耦")
    lines.append("4. **跨端交互**：Watch Firmware 作为 GATT Server，Companion App 作为 Client，通过 BLE 特征值读写实现数据同步与控制指令下发")
    lines.append("")

    # 时序图（所有 Feature 都生成）
    lines.append("**时序图（Sequence Diagram）**：\n")
    lines.append("```mermaid")
    lines.append("sequenceDiagram")
    lines.append("    participant User as 用户")
    lines.append("    participant UI as UI层")
    lines.append("    participant Service as 业务Service")
    lines.append("    participant HAL as HAL驱动")
    lines.append("    participant Storage as 存储服务")
    lines.append("    participant BT as BT栈")
    lines.append("    participant App as CompanionApp")
    lines.append("    Note over Service: 系统初始化")
    lines.append("    Service->>HAL: 硬件初始化")
    lines.append("    HAL-->>Service: 初始化完成")
    lines.append("    Service->>Storage: 加载持久化状态")
    lines.append("    Note over User,App: 正常触发流程")
    lines.append("    User->>UI: 触发操作")
    lines.append("    UI->>Service: 事件通知")
    lines.append("    Service->>HAL: 访问硬件/读取数据")
    lines.append("    HAL-->>Service: 返回数据")
    lines.append("    Service->>Service: 业务逻辑处理")
    lines.append("    Service->>UI: 回调更新界面")
    lines.append("    Service->>Storage: 持久化关键数据")
    if feature['covered_layer'].find('Companion') >= 0:
        lines.append("    Service->>BT: 跨端数据同步")
        lines.append("    BT->>App: 发送数据/通知")
        lines.append("    App-->>BT: 确认/响应")
        lines.append("    BT-->>Service: 同步完成")
    lines.append("```")
    lines.append("")

    # 状态机（所有 Feature 都生成）
    lines.append("**状态机（State Diagram）**：\n")
    lines.append("```mermaid")
    lines.append("stateDiagram-v2")
    lines.append("    [*] --> Uninitialized")
    lines.append("    Uninitialized --> Initialized: 系统初始化完成")
    lines.append("    Initialized --> Idle: 进入待机")
    lines.append("    Idle --> Active: 用户触发/事件到达")
    lines.append("    Active --> Processing: 业务处理中")
    lines.append("    Processing --> Active: 处理完成，等待下一事件")
    lines.append("    Active --> Idle: 超时无操作/用户退出")
    lines.append("    Processing --> Error: 异常发生")
    lines.append("    Error --> Recovery: 触发自愈策略")
    lines.append("    Recovery --> Idle: 恢复成功")
    lines.append("    Recovery --> Error: 恢复失败，上报")
    if feature['is_enhanced']:
        lines.append("    Active --> LowPowerMode: 低电量保护触发")
        lines.append("    LowPowerMode --> Active: 电量恢复/用户确认")
        lines.append("    Processing --> OfflineBuffer: BT断开，离线落盘")
        lines.append("    OfflineBuffer --> Active: BT重连，同步完成")
    lines.append("```")
    lines.append("")

    # 4.3 异常流程与自愈
    lines.append("### 4.3 异常流程与自愈\n")
    lines.append("**通用异常场景**：")
    lines.append("")
    lines.append("| 异常场景 | 自愈策略 | 影响范围 |")
    lines.append("|----------|----------|----------|")
    lines.append("| IO 读写错误 | 重试3次，失败后降级到内存缓存，上报错误 | 数据持久化 |")
    lines.append("| BT 连接断开 | 自动重连（指数退避，最多5次），离线数据落盘待同步 | 跨端同步 |")
    lines.append("| 系统重启 | 启动时从持久化存储恢复状态，断点续传 | 全模块 |")
    lines.append("| 协议版本不兼容 | 降级到基础功能集，提示用户升级 | 跨端交互 |")
    lines.append("| 内存不足 | 释放非关键缓存，拒绝新请求，上报系统 | 全模块 |")
    lines.append("| 传感器数据异常 | 丢弃异常帧，使用上一有效值，触发硬件自检 | 数据采集 |")
    lines.append("")

    if feature['is_enhanced']:
        lines.append("**GPS/Fitness 专项异常场景**：")
        lines.append("")
        lines.append("| 异常场景 | 自愈策略 | 影响范围 |")
        lines.append("|----------|----------|----------|")
        lines.append("| GPS 丢星 / 信号弱 | 切换到 ELPO 低功耗定位，融合传感器航位推算，标记数据置信度 | 定位精度 |")
        lines.append("| ELPO 算法失败 | 降级到纯 GPS 模式，关闭融合，降低采样率 | 功耗/精度 |")
        lines.append("| 传感器采样故障 | 切换备用传感器，降低采样率，上报硬件异常 | 数据采集 |")
        lines.append("| 存储满 / LRU 淘汰 | 环形缓存覆盖最旧数据，优先同步到 App，标记数据不完整 | 数据完整性 |")
        lines.append("| 低电量保护 | 自动降采样率，关闭非必要传感器，仅保留核心功能 | 功耗/功能 |")
        lines.append("| 离线数据待同步 | 本地环形缓存，BT 重连后批量同步，支持断点续传 | 数据同步 |")
        lines.append("| 算法处理超时 | 跳过当前帧，降低算法复杂度，使用简化模型 | 实时性 |")
        lines.append("| GPS 源切换 | 多源融合加权，平滑过渡，避免位置跳变 | 定位稳定性 |")
        lines.append("")

    return '\n'.join(lines)


def generate_lld_detail(feature):
    """生成 LLD 级细节设计章节"""
    lines = []
    lines.append("## 5. LLD 级细节设计\n")

    # 5.1 模块接口定义
    lines.append("### 5.1 模块接口定义\n")
    lines.append("#### 5.1.1 业务 Service 接口\n")
    lines.append("```c")
    lines.append("/* 初始化接口 */")
    lines.append("int " + sanitize_name(feature['name']) + "_init(void);")
    lines.append("")
    lines.append("/* 反初始化接口 */")
    lines.append("int " + sanitize_name(feature['name']) + "_deinit(void);")
    lines.append("")
    lines.append("/* 事件处理接口 */")
    lines.append("int " + sanitize_name(feature['name']) + "_handle_event(event_t *evt);")
    lines.append("")
    lines.append("/* 数据获取接口 */")
    lines.append("int " + sanitize_name(feature['name']) + "_get_data(data_type_t type, void *buf, uint32_t len);")
    lines.append("")
    lines.append("/* 数据设置接口 */")
    lines.append("int " + sanitize_name(feature['name']) + "_set_data(data_type_t type, const void *buf, uint32_t len);")
    lines.append("")
    lines.append("/* 状态查询接口 */")
    lines.append("int " + sanitize_name(feature['name']) + "_get_state(state_t *state);")
    lines.append("```")
    lines.append("")

    lines.append("#### 5.1.2 HAL 抽象接口\n")
    lines.append("```c")
    lines.append("/* HAL 读接口 */")
    lines.append("int hal_" + sanitize_name(feature['name']) + "_read(uint32_t addr, void *buf, uint32_t len);")
    lines.append("")
    lines.append("/* HAL 写接口 */")
    lines.append("int hal_" + sanitize_name(feature['name']) + "_write(uint32_t addr, const void *buf, uint32_t len);")
    lines.append("")
    lines.append("/* HAL 控制接口 */")
    lines.append("int hal_" + sanitize_name(feature['name']) + "_ioctl(uint32_t cmd, void *arg);")
    lines.append("")
    lines.append("/* HAL 中断回调注册 */")
    lines.append("int hal_" + sanitize_name(feature['name']) + "_register_isr(isr_handler_t handler, void *ctx);")
    lines.append("```")
    lines.append("")

    if feature['covered_layer'].find('Companion') >= 0:
        lines.append("#### 5.1.3 跨端通信接口（BLE GATT）\n")
        lines.append("| 特征值 UUID | 属性 | 数据格式 | 说明 |")
        lines.append("|------------|------|----------|------|")
        lines.append("| 0xXX01 | Read/Notify | uint8[20] | 状态通知 |")
        lines.append("| 0xXX02 | Write | uint8[20] | 控制指令下发 |")
        lines.append("| 0xXX03 | Read/Write | uint8[244] | 数据批量传输（MTU 协商后） |")
        lines.append("| 0xXX04 | Notify | uint8[20] | 异常/事件上报 |")
        lines.append("")

    # 5.2 关键数据结构
    lines.append("### 5.2 关键数据结构\n")
    lines.append("```c")
    lines.append("/* 模块上下文结构体 */")
    lines.append("typedef struct {")
    lines.append("    uint8_t         state;          /* 模块状态：0=未初始化 1=待机 2=活跃 3=异常 */")
    lines.append("    uint8_t         flags;          /* 配置标志位 */")
    lines.append("    uint16_t        event_mask;     /* 事件订阅掩码 */")
    lines.append("    uint32_t        last_update;    /* 最后更新时间戳（tick） */")
    lines.append("    void            *hal_ctx;       /* HAL 层上下文指针 */")
    lines.append("    void            *storage_ctx;   /* 存储服务上下文指针 */")
    lines.append("    ring_buffer_t   *rx_buf;        /* 接收环形缓冲区 */")
    lines.append("    ring_buffer_t   *tx_buf;        /* 发送环形缓冲区 */")
    lines.append("} " + sanitize_name(feature['name']) + "_ctx_t;")
    lines.append("")
    lines.append("/* 事件结构体 */")
    lines.append("typedef struct {")
    lines.append("    uint16_t        type;           /* 事件类型 */")
    lines.append("    uint16_t        length;         /* 数据长度 */")
    lines.append("    uint32_t        timestamp;      /* 事件时间戳 */")
    lines.append("    uint8_t         data[244];      /* 事件数据（最大 MTU） */")
    lines.append("} event_t;")
    lines.append("")
    lines.append("/* 数据包头 */")
    lines.append("typedef struct __attribute__((packed)) {")
    lines.append("    uint16_t        magic;          /* 魔数 0xA5A5 */")
    lines.append("    uint8_t         version;        /* 协议版本 */")
    lines.append("    uint8_t         type;           /* 数据类型 */")
    lines.append("    uint16_t        length;         /* 数据体长度 */")
    lines.append("    uint16_t        checksum;       /* CRC16 校验 */")
    lines.append("} data_header_t;")
    lines.append("```")
    lines.append("")

    # 5.3 核心算法伪代码
    lines.append("### 5.3 核心算法伪代码\n")
    lines.append("#### 5.3.1 主循环处理流程\n")
    lines.append("```")
    lines.append("function " + sanitize_name(feature['name']) + "_main_loop():")
    lines.append("    while running:")
    lines.append("        event = wait_event(timeout=100ms)")
    lines.append("        if event is null:")
    lines.append("            continue")
    lines.append("        ")
    lines.append("        switch event.type:")
    lines.append("            case EVENT_INIT:")
    lines.append("                do_init()")
    lines.append("            case EVENT_USER_INPUT:")
    lines.append("                handle_user_input(event.data)")
    lines.append("            case EVENT_HAL_DATA:")
    lines.append("                process_hal_data(event.data)")
    lines.append("            case EVENT_BT_DATA:")
    lines.append("                handle_bt_data(event.data)")
    lines.append("            case EVENT_TIMER:")
    lines.append("                do_periodic_task()")
    lines.append("            case EVENT_ERROR:")
    lines.append("                handle_error(event.data)")
    lines.append("        ")
    lines.append("        if need_persist:")
    lines.append("            save_to_storage()")
    lines.append("        if need_sync and bt_connected:")
    lines.append("            sync_to_companion()")
    lines.append("```")
    lines.append("")

    lines.append("#### 5.3.2 数据处理流程\n")
    lines.append("```")
    lines.append("function process_data(raw_data):")
    lines.append("    // 1. 数据校验")
    lines.append("    if not validate_checksum(raw_data):")
    lines.append("        log_error(ERR_CHECKSUM)")
    lines.append("        return ERROR")
    lines.append("    ")
    lines.append("    // 2. 数据解析")
    lines.append("    parsed = parse_header(raw_data)")
    lines.append("    if parsed.version != SUPPORTED_VERSION:")
    lines.append("        log_error(ERR_VERSION)")
    lines.append("        return ERROR")
    lines.append("    ")
    lines.append("    // 3. 业务处理")
    lines.append("    result = do_business_logic(parsed)")
    lines.append("    ")
    lines.append("    // 4. 结果输出")
    lines.append("    update_ui(result)")
    lines.append("    persist_if_needed(result)")
    lines.append("    notify_if_needed(result)")
    lines.append("    ")
    lines.append("    return SUCCESS")
    lines.append("```")
    lines.append("")

    if feature['is_enhanced']:
        lines.append("#### 5.3.3 GPS/Fitness 数据融合算法\n")
        lines.append("```")
        lines.append("function sensor_fusion(gps_data, imu_data, hr_data):")
        lines.append("    // 1. 数据质量评估")
        lines.append("    gps_quality = assess_gps_quality(gps_data)")
        lines.append("    imu_quality = assess_imu_quality(imu_data)")
        lines.append("    ")
        lines.append("    // 2. 加权融合")
        lines.append("    if gps_quality > THRESHOLD_HIGH:")
        lines.append("        weight_gps = 0.8")
        lines.append("        weight_imu = 0.2")
        lines.append("    elif gps_quality > THRESHOLD_LOW:")
        lines.append("        weight_gps = 0.5")
        lines.append("        weight_imu = 0.5")
        lines.append("    else:")
        lines.append("        // GPS 丢星，纯航位推算")
        lines.append("        weight_gps = 0.0")
        lines.append("        weight_imu = 1.0")
        lines.append("        enable_elpo_mode()")
        lines.append("    ")
        lines.append("    // 3. 卡尔曼滤波融合")
        lines.append("    fused = kalman_filter(gps_data * weight_gps + imu_data * weight_imu)")
    lines.append("    ")
    lines.append("    // 4. 异常检测与修正")
    lines.append("    if detect_outlier(fused):")
    lines.append("        fused = use_previous_valid()")
    lines.append("    ")
    lines.append("    return fused")
    lines.append("```")
    lines.append("")

    # 5.4 错误码定义
    lines.append("### 5.4 错误码定义\n")
    lines.append("| 错误码 | 值 | 说明 | 处理策略 |")
    lines.append("|--------|-----|------|----------|")
    lines.append("| ERR_OK | 0x0000 | 成功 | 无 |")
    lines.append("| ERR_PARAM | 0x0001 | 参数错误 | 拒绝操作，上报 |")
    lines.append("| ERR_NOT_INIT | 0x0002 | 模块未初始化 | 触发初始化 |")
    lines.append("| ERR_BUSY | 0x0003 | 模块忙 | 重试（最多3次） |")
    lines.append("| ERR_TIMEOUT | 0x0004 | 操作超时 | 取消操作，恢复状态 |")
    lines.append("| ERR_IO | 0x0005 | IO 读写错误 | 重试3次，失败降级 |")
    lines.append("| ERR_MEMORY | 0x0006 | 内存不足 | 释放缓存，拒绝新请求 |")
    lines.append("| ERR_CHECKSUM | 0x0007 | 校验失败 | 丢弃数据，请求重传 |")
    lines.append("| ERR_VERSION | 0x0008 | 版本不兼容 | 降级到基础功能 |")
    lines.append("| ERR_HW_FAIL | 0x0009 | 硬件故障 | 上报，切换备用 |")
    lines.append("| ERR_STORAGE_FULL | 0x000A | 存储满 | LRU 淘汰，优先同步 |")
    lines.append("| ERR_BT_DISCONNECT | 0x000B | BT 断开 | 自动重连，离线落盘 |")
    if feature['is_enhanced']:
        lines.append("| ERR_GPS_LOST | 0x0010 | GPS 丢星 | 切换 ELPO，航位推算 |")
        lines.append("| ERR_SENSOR_FAIL | 0x0011 | 传感器故障 | 切换备用传感器 |")
        lines.append("| ERR_LOW_BATTERY | 0x0012 | 低电量 | 降采样，功能降级 |")
        lines.append("| ERR_ALGO_TIMEOUT | 0x0013 | 算法超时 | 跳帧，降低复杂度 |")
    lines.append("")

    # 5.5 内存与资源规划
    lines.append("### 5.5 内存与资源规划\n")
    lines.append("| 资源类型 | 大小 | 分配方式 | 生命周期 | 说明 |")
    lines.append("|----------|------|----------|----------|------|")
    lines.append("| 模块上下文 | " + ("64" if not feature['is_enhanced'] else "128") + " B | 静态分配 | 全程 | " + sanitize_name(feature['name']) + "_ctx_t |")
    lines.append("| 接收缓冲区 | 512 B | 静态分配 | 全程 | ring_buffer，防止溢出 |")
    lines.append("| 发送缓冲区 | 256 B | 静态分配 | 全程 | ring_buffer |")
    lines.append("| 事件队列 | 16 × event_t | 静态分配 | 全程 | 消息队列，防止丢失 |")
    lines.append("| 持久化存储 | " + ("2" if not feature['is_enhanced'] else "8") + " KB | KV/FS | 持久 | 配置+历史数据 |")
    if feature['is_enhanced']:
        lines.append("| 算法工作内存 | 4 KB | 动态分配 | 运行时 | 卡尔曼滤波/融合算法 |")
        lines.append("| GPS 星历缓存 | 2 KB | 静态分配 | 全程 | 热启动加速 |")
        lines.append("| 离线数据缓存 | 16 KB | 环形缓存 | 全程 | LRU，7天数据 |")
    lines.append("")
    lines.append("**内存约束**：")
    lines.append("- 静态内存总量 ≤ " + ("2" if not feature['is_enhanced'] else "8") + " KB")
    lines.append("- 动态内存峰值 ≤ " + ("1" if not feature['is_enhanced'] else "6") + " KB")
    lines.append("- 栈使用峰值 ≤ 512 B")
    lines.append("- 禁止运行时内存泄漏（malloc/free 必须配对）")
    lines.append("")

    # 5.6 中断与并发
    lines.append("### 5.6 中断与并发\n")
    lines.append("| 中断源 | 优先级 | 处理函数 | 说明 |")
    lines.append("|--------|--------|----------|------|")
    lines.append("| 定时器 | 中 | " + sanitize_name(feature['name']) + "_timer_isr | 周期性任务触发 |")
    lines.append("| HAL 数据就绪 | 高 | hal_data_ready_isr | 硬件数据到达 |")
    lines.append("| BT 数据接收 | 高 | bt_rx_isr | 跨端数据到达 |")
    lines.append("| 用户按键 | 中 | key_isr | 用户输入 |")
    lines.append("")
    lines.append("**并发保护**：")
    lines.append("- ISR 与主循环共享数据使用临界区保护（关中断/信号量）")
    lines.append("- 环形缓冲区支持单生产者单消费者无锁访问")
    lines.append("- 共享状态变量使用原子操作")
    lines.append("- ISR 内仅做数据搬运和标志位设置，业务逻辑在主循环处理")
    lines.append("")

    # 5.7 函数调用关系
    lines.append("### 5.7 函数调用关系\n")
    lines.append("#### 5.7.1 初始化调用链\n")
    lines.append("```")
    lines.append(sanitize_name(feature['name']) + "_init()")
    lines.append("  ├── hal_init()                          // HAL 层硬件初始化")
    lines.append("  ├── storage_open()                      // 打开持久化存储")
    lines.append("  ├── timer_create()                      // 创建周期性定时器")
    lines.append("  └── event_subscribe()                   // 订阅系统事件")
    lines.append("```")
    lines.append("")
    lines.append("#### 5.7.2 主循环调用链\n")
    lines.append("```")
    lines.append(sanitize_name(feature['name']) + "_main_loop()")
    lines.append("  └── wait_event(timeout=100ms)")
    lines.append("        ├── handle_user_input()           // 用户输入事件")
    lines.append("        │     └── ui_update()             // 更新 UI 渲染")
    lines.append("        ├── process_hal_data()            // HAL 数据就绪事件")
    lines.append("        │     ├── do_business_logic()     // 业务逻辑处理")
    lines.append("        │     └── save_to_storage()       // 持久化关键数据")
    lines.append("        ├── handle_bt_data()              // BT 数据接收事件")
    lines.append("        │     └── sync_to_companion()     // 跨端数据同步")
    lines.append("        └── do_periodic_task()            // 定时器事件")
    lines.append("              ├── save_to_storage()       // 周期数据持久化")
    lines.append("              └── sync_to_companion()     // 周期数据同步")
    lines.append("```")
    lines.append("")
    lines.append("#### 5.7.3 异常处理调用链\n")
    lines.append("```")
    lines.append("handle_error(error_code)")
    lines.append("  ├── log_error(error_code)               // 记录错误日志")
    lines.append("  ├── retry(max=3)                        // 重试机制")
    lines.append("  │     └── fallback()                    // 重试失败降级")
    lines.append("  ├── notify_ui(error_code)               // 通知 UI 显示错误")
    lines.append("  └── report_to_system(error_code)        // 上报系统错误")
    lines.append("```")
    lines.append("")

    return '\n'.join(lines)


def sanitize_name(name):
    """将 Feature 名称转换为合法的 C 函数名前缀"""
    # 移除特殊字符，替换为下划线
    safe = re.sub(r'[^a-zA-Z0-9]', '_', name)
    # 去除连续下划线
    safe = re.sub(r'_+', '_', safe)
    # 去除首尾下划线
    safe = safe.strip('_')
    # 转小写
    safe = safe.lower()
    # 如果以数字开头，加前缀
    if safe and safe[0].isdigit():
        safe = 'f_' + safe
    # 限制长度
    return safe[:30] if safe else 'feature'


def generate_testing(feature):
    """生成测试验收关键点章节"""
    lines = []
    lines.append("## 6. 测试验收关键点\n")

    lines.append("### 6.1 功能测试用例\n")
    lines.append("| 用例ID | 测试场景 | 前置条件 | 预期结果 | 优先级 |")
    lines.append("|--------|----------|----------|----------|--------|")
    lines.append(f"| TC-01 | {feature['name']} 正常功能验证 | 系统初始化完成 | 功能正常，符合 OD 定义 | {feature['priority']} |")
    lines.append("| TC-02 | UI 交互验证 | 进入功能页面 | 交互流畅，响应 ≤ 200ms | P1 |")
    lines.append("| TC-03 | 数据持久化验证 | 操作后重启设备 | 数据正确恢复，无丢失 | P1 |")
    if feature['covered_layer'].find('Companion') >= 0:
        lines.append("| TC-04 | 跨端同步验证 | BT 已连接 | 数据双向同步，状态一致 | P1 |")
    lines.append("| TC-05 | 异常恢复验证 | 模拟 BT 断开/IO错误 | 自动恢复，无数据丢失 | P2 |")
    lines.append("")

    # i18n 测试
    lines.append("### 6.2 国际化测试\n")
    lines.append("| 用例ID | 测试场景 | 预期结果 |")
    lines.append("|--------|----------|----------|")
    lines.append("| TC-I18N-01 | 多语言切换 | 所有文本正确翻译，无乱码 |")
    lines.append("| TC-I18N-02 | RTL 语言（阿拉伯语/希伯来语） | 布局自动镜像，文字方向正确 |")
    lines.append("| TC-I18N-03 | 翻译膨胀 30% | 长文本布局不溢出，marquee 正常 |")
    lines.append("| TC-I18N-04 | 多数字系统 | 阿拉伯文/波斯文数字正确显示 |")
    lines.append("| TC-I18N-05 | 计量单位本地化 | 公制/英制切换正确 |")
    lines.append("")

    # GPS/Fitness 增强测试
    if feature['is_enhanced']:
        lines.append("### 6.3 GPS/Fitness 专项测试\n")
        lines.append("| 用例ID | 测试场景 | 前置条件 | 预期结果 |")
        lines.append("|--------|----------|----------|----------|")
        lines.append("| TC-GPS-01 | 冷启动首次定位 | 无星历缓存 | TTFF ≤ 30s |")
        lines.append("| TC-GPS-02 | 热启动首次定位 | 有星历缓存 | TTFF ≤ 5s |")
        lines.append("| TC-GPS-03 | 定位精度验证 | 开阔场景 | CEP50 ≤ 5m |")
        lines.append("| TC-GPS-04 | GPS 丢星恢复 | 模拟信号遮挡 | 自动恢复，数据平滑 |")
        lines.append("| TC-GPS-05 | 功耗压力测试 | 连续运行2小时 | 平均电流 ≤ 5mA |")
        lines.append("| TC-GPS-06 | 存储 LRU 验证 | 存储满 | 环形覆盖，数据不丢失 |")
        lines.append("| TC-GPS-07 | 离线重连同步 | BT断开24小时后重连 | 数据完整同步，无遗漏 |")
        lines.append("| TC-GPS-08 | 低电量保护 | 电量 ≤ 10% | 自动降采样，功能降级 |")
        lines.append("| TC-GPS-09 | 异常注入测试 | 传感器/GPS异常 | 自愈策略生效，系统不崩溃 |")
        lines.append("| TC-GPS-10 | 算法降级验证 | 高负载场景 | 自动降低复杂度，不丢帧 |")
        lines.append("")

    return '\n'.join(lines)


def generate_references():
    """生成引用参考章节"""
    lines = []
    lines.append("## 7. 引用参考\n")
    lines.append("| 编号 | 文档名称 | 说明 |")
    lines.append("|------|----------|------|")
    lines.append("| [1] | OD 需求定义文档 | Arceau SW OD-Living Excel，Feature 需求来源 |")
    lines.append("| [2] | Moto BT 私有协议规范 | 跨端通信协议定义 |")
    lines.append("| [3] | ICU 国际化文档 | 多语言/RTL/数字系统支持 |")
    lines.append("| [4] | GPS/GNSS 算法文档 | ELPO/多频定位/融合算法说明 |")
    lines.append("| [5] | Fitness 健康算法文档 | 心率/血氧/睡眠/压力算法说明 |")
    lines.append("| [6] | ODM 硬件规格书 | 传感器/GPS/存储硬件参数 |")
    lines.append("| [7] | Mermaid 图表规范 | 时序图/状态机/流程图语法 |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*本文档由 HLD Generator 自动生成，基于 OD 需求做设计推导，包含 HLD 架构与 LLD 级接口/数据结构/算法细节。*")
    return '\n'.join(lines)


# ==================== 索引文件生成 ====================

def generate_index(features):
    """生成索引文件"""
    lines = []
    lines.append("# HLD 文档索引 — 00_INDEX_Enhanced\n")
    lines.append(f"**生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Feature 总数**：{len(features)}")
    enhanced_count = sum(1 for f in features if f['is_enhanced'])
    lines.append(f"**GPS/Fitness 增强**：{enhanced_count} 个")
    lines.append(f"**标准 Feature**：{len(features) - enhanced_count} 个")
    lines.append("")

    # 按大类分组
    categories = {}
    for f in features:
        cat = f['category'] or 'Uncategorized'
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(f)

    for cat, cat_features in sorted(categories.items()):
        lines.append(f"## {cat}\n")
        lines.append("| FeatureID | FeatureName | Priority | Type | 标签 | Markdown文件名 |")
        lines.append("|-----------|-------------|----------|------|------|----------------|")
        for idx, f in enumerate(cat_features, 1):
            fid = f"F{idx:03d}"
            safe_name = re.sub(r'[\\/:*?"<>|]', '_', f['name'])[:50]
            filename = f"{fid}_{safe_name}_HLD.md"
            tag = '[Enhanced-GPS-Fitness]' if f['is_enhanced'] else '[Standard-With-Diagram]'
            lines.append(f"| {fid} | {f['name']} | {f['priority']} | {f['type']} | {tag} | {filename} |")
        lines.append("")

    return '\n'.join(lines)


# ==================== 路由 ====================

@bp_hld.route('/')
def hld_page():
    """HLD 生成器页面"""
    from flask import render_template
    return render_template('hld_generator.html', nav_title='HLD 生成器')


@bp_hld.route('/api/parse', methods=['POST'])
def parse_od():
    """解析 OD Excel，返回 Feature 列表预览"""
    if 'file' not in request.files:
        return jsonify({'error': '请上传 OD Excel 文件'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': '文件名为空'}), 400

    features, error = parse_od_excel(file)
    if error:
        return jsonify({'error': error}), 500

    if not features:
        return jsonify({'error': '未解析到有效 Feature，请检查 OD 表格格式'}), 400

    # 返回预览（前20个 + 统计）
    preview = []
    for idx, f in enumerate(features[:20], 1):
        preview.append({
            'id': f"F{idx:03d}",
            'name': f['name'],
            'priority': f['priority'],
            'category': f['category'],
            'type': f['type'],
            'is_enhanced': f['is_enhanced'],
            'covered_layer': f['covered_layer'],
        })

    return jsonify({
        'total': len(features),
        'enhanced_count': sum(1 for f in features if f['is_enhanced']),
        'preview': preview,
        'features': features,  # 完整列表用于后续生成
    })


@bp_hld.route('/api/generate', methods=['POST'])
def generate_all():
    """生成所有 HLD 并打包 ZIP 下载"""
    data = request.get_json()
    if not data or 'features' not in data:
        return jsonify({'error': '缺少 Feature 数据'}), 400

    features = data['features']
    if not features:
        return jsonify({'error': 'Feature 列表为空'}), 400

    # 生成 ZIP
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 生成索引文件
        index_content = generate_index(features)
        zf.writestr('00_INDEX_Enhanced.md', index_content)

        # 生成每个 Feature 的 HLD
        for idx, f in enumerate(features, 1):
            fid = f"F{idx:03d}"
            content, filename = generate_hld(f, fid)
            zf.writestr(filename, content)

    zip_buffer.seek(0)

    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'HLD_Arceau_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip'
    )


@bp_hld.route('/api/preview', methods=['POST'])
def preview_single():
    """预览单个 Feature 的 HLD"""
    data = request.get_json()
    if not data or 'feature' not in data:
        return jsonify({'error': '缺少 Feature 数据'}), 400

    feature = data['feature']
    fid = data.get('feature_id', 'F001')
    content, filename = generate_hld(feature, fid)

    return jsonify({
        'filename': filename,
        'content': content,
    })
