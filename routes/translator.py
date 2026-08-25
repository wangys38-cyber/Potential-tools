"""
IT 技术文档翻译器 Blueprint
- 基于 ai_utils.call_ai / call_ai_stream 的 GPT 翻译引擎
- 代码块/占位符/HTML 标签保护
- IT 术语库预置 + 用户上传术语库
- 流式 SSE 输出
- 术语命中位置标注（前端高亮）
"""
import re
import os
import json
import csv
import io
import logging
from flask import Blueprint, request, jsonify, Response, stream_with_context

import ai_utils

logger = logging.getLogger(__name__)

bp_translator = Blueprint('translator', __name__, url_prefix='/api/translate')

# ==================== 预置 IT 术语库（内置默认，可被外部 JSON 覆盖） ====================
_DEFAULT_IT_GLOSSARY = {
    'Cloud Native': '云原生',
    'Container': '容器',
    'Orchestration': '编排',
    'Ingress': '入站',
    'Pod': 'Pod',
    'Middleware': '中间件',
    'Latency': '延迟',
    'Idempotent': '幂等',
    'API': 'API',
    'SDK': 'SDK',
    'Kubernetes': 'Kubernetes',
    'Docker': 'Docker',
    'Cluster': '集群',
    'Namespace': '命名空间',
    'Deployment': '部署',
    'Replica': '副本',
    'Service Mesh': '服务网格',
    'Microservices': '微服务',
    'Monolithic': '单体',
    'CI/CD': 'CI/CD',
    'DevOps': 'DevOps',
    'Agile': '敏捷',
    'Scrum': 'Scrum',
    'Sprint': '迭代',
    'Backlog': '待办列表',
    'Refactor': '重构',
    'Debug': '调试',
    'Compile': '编译',
    'Runtime': '运行时',
    'Build': '构建',
    'Deploy': '部署',
    'Rollback': '回滚',
    'Hotfix': '热修复',
    'Patch': '补丁',
    'Release': '发布',
    'Version': '版本',
    'Repository': '仓库',
    'Branch': '分支',
    'Merge': '合并',
    'Conflict': '冲突',
    'Commit': '提交',
    'Pull Request': '拉取请求',
    'Code Review': '代码审查',
    'Unit Test': '单元测试',
    'Integration Test': '集成测试',
    'End-to-End': '端到端',
    'Regression': '回归',
    'Coverage': '覆盖率',
    'Benchmark': '基准测试',
    'Profiling': '性能分析',
    'Memory Leak': '内存泄漏',
    'Deadlock': '死锁',
    'Race Condition': '竞态条件',
    'Thread Safety': '线程安全',
    'Concurrency': '并发',
    'Parallelism': '并行',
    'Asynchronous': '异步',
    'Synchronous': '同步',
    'Callback': '回调',
    'Promise': 'Promise',
    'Event Loop': '事件循环',
    'Garbage Collection': '垃圾回收',
    'Heap': '堆',
    'Stack': '栈',
    'Buffer': '缓冲区',
    'Cache': '缓存',
    'Queue': '队列',
    'Stack Trace': '堆栈跟踪',
    'Exception': '异常',
    'Error Handling': '错误处理',
    'Logging': '日志',
    'Monitoring': '监控',
    'Alerting': '告警',
    'Tracing': '链路追踪',
    'Metrics': '指标',
    'Dashboard': '看板',
    'SLA': 'SLA',
    'SLO': 'SLO',
    'SLI': 'SLI',
    'Uptime': '可用率',
    'Downtime': '停机时间',
    'Outage': '故障',
    'Incident': '事件',
    'Postmortem': '事后复盘',
    'Root Cause': '根因',
    'Mitigation': '缓解措施',
    'Workaround': '临时方案',
    'Fix': '修复',
    'Bug': 'Bug',
    'Defect': '缺陷',
    'Issue': '问题',
    'Ticket': '工单',
    'Feature': '功能',
    'Enhancement': '增强',
    'Refactoring': '重构',
    'Deprecation': '弃用',
    'Breaking Change': '破坏性变更',
    'Backward Compatible': '向后兼容',
    'Forward Compatible': '向前兼容',
    'Migration': '迁移',
    'Upgrade': '升级',
    'Downgrade': '降级',
    'Scalability': '可扩展性',
    'Availability': '可用性',
    'Reliability': '可靠性',
    'Maintainability': '可维护性',
    'Readability': '可读性',
    'Performance': '性能',
    'Security': '安全性',
    'Usability': '易用性',
    'Accessibility': '无障碍',
    'Responsive': '响应式',
    'Adaptive': '自适应',
    'Cross-platform': '跨平台',
    'Native': '原生',
    'Hybrid': '混合',
    'Web App': 'Web 应用',
    'Mobile App': '移动应用',
    'Desktop App': '桌面应用',
    'Backend': '后端',
    'Frontend': '前端',
    'Full-stack': '全栈',
    'Client-side': '客户端',
    'Server-side': '服务端',
    'Middleware': '中间件',
    'Gateway': '网关',
    'Proxy': '代理',
    'Load Balancer': '负载均衡器',
    'Firewall': '防火墙',
    'CDN': 'CDN',
    'DNS': 'DNS',
    'SSL': 'SSL',
    'TLS': 'TLS',
    'HTTPS': 'HTTPS',
    'OAuth': 'OAuth',
    'JWT': 'JWT',
    'Session': '会话',
    'Cookie': 'Cookie',
    'Token': '令牌',
    'Authentication': '认证',
    'Authorization': '授权',
    'Encryption': '加密',
    'Decryption': '解密',
    'Hashing': '哈希',
    'Salting': '加盐',
    'Vulnerability': '漏洞',
    'Exploit': '利用',
    'Patch': '补丁',
    'Penetration Testing': '渗透测试',
    'Threat Model': '威胁模型',
    'Risk Assessment': '风险评估',
    'Compliance': '合规',
    'GDPR': 'GDPR',
    'SOC2': 'SOC2',
    'ISO 27001': 'ISO 27001',
    'Audit': '审计',
    'Logging': '日志',
    'Retention': '保留',
    'Archiving': '归档',
    'Backup': '备份',
    'Restore': '恢复',
    'Disaster Recovery': '灾难恢复',
    'Business Continuity': '业务连续性',
    'RPO': 'RPO',
    'RTO': 'RTO',
    'Failover': '故障转移',
    'Redundancy': '冗余',
    'Replication': '复制',
    'Sharding': '分片',
    'Partitioning': '分区',
    'Indexing': '索引',
    'Query Optimization': '查询优化',
    'Normalization': '规范化',
    'Denormalization': '反规范化',
    'ACID': 'ACID',
    'BASE': 'BASE',
    'CAP Theorem': 'CAP 定理',
    'Consistency': '一致性',
    'Availability': '可用性',
    'Partition Tolerance': '分区容错',
    'Eventual Consistency': '最终一致性',
    'Strong Consistency': '强一致性',
    'Read Replica': '只读副本',
    'Write Ahead Log': '预写日志',
    'Checkpoint': '检查点',
    'Snapshot': '快照',
    'MVCC': 'MVCC',
    'Deadlock': '死锁',
    'Livelock': '活锁',
    'Starvation': '饥饿',
    'Fairness': '公平性',
    'Throughput': '吞吐量',
    'Bandwidth': '带宽',
    'Latency': '延迟',
    'Jitter': '抖动',
    'Packet Loss': '丢包',
    'Round Trip Time': '往返时间',
    'TTL': 'TTL',
    'Keepalive': '保活',
    'Heartbeat': '心跳',
    'Health Check': '健康检查',
    'Circuit Breaker': '熔断器',
    'Bulkhead': '舱壁隔离',
    'Rate Limiting': '限流',
    'Throttling': '节流',
    'Backpressure': '背压',
    'Retry': '重试',
    'Exponential Backoff': '指数退避',
    'Timeout': '超时',
    'Fallback': '降级',
    'Graceful Degradation': '优雅降级',
    'Graceful Shutdown': '优雅关闭',
    'Liveness Probe': '存活探针',
    'Readiness Probe': '就绪探针',
    'Startup Probe': '启动探针',
    'Resource Quota': '资源配额',
    'Limit Range': '限制范围',
    'Horizontal Pod Autoscaler': '水平 Pod 自动扩缩容',
    'Vertical Pod Autoscaler': '垂直 Pod 自动扩缩容',
    'Cluster Autoscaler': '集群自动扩缩容',
    'Node': '节点',
    'Worker Node': '工作节点',
    'Master Node': '主节点',
    'Control Plane': '控制平面',
    'Data Plane': '数据平面',
    'etcd': 'etcd',
    'kubelet': 'kubelet',
    'kube-proxy': 'kube-proxy',
    'kubectl': 'kubectl',
    'Helm': 'Helm',
    'Chart': 'Chart',
    'Manifest': '清单',
    'YAML': 'YAML',
    'JSON': 'JSON',
    'TOML': 'TOML',
    'XML': 'XML',
    'Protocol Buffers': 'Protocol Buffers',
    'gRPC': 'gRPC',
    'REST': 'REST',
    'GraphQL': 'GraphQL',
    'WebSocket': 'WebSocket',
    'SSE': 'SSE',
    'Webhook': 'Webhook',
    'Polling': '轮询',
    'Long Polling': '长轮询',
    'Push': '推送',
    'Pub/Sub': '发布/订阅',
    'Message Queue': '消息队列',
    'Topic': '主题',
    'Partition': '分区',
    'Consumer': '消费者',
    'Producer': '生产者',
    'Broker': '代理',
    'Offset': '偏移量',
    'Commit Offset': '提交偏移量',
    'Rebalance': '再平衡',
    'Consumer Group': '消费者组',
    'Exactly Once': '精确一次',
    'At Least Once': '至少一次',
    'At Most Once': '至多一次',
    'Idempotent': '幂等',
    'Transaction': '事务',
    ' Saga': 'Saga',
    'CQRS': 'CQRS',
    'Event Sourcing': '事件溯源',
    'DDD': '领域驱动设计',
    'Domain Model': '领域模型',
    'Aggregate': '聚合',
    'Entity': '实体',
    'Value Object': '值对象',
    'Repository': '仓库',
    'Service': '服务',
    'Factory': '工厂',
    'Builder': '构建器',
    'Singleton': '单例',
    'Observer': '观察者',
    'Strategy': '策略',
    'Decorator': '装饰器',
    'Adapter': '适配器',
    'Facade': '外观',
    'Proxy': '代理',
    'Bridge': '桥接',
    'Composite': '组合',
    'Flyweight': '享元',
    'Template Method': '模板方法',
    'Command': '命令',
    'Iterator': '迭代器',
    'Mediator': '中介者',
    'Memento': '备忘录',
    'State': '状态',
    'Visitor': '访问者',
    'Interpreter': '解释器',
    'SOLID': 'SOLID',
    'DRY': 'DRY',
    'KISS': 'KISS',
    'YAGNI': 'YAGNI',
    'Boy Scout Rule': '童子军规则',
    'Clean Code': '整洁代码',
    'Code Smell': '代码异味',
    'Technical Debt': '技术债务',
    'Spike': '技术探索',
    'POC': '概念验证',
    'Prototype': '原型',
    'MVP': '最小可行产品',
    'Roadmap': '路线图',
    'Milestone': '里程碑',
    'Deliverable': '交付物',
    'Acceptance Criteria': '验收标准',
    'Definition of Done': '完成定义',
    'Story Point': '故事点',
    'Velocity': '速率',
    'Burndown': '燃尽图',
    'Burnup': '燃起图',
    'Cumulative Flow': '累积流图',
    'Lead Time': '前置时间',
    'Cycle Time': '周期时间',
    'Throughput': '吞吐量',
    'WIP': '在制品',
    'Kanban': '看板',
    'Scrum': 'Scrum',
    'XP': '极限编程',
    'Pair Programming': '结对编程',
    'TDD': '测试驱动开发',
    'BDD': '行为驱动开发',
    'ATDD': '验收测试驱动开发',
    'Continuous Integration': '持续集成',
    'Continuous Delivery': '持续交付',
    'Continuous Deployment': '持续部署',
    'Pipeline': '流水线',
    'Stage': '阶段',
    'Job': '任务',
    'Artifact': '制品',
    'Registry': '注册中心',
    'Image': '镜像',
    'Layer': '层',
    'Volume': '卷',
    'Mount': '挂载',
    'Bind Mount': '绑定挂载',
    'Tmpfs': 'Tmpfs',
    'Network': '网络',
    'Bridge': '桥接',
    'Overlay': '覆盖',
    'Host': '主机',
    'None': '无',
    'Port Mapping': '端口映射',
    'Expose': '暴露',
    'Publish': '发布',
    'Link': '链接',
    'Alias': '别名',
    'DNS Resolution': 'DNS 解析',
    'Service Discovery': '服务发现',
    'Registrar': '注册器',
    'Resolver': '解析器',
    'Load Balancing': '负载均衡',
    'Round Robin': '轮询',
    'Least Connections': '最少连接',
    'IP Hash': 'IP 哈希',
    'Random': '随机',
    'Sticky Session': '粘性会话',
    'Health Check': '健康检查',
    'Active Health Check': '主动健康检查',
    'Passive Health Check': '被动健康检查',
    'Connection Pool': '连接池',
    'Thread Pool': '线程池',
    'Object Pool': '对象池',
    'Resource Pool': '资源池',
    'Eviction': '驱逐',
    'Expiration': '过期',
    'Invalidation': '失效',
    'Cache Hit': '缓存命中',
    'Cache Miss': '缓存未命中',
    'Cache Stampede': '缓存击穿',
    'Cache Avalanche': '缓存雪崩',
    'Cache Penetration': '缓存穿透',
    'Bloom Filter': '布隆过滤器',
    'HyperLogLog': 'HyperLogLog',
    'Bitmap': '位图',
    'GeoHash': 'GeoHash',
    'Pub/Sub': '发布/订阅',
    'Stream': '流',
    'List': '列表',
    'Set': '集合',
    'Sorted Set': '有序集合',
    'Hash': '哈希',
    'String': '字符串',
    'TTL': 'TTL',
    'Persistence': '持久化',
    'RDB': 'RDB',
    'AOF': 'AOF',
    'Cluster': '集群',
    'Sentinel': '哨兵',
    'Master-Slave': '主从',
    'Read-Write Separation': '读写分离',
    'Sharding': '分片',
    'Proxy': '代理',
    'Middleware': '中间件',
    'ORM': 'ORM',
    'ODM': 'ODM',
    'SQL': 'SQL',
    'NoSQL': 'NoSQL',
    'NewSQL': 'NewSQL',
    'RDBMS': '关系型数据库',
    'Document Store': '文档存储',
    'Key-Value Store': '键值存储',
    'Column Family': '列族',
    'Graph Database': '图数据库',
    'Time Series': '时序',
    'Search Engine': '搜索引擎',
    'Full-Text Search': '全文搜索',
    'Inverted Index': '倒排索引',
    'Tokenization': '分词',
    'Stemming': '词干提取',
    'Lemmatization': '词形还原',
    'Stop Words': '停用词',
    'Synonym': '同义词',
    'Relevance': '相关性',
    'Ranking': '排序',
    'Scoring': '评分',
    'Boost': '提升',
    'Filter': '过滤',
    'Facet': '分面',
    'Aggregation': '聚合',
    'Bucket': '桶',
    'Metric': '指标',
    'Pipeline Aggregation': '管道聚合',
    'Shard': '分片',
    'Replica': '副本',
    'Segment': '段',
    'Commit': '提交',
    'Refresh': '刷新',
    'Flush': '刷盘',
    'Merge': '合并',
    'Optimize': '优化',
    'Snapshot': '快照',
    'Restore': '恢复',
    'Reindex': '重建索引',
    'Alias': '别名',
    'Template': '模板',
    'Mapping': '映射',
    'Setting': '设置',
    'Analyzer': '分析器',
    'Tokenizer': '分词器',
    'Filter': '过滤器',
    'Char Filter': '字符过滤器',
    'Ingest Pipeline': '摄取管道',
    'Processor': '处理器',
    'Watcher': '观察器',
    'Alert': '告警',
    'Action': '动作',
    'Condition': '条件',
    'Transform': '转换',
    'Throttle': '节流',
    'Period': '周期',
    'Schedule': '调度',
    'Cron': 'Cron',
    'Interval': '间隔',
    'Delay': '延迟',
    'Timeout': '超时',
    'Retry': '重试',
    'Backoff': '退避',
    'Jitter': '抖动',
    'Dead Letter Queue': '死信队列',
    'DLQ': 'DLQ',
    'Poison Message': '毒消息',
    'Redelivery': '重新投递',
    'Ack': '确认',
    'Nack': '否定确认',
    'Reject': '拒绝',
    'Prefetch': '预取',
    'Concurrency': '并发',
    'Parallelism': '并行度',
    'Worker': '工作器',
    'Executor': '执行器',
    'Scheduler': '调度器',
    'Dispatcher': '分发器',
    'Router': '路由器',
    'Handler': '处理器',
    'Listener': '监听器',
    'Subscriber': '订阅者',
    'Publisher': '发布者',
    'Emitter': '发射器',
    'Trigger': '触发器',
    'Hook': '钩子',
    'Callback': '回调',
    'Event': '事件',
    'Message': '消息',
    'Command': '命令',
    'Query': '查询',
    'Request': '请求',
    'Response': '响应',
    'Result': '结果',
    'Output': '输出',
    'Input': '输入',
    'Payload': '载荷',
    'Header': '头',
    'Body': '体',
    'Metadata': '元数据',
    'Context': '上下文',
    'State': '状态',
    'Status': '状态',
    'Code': '码',
    'Error': '错误',
    'Exception': '异常',
    'Failure': '失败',
    'Success': '成功',
    'Pending': '待处理',
    'Running': '运行中',
    'Completed': '已完成',
    'Failed': '失败',
    'Cancelled': '已取消',
    'Aborted': '已中止',
    'Timeout': '超时',
    'Skipped': '已跳过',
    'Queued': '排队中',
    'Scheduled': '已调度',
    'Waiting': '等待中',
    'Processing': '处理中',
    'Retrying': '重试中',
    'Paused': '已暂停',
    'Resumed': '已恢复',
    'Blocked': '被阻塞',
    'Unblocked': '已解除阻塞',
}

