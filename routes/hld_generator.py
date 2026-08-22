"""
HLD 生成器蓝图
基于 OD Excel 需求文档，自动生成每个 Feature 的高层设计文档（HLD）
支持 GPS/Fitness 增强分支、Mermaid 时序图/状态机、批量 ZIP 下载
"""
import os
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
    sections.append(f"# {name} — 高层设计文档（HLD）\n")

    # 1. 文档信息
    sections.append(generate_doc_info(feature, feature_id, terms))

    # 2. 背景与目标
    sections.append(generate_background(feature))

    # 3. 需求与约束
    sections.append(generate_requirements(feature))

    # 4. 概要设计方案
    sections.append(generate_design(feature))

    # 5. 测试验收关键点
    sections.append(generate_testing(feature))

    # 6. 引用参考
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
    lines.append(f"| Document Type | High-Level Design (HLD) |")
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
    lines.append("- 本文档仅覆盖高层设计（HLD），定义模块职责、数据流、状态流转")
    lines.append("- 不包含函数级实现、寄存器配置、具体变量定义（属于 LLD 范畴）")
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
        lines.append("    UI[UI / i18n 引擎] --> Service[业务 Service]")
        lines.append("    Service --> Algo[算法适配器]")
        lines.append("    Algo --> HAL[HAL / GPS 驱动]")
        lines.append("    HAL --> Sensor[传感器 / GPS 硬件]")
        lines.append("    Service --> Storage[存储服务 / LRU]")
        lines.append("    Service --> BT[BT 协议栈]")
        lines.append("    BT <--> App[Companion App]")
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
    lines.append("    participant UI as UI 层")
    lines.append("    participant Service as 业务 Service")
    lines.append("    participant HAL as HAL/驱动")
    lines.append("    participant BT as BT 栈")
    lines.append("    participant App as Companion App")
    lines.append("")
    lines.append("    Note over Service: 系统初始化")
    lines.append("    Service->>HAL: 硬件初始化")
    lines.append("    HAL-->>Service: 初始化完成")
    lines.append("    Service->>Storage: 加载持久化状态")
    lines.append("")
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


def generate_testing(feature):
    """生成测试验收关键点章节"""
    lines = []
    lines.append("## 5. 测试验收关键点\n")

    lines.append("### 5.1 功能测试用例\n")
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
    lines.append("### 5.2 国际化测试\n")
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
        lines.append("### 5.3 GPS/Fitness 专项测试\n")
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
    lines.append("## 6. 引用参考\n")
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
    lines.append("*本文档由 HLD Generator 自动生成，基于 OD 需求做高层设计推导，不含 LLD 级实现细节。*")
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
    return render_template('hld_generator.html')


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
