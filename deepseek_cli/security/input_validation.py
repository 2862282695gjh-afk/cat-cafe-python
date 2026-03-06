"""
第一层：输入验证层 (Input Validation Layer)
- Zod Schema 严格验证
- 参数类型强制检查
- 格式验证边界约束
"""
import re
import json
from typing import Any, Dict, List, Optional, Union, Callable, Type
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from abc import ABC, abstractmethod


class ValidationErrorCode(Enum):
    """验证错误代码"""
    TYPE_MISMATCH = "TYPE_MISMATCH"
    MISSING_REQUIRED = "MISSING_REQUIRED"
    INVALID_FORMAT = "INVALID_FORMAT"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    PATTERN_MISMATCH = "PATTERN_MISMATCH"
    CUSTOM_ERROR = "CUSTOM_ERROR"
    SECURITY_VIOLATION = "SECURITY_VIOLATION"
    INJECTION_DETECTED = "INJECTION_DETECTED"


@dataclass
class ValidationError:
    """验证错误"""
    code: ValidationErrorCode
    field: str
    message: str
    value: Any = None
    expected: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "code": self.code.value,
            "field": self.field,
            "message": self.message,
            "expected": self.expected
        }


@dataclass
class ValidationResult:
    """验证结果"""
    valid: bool
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    normalized_value: Any = None
    sanitized: bool = False

    def add_error(self, error: ValidationError):
        self.errors.append(error)
        self.valid = False

    def to_dict(self) -> Dict:
        return {
            "valid": self.valid,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": self.warnings,
            "sanitized": self.sanitized
        }


# ============================================================================
# Zod-like Schema 定义
# ============================================================================

class ZodSchema(ABC):
    """Zod-like Schema 基类"""

    def __init__(self):
        self._optional = False
        self._nullable = False
        self._default = None
        self._has_default = False
        self._transform: Optional[Callable] = None
        self._refine: Optional[Callable] = None
        self._refine_message: str = ""

    def optional(self) -> 'ZodSchema':
        self._optional = True
        return self

    def nullable(self) -> 'ZodSchema':
        self._nullable = True
        return self

    def default(self, value: Any) -> 'ZodSchema':
        self._default = value
        self._has_default = True
        return self

    def transform(self, fn: Callable) -> 'ZodSchema':
        self._transform = fn
        return self

    def refine(self, fn: Callable, message: str = "") -> 'ZodSchema':
        self._refine = fn
        self._refine_message = message
        return self

    @abstractmethod
    def _validate(self, value: Any, path: str = "") -> ValidationResult:
        pass

    def validate(self, value: Any, path: str = "") -> ValidationResult:
        result = ValidationResult(valid=True)

        # 处理 None
        if value is None:
            if self._nullable:
                result.normalized_value = None
                return result
            if self._optional:
                if self._has_default:
                    result.normalized_value = self._default
                else:
                    result.normalized_value = None
                return result
            result.add_error(ValidationError(
                code=ValidationErrorCode.MISSING_REQUIRED,
                field=path,
                message=f"Field '{path}' is required",
                expected="non-null value"
            ))
            return result

        # 执行验证
        result = self._validate(value, path)

        # 应用自定义验证
        if result.valid and self._refine:
            try:
                if not self._refine(result.normalized_value):
                    result.add_error(ValidationError(
                        code=ValidationErrorCode.CUSTOM_ERROR,
                        field=path,
                        message=self._refine_message or "Custom validation failed"
                    ))
            except Exception as e:
                result.add_error(ValidationError(
                    code=ValidationErrorCode.CUSTOM_ERROR,
                    field=path,
                    message=str(e)
                ))

        # 应用转换
        if result.valid and self._transform and result.normalized_value is not None:
            try:
                result.normalized_value = self._transform(result.normalized_value)
            except Exception as e:
                result.add_error(ValidationError(
                    code=ValidationErrorCode.CUSTOM_ERROR,
                    field=path,
                    message=f"Transform failed: {e}"
                ))

        return result