# 运行时加载术语库：优先运行时目录 → bundled glossaries/ → 内置默认
_BUNDLED_GLOSSARY_DIR = os.path.join(os.path.dirname(__file__), '..', 'glossaries')
_RUNTIME_GLOSSARY_DIR = os.path.join(os.environ.get('DB_DIR', '/tmp/toolbox'), 'glossaries')


def _load_glossary():
    """加载 IT 术语库 JSON，支持运行时覆盖"""
    for d in [_RUNTIME_GLOSSARY_DIR, _BUNDLED_GLOSSARY_DIR]:
        path = os.path.join(d, 'it_glossary.json')
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    logger.info(f'术语库已从外部加载: {path} ({len(loaded)} 条)')
                    return loaded
            except Exception as e:
                logger.warning(f'加载术语库失败 {path}: {e}')
    return dict(_DEFAULT_IT_GLOSSARY)


IT_GLOSSARY = _load_glossary()

# ==================== 代码块保护 ====================
# 匹配模式：fenced code block, inline code, HTML tag, ${var}, {{placeholder}}
PROTECT_PATTERNS = [
    (re.compile(r'```[\s\S]*?```', re.MULTILINE), 'FENCED'),
    (re.compile(r'`[^`\n]+`'), 'INLINE'),
    (re.compile(r'<\/?[a-zA-Z][^>]*>'), 'HTML'),
    (re.compile(r'\$\{[^}]+\}'), 'TEMPLATE_VAR'),
    (re.compile(r'\{\{[^}]+\}\}'), 'PLACEHOLDER'),
]


