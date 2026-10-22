# -*- coding: utf-8 -*-
"""
Agent 能力评估框架

提供标准测试用例、多维度评分、能力雷达图和退化检测。
"""
import logging
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TestCase:
    """测试用例"""
    test_id: str
    name: str
    description: str
    category: str
    input: Dict
    expected_output: Dict
    difficulty: str = 'medium'  # easy, medium, hard


@dataclass
class TestResult:
    """测试结果"""
    test_id: str
    passed: bool
    score: float
    duration: float
    error: str = ''
    details: Dict = field(default_factory=dict)


@dataclass
class EvaluationReport:
    """评估报告"""
    agent_name: str
    total_tests: int
    passed_tests: int
    failed_tests: int
    overall_score: float
    dimension_scores: Dict[str, float]
    test_results: List[TestResult]
    radar_data: List[Dict]
    degradation_detected: bool
    degradation_details: str
    evaluated_at: float


# 标准测试用例
STANDARD_TEST_CASES = [
    TestCase(
        test_id='test_001',
        name='项目状态查询',
        description='测试Agent能否正确查询项目状态',
        category='task_completion',
        input={'task': '查询EKSANTOS项目状态', 'project_key': 'EKSANTOS'},
        expected_output={'tool': 'query_project_status', 'has_project_key': True},
        difficulty='easy'
    ),
    TestCase(
        test_id='test_002',
        name='CR趋势分析',
        description='测试Agent能否分析CR趋势',
        category='tool_selection',
        input={'task': '分析EKSANTOS项目的CR趋势', 'project_key': 'EKSANTOS'},
        expected_output={'tool': 'analyze_cr_trend'},
        difficulty='easy'
    ),
    TestCase(
        test_id='test_003',
        name='风险评估',
        description='测试Agent能否评估项目风险',
        category='task_completion',
        input={'task': '评估EKSANTOS项目风险', 'project_key': 'EKSANTOS'},
        expected_output={'tool': 'assess_project_risk'},
        difficulty='medium'
    ),
    TestCase(
        test_id='test_004',
        name='周报生成',
        description='测试Agent能否生成周报',
        category='result_quality',
        input={'task': '生成EKSANTOS项目周报', 'project_key': 'EKSANTOS'},
        expected_output={'tool': 'generate_weekly_report'},
        difficulty='medium'
    ),
    TestCase(
        test_id='test_005',
        name='多步骤任务规划',
        description='测试Agent能否规划复杂的多步骤任务',
        category='planning_quality',
        input={'task': '全面分析EKSANTOS项目，包括状态查询、CR趋势分析、风险评估，并生成综合报告', 'project_key': 'EKSANTOS'},
        expected_output={'step_count': 4, 'has_query_status': True, 'has_analyze_trend': True, 'has_assess_risk': True, 'has_generate_report': True},
        difficulty='hard'
    ),
    TestCase(
        test_id='test_006',
        name='知识库检索',
        description='测试Agent能否检索知识库',
        category='tool_selection',
        input={'task': '在知识库中搜索蓝牙断连问题', 'query': '蓝牙断连'},
        expected_output={'tool': 'knowledge_search'},
        difficulty='easy'
    ),
    TestCase(
        test_id='test_007',
        name='错误恢复',
        description='测试Agent在工具失败时能否恢复',
        category='error_recovery',
        input={'task': '查询不存在的项目状态', 'project_key': 'INVALID_PROJECT'},
        expected_output={'has_error_handling': True},
        difficulty='hard'
    ),
    TestCase(
        test_id='test_008',
        name='参数提取',
        description='测试Agent能否从任务中正确提取参数',
        category='task_completion',
        input={'task': '查询Santos项目的未解决BC问题', 'project_key': 'EKSANTOS'},
        expected_output={'tool': 'query_unresolved_bc', 'project_key_extracted': True},
        difficulty='medium'
    )
]


# 评估维度
EVALUATION_DIMENSIONS = {
    'task_completion': '任务完成度',
    'tool_selection': '工具选择',
    'planning_quality': '规划质量',
    'result_quality': '结果质量',
    'efficiency': '效率',
    'error_recovery': '错误恢复'
}


