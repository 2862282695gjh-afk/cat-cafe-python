"""
第六层：审计记录层 (Audit Logging Layer)
- 操作日志完整追踪
- 安全事件实时告警
- 合规报告定期审计
"""
import os
import re
import json
import time
import asyncio
import hashlib
import threading
from typing import Any, Dict, List, Optional, Callable, Set, Union
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
import logging
from abc import ABC, abstractmethod


class AuditEventType(Enum):
    """审计事件类型"""
    # 工具执行
    TOOL_EXECUTE = "tool_execute"
    TOOL_SUCCESS = "tool_success"
    TOOL_FAILURE = "tool_failure"
    TOOL_CANCELLED = "tool_cancelled"

    # 权限
    PERMISSION_CHECK = "permission_check"
    PERMISSION_GRANTED = "permission_granted"
    PERMISSION_DENIED = "permission_denied"
    PERMISSION_ASK = "permission_ask"

    # 安全事件
    SECURITY_VIOLATION = "security_violation"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    INJECTION_ATTEMPT = "injection_attempt"

    # 系统事件
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    CONFIG_CHANGE = "config_change"
    ERROR_OCCURRED = "error_occurred"

    # 资源事件
    RESOURCE_LIMIT_EXCEEDED = "resource_limit_exceeded"
    SANDBOX_VIOLATION = "sandbox_violation"