def protect_code(text):
    """将代码块/占位符替换为唯一占位符，返回 (处理后文本, 占位符映射)"""
    placeholders = {}
    counter = [0]

    def _replace(match, prefix):
        counter[0] += 1
        key = f'\x00{prefix}_{counter[0]}\x00'
        placeholders[key] = match.group(0)
        return key

    result = text
    for pattern, prefix in PROTECT_PATTERNS:
        result = pattern.sub(lambda m, p=prefix: _replace(m, p), result)

    return result, placeholders


def restore_code(text, placeholders):
    """将占位符还原为原代码块"""
    for key, original in placeholders.items():
        text = text.replace(key, original)
    return text


# ==================== 术语处理 ====================
def build_glossary_prompt(user_glossary=None, it_mode=True):
    """构建术语库 prompt 文本"""
    glossary = {}
    if it_mode:
        glossary.update(IT_GLOSSARY)
    if user_glossary:
        glossary.update(user_glossary)

    if not glossary:
        return ''

    lines = []
    for en, zh in glossary.items():
        lines.append(f'- {en} → {zh}')
    return '\n'.join(lines)


def find_glossary_hits(translated_text, user_glossary=None, it_mode=True):
    """在译文中查找命中术语库的位置，返回 [{term, translation, index}]"""
    glossary = {}
    if it_mode:
        glossary.update(IT_GLOSSARY)
    if user_glossary:
        glossary.update(user_glossary)

    hits = []
    # 按术语长度降序，避免短词先匹配
    for en, zh in sorted(glossary.items(), key=lambda x: -len(x[1])):
        if not zh or zh == en:
            continue
        start = 0
        while True:
            idx = translated_text.find(zh, start)
            if idx == -1:
                break
            hits.append({'term': en, 'translation': zh, 'index': idx})
            start = idx + len(zh)

    # 按位置排序，去重重叠
    hits.sort(key=lambda x: x['index'])
    return hits