class ZodString(ZodSchema):
    """字符串 Schema"""

    def __init__(self):
        super().__init__()
        self._min_length: Optional[int] = None
        self._max_length: Optional[int] = None
        self._pattern: Optional[re.Pattern] = None
        self._format: Optional[str] = None
        self._allow_html: bool = False
        self._escape_html: bool = False

    def min(self, length: int) -> 'ZodString':
        self._min_length = length
        return self

    def max(self, length: int) -> 'ZodString':
        self._max_length = length
        return self

    def pattern(self, regex: str) -> 'ZodString':
        self._pattern = re.compile(regex)
        return self

    def email(self) -> 'ZodString':
        self._format = 'email'
        self._pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
        return self

    def url(self) -> 'ZodString':
        self._format = 'url'
        self._pattern = re.compile(r'^https?://[^\s/$.?#].[^\s]*$')
        return self

    def uuid(self) -> 'ZodString':
        self._format = 'uuid'
        self._pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
        return self

    def file_path(self) -> 'ZodString':
        self._format = 'file_path'
        return self

    def no_html(self) -> 'ZodString':
        self._allow_html = False
        return self

    def escape_html(self) -> 'ZodString':
        self._escape_html = True
        return self

    def _validate(self, value: Any, path: str = "") -> ValidationResult:
        result = ValidationResult(valid=True)

        # 类型检查
        if not isinstance(value, str):
            result.add_error(ValidationError(
                code=ValidationErrorCode.TYPE_MISMATCH,
                field=path,
                message=f"Expected string, got {type(value).__name__}",
                value=value,
                expected="string"
            ))
            return result

        text = value

        # 长度检查
        if self._min_length is not None and len(text) < self._min_length:
            result.add_error(ValidationError(
                code=ValidationErrorCode.OUT_OF_RANGE,
                field=path,
                message=f"String length {len(text)} is less than minimum {self._min_length}",
                expected=f"min {self._min_length} characters"
            ))

        if self._max_length is not None and len(text) > self._max_length:
            result.add_error(ValidationError(
                code=ValidationErrorCode.OUT_OF_RANGE,
                field=path,
                message=f"String length {len(text)} exceeds maximum {self._max_length}",
                expected=f"max {self._max_length} characters"
            ))

        # 正则模式检查
        if self._pattern and not self._pattern.match(text):
            result.add_error(ValidationError(
                code=ValidationErrorCode.PATTERN_MISMATCH,
                field=path,
                message=f"String does not match pattern: {self._pattern.pattern}",
                value=text
            ))

        # HTML 检查和转义
        if self._escape_html:
            import html
            text = html.escape(text)
            result.sanitized = True

        result.normalized_value = text
        return result


class ZodNumber(ZodSchema):
    """数字 Schema"""

    def __init__(self):
        super().__init__()
        self._min_value: Optional[float] = None
        self._max_value: Optional[float] = None
        self._integer_only: bool = False
        self._positive_only: bool = False

    def min(self, value: float) -> 'ZodNumber':
        self._min_value = value
        return self

    def max(self, value: float) -> 'ZodNumber':
        self._max_value = value
        return self

    def int(self) -> 'ZodNumber':
        self._integer_only = True
        return self

    def positive(self) -> 'ZodNumber':
        self._positive_only = True
        self._min_value = 0.0001
        return self

    def _validate(self, value: Any, path: str = "") -> ValidationResult:
        result = ValidationResult(valid=True)

        # 类型检查（允许字符串数字转换）
        if isinstance(value, str):
            try:
                if self._integer_only:
                    value = int(value)
                else:
                    value = float(value)
            except ValueError:
                result.add_error(ValidationError(
                    code=ValidationErrorCode.TYPE_MISMATCH,
                    field=path,
                    message=f"Cannot convert '{value}' to number",
                    expected="number"
                ))
                return result
        elif not isinstance(value, (int, float)) or isinstance(value, bool):
            result.add_error(ValidationError(
                code=ValidationErrorCode.TYPE_MISMATCH,
                field=path,
                message=f"Expected number, got {type(value).__name__}",
                value=value,
                expected="number"
            ))
            return result

        num = value

        # 整数检查
        if self._integer_only and not isinstance(num, int):
            result.add_error(ValidationError(
                code=ValidationErrorCode.TYPE_MISMATCH,
                field=path,
                message=f"Expected integer, got float",
                expected="integer"
            ))

        # 范围检查
        if self._min_value is not None and num < self._min_value:
            result.add_error(ValidationError(
                code=ValidationErrorCode.OUT_OF_RANGE,
                field=path,
                message=f"Value {num} is less than minimum {self._min_value}",
                expected=f">= {self._min_value}"
            ))

        if self._max_value is not None and num > self._max_value:
            result.add_error(ValidationError(
                code=ValidationErrorCode.OUT_OF_RANGE,
                field=path,
                message=f"Value {num} exceeds maximum {self._max_value}",
                expected=f"<= {self._max_value}"
            ))

        result.normalized_value = num
        return result