class AgentEvaluator:
    """Agent能力评估器"""

    def __init__(self):
        self.test_cases = STANDARD_TEST_CASES
        self.dimensions = EVALUATION_DIMENSIONS
        self.history: List[EvaluationReport] = []

    def evaluate(self, agent_name: str, execute_fn: callable) -> EvaluationReport:
        """执行评估"""
        start_time = time.time()
        test_results = []

        for test_case in self.test_cases:
            test_start = time.time()
            try:
                result = execute_fn(test_case.input)
                passed, score, details = self._check_result(test_case, result)
                test_results.append(TestResult(
                    test_id=test_case.test_id,
                    passed=passed,
                    score=score,
                    duration=time.time() - test_start,
                    details=details
                ))
            except Exception as e:
                test_results.append(TestResult(
                    test_id=test_case.test_id,
                    passed=False,
                    score=0,
                    duration=time.time() - test_start,
                    error=str(e)
                ))

        # 计算各维度得分
        dimension_scores = self._calculate_dimension_scores(test_results)

        # 计算总分
        passed_count = sum(1 for r in test_results if r.passed)
        overall_score = sum(r.score for r in test_results) / len(test_results) if test_results else 0

        # 生成雷达图数据
        radar_data = [
            {'dimension': name, 'score': dimension_scores.get(dim_id, 0)}
            for dim_id, name in self.dimensions.items()
        ]

        # 退化检测
        degradation_detected, degradation_details = self._detect_degradation(overall_score, dimension_scores)

        report = EvaluationReport(
            agent_name=agent_name,
            total_tests=len(test_results),
            passed_tests=passed_count,
            failed_tests=len(test_results) - passed_count,
            overall_score=overall_score,
            dimension_scores=dimension_scores,
            test_results=test_results,
            radar_data=radar_data,
            degradation_detected=degradation_detected,
            degradation_details=degradation_details,
            evaluated_at=time.time()
        )

        self.history.append(report)
        return report

    def _check_result(self, test_case: TestCase, result: Dict) -> Tuple[bool, float, Dict]:
        """检查测试结果"""
        expected = test_case.expected_output
        score = 0.0
        details = {}

        # 检查工具选择
        if 'tool' in expected:
            actual_tool = result.get('tool', '')
            if actual_tool == expected['tool']:
                score += 0.4
                details['tool_correct'] = True
            else:
                details['tool_correct'] = False
                details['expected_tool'] = expected['tool']
                details['actual_tool'] = actual_tool

        # 检查参数
        if 'has_project_key' in expected:
            has_key = bool(result.get('params', {}).get('project_key'))
            if has_key == expected['has_project_key']:
                score += 0.2
                details['project_key_correct'] = True
            else:
                details['project_key_correct'] = False

        # 检查步骤数
        if 'step_count' in expected:
            actual_steps = len(result.get('steps', []))
            if actual_steps >= expected['step_count']:
                score += 0.2
                details['step_count_correct'] = True
            else:
                details['step_count_correct'] = False
                details['expected_steps'] = expected['step_count']
                details['actual_steps'] = actual_steps

        # 检查错误处理
        if 'has_error_handling' in expected:
            has_error = 'error' in result or 'error_message' in result
            if has_error == expected['has_error_handling']:
                score += 0.2
                details['error_handling_correct'] = True
            else:
                details['error_handling_correct'] = False

        passed = score >= 0.6
        return passed, min(score, 1.0), details

    def _calculate_dimension_scores(self, test_results: List[TestResult]) -> Dict[str, float]:
        """计算各维度得分"""
        dimension_tests = {}
        for test in self.test_cases:
            if test.category not in dimension_tests:
                dimension_tests[test.category] = []
            dimension_tests[test.category].append(test.test_id)

        scores = {}
        for dim_id, test_ids in dimension_tests.items():
            dim_results = [r for r in test_results if r.test_id in test_ids]
            if dim_results:
                scores[dim_id] = sum(r.score for r in dim_results) / len(dim_results)
            else:
                scores[dim_id] = 0.0

        return scores

    def _detect_degradation(self, current_score: float, dimension_scores: Dict) -> Tuple[bool, str]:
        """检测性能退化"""
        if not self.history:
            return False, ''

        last_report = self.history[-1]
        if current_score < last_report.overall_score * 0.9:  # 下降超过10%
            return True, f'总体得分从 {last_report.overall_score:.2f} 下降到 {current_score:.2f}，下降超过10%'

        for dim_id, score in dimension_scores.items():
            last_score = last_report.dimension_scores.get(dim_id, 0)
            if last_score > 0 and score < last_score * 0.8:  # 维度下降超过20%
                dim_name = self.dimensions.get(dim_id, dim_id)
                return True, f'{dim_name}维度得分从 {last_score:.2f} 下降到 {score:.2f}，下降超过20%'

        return False, ''

    def get_radar_chart_data(self, report: EvaluationReport) -> List[Dict]:
        """获取雷达图数据"""
        return report.radar_data

    def compare_reports(self, report1: EvaluationReport, report2: EvaluationReport) -> Dict:
        """比较两次评估结果"""
        return {
            'score_change': report2.overall_score - report1.overall_score,
            'passed_change': report2.passed_tests - report1.passed_tests,
            'dimension_changes': {
                dim: report2.dimension_scores.get(dim, 0) - report1.dimension_scores.get(dim, 0)
                for dim in self.dimensions
            },
            'degradation_detected': report2.degradation_detected,
            'degradation_details': report2.degradation_details
        }


_evaluator_instance = None


def get_evaluator() -> AgentEvaluator:
    """获取评估器单例"""
    global _evaluator_instance
    if _evaluator_instance is None:
        _evaluator_instance = AgentEvaluator()
    return _evaluator_instance