# ==================== System Prompt 构建 ====================
def build_system_prompt(target_lang, glossary_text, it_mode):
    """构建翻译 system prompt"""
    lang_map = {
        'zh': 'Simplified Chinese (zh-CN)',
        'en': 'English (US)',
        'ja': 'Japanese',
        'ko': 'Korean',
        'fr': 'French',
        'de': 'German',
        'es': 'Spanish',
        'ru': 'Russian',
        'pt': 'Portuguese',
        'it': 'Italian',
        'ar': 'Arabic',
    }
    target = lang_map.get(target_lang, target_lang)

    rules = [
        'You are a professional IT technical translator.',
        f'Translate the following text into {target}.',
        'Rules:',
        '1. Do NOT translate code blocks, inline code, variables, CLI commands, API names, SDK names, brand names, or error codes. They are wrapped in special markers (\\x00...\\x00) — keep them EXACTLY as-is.',
        '2. Keep Markdown structure (headers, lists, bold, italic, links) intact.',
        '3. Preserve numbers and units (e.g. 2.5GHz, 64GB, 100ms).',
        '4. Do NOT add explanations, notes, or comments. Output ONLY the translated text.',
        '5. Maintain the original paragraph breaks and line breaks.',
    ]

    if it_mode and glossary_text:
        rules.append('6. Apply the following glossary strictly (use the target translation for each term):')
        rules.append(glossary_text)

    return '\n'.join(rules)


