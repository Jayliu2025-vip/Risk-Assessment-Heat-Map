"""Strict, JSON-friendly contracts for the desktop assessment workflow."""

from dataclasses import asdict, dataclass
from typing import Any, Literal, Mapping
from urllib.parse import urlparse

from tools.common import DIMS, DOMAINS

TaskStatus = Literal["提取中", "分析中", "待复核", "已完成", "失败"]
ReviewStatus = Literal["待确认", "已接受", "已排除"]


class ValidationError(ValueError):
    """Raised when a desktop domain value violates its contract."""


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field}不能为空")
    return value.strip()


def score_or_none(value: Any) -> int | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
        raise ValidationError("评分必须是 1~5 的整数或空值")
    return value


def _scores(values: Mapping[str, Any] | None) -> dict[str, int | None]:
    if not isinstance(values, Mapping):
        raise ValidationError("impact_scores必须是对象")
    unknown = set(values) - set(DIMS)
    if unknown:
        raise ValidationError(f"未知影响维度: {sorted(unknown)}")
    return {dim: score_or_none(values.get(dim)) for dim in DIMS}


def _domain(value: Any) -> str:
    value = _text(value, "domain")
    if value not in DOMAINS:
        raise ValidationError(f"未知风险领域: {value}")
    return value


@dataclass(slots=True)
class AnalysisTask:
    task_id: str
    file_name: str
    file_hash: str
    created_at: str
    status: TaskStatus
    model_profile: str
    extraction_method: str

    def __post_init__(self) -> None:
        self.task_id = _text(self.task_id, "task_id")
        self.file_name = _text(self.file_name, "file_name")
        if ("/" in self.file_name or "\\" in self.file_name or self.file_name in (".", "..") or self.file_name.startswith(("/", "\\")) or (len(self.file_name) > 1 and self.file_name[1] == ":")):
            raise ValidationError("file_name必须是叶级文件名")
        self.file_hash = _text(self.file_hash, "file_hash")
        self.created_at = _text(self.created_at, "created_at")
        if self.status not in ("提取中", "分析中", "待复核", "已完成", "失败"):
            raise ValidationError("无效任务状态")
        self.model_profile = _text(self.model_profile, "model_profile")
        self.extraction_method = _text(self.extraction_method, "extraction_method")


@dataclass(slots=True)
class ExtractedBlock:
    locator: str
    text: str
    method: Literal["text", "ocr", "vision_required"]
    needs_review: bool = False
    image_path: str | None = None

    def __post_init__(self) -> None:
        self.locator = _text(self.locator, "locator")
        self.text = _text(self.text, "text")
        if self.method not in ("text", "ocr", "vision_required"):
            raise ValidationError("无效提取方法")
        if not isinstance(self.needs_review, bool):
            raise ValidationError("needs_review必须是布尔值")
        if self.image_path is not None:
            self.image_path = _text(self.image_path, "image_path")


@dataclass(slots=True)
class FindingDraft:
    task_id: str
    finding_id: str
    title: str
    fact_summary: str
    source_page: str
    source_excerpt: str
    matched_risk_id: str
    domain: str
    likelihood: int | None
    impact_scores: dict[str, int | None]
    rationale: str
    needs_review: bool
    review_status: ReviewStatus = "待确认"

    def __post_init__(self) -> None:
        for name in ("task_id", "finding_id", "title", "fact_summary", "source_page", "source_excerpt", "rationale"):
            setattr(self, name, _text(getattr(self, name), name))
        self.domain = _domain(self.domain)
        if not isinstance(self.matched_risk_id, str):
            raise ValidationError("matched_risk_id必须是字符串")
        self.matched_risk_id = self.matched_risk_id.strip()
        self.likelihood = score_or_none(self.likelihood)
        self.impact_scores = _scores(self.impact_scores)
        if not isinstance(self.needs_review, bool) or self.review_status not in ("待确认", "已接受", "已排除"):
            raise ValidationError("无效复核状态")

    @classmethod
    def from_model(cls, task_id: str, payload: Mapping[str, Any], known_risk_ids: set[str]) -> "FindingDraft":
        if not isinstance(payload, Mapping):
            raise ValidationError("模型结果必须是对象")
        risk_id = payload.get("matched_risk_id")
        if not isinstance(risk_id, str):
            raise ValidationError("matched_risk_id必须是字符串")
        risk_id = risk_id.strip()
        if risk_id and risk_id not in known_risk_ids:
            raise ValidationError(f"未知风险ID: {risk_id}")
        if "needs_review" not in payload:
            raise ValidationError("needs_review不能为空")
        return cls(task_id=task_id, finding_id=payload.get("finding_id"), title=payload.get("title"), fact_summary=payload.get("fact_summary"), source_page=payload.get("source_page"), source_excerpt=payload.get("source_excerpt"), matched_risk_id=risk_id, domain=payload.get("domain"), likelihood=payload.get("likelihood"), impact_scores=payload.get("impact_scores"), rationale=payload.get("rationale"), needs_review=payload["needs_review"], review_status="待确认")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ModelProfile:
    name: str
    base_url: str
    model: str
    supports_vision: bool

    def __post_init__(self) -> None:
        self.name = _text(self.name, "name")
        base = _text(self.base_url, "base_url")
        self.base_url = base
        parsed = urlparse(base)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValidationError("base_url必须是http/https地址")
        self.model = _text(self.model, "model")
        if not isinstance(self.supports_vision, bool):
            raise ValidationError("supports_vision必须是布尔值")