class ZodBoolean(ZodSchema):
    """布尔值 Schema"""

    def _validate(self, value: Any, path: str = "") -> ValidationResult:
        result = ValidationResult(valid=True)

        # 允许字符串转换
        if isinstance(value, str):
            if value.lower() in ('true', '1', 'yes', 'on'):
                result.normalized_value = True
                return result
            elif value.lower() in ('false', '0', 'no', 'off'):
                result.normalized_value = False
                return result

        if not isinstance(value, bool):
            result.add_error(ValidationError(
                code=ValidationErrorCode.TYPE_MISMATCH,
                field=path,
                message=f"Expected boolean, got {type(value).__name__}",
                value=value,
                expected="boolean"
            ))
            return result

        result.normalized_value = value
        return result


class ZodArray(ZodSchema):
    """数组 Schema"""

    def __init__(self, item_schema: ZodSchema):
        super().__init__()
        self.item_schema = item_schema
        self._min_items: Optional[int] = None
        self._max_items: Optional[int] = None

    def min(self, count: int) -> 'ZodArray':
        self._min_items = count
        return self

    def max(self, count: int) -> 'ZodArray':
        self._max_items = count
        return self

    def _validate(self, value: Any, path: str = "") -> ValidationResult:
        result = ValidationResult(valid=True)

        if not isinstance(value, (list, tuple)):
            result.add_error(ValidationError(
                code=ValidationErrorCode.TYPE_MISMATCH,
                field=path,
                message=f"Expected array, got {type(value).__name__}",
                value=value,
                expected="array"
            ))
            return result

        # 长度检查
        if self._min_items is not None and len(value) < self._min_items:
            result.add_error(ValidationError(
                code=ValidationErrorCode.OUT_OF_RANGE,
                field=path,
                message=f"Array length {len(value)} is less than minimum {self._min_items}",
                expected=f">= {self._min_items} items"
            ))

        if self._max_items is not None and len(value) > self._max_items:
            result.add_error(ValidationError(
                code=ValidationErrorCode.OUT_OF_RANGE,
                field=path,
                message=f"Array length {len(value)} exceeds maximum {self._max_items}",
                expected=f"<= {self._max_items} items"
            ))

        # 验证每个元素
        normalized = []
        for i, item in enumerate(value):
            item_result = self.item_schema.validate(item, f"{path}[{i}]")
            if not item_result.valid:
                result.errors.extend(item_result.errors)
                result.valid = False
            else:
                normalized.append(item_result.normalized_value)

        if result.valid:
            result.normalized_value = normalized

        return result