# ==================== 翻译主逻辑 ====================
def translate_text(text, source_lang='auto', target_lang='zh',
                    user_glossary=None, it_mode=True, stream=False):
    """执行翻译，返回译文或流式生成器"""
    if not text or not text.strip():
        if stream:
            yield 'data: {"done": true}\n\n'
            return
        return ''

    # 1. 预处理：保护代码块
    protected_text, placeholders = protect_code(text)

    # 2. 构建术语库
    glossary_text = build_glossary_prompt(user_glossary, it_mode)

    # 3. 构建 system prompt
    system_prompt = build_system_prompt(target_lang, glossary_text, it_mode)

    messages = [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': protected_text},
    ]

    if stream:
        # 流式输出
        buffer = ''
        for chunk in ai_utils.call_ai_stream(messages, temperature=0.3, max_tokens=4000):
            try:
                # 解析 SSE 数据
                if chunk.startswith('data: '):
                    data_str = chunk[6:].strip()
                    if data_str == '[DONE]':
                        break
                    data = json.loads(data_str)
                    if 'error' in data:
                        yield f'data: {{"error": "{data["error"]}"}}\n\n'
                        return
                    content = ''
                    # 兼容 DashScope 和 OpenAI 格式
                    if 'output' in data:
                        content = data.get('output', {}).get('choices', [{}])[0].get('message', {}).get('content', '')
                    elif 'choices' in data:
                        content = data.get('choices', [{}])[0].get('delta', {}).get('content', '')
                    if content:
                        buffer += content
                        # 还原占位符（增量）
                        restored = restore_code(content, placeholders)
                        yield f'data: {{"chunk": {json.dumps(restored, ensure_ascii=False)}}}\n\n'
            except (json.JSONDecodeError, KeyError, IndexError):
                continue

        # 完成
        final_text = restore_code(buffer, placeholders)
        hits = find_glossary_hits(final_text, user_glossary, it_mode)
        yield f'data: {{"done": true, "hits": {json.dumps(hits, ensure_ascii=False)}}}\n\n'
        return

    # 非流式
    try:
        result = ai_utils.call_ai(messages, temperature=0.3, max_tokens=4000, timeout=120)
    except Exception as e:
        logger.error(f'翻译失败: {e}')
        raise

    # 4. 后处理：还原代码块
    translated = restore_code(result, placeholders)

    # 5. 术语命中标注
    hits = find_glossary_hits(translated, user_glossary, it_mode)

    return translated, hits