class AuditSeverity(Enum):
    """审计严重程度"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertType(Enum):
    """告警类型"""
    SECURITY = "security"
    PERFORMANCE = "performance"
    COMPLIANCE = "compliance"
    OPERATIONAL = "operational"


@dataclass
class AuditEvent:
    """审计事件"""
    event_id: str
    event_type: AuditEventType
    severity: AuditSeverity
    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    tool_name: Optional[str] = None
    execution_id: Optional[str] = None
    description: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.event_id:
            self.event_id = self._generate_id()

    def _generate_id(self) -> str:
        """生成事件 ID"""
        data = f"{self.event_type.value}:{self.timestamp}:{self.tool_name or ''}"
        return hashlib.md5(data.encode()).hexdigest()[:16]

    def to_dict(self) -> Dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "severity": self.severity.value,
            "timestamp": self.timestamp,
            "datetime": datetime.fromtimestamp(self.timestamp / 1000).isoformat(),
            "user_id": self.user_id,
            "session_id": self.session_id,
            "tool_name": self.tool_name,
            "execution_id": self.execution_id,
            "description": self.description,
            "details": self._sanitize_details(self.details),
            "metadata": self.metadata,
        }

    def _sanitize_details(self, details: Dict) -> Dict:
        """清理敏感信息"""
        sensitive_keys = {
            "password", "secret", "key", "token", "credential",
            "api_key", "auth", "private"
        }

        sanitized = {}
        for k, v in details.items():
            if any(s in k.lower() for s in sensitive_keys):
                sanitized[k] = "[REDACTED]"
            elif isinstance(v, dict):
                sanitized[k] = self._sanitize_details(v)
            elif isinstance(v, str) and len(v) > 500:
                sanitized[k] = v[:500] + "...[truncated]"
            else:
                sanitized[k] = v

        return sanitized


@dataclass
class SecurityAlert:
    """安全告警"""
    alert_id: str
    alert_type: AlertType
    severity: AuditSeverity
    title: str
    message: str
    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))
    source_event: Optional[AuditEvent] = None
    acknowledged: bool = False
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "alert_id": self.alert_id,
            "alert_type": self.alert_type.value,
            "severity": self.severity.value,
            "title": self.title,
            "message": self.message,
            "timestamp": self.timestamp,
            "datetime": datetime.fromtimestamp(self.timestamp / 1000).isoformat(),
            "source_event": self.source_event.to_dict() if self.source_event else None,
            "acknowledged": self.acknowledged,
            "acknowledged_by": self.acknowledged_by,
            "acknowledged_at": self.acknowledged_at,
        }


# ============================================================================
# 审计存储
# ============================================================================

class AuditStorage(ABC):
    """审计存储基类"""

    @abstractmethod
    async def store(self, event: AuditEvent):
        """存储事件"""
        pass

    @abstractmethod
    async def query(
        self,
        start_time: int = None,
        end_time: int = None,
        event_types: List[AuditEventType] = None,
        severity: List[AuditSeverity] = None,
        limit: int = 100
    ) -> List[AuditEvent]:
        """查询事件"""
        pass

    @abstractmethod
    async def get_stats(self, period_hours: int = 24) -> Dict[str, Any]:
        """获取统计"""
        pass


class FileAuditStorage(AuditStorage):
    """文件审计存储"""

    def __init__(self, storage_dir: str = None, max_file_size_mb: int = 10):
        self.storage_dir = storage_dir or os.path.join(os.getcwd(), ".deepseek", "audit")
        self.max_file_size_mb = max_file_size_mb

        os.makedirs(self.storage_dir, exist_ok=True)

        self._current_file = None
        self._current_file_date = None
        self._lock = asyncio.Lock()

    async def store(self, event: AuditEvent):
        """存储事件"""
        async with self._lock:
            file_path = self._get_current_file()

            with open(file_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    async def query(
        self,
        start_time: int = None,
        end_time: int = None,
        event_types: List[AuditEventType] = None,
        severity: List[AuditSeverity] = None,
        limit: int = 100
    ) -> List[AuditEvent]:
        """查询事件"""
        results = []
        event_type_set = {et.value for et in event_types} if event_types else None
        severity_set = {s.value for s in severity} if severity else None

        # 遍历所有审计文件
        for file_path in sorted(Path(self.storage_dir).glob("audit_*.jsonl")):
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())
                        event = AuditEvent(**{
                            k: v for k, v in data.items()
                            if k in AuditEvent.__dataclass_fields__
                        })

                        # 应用过滤
                        if start_time and event.timestamp < start_time:
                            continue
                        if end_time and event.timestamp > end_time:
                            continue
                        if event_type_set and event.event_type.value not in event_type_set:
                            continue
                        if severity_set and event.severity.value not in severity_set:
                            continue

                        results.append(event)

                        if len(results) >= limit:
                            return results

                    except (json.JSONDecodeError, Exception):
                        continue

        return results

    async def get_stats(self, period_hours: int = 24) -> Dict[str, Any]:
        """获取统计"""
        start_time = int((datetime.now() - timedelta(hours=period_hours)).timestamp() * 1000)

        events = await self.query(start_time=start_time, limit=10000)

        stats = {
            "total_events": len(events),
            "by_type": defaultdict(int),
            "by_severity": defaultdict(int),
            "by_tool": defaultdict(int),
        }

        for event in events:
            stats["by_type"][event.event_type.value] += 1
            stats["by_severity"][event.severity.value] += 1
            if event.tool_name:
                stats["by_tool"][event.tool_name] += 1

        return stats

    def _get_current_file(self) -> str:
        """获取当前文件路径"""
        today = datetime.now().strftime("%Y-%m-%d")

        if self._current_file_date != today:
            self._current_file_date = today
            self._current_file = os.path.join(
                self.storage_dir,
                f"audit_{today}.jsonl"
            )

        return self._current_file


# ============================================================================
# 告警系统
# ============================================================================

class AlertRule:
    """告警规则"""

    def __init__(
        self,
        rule_id: str,
        name: str,
        condition: Callable[[AuditEvent], bool],
        alert_type: AlertType,
        severity: AuditSeverity,
        message_template: str,
        cooldown_seconds: int = 300  # 冷却时间，避免重复告警
    ):
        self.rule_id = rule_id
        self.name = name
        self.condition = condition
        self.alert_type = alert_type
        self.severity = severity
        self.message_template = message_template
        self.cooldown_seconds = cooldown_seconds

        self._last_triggered: Dict[str, int] = {}  # key -> timestamp

    def should_trigger(self, event: AuditEvent) -> bool:
        """检查是否应该触发告警"""
        # 检查冷却
        key = f"{self.rule_id}:{event.tool_name or 'system'}"
        last = self._last_triggered.get(key, 0)

        if time.time() * 1000 - last < self.cooldown_seconds * 1000:
            return False

        # 检查条件
        if self.condition(event):
            self._last_triggered[key] = int(time.time() * 1000)
            return True

        return False

    def create_alert(self, event: AuditEvent) -> SecurityAlert:
        """创建告警"""
        return SecurityAlert(
            alert_id=f"alert_{int(time.time() * 1000)}",
            alert_type=self.alert_type,
            severity=self.severity,
            title=self.name,
            message=self.message_template.format(event=event),
            source_event=event
        )


class AlertManager:
    """告警管理器"""

    def __init__(self):
        self.rules: List[AlertRule] = []
        self._active_alerts: List[SecurityAlert] = []
        self._handlers: List[Callable[[SecurityAlert], None]] = []
        self._lock = threading.Lock()

    def add_rule(self, rule: AlertRule):
        """添加告警规则"""
        self.rules.append(rule)

    def add_handler(self, handler: Callable[[SecurityAlert], None]):
        """添加告警处理器"""
        self._handlers.append(handler)

    def check_event(self, event: AuditEvent):
        """检查事件是否触发告警"""
        for rule in self.rules:
            if rule.should_trigger(event):
                alert = rule.create_alert(event)
                self._trigger_alert(alert)

    def _trigger_alert(self, alert: SecurityAlert):
        """触发告警"""
        with self._lock:
            self._active_alerts.append(alert)

        # 调用处理器
        for handler in self._handlers:
            try:
                handler(alert)
            except Exception as e:
                logging.error(f"Alert handler error: {e}")

    def acknowledge_alert(self, alert_id: str, acknowledged_by: str = None):
        """确认告警"""
        with self._lock:
            for alert in self._active_alerts:
                if alert.alert_id == alert_id:
                    alert.acknowledged = True
                    alert.acknowledged_by = acknowledged_by
                    alert.acknowledged_at = int(time.time() * 1000)
                    break

    def get_active_alerts(self, include_acknowledged: bool = False) -> List[SecurityAlert]:
        """获取活动告警"""
        with self._lock:
            if include_acknowledged:
                return self._active_alerts.copy()
            return [a for a in self._active_alerts if not a.acknowledged]


# ============================================================================
# 内置告警规则
# ============================================================================

def create_default_alert_rules() -> List[AlertRule]:
    """创建默认告警规则"""
    rules = []

    # 安全违规
    rules.append(AlertRule(
        rule_id="security_violation",
        name="安全违规",
        condition=lambda e: e.event_type == AuditEventType.SECURITY_VIOLATION,
        alert_type=AlertType.SECURITY,
        severity=AuditSeverity.CRITICAL,
        message_template="检测到安全违规: {event.description}",
        cooldown_seconds=60
    ))

    # 注入尝试
    rules.append(AlertRule(
        rule_id="injection_attempt",
        name="注入攻击尝试",
        condition=lambda e: e.event_type == AuditEventType.INJECTION_ATTEMPT,
        alert_type=AlertType.SECURITY,
        severity=AuditSeverity.CRITICAL,
        message_template="检测到潜在注入攻击: {event.description}",
        cooldown_seconds=60
    ))

    # 权限拒绝频繁
    rules.append(AlertRule(
        rule_id="frequent_permission_denied",
        name="频繁权限拒绝",
        condition=lambda e: (
            e.event_type == AuditEventType.PERMISSION_DENIED and
            e.details.get("consecutive_denials", 0) >= 3
        ),
        alert_type=AlertType.SECURITY,
        severity=AuditSeverity.WARNING,
        message_template="连续多次权限被拒绝，可能存在异常行为",
        cooldown_seconds=300
    ))

    # 资源超限
    rules.append(AlertRule(
        rule_id="resource_exceeded",
        name="资源超限",
        condition=lambda e: e.event_type == AuditEventType.RESOURCE_LIMIT_EXCEEDED,
        alert_type=AlertType.OPERATIONAL,
        severity=AuditSeverity.ERROR,
        message_template="资源使用超过限制: {event.description}",
        cooldown_seconds=300
    ))

    # 沙箱违规
    rules.append(AlertRule(
        rule_id="sandbox_violation",
        name="沙箱违规",
        condition=lambda e: e.event_type == AuditEventType.SANDBOX_VIOLATION,
        alert_type=AlertType.SECURITY,
        severity=AuditSeverity.WARNING,
        message_template="沙箱规则被违反: {event.description}",
        cooldown_seconds=300
    ))

    return rules


# ============================================================================
# 合规报告
# ============================================================================

@dataclass
class ComplianceReport:
    """合规报告"""
    report_id: str
    report_type: str
    period_start: int
    period_end: int
    generated_at: int = field(default_factory=lambda: int(time.time() * 1000))
    summary: Dict[str, Any] = field(default_factory=dict)
    details: Dict[str, Any] = field(default_factory=dict)
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "report_id": self.report_id,
            "report_type": self.report_type,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "generated_at": self.generated_at,
            "summary": self.summary,
            "details": self.details,
            "recommendations": self.recommendations,
        }


class ComplianceReporter:
    """合规报告生成器"""

    def __init__(self, storage: AuditStorage):
        self.storage = storage

    async def generate_daily_report(self, date: datetime = None) -> ComplianceReport:
        """生成日报表"""
        date = date or datetime.now()
        period_start = int(date.replace(hour=0, minute=0, second=0).timestamp() * 1000)
        period_end = int(date.replace(hour=23, minute=59, second=59).timestamp() * 1000)

        stats = await self.storage.get_stats(24)

        # 分析安全事件
        security_events = await self.storage.query(
            start_time=period_start,
            end_time=period_end,
            event_types=[
                AuditEventType.SECURITY_VIOLATION,
                AuditEventType.INJECTION_ATTEMPT,
                AuditEventType.SANDBOX_VIOLATION
            ]
        )

        # 生成建议
        recommendations = []
        if stats.get("by_severity", {}).get("critical", 0) > 0:
            recommendations.append("存在严重安全事件，建议立即审查")
        if stats.get("by_severity", {}).get("warning", 0) > 10:
            recommendations.append("警告事件较多，建议检查系统配置")
        if len(security_events) > 5:
            recommendations.append("安全事件频发，建议加强安全策略")

        return ComplianceReport(
            report_id=f"daily_{date.strftime('%Y%m%d')}",
            report_type="daily",
            period_start=period_start,
            period_end=period_end,
            summary={
                "total_events": stats.get("total_events", 0),
                "by_severity": stats.get("by_severity", {}),
                "security_events": len(security_events),
            },
            details={
                "event_types": stats.get("by_type", {}),
                "tools_used": stats.get("by_tool", {}),
            },
            recommendations=recommendations
        )

    async def generate_weekly_report(self) -> ComplianceReport:
        """生成周报表"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)

        period_start = int(start_date.timestamp() * 1000)
        period_end = int(end_date.timestamp() * 1000)

        stats = await self.storage.get_stats(24 * 7)

        # 安全事件趋势
        security_events = await self.storage.query(
            start_time=period_start,
            end_time=period_end,
            event_types=[
                AuditEventType.SECURITY_VIOLATION,
                AuditEventType.PERMISSION_DENIED,
                AuditEventType.INJECTION_ATTEMPT
            ],
            limit=1000
        )

        # 按天分组
        daily_counts = defaultdict(int)
        for event in security_events:
            day = datetime.fromtimestamp(event.timestamp / 1000).strftime("%Y-%m-%d")
            daily_counts[day] += 1

        return ComplianceReport(
            report_id=f"weekly_{end_date.strftime('%Y%m%d')}",
            report_type="weekly",
            period_start=period_start,
            period_end=period_end,
            summary={
                "total_events": stats.get("total_events", 0),
                "security_events": len(security_events),
                "daily_trend": dict(daily_counts),
            },
            details={
                "event_types": stats.get("by_type", {}),
                "top_tools": dict(sorted(
                    stats.get("by_tool", {}).items(),
                    key=lambda x: x[1],
                    reverse=True
                )[:10]),
            },
            recommendations=[]
        )