class ZodObject(ZodSchema):
    """对象 Schema"""

    def __init__(self, shape: Dict[str, ZodSchema]):
        super().__init__()
        self.shape = shape
        self._strict = False
        self._strip_unknown = True

    def strict(self) -> 'ZodObject':
        self._strict = True
        self._strip_unknown = False
        return self

    def passthrough(self) -> 'ZodObject':
        self._strict = False
        self._strip_unknown = False
        return self

    def _validate(self, value: Any, path: str = "") -> ValidationResult:
        result = ValidationResult(valid=True)

        if not isinstance(value, dict):
            result.add_error(ValidationError(
                code=ValidationErrorCode.TYPE_MISMATCH,
                field=path,
                message=f"Expected object, got {type(value).__name__}",
                value=value,
                expected="object"
            ))
            return result

        normalized = {}
        known_keys = set(self.shape.keys())

        # 验证已知字段
        for key, schema in self.shape.items():
            field_path = f"{path}.{key}" if path else key

            if key in value:
                field_result = schema.validate(value[key], field_path)
                if not field_result.valid:
                    result.errors.extend(field_result.errors)
                    result.valid = False
                else:
                    normalized[key] = field_result.normalized_value
            elif schema._has_default:
                normalized[key] = schema._default
            elif not schema._optional:
                result.add_error(ValidationError(
                    code=ValidationErrorCode.MISSING_REQUIRED,
                    field=field_path,
                    message=f"Missing required field: {key}",
                    expected="required"
                ))
                result.valid = False

        # 处理未知字段
        for key in value.keys():
            if key not in known_keys:
                if self._strict:
                    result.add_error(ValidationError(
                        code=ValidationErrorCode.CUSTOM_ERROR,
                        field=f"{path}.{key}" if path else key,
                        message=f"Unknown field: {key}"
                    ))
                    result.valid = False
                elif not self._strip_unknown:
                    normalized[key] = value[key]
                else:
                    result.warnings.append(f"Unknown field stripped: {key}")

        if result.valid:
            result.normalized_value = normalized

        return result


class ZodUnion(ZodSchema):
    """联合类型 Schema"""

    def __init__(self, schemas: List[ZodSchema]):
        super().__init__()
        self.schemas = schemas

    def _validate(self, value: Any, path: str = "") -> ValidationResult:
        errors = []

        for schema in self.schemas:
            result = schema.validate(value, path)
            if result.valid:
                return result
            errors.extend(result.errors)

        return ValidationResult(
            valid=False,
            errors=[ValidationError(
                code=ValidationErrorCode.TYPE_MISMATCH,
                field=path,
                message=f"Value does not match any of the union types",
                value=value
            )]
        )


class ZodEnum(ZodSchema):
    """枚举 Schema"""

    def __init__(self, values: List[Any]):
        super().__init__()
        self.values = values

    def _validate(self, value: Any, path: str = "") -> ValidationResult:
        if value in self.values:
            return ValidationResult(valid=True, normalized_value=value)

        return ValidationResult(
            valid=False,
            errors=[ValidationError(
                code=ValidationErrorCode.PATTERN_MISMATCH,
                field=path,
                message=f"Value must be one of: {self.values}",
                value=value,
                expected=f"one of {self.values}"
            )]
        )


# ============================================================================
# 安全模式检测
# ============================================================================