# ==================== API 端点 ====================

@bp_translator.route('', methods=['POST'])
def translate():
    """翻译主接口（非流式）"""
    data = request.get_json(silent=True) or {}
    text = data.get('text', '').strip()
    source_lang = data.get('source_lang', 'auto')
    target_lang = data.get('target_lang', 'zh')
    user_glossary = data.get('glossary')
    it_mode = data.get('it_mode', True)

    if not text:
        return jsonify({'error': '文本不能为空'}), 400

    if len(text) > 50000:
        return jsonify({'error': '文本过长，最大支持 50000 字符'}), 400

    try:
        translated, hits = translate_text(
            text, source_lang, target_lang, user_glossary, it_mode, stream=False
        )
        return jsonify({
            'translation': translated,
            'hits': hits,
            'source_lang': source_lang,
            'target_lang': target_lang,
        })
    except Exception as e:
        logger.error(f'翻译接口错误: {e}')
        return jsonify({'error': str(e)}), 500


@bp_translator.route('/stream', methods=['POST'])
def translate_stream():
    """流式翻译接口（SSE）"""
    data = request.get_json(silent=True) or {}
    text = data.get('text', '').strip()
    source_lang = data.get('source_lang', 'auto')
    target_lang = data.get('target_lang', 'zh')
    user_glossary = data.get('glossary')
    it_mode = data.get('it_mode', True)

    if not text:
        return jsonify({'error': '文本不能为空'}), 400

    if len(text) > 50000:
        return jsonify({'error': '文本过长，最大支持 50000 字符'}), 400

    def generate():
        try:
            yield from translate_text(
                text, source_lang, target_lang, user_glossary, it_mode, stream=True
            )
        except Exception as e:
            logger.error(f'流式翻译错误: {e}')
            yield f'data: {{"error": "{str(e)}"}}\n\n'

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        }
    )