# ============================================================================
# 审计记录层
# ============================================================================

class AuditLoggingLayer:
    """
    第六层：审计记录层

    功能：
    - 操作日志完整追踪
    - 安全事件实时告警
    - 合规报告定期审计
    """

    def __init__(
        self,
        storage: AuditStorage = None,
        enable_alerts: bool = True,
        alert_handlers: List[Callable[[SecurityAlert], None]] = None,
        user_id: str = None,
        session_id: str = None
    ):
        self.storage = storage or FileAuditStorage()
        self.user_id = user_id
        self.session_id = session_id or self._generate_session_id()

        # 告警系统
        self.alert_manager = AlertManager()
        if enable_alerts:
            for rule in create_default_alert_rules():
                self.alert_manager.add_rule(rule)

        # 添加告警处理器
        if alert_handlers:
            for handler in alert_handlers:
                self.alert_manager.add_handler(handler)

        # 添加默认日志处理器
        self.alert_manager.add_handler(self._log_alert)

        # 合规报告
        self.compliance_reporter = ComplianceReporter(self.storage)

        # 事件缓冲
        self._event_buffer: List[AuditEvent] = []
        self._buffer_size = 100
        self._flush_interval_seconds = 5
        self._flush_task = None

    def _generate_session_id(self) -> str:
        """生成会话 ID"""
        import uuid
        return f"session_{uuid.uuid4().hex[:12]}"

    async def start(self):
        """启动审计层"""
        self._flush_task = asyncio.create_task(self._flush_loop())

        # 记录会话开始
        await self.log_event(
            event_type=AuditEventType.SESSION_START,
            severity=AuditSeverity.INFO,
            description="审计会话开始"
        )

    async def stop(self):
        """停止审计层"""
        # 记录会话结束
        await self.log_event(
            event_type=AuditEventType.SESSION_END,
            severity=AuditSeverity.INFO,
            description="审计会话结束"
        )

        # 停止刷新任务
        if self._flush_task:
            self._flush_task.cancel()

        # 刷新剩余事件
        await self._flush_events()

    async def log_event(
        self,
        event_type: AuditEventType,
        severity: AuditSeverity,
        description: str = "",
        tool_name: str = None,
        execution_id: str = None,
        details: Dict[str, Any] = None,
        metadata: Dict[str, Any] = None
    ) -> AuditEvent:
        """
        记录审计事件

        Args:
            event_type: 事件类型
            severity: 严重程度
            description: 描述
            tool_name: 工具名称
            execution_id: 执行 ID
            details: 详细信息
            metadata: 元数据

        Returns:
            创建的审计事件
        """
        event = AuditEvent(
            event_id="",
            event_type=event_type,
            severity=severity,
            user_id=self.user_id,
            session_id=self.session_id,
            tool_name=tool_name,
            execution_id=execution_id,
            description=description,
            details=details or {},
            metadata=metadata or {}
        )

        # 添加到缓冲区
        self._event_buffer.append(event)

        # 检查告警
        self.alert_manager.check_event(event)

        # 如果缓冲区满了，立即刷新
        if len(self._event_buffer) >= self._buffer_size:
            await self._flush_events()

        return event

    async def log_tool_execution(
        self,
        tool_name: str,
        execution_id: str,
        arguments: Dict[str, Any],
        result: Any = None,
        success: bool = True,
        duration_ms: int = 0
    ):
        """记录工具执行"""
        event_type = AuditEventType.TOOL_SUCCESS if success else AuditEventType.TOOL_FAILURE
        severity = AuditSeverity.INFO if success else AuditSeverity.WARNING

        await self.log_event(
            event_type=event_type,
            severity=severity,
            description=f"工具 {tool_name} 执行{'成功' if success else '失败'}",
            tool_name=tool_name,
            execution_id=execution_id,
            details={
                "arguments": arguments,
                "success": success,
                "duration_ms": duration_ms,
            }
        )

    async def log_permission_event(
        self,
        tool_name: str,
        action: str,  # "allow", "deny", "ask"
        reason: str = None
    ):
        """记录权限事件"""
        event_type_map = {
            "allow": AuditEventType.PERMISSION_GRANTED,
            "deny": AuditEventType.PERMISSION_DENIED,
            "ask": AuditEventType.PERMISSION_ASK,
        }

        severity_map = {
            "allow": AuditSeverity.INFO,
            "deny": AuditSeverity.WARNING,
            "ask": AuditSeverity.INFO,
        }

        await self.log_event(
            event_type=event_type_map.get(action, AuditEventType.PERMISSION_CHECK),
            severity=severity_map.get(action, AuditSeverity.INFO),
            description=f"权限检查: {action}",
            tool_name=tool_name,
            details={"action": action, "reason": reason}
        )

    async def log_security_event(
        self,
        event_type: AuditEventType,
        description: str,
        details: Dict[str, Any] = None
    ):
        """记录安全事件"""
        await self.log_event(
            event_type=event_type,
            severity=AuditSeverity.CRITICAL,
            description=description,
            details=details
        )

    async def query_events(
        self,
        start_time: int = None,
        end_time: int = None,
        event_types: List[AuditEventType] = None,
        severity: List[AuditSeverity] = None,
        limit: int = 100
    ) -> List[AuditEvent]:
        """查询审计事件"""
        return await self.storage.query(
            start_time=start_time,
            end_time=end_time,
            event_types=event_types,
            severity=severity,
            limit=limit
        )

    async def get_daily_report(self, date: datetime = None) -> ComplianceReport:
        """获取日报表"""
        return await self.compliance_reporter.generate_daily_report(date)

    async def get_weekly_report(self) -> ComplianceReport:
        """获取周报表"""
        return await self.compliance_reporter.generate_weekly_report()

    def get_active_alerts(self, include_acknowledged: bool = False) -> List[SecurityAlert]:
        """获取活动告警"""
        return self.alert_manager.get_active_alerts(include_acknowledged)

    def acknowledge_alert(self, alert_id: str, acknowledged_by: str = None):
        """确认告警"""
        self.alert_manager.acknowledge_alert(alert_id, acknowledged_by)

    async def get_stats(self, period_hours: int = 24) -> Dict[str, Any]:
        """获取审计统计"""
        return await self.storage.get_stats(period_hours)

    async def _flush_loop(self):
        """定期刷新事件"""
        while True:
            await asyncio.sleep(self._flush_interval_seconds)
            await self._flush_events()

    async def _flush_events(self):
        """刷新事件到存储"""
        if not self._event_buffer:
            return

        events_to_flush = self._event_buffer.copy()
        self._event_buffer.clear()

        for event in events_to_flush:
            try:
                await self.storage.store(event)
            except Exception as e:
                logging.error(f"Failed to store audit event: {e}")

    def _log_alert(self, alert: SecurityAlert):
        """日志记录告警"""
        logging.warning(
            f"[SECURITY ALERT] {alert.title}: {alert.message}"
        )