class SecurityPatternChecker:
    """安全模式检测器"""

    # SQL 注入模式
    SQL_INJECTION_PATTERNS = [
        r"('\s*(OR|AND)\s*'|\"\s*(OR|AND)\s*\")",
        r"(UNION\s+SELECT)",
        r"(--\s*$)",
        r"(;\s*DROP\s+TABLE)",
        r"(;\s*DELETE\s+FROM)",
        r"(;\s*INSERT\s+INTO)",
        r"(;\s*UPDATE\s+.*SET)",
        r"(\bEXEC\b|\bEXECUTE\b)",
        r"(xp_cmdshell)",
        r"(CONCAT\s*\()",
    ]

    # 命令注入模式
    COMMAND_INJECTION_PATTERNS = [
        r"[;&|`$]",
        r"\$\([^)]+\)",
        r"`[^`]+`",
        r"\|\s*\w+",
        r">\s*/",
        r"2>&1",
        r"\b(cat|ls|rm|wget|curl|nc|bash|sh|python|perl|ruby|php)\b.*[;&|]",
    ]

    # 路径遍历模式
    PATH_TRAVERSAL_PATTERNS = [
        r"\.\./",
        r"\.\.\\",
        r"%2e%2e[/\\]",
        r"%252e%252e",
        r"\.\.%2f",
        r"\.\.%5c",
    ]

    # XSS 模式
    XSS_PATTERNS = [
        r"<script[^>]*>",
        r"javascript:",
        r"on\w+\s*=",
        r"<iframe",
        r"<object",
        r"<embed",
        r"expression\s*\(",
    ]

    @classmethod
    def check_sql_injection(cls, value: str) -> Optional[str]:
        """检测 SQL 注入"""
        for pattern in cls.SQL_INJECTION_PATTERNS:
            if re.search(pattern, value, re.IGNORECASE):
                return f"Potential SQL injection detected: pattern '{pattern}'"
        return None

    @classmethod
    def check_command_injection(cls, value: str) -> Optional[str]:
        """检测命令注入"""
        for pattern in cls.COMMAND_INJECTION_PATTERNS:
            if re.search(pattern, value, re.IGNORECASE):
                return f"Potential command injection detected: pattern '{pattern}'"
        return None

    @classmethod
    def check_path_traversal(cls, value: str) -> Optional[str]:
        """检测路径遍历"""
        for pattern in cls.PATH_TRAVERSAL_PATTERNS:
            if re.search(pattern, value, re.IGNORECASE):
                return f"Path traversal attempt detected"
        return None

    @classmethod
    def check_xss(cls, value: str) -> Optional[str]:
        """检测 XSS"""
        for pattern in cls.XSS_PATTERNS:
            if re.search(pattern, value, re.IGNORECASE):
                return f"Potential XSS detected"
        return None

    @classmethod
    def full_security_check(cls, value: str) -> List[str]:
        """完整安全检查"""
        issues = []

        sql_issue = cls.check_sql_injection(value)
        if sql_issue:
            issues.append(sql_issue)

        cmd_issue = cls.check_command_injection(value)
        if cmd_issue:
            issues.append(cmd_issue)

        path_issue = cls.check_path_traversal(value)
        if path_issue:
            issues.append(path_issue)

        xss_issue = cls.check_xss(value)
        if xss_issue:
            issues.append(xss_issue)

        return issues


# ============================================================================
# 输入验证层
# ============================================================================