@bp_translator.route('/glossary', methods=['POST'])
def parse_glossary():
    """解析上传的 CSV 术语库"""
    if 'file' not in request.files:
        return jsonify({'error': '未上传文件'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '文件名为空'}), 400

    if not file.filename.lower().endswith('.csv'):
        return jsonify({'error': '仅支持 CSV 格式'}), 400

    try:
        content = file.read().decode('utf-8-sig')
        reader = csv.reader(io.StringIO(content))
        glossary = {}
        for row in reader:
            if len(row) >= 2:
                en = row[0].strip()
                zh = row[1].strip()
                if en and zh:
                    glossary[en] = zh
        return jsonify({
            'glossary': glossary,
            'count': len(glossary),
        })
    except Exception as e:
        logger.error(f'术语库解析失败: {e}')
        return jsonify({'error': f'解析失败: {str(e)}'}), 500


@bp_translator.route('/languages', methods=['GET'])
def get_languages():
    """获取支持的语言列表"""
    languages = [
        {'code': 'auto', 'name': '自动检测'},
        {'code': 'zh', 'name': '中文'},
        {'code': 'en', 'name': '英语'},
        {'code': 'ja', 'name': '日语'},
        {'code': 'ko', 'name': '韩语'},
        {'code': 'fr', 'name': '法语'},
        {'code': 'de', 'name': '德语'},
        {'code': 'es', 'name': '西班牙语'},
        {'code': 'ru', 'name': '俄语'},
        {'code': 'pt', 'name': '葡萄牙语'},
        {'code': 'it', 'name': '意大利语'},
        {'code': 'ar', 'name': '阿拉伯语'},
    ]
    return jsonify({'languages': languages})