@dataclass(slots=True)
class ConfirmedControl:
    description: str
    score: int
    key: bool

    def __post_init__(self) -> None:
        self.description = _text(self.description, "description")
        checked = score_or_none(self.score)
        if checked is None:
            raise ValidationError("score不能为空")
        self.score = checked
        if not isinstance(self.key, bool):
            raise ValidationError("key必须是布尔值")


@dataclass(slots=True)
class RiskDecision:
    action: Literal["merge", "create", "exclude"]
    finding_ids: tuple[str, ...]
    risk_id: str | None = None
    name: str | None = None
    domain: str | None = None
    description: str | None = None
    owner_dept: str | None = None
    period: str | None = None
    likelihood: int | None = None
    impact_scores: dict[str, int | None] | None = None
    rationale: str | None = None
    controls: tuple[ConfirmedControl, ...] = ()

    def __post_init__(self) -> None:
        if self.action not in ("merge", "create", "exclude"):
            raise ValidationError("无效决策动作")
        if not isinstance(self.finding_ids, (tuple, list)) or any(not isinstance(fid, str) or not fid.strip() for fid in self.finding_ids):
            raise ValidationError("finding_ids必须是非空字符串列表")
        self.finding_ids = tuple(fid.strip() for fid in self.finding_ids)
        if len(set(self.finding_ids)) != len(self.finding_ids):
            raise ValidationError("finding_ids不得重复")
        if self.domain is not None and not isinstance(self.domain, str):
            raise ValidationError("domain必须是字符串")
        if isinstance(self.domain, str):
            self.domain = self.domain.strip()
        for name in ("risk_id", "name", "description", "owner_dept", "period", "rationale"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise ValidationError(f"{name}必须是字符串")
            if isinstance(value, str):
                setattr(self, name, value.strip())
        if self.action != "exclude":
            if not self.finding_ids:
                raise ValidationError("合并或新建决策至少需要一个finding_id")
            # New risks may omit an ID: the workbook writer allocates the next R###
            # after it has checked the immutable source workbook.  A merge remains
            # deliberately strict because it must identify an existing row.
            if self.action == "merge":
                self.risk_id = _text(self.risk_id, "risk_id")
            elif self.risk_id is None:
                self.risk_id = ""
            for name in ("name", "description", "owner_dept", "period", "rationale"):
                setattr(self, name, _text(getattr(self, name), name))
            self.domain = _domain(self.domain)
            self.likelihood = score_or_none(self.likelihood)
            self.impact_scores = _scores(self.impact_scores)
            if self.likelihood is None:
                raise ValidationError("likelihood不能为空")
        else:
            if any(getattr(self, name) is not None for name in ("risk_id", "name", "domain", "description", "owner_dept", "period", "likelihood", "impact_scores", "rationale")) or self.controls:
                raise ValidationError("排除决策不得携带正式风险字段或控制")
        if not isinstance(self.controls, (tuple, list)) or any(not isinstance(control, ConfirmedControl) for control in self.controls):
            raise ValidationError("controls必须由ConfirmedControl组成")
        self.controls = tuple(self.controls)