class InputValidationLayer:
    """
    第一层：输入验证层

    功能：
    - Zod Schema 严格验证
    - 参数类型强制检查
    - 格式验证边界约束
    - 安全模式检测
    """

    # 工具参数 Schema 定义
    TOOL_SCHEMAS = {
        "Read": ZodObject({
            "file_path": ZodString().file_path().min(1),
            "offset": ZodNumber().int().positive().default(1),
            "limit": ZodNumber().int().positive().max(10000).default(2000),
        }),
        "Write": ZodObject({
            "file_path": ZodString().file_path().min(1),
            "content": ZodString(),
        }),
        "Edit": ZodObject({
            "file_path": ZodString().file_path().min(1),
            "old_string": ZodString().min(1),
            "new_string": ZodString(),
            "replace_all": ZodBoolean().default(False),
        }),
        "Bash": ZodObject({
            "command": ZodString().min(1),
            "timeout": ZodNumber().int().positive().max(600000).default(120000),
            "description": ZodString().optional(),
        }),
        "Glob": ZodObject({
            "pattern": ZodString().min(1),
            "path": ZodString().optional(),
        }),
        "Grep": ZodObject({
            "pattern": ZodString().min(1),
            "path": ZodString().optional(),
            "output_mode": ZodEnum(["content", "files_with_matches", "count"]).default("content"),
            "-i": ZodBoolean().default(False),
            "-n": ZodBoolean().default(True),
        }),
    }

    def __init__(
        self,
        enable_security_check: bool = True,
        strict_mode: bool = False,
        custom_schemas: Dict[str, ZodSchema] = None
    ):
        self.enable_security_check = enable_security_check
        self.strict_mode = strict_mode
        self.custom_schemas = custom_schemas or {}
        self._security_checker = SecurityPatternChecker()

        # 合并自定义 Schema
        self.schemas = {**self.TOOL_SCHEMAS, **self.custom_schemas}

    def validate_tool_input(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> ValidationResult:
        """
        验证工具输入参数

        Args:
            tool_name: 工具名称
            arguments: 工具参数

        Returns:
            ValidationResult
        """
        result = ValidationResult(valid=True)

        # 1. 检查工具是否存在 Schema
        schema = self.schemas.get(tool_name)

        if schema:
            # 使用 Zod Schema 验证
            result = schema.validate(arguments)
        else:
            # 无 Schema，使用基本验证
            result.normalized_value = arguments
            if self.strict_mode:
                result.warnings.append(f"No schema defined for tool: {tool_name}")

        # 2. 安全模式检查
        if self.enable_security_check and result.valid:
            security_issues = self._check_security_patterns(result.normalized_value or arguments)
            if security_issues:
                for issue in security_issues:
                    result.add_error(ValidationError(
                        code=ValidationErrorCode.SECURITY_VIOLATION,
                        field="",
                        message=issue
                    ))

        # 3. 边界约束检查
        if result.valid and result.normalized_value:
            self._check_boundary_constraints(result)

        return result

    def _check_security_patterns(self, data: Any) -> List[str]:
        """递归检查安全模式"""
        issues = []

        if isinstance(data, str):
            issues.extend(self._security_checker.full_security_check(data))
        elif isinstance(data, dict):
            for value in data.values():
                issues.extend(self._check_security_patterns(value))
        elif isinstance(data, (list, tuple)):
            for item in data:
                issues.extend(self._check_security_patterns(item))

        return issues

    def _check_boundary_constraints(self, result: ValidationResult):
        """检查边界约束"""
        args = result.normalized_value
        if not isinstance(args, dict):
            return

        # 文件路径边界检查
        if "file_path" in args:
            path = args["file_path"]
            # 检查绝对路径
            if path.startswith("/"):
                blocked_paths = ["/etc/passwd", "/etc/shadow", "/root/.ssh"]
                for blocked in blocked_paths:
                    if blocked in path:
                        result.add_error(ValidationError(
                            code=ValidationErrorCode.SECURITY_VIOLATION,
                            field="file_path",
                            message=f"Access to sensitive path blocked: {blocked}"
                        ))

        # 命令超时边界检查
        if "timeout" in args:
            timeout = args["timeout"]
            if timeout > 600000:  # 10 分钟
                result.warnings.append(f"Timeout {timeout}ms exceeds recommended maximum")

        # 内容大小检查
        if "content" in args:
            content = args["content"]
            max_content_size = 10 * 1024 * 1024  # 10MB
            if len(content) > max_content_size:
                result.add_error(ValidationError(
                    code=ValidationErrorCode.OUT_OF_RANGE,
                    field="content",
                    message=f"Content size {len(content)} exceeds maximum {max_content_size}",
                    expected=f"<= {max_content_size} bytes"
                ))

    def register_schema(self, tool_name: str, schema: ZodSchema):
        """注册自定义 Schema"""
        self.schemas[tool_name] = schema

    def validate_string(self, value: str, **constraints) -> ValidationResult:
        """快速验证字符串"""
        schema = ZodString()
        for key, val in constraints.items():
            if hasattr(schema, key):
                getattr(schema, key)(val)
        return schema.validate(value)

    def validate_number(self, value: Union[int, float], **constraints) -> ValidationResult:
        """快速验证数字"""
        schema = ZodNumber()
        for key, val in constraints.items():
            if hasattr(schema, key):
                getattr(schema, key)(val)
        return schema.validate(value)
